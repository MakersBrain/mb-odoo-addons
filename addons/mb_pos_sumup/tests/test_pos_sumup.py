from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.account.tests.common import AccountTestInvoicingCommon

_SEND_REQUEST = (
    "odoo.addons.payment.models.payment_provider.PaymentProvider._send_api_request"
)


@tagged("post_install", "-at_install")
class TestPosSumUp(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.env.user.group_ids |= cls.env.ref("point_of_sale.group_pos_manager")
        cls.provider = cls.env["payment.provider"].search(
            [("code", "=", "sumup"), ("company_id", "=", cls.env.company.id)], limit=1
        )
        cls.provider.write({
            "state": "test",
            "sumup_api_key": "sup_sk_dummy",
            "sumup_merchant_code": "MCTEST01",
        })
        cls.payment_method = cls.env["pos.payment.method"].create({
            "name": "SumUp",
            "journal_id": cls.company_data["default_journal_bank"].id,
            "receivable_account_id": cls.company_data["default_account_receivable"].id,
            "payment_method_type": "terminal",
            "use_payment_terminal": "sumup_mobile",
            "sumup_affiliate_key": "aff-key",
            "sumup_app_id": "com.example.pos",
            "sumup_payment_provider_id": cls.provider.id,
        })
        cls.base_url = cls.payment_method.get_base_url()
        cls.callback_url = f"{cls.base_url}/pos/ui/1/payment/order-uuid"
        cls.line_uuid = "0dc4c5f8-1c00-4c00-9c00-000000000001"

    def _prepare(self, **kwargs):
        return self.payment_method.sumup_prepare_payment(
            kwargs.pop("amount", 12.34),
            kwargs.pop("payment_uuid", self.line_uuid),
            kwargs.pop("callback_url", self.callback_url),
            **kwargs,
        )

    # === The deep link === #

    def test_deep_link_carries_what_both_platforms_read(self):
        url = self._prepare(title="Order 0042")

        parsed = urlparse(url)
        params = {key: value[0] for key, value in parse_qs(parsed.query).items()}
        self.assertEqual(f"{parsed.scheme}://{parsed.netloc}{parsed.path}", "sumupmerchant://pay/1.0")
        self.assertEqual(params["affiliate-key"], "aff-key")
        self.assertEqual(params["app-id"], "com.example.pos")
        # Android reads `total`, iOS reads `amount`.
        self.assertEqual(params["total"], "12.34")
        self.assertEqual(params["amount"], "12.34")
        # The line uuid is the only handle SumUp gives back unchanged.
        self.assertEqual(params["foreign-tx-id"], self.line_uuid)
        self.assertEqual(params["title"], "Order 0042")
        self.assertEqual(params["skip-screen-success"], "true")
        # Android's callback parameter and iOS's pair all point at the POS page.
        for key in ("callback", "callbacksuccess", "callbackfail"):
            self.assertEqual(params[key], self.callback_url)

    def test_callback_must_be_ours(self):
        """The callback is where the SumUp app sends the cashier next."""
        with self.assertRaises(UserError):
            self._prepare(callback_url="https://evil.example/pos/ui/1/payment/x")

    def test_missing_affiliate_key_refuses_the_payment(self):
        self.payment_method.sumup_affiliate_key = False
        with self.assertRaises(UserError):
            self._prepare()

    # === Confirming the callback === #

    def test_success_is_verified_against_sumup(self):
        with patch(_SEND_REQUEST, return_value={
            "id": "tx_0001",
            "transaction_code": "TEEPUC2VLF",
            "status": "SUCCESSFUL",
            "amount": 12.34,
            "currency": self.env.company.currency_id.name,
            "merchant_code": "MCTEST01",
            "foreign_transaction_id": self.line_uuid,
            "card": {"last_4_digits": "4242", "type": "VISA"},
        }) as send_request:
            result = self.payment_method.sumup_confirm_payment(
                self.line_uuid, 12.34, {"smp-status": "success", "smp-tx-code": "TEEPUC2VLF"}
            )

        method, endpoint = send_request.call_args[0][:2]
        self.assertEqual(method, "GET")
        self.assertEqual(endpoint, "/v2.1/merchants/MCTEST01/transactions")
        self.assertEqual(
            send_request.call_args[1]["params"], {"foreign_transaction_id": self.line_uuid}
        )
        self.assertTrue(result["successful"])
        self.assertTrue(result["verified"])
        self.assertEqual(result["transaction_code"], "TEEPUC2VLF")
        self.assertEqual(result["card_no"], "4242")

    @mute_logger("odoo.addons.mb_pos_sumup.models.pos_payment_method")
    def test_a_claimed_success_sumup_has_no_record_of_is_refused(self):
        """`smp-status` is a URL parameter, which is a claim and not evidence."""
        with patch(_SEND_REQUEST, return_value={}):
            result = self.payment_method.sumup_confirm_payment(
                self.line_uuid, 12.34, {"smp-status": "success"}
            )

        self.assertFalse(result["successful"])
        self.assertTrue(result["verified"])

    def test_a_different_amount_is_refused(self):
        with patch(_SEND_REQUEST, return_value={
            "id": "tx_0001",
            "status": "SUCCESSFUL",
            "amount": 1.0,
            "currency": self.env.company.currency_id.name,
            "merchant_code": "MCTEST01",
            "foreign_transaction_id": self.line_uuid,
        }):
            result = self.payment_method.sumup_confirm_payment(
                self.line_uuid, 12.34, {"smp-status": "success"}
            )

        self.assertFalse(result["successful"])

    def test_without_an_account_the_callback_is_refused(self):
        self.payment_method.sumup_payment_provider_id = False

        with patch(_SEND_REQUEST) as send_request:
            with self.assertRaises(UserError):
                self.payment_method.sumup_confirm_payment(
                    self.line_uuid, 12.34,
                    {"smp-status": "success", "smp-tx-code": "TEEPUC2VLF"},
                )

        send_request.assert_not_called()

    def test_without_an_account_payment_handover_is_refused(self):
        self.payment_method.sumup_payment_provider_id = False

        with self.assertRaises(UserError):
            self._prepare()

    def test_disabled_account_payment_handover_is_refused(self):
        self.provider.state = "disabled"

        with self.assertRaises(UserError):
            self._prepare()

    def test_wrong_currency_merchant_or_reference_is_refused(self):
        valid = {
            "id": "tx_0001",
            "status": "SUCCESSFUL",
            "amount": 12.34,
            "currency": self.env.company.currency_id.name,
            "merchant_code": "MCTEST01",
            "foreign_transaction_id": self.line_uuid,
        }
        other_currency = (
            "USD" if self.env.company.currency_id.name != "USD" else "EUR"
        )
        for mismatch in (
            {"currency": other_currency},
            {"merchant_code": "OTHER"},
            {"foreign_transaction_id": "another-payment"},
        ):
            with self.subTest(mismatch=mismatch), patch(
                _SEND_REQUEST, return_value=dict(valid, **mismatch)
            ):
                result = self.payment_method.sumup_confirm_payment(
                    self.line_uuid, 12.34, {"smp-status": "success"}
                )
                self.assertFalse(result["successful"])

    # === Refunds === #

    def test_refund_needs_an_account(self):
        self.payment_method.sumup_payment_provider_id = False

        with self.assertRaises(UserError):
            self.payment_method.sumup_refund_payment("TEEPUC2VLF", 12.34)

    def test_refund_addresses_the_original_transaction(self):
        with patch(_SEND_REQUEST, side_effect=[
            {"id": "tx_0001", "transaction_code": "TEEPUC2VLF", "status": "SUCCESSFUL"},
            {},
        ]) as send_request:
            result = self.payment_method.sumup_refund_payment("TEEPUC2VLF", 12.34)

        self.assertTrue(result["successful"])
        method, endpoint = send_request.call_args[0][:2]
        self.assertEqual(method, "POST")
        self.assertEqual(endpoint, "/v1.0/merchants/MCTEST01/payments/tx_0001/refunds")
        self.assertEqual(send_request.call_args[1]["json"], {"amount": 12.34})

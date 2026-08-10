from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.payment.tests.http_common import PaymentHttpCommon
from odoo.addons.mb_payment_sumup.controllers.main import SumUpController
from odoo.addons.mb_payment_sumup.tests.common import SumUpCommon

_SEND_REQUEST = (
    "odoo.addons.payment.models.payment_provider.PaymentProvider._send_api_request"
)


@tagged("post_install", "-at_install")
class TestSumUp(SumUpCommon, PaymentHttpCommon):

    # === The request === #

    def test_request_url_keeps_the_version_of_the_endpoint(self):
        """SumUp serves checkouts, refunds and transactions from three
        different API versions, so the version belongs to the endpoint."""
        self.assertEqual(
            self.provider._build_request_url("/v0.1/checkouts"),
            "https://api.sumup.com/v0.1/checkouts",
        )
        self.assertEqual(
            self.provider._build_request_url("/v1.0/merchants/MC/payments/tx/refunds"),
            "https://api.sumup.com/v1.0/merchants/MC/payments/tx/refunds",
        )

    def test_checkout_payload_names_the_merchant_and_the_reference(self):
        tx = self._create_transaction(flow="redirect")

        payload = tx._sumup_prepare_checkout_payload()

        self.assertEqual(payload["checkout_reference"], tx.reference)
        self.assertEqual(payload["amount"], 1111.11)
        self.assertEqual(payload["currency"], "EUR")
        self.assertEqual(payload["merchant_code"], "MCTEST01")
        self.assertTrue(payload["hosted_checkout"]["enabled"])
        # Both callbacks carry the reference: SumUp returns neither it nor a
        # signature on its own.
        self.assertIn(f"ref={tx.reference}", payload["redirect_url"])
        self.assertIn(f"ref={tx.reference}", payload["return_url"])

    def test_missing_merchant_code_refuses_the_payment(self):
        """A checkout without a merchant code would be a payment into an
        unnamed account, so it must fail rather than default."""
        # A provider that is still enabled refuses to lose the field at all;
        # disabling it is the only way to reach the state being tested.
        self.provider.sudo().write({"state": "disabled", "sumup_merchant_code": False})
        tx = self._create_transaction(flow="redirect")

        with self.assertRaises(UserError):
            tx._sumup_prepare_checkout_payload()

    def test_rendering_values_return_the_hosted_checkout_url(self):
        tx = self._create_transaction(flow="redirect")

        with patch(_SEND_REQUEST, return_value=self.checkout_data):
            values = tx._get_specific_rendering_values(None)

        self.assertEqual(values["api_url"], "https://pay.sumup.com/b2c/QWERTY")
        self.assertEqual(tx.provider_reference, self.checkout_data["id"])
        self.assertEqual(tx.sumup_checkout_url, "https://pay.sumup.com/b2c/QWERTY")

    def test_existing_checkout_is_reused(self):
        """Re-opening a payment link must not mint a second checkout."""
        tx = self._create_transaction(flow="redirect")
        with patch(_SEND_REQUEST, return_value=self.checkout_data) as send_request:
            tx._sumup_create_checkout()
            tx._sumup_create_checkout()

        self.assertEqual(send_request.call_count, 1)

    def test_deactivating_checkout_removes_its_payable_url(self):
        tx = self._create_transaction(flow="redirect")
        tx.provider_reference = self.checkout_data["id"]
        tx.sumup_checkout_url = self.checkout_data["hosted_checkout_url"]

        with patch(_SEND_REQUEST, return_value=dict(self.checkout_data, status="EXPIRED")) as req:
            tx._sumup_deactivate_checkout()

        self.assertEqual(req.call_args[0][:2], (
            "DELETE", f"/v0.1/checkouts/{self.checkout_data['id']}"
        ))
        self.assertFalse(tx.sumup_checkout_url)
        self.assertEqual(tx.state, "cancel")

    # === The payment data === #

    def test_reference_is_read_from_either_shape(self):
        tx_model = self.env["payment.transaction"]
        self.assertEqual(
            tx_model._extract_reference("sumup", {"ref": "INV/2026/0001"}),
            "INV/2026/0001",
        )
        self.assertEqual(
            tx_model._extract_reference("sumup", {"checkout_reference": "INV/2026/0002"}),
            "INV/2026/0002",
        )

    def test_paid_checkout_confirms_and_records_the_transaction_id(self):
        tx = self._create_transaction(flow="redirect")

        tx._process("sumup", self._paid_checkout_data())

        self.assertEqual(tx.state, "done")
        # The refund endpoint addresses the transaction, not the checkout.
        self.assertEqual(tx.sumup_transaction_id, "tx_0001")

    def test_expired_checkout_cancels(self):
        tx = self._create_transaction(flow="redirect")

        tx._process("sumup", dict(self.checkout_data, status="EXPIRED"))

        self.assertEqual(tx.state, "cancel")

    @mute_logger("odoo.addons.payment.models.payment_transaction")
    def test_amount_mismatch_errors(self):
        """The amount is checked against the checkout, not assumed from it."""
        tx = self._create_transaction(flow="redirect")

        tx._process("sumup", dict(self._paid_checkout_data(), amount=1.0))

        self.assertEqual(tx.state, "error")

    # === The callbacks === #

    @mute_logger(
        "odoo.addons.mb_payment_sumup.controllers.main",
        "odoo.addons.mb_payment_sumup.models.payment_transaction",
    )
    def test_webhook_reads_the_checkout_back_before_settling(self):
        """The notification is a wake-up, never evidence: whatever the caller
        posts, the state comes from the API."""
        tx = self._create_transaction("redirect")
        tx.provider_reference = self.checkout_data["id"]
        url = self._build_url(SumUpController._webhook_url)

        with patch(_SEND_REQUEST, return_value=self._paid_checkout_data()) as send_request:
            self._make_http_post_request(url, data=dict(self.callback_data, status="FAILED"))

        send_request.assert_called_once()
        self.assertEqual(send_request.call_args[0][0], "GET")
        self.assertEqual(tx.state, "done")

    @mute_logger(
        "odoo.addons.mb_payment_sumup.controllers.main",
        "odoo.addons.payment.models.payment_transaction",
    )
    def test_webhook_for_an_unknown_reference_does_nothing(self):
        url = self._build_url(SumUpController._webhook_url)

        with patch(_SEND_REQUEST) as send_request:
            self._make_http_post_request(url, data={"ref": "no-such-reference"})

        send_request.assert_not_called()

    # === Polling === #

    def test_cron_settles_a_checkout_nobody_came_back_from(self):
        """The QR code on a printed invoice is paid without any Odoo page ever
        being loaded, which is what this cron exists for."""
        tx = self._create_transaction("redirect")
        tx.provider_reference = self.checkout_data["id"]
        tx._set_pending()

        with patch(_SEND_REQUEST, return_value=self._paid_checkout_data()):
            self.env["payment.transaction"]._cron_poll_sumup_checkouts()

        self.assertEqual(tx.state, "done")

    # === Refunds === #

    def test_refund_addresses_the_sumup_transaction(self):
        tx = self._create_transaction("redirect", state="done")
        tx.sumup_transaction_id = "tx_0001"

        with patch(_SEND_REQUEST, return_value={}) as send_request:
            refund_tx = tx._refund(amount_to_refund=100.0)

        method, endpoint = send_request.call_args[0][:2]
        self.assertEqual(method, "POST")
        self.assertEqual(
            endpoint, "/v1.0/merchants/MCTEST01/payments/tx_0001/refunds"
        )
        # Odoo holds refunds as negative amounts; SumUp only knows positive ones.
        self.assertEqual(send_request.call_args[1]["json"], {"amount": 100.0})
        self.assertEqual(refund_tx.state, "pending")
        self.assertEqual(refund_tx.sumup_refund_target_amount, 100.0)

    def test_refund_is_done_only_after_sumup_reports_its_event(self):
        tx = self._create_transaction("redirect", state="done")
        tx.sumup_transaction_id = "tx_0001"
        with patch(_SEND_REQUEST, return_value={}):
            refund_tx = tx._refund(amount_to_refund=100.0)

        with patch(_SEND_REQUEST, return_value={
            "id": "tx_0001",
            "events": [{"type": "REFUND", "status": "REFUNDED", "amount": 100.0}],
        }):
            refund_tx._sumup_poll_refund()

        self.assertEqual(refund_tx.state, "done")

    def test_pending_refund_stays_pending_without_settlement_event(self):
        tx = self._create_transaction("redirect", state="done")
        tx.sumup_transaction_id = "tx_0001"
        with patch(_SEND_REQUEST, return_value={}):
            refund_tx = tx._refund(amount_to_refund=100.0)

        with patch(_SEND_REQUEST, return_value={"id": "tx_0001", "events": []}):
            refund_tx._sumup_poll_refund()

        self.assertEqual(refund_tx.state, "pending")

    def test_refund_of_an_unpaid_checkout_is_refused(self):
        tx = self._create_transaction("redirect", state="done")

        with self.assertRaises(UserError):
            tx._refund(amount_to_refund=100.0)

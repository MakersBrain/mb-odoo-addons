from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon

_SEND_REQUEST = (
    "odoo.addons.payment.models.payment_provider.PaymentProvider._send_api_request"
)


@tagged("post_install", "-at_install")
class TestInvoiceSumUpLink(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.provider = cls.env["payment.provider"].search([
            ("code", "=", "sumup"), ("company_id", "=", cls.env.company.id),
        ], limit=1)
        cls.provider.write({
            "state": "test",
            "sumup_api_key": "sup_sk_dummy",
            "sumup_merchant_code": "MCTEST01",
        })
        cls.invoice = cls.init_invoice(
            "out_invoice", partner=cls.partner_a, amounts=[100.0], post=True
        )

    def _checkout_response(self, **overrides):
        return dict({
            "id": "cd0d6c1a-0000-4000-8000-000000000001",
            "checkout_reference": "ref",
            "amount": self.invoice.amount_total,
            "currency": self.invoice.currency_id.name,
            "status": "PENDING",
            "hosted_checkout_url": "https://pay.sumup.com/b2c/QWERTY",
            "transactions": [],
        }, **overrides)

    def _open_wizard(self):
        return self.env["mb.sumup.link.wizard"].with_context(
            default_move_id=self.invoice.id
        ).create({})

    # === The wizard === #

    def test_wizard_defaults_to_what_is_still_due(self):
        wizard = self._open_wizard()

        self.assertEqual(wizard.amount, self.invoice.amount_residual)
        self.assertEqual(wizard.destination, "sumup")

    def test_sumup_link_creates_a_checkout_bound_to_the_invoice(self):
        wizard = self._open_wizard()

        with patch(_SEND_REQUEST, return_value=self._checkout_response()) as send_request:
            wizard.action_generate()

        endpoint = send_request.call_args[0][1]
        self.assertEqual(endpoint, "/v0.1/checkouts")
        self.assertEqual(wizard.link, "https://pay.sumup.com/b2c/QWERTY")
        self.assertTrue(wizard.qr_code)
        tx = self.invoice.mb_sumup_transaction_id
        self.assertEqual(tx.sumup_checkout_url, "https://pay.sumup.com/b2c/QWERTY")
        self.assertEqual(tx.invoice_ids, self.invoice)
        self.assertEqual(tx.amount, self.invoice.amount_residual)

    def test_the_same_link_is_handed_out_twice(self):
        """A link already printed on a PDF has to keep working."""
        wizard = self._open_wizard()

        with patch(_SEND_REQUEST, return_value=self._checkout_response()) as send_request:
            wizard.action_generate()
            self._open_wizard().action_generate()

        self.assertEqual(send_request.call_count, 1)

    def test_a_different_amount_gets_its_own_checkout(self):
        wizard = self._open_wizard()

        with patch(_SEND_REQUEST, side_effect=[
            self._checkout_response(),
            self._checkout_response(status="EXPIRED"),
            self._checkout_response(
                id="cd0d6c1a-0000-4000-8000-000000000002",
                hosted_checkout_url="https://pay.sumup.com/b2c/ASDFGH",
                amount=40.0,
            ),
        ]) as send_request:
            wizard.action_generate()
            partial = self._open_wizard()
            partial.amount = 40.0
            partial.action_generate()

        self.assertEqual(send_request.call_count, 3)
        self.assertEqual(send_request.call_args_list[1].args[:2], (
            "DELETE", f"/v0.1/checkouts/{self._checkout_response()['id']}"
        ))
        self.assertEqual(self.invoice.mb_sumup_transaction_id.amount, 40.0)

    def test_amount_over_current_residual_is_refused(self):
        wizard = self._open_wizard()
        wizard.amount = self.invoice.amount_residual + 0.01

        with patch(_SEND_REQUEST) as send_request, self.assertRaises(UserError):
            wizard.action_generate()

        send_request.assert_not_called()

    def test_zero_amount_is_refused(self):
        wizard = self._open_wizard()
        wizard.amount = 0.0

        with self.assertRaises(UserError):
            wizard.action_generate()

    def test_portal_destination_asks_no_api(self):
        wizard = self._open_wizard()
        wizard.destination = "portal"

        with patch(_SEND_REQUEST) as send_request:
            wizard.action_generate()

        send_request.assert_not_called()
        # The portal link is the invoice's own page, with the signed token that
        # lets someone who is not logged in open it.
        self.assertIn(f"/my/invoices/{self.invoice.id}", wizard.link)
        self.assertIn("payment_token", wizard.link)
        self.assertTrue(wizard.link.endswith("#portal_pay"))
        self.assertTrue(wizard.qr_code)

    # === The printed invoice === #

    def test_a_sumup_link_replaces_the_portal_qr_on_the_pdf(self):
        """Two QR codes on one invoice is a question, not an instruction."""
        self.env.company.link_qr_code = True
        self.invoice.invalidate_recordset(["display_link_qr_code"])
        self.assertTrue(self.invoice.display_link_qr_code)

        with patch(_SEND_REQUEST, return_value=self._checkout_response()):
            self._open_wizard().action_generate()

        self.assertFalse(self.invoice.display_link_qr_code)
        self.assertTrue(self.invoice._mb_sumup_payment_qr().startswith("data:image/png;base64,"))

    # === Settlement === #

    def test_paying_the_checkout_pays_the_invoice(self):
        with patch(_SEND_REQUEST, return_value=self._checkout_response()):
            self._open_wizard().action_generate()
        tx = self.invoice.mb_sumup_transaction_id

        tx._process("sumup", self._checkout_response(
            status="PAID", transactions=[{"id": "tx_0001", "status": "SUCCESSFUL"}]
        ))
        tx._post_process()

        self.assertEqual(tx.state, "done")
        self.assertEqual(self.invoice.payment_state, "paid")

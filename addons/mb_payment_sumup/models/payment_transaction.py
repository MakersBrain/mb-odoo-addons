from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import urls

from odoo.addons.payment.logging import get_payment_logger

from .. import const
from ..controllers.main import SumUpController

_logger = get_payment_logger(__name__)


class PaymentTransaction(models.Model):
    _inherit = "payment.transaction"

    sumup_checkout_url = fields.Char(
        string="SumUp Checkout URL",
        help="The SumUp-hosted page that takes this payment. It is what a "
        "payment link points at and what a QR code encodes.",
        readonly=True,
        copy=False,
    )
    sumup_transaction_id = fields.Char(
        string="SumUp Transaction ID",
        help="The identifier of the transaction inside the checkout. Refunds "
        "are addressed to it, not to the checkout.",
        readonly=True,
        copy=False,
    )
    sumup_refund_target_amount = fields.Monetary(
        string="SumUp Refund Target",
        currency_field="currency_id",
        readonly=True,
        copy=False,
        help="Cumulative successful refund amount that SumUp must report "
        "before this refund transaction may be completed.",
    )

    # === BUSINESS METHODS - PAYMENT FLOW === #

    def _get_specific_rendering_values(self, processing_values):
        """Override of `payment` to return SumUp-specific rendering values.

        Note: `self.ensure_one()` from `_get_processing_values`

        :param dict processing_values: The generic and specific processing values of the transaction
        :return: The dict of provider-specific rendering values
        :rtype: dict
        """
        if self.provider_code != "sumup":
            return super()._get_specific_rendering_values(processing_values)

        checkout_url = self._sumup_create_checkout()
        if not checkout_url:
            return {}
        return {"api_url": checkout_url}

    def _sumup_create_checkout(self):
        """Create the SumUp checkout that will take this transaction's payment.

        The checkout is created once and then reused: calling this a second time
        on a transaction that already has a live checkout returns the same URL,
        so re-opening a payment link does not leave a trail of abandoned
        checkouts in the merchant's reporting.

        Note: `self.ensure_one()`

        :return: The URL of the SumUp-hosted checkout page, empty on failure.
        :rtype: str
        """
        self.ensure_one()

        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(%s, %s)",
            [0x4D425054, self.id],
        )
        self.invalidate_recordset(["sumup_checkout_url", "state"])
        if self.sumup_checkout_url and self.state in ("draft", "pending"):
            return self.sumup_checkout_url

        self._ensure_provider_is_not_disabled()

        payload = self._sumup_prepare_checkout_payload()
        try:
            checkout_data = self._send_api_request("POST", "/v0.1/checkouts", json=payload)
        except (UserError, ValidationError) as error:
            self._set_error(str(error))
            return ""

        # Set now rather than on the callback: without it, a customer who pays
        # and never comes back cannot be matched to this transaction at all.
        self.provider_reference = checkout_data.get("id")
        self.sumup_checkout_url = checkout_data.get("hosted_checkout_url")
        return self.sumup_checkout_url or ""

    def _sumup_deactivate_checkout(self):
        """Deactivate a checkout before replacing its public link."""
        self.ensure_one()
        if self.provider_code != "sumup" or not self.provider_reference:
            return
        if self.state not in ("draft", "pending"):
            raise UserError(_("A completed SumUp checkout cannot be replaced."))
        self._send_api_request("DELETE", f"/v0.1/checkouts/{self.provider_reference}")
        self.sumup_checkout_url = False
        self._set_canceled(_("This SumUp checkout was replaced by a new payment link."))

    def _sumup_prepare_checkout_payload(self):
        """Create the payload of the checkout request from the transaction.

        Note: `self.ensure_one()`

        :return: The request payload.
        :rtype: dict
        """
        self.ensure_one()

        base_url = self.provider_id.get_base_url()
        redirect_url = urls.urljoin(base_url, SumUpController._return_url)
        webhook_url = urls.urljoin(base_url, SumUpController._webhook_url)
        return {
            "checkout_reference": self.reference,
            "amount": self.currency_id.round(self.amount),
            "currency": self.currency_id.name,
            "merchant_code": self.provider_id._sumup_get_merchant_code(),
            "description": self.reference,
            # SumUp returns neither the reference nor a signature on either
            # callback, so the reference travels in the URL we hand them and
            # the payment data is read back from the API before use.
            "redirect_url": f"{redirect_url}?ref={self.reference}",
            "return_url": f"{webhook_url}?ref={self.reference}",
            "hosted_checkout": {"enabled": True},
        }

    def _send_refund_request(self):
        """Override of `payment` to send a refund request to SumUp."""
        if self.provider_code != "sumup":
            return super()._send_refund_request()

        source_tx = self.source_transaction_id
        if not source_tx.sumup_transaction_id:
            raise UserError(
                _(
                    "This payment has no SumUp transaction to refund. A checkout "
                    "that was never paid has nothing to give back."
                )
            )

        merchant_code = self.provider_id._sumup_get_merchant_code()
        self._send_api_request(
            "POST",
            f"/v1.0/merchants/{merchant_code}/payments/{source_tx.sumup_transaction_id}/refunds",
            # The amount of a refund transaction is negative in Odoo and
            # positive everywhere at SumUp.
            json={"amount": self.currency_id.round(-self.amount)},
        )
        # An empty response acknowledges only the request.  Transactions are
        # the authoritative SumUp record; the polling job completes this Odoo
        # refund only after a successful refund event appears there.
        self.provider_reference = source_tx.provider_reference
        earlier_refunds = source_tx.child_transaction_ids.filtered(
            lambda tx: tx != self and tx.operation == "refund" and tx.state in ("pending", "done")
        )
        self.sumup_refund_target_amount = self.currency_id.round(
            sum(-tx.amount for tx in earlier_refunds) - self.amount
        )
        self._set_pending()

    # === BUSINESS METHODS - PAYMENT DATA === #

    @api.model
    def _extract_reference(self, provider_code, payment_data):
        """Override of `payment` to extract the reference from the payment data.

        `ref` is the parameter this module puts on the callback URLs; the
        checkout read back from the API carries `checkout_reference` instead.
        """
        if provider_code != "sumup":
            return super()._extract_reference(provider_code, payment_data)
        return payment_data.get("ref") or payment_data.get("checkout_reference")

    def _extract_amount_data(self, payment_data):
        """Override of `payment` to extract the amount and currency."""
        if self.provider_code != "sumup":
            return super()._extract_amount_data(payment_data)

        return {
            "amount": float(payment_data.get("amount") or 0.0),
            "currency_code": payment_data.get("currency"),
        }

    def _apply_updates(self, payment_data):
        """Override of `payment` to update the transaction from the checkout."""
        if self.provider_code != "sumup":
            return super()._apply_updates(payment_data)

        if not self.provider_reference and payment_data.get("id"):
            self.provider_reference = payment_data["id"]

        # A paid checkout carries the transaction that paid it, and that is the
        # identifier a refund has to name later.
        transactions = payment_data.get("transactions") or []
        if transactions:
            self.sumup_transaction_id = transactions[0].get("id")

        payment_status = payment_data.get("status")
        target_state = const.CHECKOUT_STATUS.get(payment_status)
        if target_state == "pending":
            self._set_pending()
        elif target_state == "done":
            self._set_done()
        elif target_state == "cancel":
            self._set_canceled(_("SumUp reported the checkout as %s.", payment_status))
        else:
            _logger.info(
                "Received data with invalid checkout status (%s) for transaction %s.",
                payment_status,
                self.reference,
            )
            self._set_error(_("Received data with invalid checkout status: %s.", payment_status))

    # === BUSINESS METHODS - POLLING === #

    def _sumup_poll_checkout(self):
        """Read the checkout back from SumUp and process what it says.

        Note: `self.ensure_one()`

        :return: None
        """
        self.ensure_one()

        if not self.provider_reference:
            return
        try:
            checkout_data = self._send_api_request(
                "GET", f"/v0.1/checkouts/{self.provider_reference}"
            )
        except (UserError, ValidationError):
            _logger.warning("Unable to read SumUp checkout for %s.", self.reference)
            return
        self._process("sumup", checkout_data)

    def _sumup_poll_refund(self):
        """Complete an acknowledged refund from SumUp's transaction events."""
        self.ensure_one()
        source_tx = self.source_transaction_id
        if not source_tx.sumup_transaction_id:
            return
        try:
            transaction_data = self._send_api_request(
                "GET",
                f"/v2.1/merchants/{self.provider_id._sumup_get_merchant_code()}/transactions",
                params={"id": source_tx.sumup_transaction_id},
            )
        except (UserError, ValidationError):
            _logger.warning("Unable to verify SumUp refund %s.", self.reference)
            return

        events = transaction_data.get("events") or transaction_data.get("transaction_events") or []
        refunded_amount = self.currency_id.round(
            sum(
                abs(float(event.get("amount") or 0.0))
                for event in events
                if (event.get("type") or event.get("event_type")) == "REFUND"
                and event.get("status") in ("REFUNDED", "SUCCESSFUL")
            )
        )
        if self.currency_id.compare_amounts(refunded_amount, self.sumup_refund_target_amount) >= 0:
            self._set_done()
        elif transaction_data.get("simple_status") == "REFUND_FAILED":
            self._set_error(_("SumUp reported that the refund failed."))

    @api.model
    def _cron_poll_sumup_checkouts(self):
        """Settle checkouts nobody came back from.

        A QR code on a printed invoice is paid on the customer's phone, on
        SumUp's page, and the customer has no reason to ever load an Odoo page
        afterwards. SumUp's `return_url` notification usually covers that, but
        it is unsigned, best-effort and useless when this instance was
        unreachable at the moment they sent it. So the state of record is what
        the API says, and this cron is what asks.

        :return: None
        """
        transactions = self.search(
            [
                ("provider_code", "=", "sumup"),
                ("state", "in", ("draft", "pending")),
                ("provider_reference", "!=", False),
                ("operation", "!=", "refund"),
            ],
            limit=200,
        )
        for tx in transactions:
            tx._sumup_poll_checkout()

        refunds = self.search(
            [
                ("provider_code", "=", "sumup"),
                ("state", "=", "pending"),
                ("operation", "=", "refund"),
                ("source_transaction_id.sumup_transaction_id", "!=", False),
            ],
            limit=200,
        )
        for tx in refunds:
            tx._sumup_poll_refund()

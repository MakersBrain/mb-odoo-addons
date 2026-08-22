import logging
from urllib.parse import urlencode

from odoo import _, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.mb_payment_sumup import const

_logger = logging.getLogger(__name__)

# The scheme the SumUp app registers on both platforms.
SUMUP_PAY_URL = "sumupmerchant://pay/1.0"

# `foreign-tx-id` is what SumUp echoes back and what this module matches the
# payment line on. SumUp caps it at 128 printable ASCII characters; a POS
# payment uuid is 36.
FOREIGN_TX_ID_MAX_LENGTH = 128


class PosPaymentMethod(models.Model):
    _inherit = "pos.payment.method"

    def _get_payment_terminal_selection(self):
        return super()._get_payment_terminal_selection() + [
            ("sumup_mobile", "SumUp (mobile app)"),
        ]

    sumup_affiliate_key = fields.Char(
        string="SumUp Affiliate Key",
        help="From Developer settings in the SumUp dashboard. The key allows "
        "a list of application identifiers, and the POS runs in a "
        "browser rather than in an application of yours, so that list "
        "has to include the browser: on iOS the SumUp app reports the "
        "caller as com.sumup.appswitch, whatever the URL says. Add it to "
        "the key beside your own identifier.",
        copy=False,
    )
    sumup_app_id = fields.Char(
        string="SumUp App ID",
        help="Sent as the app-id parameter, which only Android reads. iOS "
        "takes no such parameter and derives the caller itself - see the "
        "affiliate key above. Use an identifier registered on the key.",
        copy=False,
    )
    sumup_payment_provider_id = fields.Many2one(
        comodel_name="payment.provider",
        string="SumUp Account",
        domain=[("code", "=", "sumup"), ("state", "in", ("enabled", "test"))],
        check_company=True,
        help="The SumUp account used to verify a payment against SumUp's own "
        "records and to refund it. It is mandatory: callback URL "
        "parameters are never accepted as payment evidence.",
    )
    sumup_skip_success_screen = fields.Boolean(
        string="Skip SumUp Success Screen",
        default=True,
        help="Return to the POS as soon as the card is approved instead of "
        "waiting for the cashier to dismiss SumUp's own screen.",
    )

    # === HELPERS === #

    def _sumup_provider_sudo(self):
        """Return the SumUp provider, refusing to run without one.

        Note: `self.ensure_one()`

        :return: The provider record, in sudo.
        :rtype: recordset of `payment.provider`
        :raise UserError: If no SumUp account is configured.
        """
        self.ensure_one()
        provider_sudo = self.sudo().sumup_payment_provider_id
        if (
            not provider_sudo
            or provider_sudo.code != "sumup"
            or provider_sudo.state not in ("enabled", "test")
            or provider_sudo.company_id != self.company_id
            or not provider_sudo.sudo().sumup_api_key
        ):
            raise UserError(
                _(
                    "Set an enabled SumUp account for the same company on payment method %s.",
                    self.display_name,
                )
            )
        provider_sudo._sumup_get_merchant_code()
        return provider_sudo

    def _sumup_find_transaction(self, **query):
        """Read one transaction from SumUp's records.

        Note: `self.ensure_one()`

        :param dict query: One of the identifying query parameters accepted by
                           SumUp: `foreign_transaction_id`, `transaction_code`
                           or `id`.
        :return: The transaction, or an empty dict when SumUp has none.
        :rtype: dict
        """
        self.ensure_one()

        provider_sudo = self._sumup_provider_sudo()
        merchant_code = provider_sudo._sumup_get_merchant_code()
        try:
            return provider_sudo._send_api_request(
                "GET", f"/v2.1/merchants/{merchant_code}/transactions", params=query
            )
        except (UserError, ValidationError):
            # A payment SumUp has no record of is not a payment. The caller
            # reports it as unconfirmed rather than as an error, because the
            # cashier's next move is the same either way: take the money again.
            _logger.warning("SumUp has no transaction matching %s.", query)
            return {}

    # === POS METHODS === #

    def sumup_prepare_payment(self, amount, payment_uuid, callback_url, title=None):
        """Build the URL that hands this payment to the SumUp app.

        Note: `self.ensure_one()`

        :param float amount: The amount to charge, in the POS currency.
        :param str payment_uuid: The uuid of the POS payment line, sent as
                                 `foreign-tx-id` and echoed back by SumUp.
        :param str callback_url: The POS page to come back to. It must belong
                                 to this Odoo instance.
        :param str title: What the cashier sees on the SumUp screen.
        :return: The deep link to open.
        :rtype: str
        :raise UserError: If the method is not configured, or the callback is
                          not one of ours.
        """
        self.ensure_one()

        self._sumup_provider_sudo()
        if not self.sumup_affiliate_key:
            raise UserError(
                _(
                    "Set the SumUp affiliate key on the payment method %s before "
                    "taking a payment with it.",
                    self.display_name,
                )
            )
        if len(payment_uuid) > FOREIGN_TX_ID_MAX_LENGTH:
            raise UserError(_("The payment identifier is too long for SumUp."))

        base_url = self.get_base_url()
        if not callback_url or not callback_url.startswith(base_url):
            # The callback is where the SumUp app sends the cashier next.
            # Nothing outside this instance has any business being there.
            raise UserError(_("The SumUp callback must return to this Odoo instance."))

        currency = self.journal_id.currency_id or self.company_id.currency_id
        params = {
            "affiliate-key": self.sumup_affiliate_key,
            # `total` is what Android reads and `amount` is what iOS reads, so
            # one URL needs both platform-specific parameters.
            "total": currency.round(amount),
            "amount": currency.round(amount),
            "currency": currency.name,
            "foreign-tx-id": payment_uuid,
            # `callback` is Android's parameter, `callbacksuccess` and
            # `callbackfail` are iOS's. All three point at the same page: the
            # outcome is read from `smp-status`, not from which URL was opened.
            "callback": callback_url,
            "callbacksuccess": callback_url,
            "callbackfail": callback_url,
        }
        if self.sumup_app_id:
            params["app-id"] = self.sumup_app_id
        if title:
            params["title"] = title
        if self.sumup_skip_success_screen:
            params["skip-screen-success"] = "true"

        return f"{SUMUP_PAY_URL}?{urlencode(params)}"

    def sumup_confirm_payment(self, payment_uuid, amount, callback_params):
        """Decide whether the payment line may be marked paid.

        The callback parameters are a claim made by a URL. When a SumUp account
        is configured, that claim is checked against SumUp's own record of the
        transaction - existence, status and amount - and the record wins.

        Note: `self.ensure_one()`

        :param str payment_uuid: The uuid of the POS payment line.
        :param float amount: The amount the POS believes was charged.
        :param dict callback_params: The parameters SumUp put on the callback.
        :return: What the POS needs to finish the line.
        :rtype: dict
        """
        self.ensure_one()

        provider_sudo = self._sumup_provider_sudo()

        transaction = self._sumup_find_transaction(foreign_transaction_id=payment_uuid)
        if not transaction:
            return {
                "successful": False,
                "verified": True,
                "message": _("SumUp has no record of this payment."),
            }

        currency = self.journal_id.currency_id or self.company_id.currency_id
        successful = transaction.get("status") == const.TRANSACTION_STATUS_SUCCESSFUL
        expected_merchant = provider_sudo._sumup_get_merchant_code()
        evidence_matches = (
            transaction.get("foreign_transaction_id") == payment_uuid
            and transaction.get("currency") == currency.name
            and transaction.get("merchant_code") == expected_merchant
        )
        if successful and not evidence_matches:
            return {
                "successful": False,
                "verified": True,
                "message": _(
                    "SumUp returned payment evidence for a different reference, "
                    "currency, or merchant account."
                ),
            }
        if (
            successful
            and currency.compare_amounts(
                float(transaction.get("amount") or 0.0), currency.round(amount)
            )
            != 0
        ):
            return {
                "successful": False,
                "verified": True,
                "message": _(
                    "SumUp took %(charged)s for this payment, not %(expected)s.",
                    charged=transaction.get("amount"),
                    expected=currency.round(amount),
                ),
            }

        card = transaction.get("card") or {}
        return {
            "successful": successful,
            "verified": True,
            "transaction_code": transaction.get("transaction_code") or "",
            "transaction_uid": transaction.get("id") or "",
            "card_no": card.get("last_4_digits") or "",
            "card_brand": card.get("type") or "",
            "card_type": transaction.get("entry_mode") or "",
            "message": ""
            if successful
            else _("SumUp reported this payment as %s.", transaction.get("status")),
        }

    def sumup_refund_payment(self, transaction_code, amount):
        """Refund a payment taken earlier through the SumUp app.

        The app's URL scheme has no refund verb, so this is an API call and it
        needs the SumUp account configured.

        Note: `self.ensure_one()`

        :param str transaction_code: The code of the payment to refund.
        :param float amount: The positive amount to give back.
        :return: Whether SumUp accepted the refund.
        :rtype: dict
        """
        self.ensure_one()

        provider_sudo = self._sumup_provider_sudo()
        transaction = self._sumup_find_transaction(transaction_code=transaction_code)
        if not transaction.get("id"):
            return {
                "successful": False,
                "message": _("SumUp has no record of the payment to refund."),
            }

        currency = self.journal_id.currency_id or self.company_id.currency_id
        merchant_code = provider_sudo._sumup_get_merchant_code()
        try:
            provider_sudo._send_api_request(
                "POST",
                f"/v1.0/merchants/{merchant_code}/payments/{transaction['id']}/refunds",
                json={"amount": currency.round(abs(amount))},
            )
        except (UserError, ValidationError) as error:
            return {"successful": False, "message": str(error)}
        # SumUp acknowledges with an empty 200 and settles the refund later.
        return {"successful": True, "transaction_code": transaction_code}

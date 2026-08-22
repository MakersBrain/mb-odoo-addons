from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools import urls

from .. import const


class PaymentProvider(models.Model):
    _inherit = "payment.provider"

    code = fields.Selection(selection_add=[("sumup", "SumUp")], ondelete={"sumup": "set default"})

    sumup_api_key = fields.Char(
        string="SumUp Secret Key",
        help="The secret key (sup_sk_...) of this workshop's SumUp account, "
        "from Developer settings in the SumUp dashboard.",
        required_if_provider="sumup",
        copy=False,
        # Same posture as every other provider in Odoo: the key is a column in
        # this database, restricted to the system group, never logged and never
        # copied when the provider is duplicated.
        groups="base.group_system",
    )
    sumup_merchant_code = fields.Char(
        string="SumUp Merchant Code",
        help="The merchant account that receives the money. Every checkout "
        "names it explicitly, so it has to be the account whose legal "
        "identity is printed on the invoice.",
        required_if_provider="sumup",
        copy=False,
    )

    # === COMPUTE METHODS === #

    def _compute_feature_support_fields(self):
        """Override of `payment` to declare what SumUp supports."""
        super()._compute_feature_support_fields()
        self.filtered(lambda p: p.code == "sumup").update(
            {
                # SumUp refunds a transaction fully or in part, from a separate
                # endpoint. Capture is not separable: the hosted checkout captures.
                "support_refund": "partial",
            }
        )

    def _get_supported_currencies(self):
        """Override of `payment` to return the supported currencies."""
        supported_currencies = super()._get_supported_currencies()
        if self.code == "sumup":
            supported_currencies = supported_currencies.filtered(
                lambda c: c.name in const.SUPPORTED_CURRENCIES
            )
        return supported_currencies

    # === CRUD METHODS === #

    def _get_default_payment_method_codes(self):
        """Override of `payment` to return the default payment method codes."""
        self.ensure_one()

        if self.code != "sumup":
            return super()._get_default_payment_method_codes()
        return const.DEFAULT_PAYMENT_METHOD_CODES

    def _get_removal_values(self):
        """Override of `payment` to clear the credentials when uninstalled."""
        res = super()._get_removal_values()
        res["sumup_api_key"] = None
        res["sumup_merchant_code"] = None
        return res

    # === REQUEST HELPERS === #

    def _build_request_url(self, endpoint, **kwargs):
        """Override of `payment` to build the request URL.

        The version is part of the endpoint rather than of the base URL because
        SumUp serves checkouts from v0.1, refunds from v1.0 and transactions
        from v2.1.
        """
        if self.code != "sumup":
            return super()._build_request_url(endpoint, **kwargs)
        return urls.urljoin(const.API_URL, endpoint.lstrip("/"))

    def _build_request_headers(self, *args, **kwargs):
        """Override of `payment` to build the request headers."""
        if self.code != "sumup":
            return super()._build_request_headers(*args, **kwargs)

        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.sudo().sumup_api_key}",
            "Content-Type": "application/json",
        }

    def _parse_response_error(self, response):
        """Override of `payment` to parse the error message.

        SumUp answers with `message` on the checkout endpoints and with
        `error_message` on transaction endpoints.
        """
        if self.code != "sumup":
            return super()._parse_response_error(response)

        content = response.json()
        return content.get("message") or content.get("error_message") or response.text

    # === BUSINESS METHODS === #

    def _sumup_get_merchant_code(self):
        """Return the merchant code, refusing to guess when it is missing.

        Note: `self.ensure_one()`

        :return: The merchant code of this provider.
        :rtype: str
        :raise UserError: If no merchant code is recorded.
        """
        self.ensure_one()
        merchant_code = self.sudo().sumup_merchant_code
        if not merchant_code:
            raise UserError(
                _(
                    "No SumUp merchant code is set on the provider %s. No payment "
                    "can be taken until it is, because the merchant code is what "
                    "decides which account receives the money.",
                    self.display_name,
                )
            )
        return merchant_code

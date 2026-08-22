from __future__ import annotations

import secrets

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.mb_webshop_carrier_base.provider import ProviderError, provider_class


class DeliveryCarrier(models.Model):
    _inherit = "delivery.carrier"

    delivery_type = fields.Selection(
        selection_add=[("mb_boxtal", "Boxtal")],
        ondelete={"mb_boxtal": "set default"},
    )
    mb_boxtal_use_locations = fields.Boolean(
        string="Offer uses parcel points",
        help="Require the customer to choose a Boxtal parcel point at checkout.",
    )
    mb_boxtal_length_cm = fields.Float(string="Default parcel length (cm)", default=30)
    mb_boxtal_width_cm = fields.Float(string="Default parcel width (cm)", default=20)
    mb_boxtal_height_cm = fields.Float(string="Default parcel height (cm)", default=15)
    mb_boxtal_content_category = fields.Char(
        string="Boxtal content category", default="content:v1:10150"
    )
    mb_boxtal_content_description = fields.Char(
        string="Parcel content description", default="Handmade ceramic goods"
    )
    mb_boxtal_commercial_readiness_confirmed = fields.Boolean(
        string="Boxtal commercial readiness confirmed",
        help=(
            "Manual release gate: the merchant confirms that Boxtal enabled "
            "deferred direct-debit payment and that the configured offer is "
            "usable. The connection test cannot verify these commercial settings."
        ),
    )

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            if values.get("delivery_type") == "mb_boxtal":
                values.setdefault("mb_provider_code", "boxtal")
                values.setdefault("company_id", self.env.company.id)
                values.setdefault("mb_subscription_id", secrets.token_urlsafe(24))
        return super().create(values_list)

    def write(self, values):
        if values.get("delivery_type") == "mb_boxtal":
            values = dict(values)
            values.setdefault("mb_provider_code", "boxtal")
            values.setdefault("company_id", self.env.company.id)
            for carrier in self.filtered(lambda record: not record.mb_subscription_id):
                carrier.mb_subscription_id = secrets.token_urlsafe(24)
        return super().write(values)

    @api.constrains(
        "delivery_type",
        "mb_boxtal_length_cm",
        "mb_boxtal_width_cm",
        "mb_boxtal_height_cm",
        "mb_label_format",
    )
    def _check_boxtal_dimensions(self):
        for carrier in self.filtered(lambda record: record.delivery_type == "mb_boxtal"):
            if (
                min(
                    carrier.mb_boxtal_length_cm,
                    carrier.mb_boxtal_width_cm,
                    carrier.mb_boxtal_height_cm,
                )
                <= 0
            ):
                raise ValidationError(_("Boxtal parcel dimensions must be greater than zero."))
            if carrier.mb_label_format not in ("A4", "10x15"):
                raise ValidationError(_("Boxtal supports only A4 and 10 × 15 cm PDF labels."))

    @api.depends("delivery_type")
    def _compute_can_generate_return(self):
        super()._compute_can_generate_return()
        self.filtered(
            lambda carrier: carrier.delivery_type == "mb_boxtal"
        ).can_generate_return = False

    def mb_boxtal_rate_shipment(self, order):
        return self.base_on_rule_rate_shipment(order)

    def mb_boxtal_send_shipping(self, pickings):
        return self._mb_send_shipping(pickings)

    def mb_boxtal_cancel_shipment(self, pickings):
        return self._mb_cancel_shipment(pickings)

    def mb_boxtal_get_tracking_link(self, picking):
        return self._mb_get_tracking_link(picking)

    def _mb_boxtal_get_close_locations(self, partner_address, **kwargs):
        return self._mb_get_close_locations(partner_address)

    def _mb_boxtal_get_default_custom_package_code(self):
        return False

    def action_mb_test_connection(self):
        for carrier in self.filtered(lambda record: record.delivery_type == "mb_boxtal"):
            if not carrier.mb_provider_service_code:
                raise UserError(
                    _("Configure a Boxtal shipping offer before testing the connection.")
                )
            if carrier.prod_environment and not carrier.mb_boxtal_commercial_readiness_confirmed:
                raise UserError(
                    _(
                        "Confirm Boxtal deferred-payment and shipping-offer readiness before enabling production."
                    )
                )
        result = super().action_mb_test_connection()
        for carrier in self.filtered(lambda record: record.delivery_type == "mb_boxtal"):
            try:
                if not carrier.mb_subscription_id:
                    raise UserError(_("The Boxtal webhook endpoint is not configured."))
                base_url = (
                    self.env["ir.config_parameter"].sudo().get_param("web.base.url", "").rstrip("/")
                )
                if not base_url.startswith("https://"):
                    raise UserError(
                        _("A public HTTPS web base URL is required for Boxtal webhooks.")
                    )
                callback = f"{base_url}/mb_carrier/webhook/boxtal/{carrier.mb_subscription_id}"
                provider = carrier._mb_provider()
                provider.reconcile_subscriptions(callback, carrier._mb_webhook_secret())
            except (ProviderError, UserError) as error:
                carrier.sudo().write(
                    {
                        "mb_credential_state": "unconfigured",
                        "mb_last_error": "webhook_subscription_failed",
                    }
                )
                raise UserError(_("Boxtal webhook setup failed.")) from error
        return result

    def _mb_resume_webhooks(self):
        carriers = self.filtered(
            lambda record: record.delivery_type == "mb_boxtal" and record.mb_secret_ref
        )
        if not carriers:
            return True
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "").rstrip("/")
        if not base_url.startswith("https://"):
            raise UserError(_("A public HTTPS web base URL is required for Boxtal webhooks."))
        for carrier in carriers:
            if not carrier.mb_subscription_id:
                carrier.mb_subscription_id = secrets.token_urlsafe(24)
            callback = f"{base_url}/mb_carrier/webhook/boxtal/{carrier.mb_subscription_id}"
            try:
                carrier._mb_provider(purpose="webhook_reactivation").reconcile_subscriptions(
                    callback,
                    carrier._mb_webhook_secret(purpose="webhook_reactivation"),
                )
                carrier.mb_last_error = False
            except (ProviderError, UserError) as error:
                carrier.mb_last_error = "webhook_subscription_failed"
                raise UserError(_("Boxtal webhook reactivation failed.")) from error
        return True

    def _mb_prepare_secret_rotation(self, credentials):
        """Create a fresh callback before atomically switching the local secret."""
        self.ensure_one()
        if self.delivery_type != "mb_boxtal":
            return super()._mb_prepare_secret_rotation(credentials)
        webhook_secret = credentials.get("webhook_secret")
        if (
            set(credentials) != {"access_key", "secret_key", "webhook_secret"}
            or not isinstance(webhook_secret, str)
            or len(webhook_secret) < 24
        ):
            raise UserError(_("The carrier rotation material is invalid."))
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "").rstrip("/")
        if not base_url.startswith("https://"):
            raise UserError(_("A public HTTPS web base URL is required for Boxtal webhooks."))
        subscription_id = secrets.token_urlsafe(24)
        callback = f"{base_url}/mb_carrier/webhook/boxtal/{subscription_id}"
        provider_class("boxtal")(
            credentials=credentials,
            production=bool(self.prod_environment),
            carrier=self,
        ).reconcile_subscriptions(callback, webhook_secret)
        return subscription_id

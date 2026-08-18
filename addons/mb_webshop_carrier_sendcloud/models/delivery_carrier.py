from __future__ import annotations

import secrets

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class DeliveryCarrier(models.Model):
    _inherit = "delivery.carrier"

    delivery_type = fields.Selection(
        selection_add=[("mb_sendcloud", "Sendcloud")],
        ondelete={"mb_sendcloud": "set default"},
    )
    mb_sendcloud_sender_address_id = fields.Integer(
        string="Sendcloud sender address ID", groups="base.group_system"
    )
    mb_sendcloud_contract_id = fields.Integer(
        string="Sendcloud contract ID", groups="base.group_system"
    )
    mb_sendcloud_carrier_code = fields.Char(
        string="Sendcloud carrier filter", groups="base.group_system"
    )
    mb_sendcloud_brand_id = fields.Integer(
        string="Sendcloud brand ID", groups="base.group_system"
    )
    mb_sendcloud_use_locations = fields.Boolean(
        string="Offer uses service points",
        help="Require a compatible Sendcloud service point at webshop checkout.",
    )
    mb_sendcloud_length_cm = fields.Float(string="Default parcel length (cm)", default=30)
    mb_sendcloud_width_cm = fields.Float(string="Default parcel width (cm)", default=20)
    mb_sendcloud_height_cm = fields.Float(string="Default parcel height (cm)", default=15)
    mb_sendcloud_content_description = fields.Char(
        string="Parcel content description", default="Handmade goods"
    )
    mb_sendcloud_webhook_ready = fields.Boolean(
        string="Signed webhook verified", copy=False, readonly=True,
        groups="base.group_system",
    )
    mb_sendcloud_last_webhook_at = fields.Datetime(
        string="Last Sendcloud webhook", copy=False, readonly=True,
        groups="base.group_system",
    )

    def _mb_restricted_configuration_fields(self):
        return super()._mb_restricted_configuration_fields() | {
            "mb_sendcloud_sender_address_id", "mb_sendcloud_contract_id",
            "mb_sendcloud_carrier_code", "mb_sendcloud_brand_id",
            "mb_sendcloud_use_locations", "mb_sendcloud_length_cm",
            "mb_sendcloud_width_cm", "mb_sendcloud_height_cm",
            "mb_sendcloud_content_description",
        }

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            if values.get("delivery_type") == "mb_sendcloud":
                values.setdefault("mb_provider_code", "sendcloud")
                values.setdefault("company_id", self.env.company.id)
                values.setdefault("mb_subscription_id", secrets.token_urlsafe(24))
        return super().create(values_list)

    def write(self, values):
        if values.get("delivery_type") == "mb_sendcloud":
            values = dict(values)
            values.setdefault("mb_provider_code", "sendcloud")
            values.setdefault("company_id", self.env.company.id)
            for carrier in self.filtered(lambda record: not record.mb_subscription_id):
                carrier.mb_subscription_id = secrets.token_urlsafe(24)
        return super().write(values)

    @api.constrains(
        "delivery_type", "mb_sendcloud_length_cm", "mb_sendcloud_width_cm",
        "mb_sendcloud_height_cm", "mb_label_format", "mb_sendcloud_sender_address_id",
    )
    def _check_sendcloud_configuration(self):
        for carrier in self.filtered(lambda record: record.delivery_type == "mb_sendcloud"):
            if min(
                carrier.mb_sendcloud_length_cm,
                carrier.mb_sendcloud_width_cm,
                carrier.mb_sendcloud_height_cm,
            ) <= 0:
                raise ValidationError(_("Sendcloud parcel dimensions must be greater than zero."))
            if carrier.mb_label_format not in ("A4", "A5", "10x15", "ZPL"):
                raise ValidationError(_("The Sendcloud label format is unsupported."))
            if carrier.mb_sendcloud_sender_address_id < 0:
                raise ValidationError(_("The Sendcloud sender address ID is invalid."))

    @api.depends("delivery_type", "mb_provider_return_service_code")
    def _compute_can_generate_return(self):
        super()._compute_can_generate_return()
        for carrier in self.filtered(lambda record: record.delivery_type == "mb_sendcloud"):
            carrier.can_generate_return = bool(carrier.mb_provider_return_service_code)

    def mb_sendcloud_rate_shipment(self, order):
        return self.base_on_rule_rate_shipment(order)

    def mb_sendcloud_send_shipping(self, pickings):
        self.ensure_one()
        if self.prod_environment and not self.mb_sendcloud_webhook_ready:
            raise UserError(_(
                "Verify a signed Sendcloud test webhook before buying production labels."
            ))
        return self._mb_send_shipping(pickings)

    def mb_sendcloud_cancel_shipment(self, pickings):
        return self._mb_cancel_shipment(pickings)

    def mb_sendcloud_get_tracking_link(self, picking):
        return self._mb_get_tracking_link(picking)

    def mb_sendcloud_get_return_label(self, pickings, tracking_number=None, origin_date=None):
        self.ensure_one()
        if self.prod_environment and not self.mb_sendcloud_webhook_ready:
            raise UserError(_(
                "Verify a signed Sendcloud test webhook before buying production return labels."
            ))
        return self._mb_get_return_label(pickings, tracking_number, origin_date)

    def _mb_sendcloud_get_close_locations(self, partner_address, **kwargs):
        return self._mb_get_close_locations(partner_address)

    def _mb_sendcloud_get_default_custom_package_code(self):
        return False

    def action_mb_test_connection(self):
        for carrier in self.filtered(lambda record: record.delivery_type == "mb_sendcloud"):
            if not carrier.mb_provider_service_code:
                raise UserError(_("Configure a Sendcloud outbound option before testing."))
            if not carrier.mb_sendcloud_sender_address_id:
                raise UserError(_("Select a Sendcloud sender address before testing."))
            if not carrier.prod_environment and carrier.mb_provider_service_code != "sendcloud:letter":
                raise UserError(_(
                    "Test policy permits only the Sendcloud unstamped-letter option."
                ))
        return super().action_mb_test_connection()

    def action_mb_copy_sendcloud_webhook_url(self):
        self.ensure_one()
        if self.delivery_type != "mb_sendcloud" or not self.mb_subscription_id:
            raise UserError(_("The Sendcloud webhook route is unavailable."))
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "").rstrip("/")
        if not base_url.startswith("https://"):
            raise UserError(_("A public HTTPS web base URL is required for Sendcloud webhooks."))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Sendcloud webhook URL"),
                "message": f"{base_url}/mb_carrier/webhook/sendcloud/{self.mb_subscription_id}",
                "sticky": True,
            },
        }

    def _mb_prepare_secret_rotation(self, credentials):
        """Invalidate webhook readiness and rotate the opaque callback route."""
        self.ensure_one()
        allowed = {"public_key", "private_key", "webhook_signature_key"}
        if (
            not isinstance(credentials, dict)
            or set(credentials) - allowed
            or not {"public_key", "private_key"}.issubset(credentials)
        ):
            raise UserError(_("The carrier rotation material is invalid."))
        self.sudo().write({
            "mb_sendcloud_webhook_ready": False,
            "mb_sendcloud_last_webhook_at": False,
        })
        return secrets.token_urlsafe(24)

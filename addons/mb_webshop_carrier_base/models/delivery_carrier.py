from __future__ import annotations

import os
from pathlib import Path
import uuid

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..provider import PickupQuery, ProviderError, provider_class


LABEL_FORMATS = [
    ("A4", "A4 PDF"),
    ("A5", "A5 PDF"),
    ("10x15", "10 × 15 cm PDF"),
    ("ZPL", "ZPL"),
]


class DeliveryCarrier(models.Model):
    _inherit = "delivery.carrier"

    mb_provider_code = fields.Char(copy=False, index=True, groups="base.group_system")
    mb_provider_service_code = fields.Char(
        string="Provider service code", copy=False, groups="base.group_system"
    )
    mb_provider_return_service_code = fields.Char(
        string="Provider return service code", copy=False, groups="base.group_system"
    )
    mb_credential_state = fields.Selection(
        [("unconfigured", "Unconfigured"), ("test", "Test"),
         ("production", "Production")],
        default="unconfigured",
        required=True,
        copy=False,
        groups="base.group_system",
    )
    mb_label_format = fields.Selection(
        LABEL_FORMATS, default="A4", required=True, groups="base.group_system"
    )
    mb_secret_ref = fields.Char(copy=False, groups="base.group_system")
    mb_last_error = fields.Char(copy=False, readonly=True, groups="base.group_system")
    mb_subscription_id = fields.Char(
        copy=False, readonly=True, index=True, groups="base.group_system"
    )
    mb_provider_enabled = fields.Boolean(default=True, copy=False)
    mb_provider_restricted = fields.Boolean(default=False, copy=False)

    def _mb_restricted_configuration_fields(self):
        return {
            "delivery_type", "prod_environment", "mb_provider_code",
            "mb_provider_service_code", "mb_provider_return_service_code",
            "mb_label_format", "mb_secret_ref", "mb_provider_enabled",
        }

    def _mb_prepare_secret_rotation(self, credentials):
        """Dispatch provider-specific secret rotation through model inheritance."""
        self.ensure_one()
        raise UserError(_("Carrier credentials could not be resolved."))

    def write(self, values):
        protected = self._mb_restricted_configuration_fields().intersection(values)
        if (
            protected
            and not self.env.context.get("mb_carrier_lifecycle_write")
            and any(self.mapped("mb_provider_restricted"))
        ):
            raise UserError(_(
                "Carrier configuration cannot be changed while its capability is restricted."
            ))
        return super().write(values)

    def _match(self, partner, source):
        self.ensure_one()
        if self.mb_provider_code and not self.mb_provider_enabled:
            return False
        return super()._match(partner, source)

    def _mb_resolve_credentials(self, timeout=(3.05, 8), purpose="provider_operation"):
        """Resolve a tenant-scoped secret without persisting its value in Odoo."""
        self.ensure_one()
        carrier = self.sudo()
        if not carrier.mb_secret_ref:
            raise UserError(_("No external credential is configured for %s.", self.display_name))
        company = carrier.company_id
        if not company.mb_control_workshop_id:
            raise UserError(_("This workshop is not linked to the control plane."))

        base_url = (
            os.environ.get("MB_CARRIER_CONTROL_URL")
            or os.environ.get("MB_CONTROL_API_URL", "")
        ).rstrip("/")
        token_path = os.environ.get("MB_CARRIER_CONTROL_TOKEN_FILE")
        if not token_path:
            token_root = os.environ.get(
                "MB_CARRIER_CONTROL_TOKEN_ROOT", "/run/makersbrain-odoo-client-secrets"
            )
            token_path = str(Path(token_root) / company.mb_control_workshop_id)
        if not base_url:
            raise UserError(_("Carrier secret resolution is not configured on this server."))
        try:
            token_file = Path(token_path).resolve(strict=True)
            if not token_file.is_file() or token_file.stat().st_size > 4096:
                raise OSError
            token = token_file.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise UserError(_("Carrier secret resolution is unavailable.")) from error
        if len(token) < 32:
            raise UserError(_("Carrier secret resolution is unavailable."))

        try:
            response = requests.post(
                f"{base_url}/internal/v1/carrier-secrets/resolve",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "workshop_id": company.mb_control_workshop_id,
                    "company_id": company.id,
                    "carrier_id": carrier.id,
                    "secret_ref": carrier.mb_secret_ref,
                    "environment": "production" if carrier.prod_environment else "test",
                    "purpose": purpose,
                    "provider": carrier.mb_provider_code,
                },
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as error:
            raise UserError(_("Carrier credentials could not be resolved.")) from error
        credentials = payload.get("credentials")
        if not isinstance(credentials, dict) or not credentials:
            raise UserError(_("Carrier credentials could not be resolved."))
        return credentials

    def _mb_webhook_secret(self, purpose="provider_operation"):
        self.ensure_one()
        secret = self._mb_resolve_credentials(
            timeout=(0.35, 0.9), purpose=purpose
        ).get("webhook_secret", "")
        if not isinstance(secret, str) or len(secret) < 24:
            raise UserError(_("The webhook validation secret is unavailable."))
        return secret

    @staticmethod
    def _mb_existing_object_purposes():
        return {
            "cancellation",
            "document_recovery",
            "reconciliation",
            "tracking_lookup",
            "webhook_verification",
            "webhook_processing",
        }

    def _mb_provider(self, purpose="provider_operation"):
        self.ensure_one()
        if not self.mb_provider_enabled:
            raise UserError(_("This shipping provider is disabled."))
        if self.mb_provider_restricted and purpose not in self._mb_existing_object_purposes():
            raise UserError(_("This shipping provider is restricted for new purchases."))
        provider_type = provider_class(self.mb_provider_code or "")
        return provider_type(
            credentials=self._mb_resolve_credentials(purpose=purpose),
            production=bool(self.prod_environment),
            carrier=self,
        )

    def action_mb_test_connection(self):
        for carrier in self:
            try:
                status = carrier._mb_provider().check_credentials()
                if not status.valid:
                    raise UserError(status.message or _("The provider rejected the credentials."))
            except (ProviderError, UserError) as error:
                carrier.sudo().write({
                    "mb_credential_state": "unconfigured",
                    "mb_last_error": str(error)[:512],
                })
                raise UserError(_("Connection failed: %s", error)) from error
            carrier.sudo().write({
                "mb_credential_state": status.environment,
                "mb_last_error": False,
            })
        return True

    def _mb_suspend_webhooks(self):
        carriers = self.filtered(lambda record: record.mb_secret_ref and record.mb_subscription_id)
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "").rstrip("/")
        if carriers and not base_url.startswith("https://"):
            raise UserError(_("A public HTTPS web base URL is required to suspend carrier webhooks."))
        for carrier in carriers:
            provider = carrier._mb_provider(purpose="webhook_suspension")
            suspend = getattr(provider, "suspend_subscriptions", None)
            if suspend:
                suspend(f"{base_url}/mb_carrier/webhook/{carrier.mb_provider_code}/{carrier.mb_subscription_id}")
        return True

    @api.model
    def _mb_cron_check_webhooks(self, limit=20):
        carriers = self.sudo().search([
            ("mb_provider_code", "!=", False),
            ("mb_provider_enabled", "=", True),
            ("mb_secret_ref", "!=", False),
            ("mb_subscription_id", "!=", False),
        ], limit=limit)
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "").rstrip("/")
        for carrier in carriers:
            try:
                provider = carrier._mb_provider()
                check = getattr(provider, "check_subscriptions", None)
                if check and base_url.startswith("https://"):
                    callback = f"{base_url}/mb_carrier/webhook/{carrier.mb_provider_code}/{carrier.mb_subscription_id}"
                    carrier.mb_last_error = False if check(callback) else "webhook_subscription_inactive"
            except (ProviderError, UserError):
                carrier.mb_last_error = "webhook_health_unavailable"
        return len(carriers)

    def _mb_estimated_price(self, picking):
        self.ensure_one()
        if picking.sale_id:
            delivery_line = picking.sale_id.order_line.filtered(
                lambda line: line.is_delivery and line.product_id == self.product_id
            )[:1]
            if delivery_line:
                return delivery_line.price_unit
            result = self.rate_shipment(picking.sale_id)
            if result.get("success"):
                return result.get("price", 0)
        return 0

    def _mb_send_shipping(self, pickings):
        self.ensure_one()
        if not self.mb_provider_enabled:
            raise UserError(_("This shipping provider is disabled."))
        if self.mb_provider_restricted:
            raise UserError(_("This shipping provider is restricted for new purchases."))
        if not self.mb_provider_code or not self.mb_provider_service_code:
            raise ValidationError(_("The provider and service code must be configured."))
        results = []
        for picking in pickings:
            key = str(uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"mb-carrier:{self.env.cr.dbname}:{self.id}:{picking.id}:outbound:0",
            ))
            self.env["mb.carrier.shipment"].sudo().create_or_get({
                "company_id": picking.company_id.id,
                "carrier_id": self.id,
                "picking_id": picking.id,
                "direction": "outbound",
                "parcel_index": 0,
                "idempotency_key": key,
            })
            results.append({
                "exact_price": self._mb_estimated_price(picking),
                "tracking_number": False,
            })
        return results

    def _mb_cancel_shipment(self, pickings):
        self.ensure_one()
        if not self.mb_provider_enabled:
            raise UserError(_("This shipping provider is disabled."))
        shipments = self.env["mb.carrier.shipment"].sudo().search([
            ("picking_id", "in", pickings.ids),
            ("carrier_id", "=", self.id),
            ("direction", "=", "outbound"),
            ("state", "not in", ("cancelled", "failed")),
        ])
        if not shipments:
            raise UserError(_("No provider shipment exists for this transfer."))
        shipments.action_queue_cancellation()
        return True

    def _mb_get_tracking_link(self, picking):
        self.ensure_one()
        shipment = self.env["mb.carrier.shipment"].sudo().search([
            ("picking_id", "=", picking.id),
            ("carrier_id", "=", self.id),
            ("tracking_url", "!=", False),
        ], order="parcel_index", limit=1)
        return shipment.tracking_url or None

    def _mb_get_close_locations(self, partner_address):
        self.ensure_one()
        if not self._mb_uses_pickup_locations():
            return []
        return self.env["mb.carrier.pickup.point"].sudo().for_checkout(
            self, partner_address
        )

    def _mb_uses_pickup_locations(self):
        self.ensure_one()
        field_name = f"{self.delivery_type}_use_locations"
        return bool(field_name in self._fields and self[field_name])

    def _mb_get_pickup_point(self, code, partner_address=None):
        self.ensure_one()
        if not code or len(code) > 128:
            raise ValidationError(_("The pickup-point code is invalid."))
        query = None
        if partner_address:
            country_code = partner_address.country_id.code or ""
            query = PickupQuery(
                country_code=country_code,
                zip=(partner_address.zip or "").strip().upper(),
                city=partner_address.city or "",
                service_code=self.mb_provider_service_code or "",
                limit=20,
            )
        return self._mb_provider().get_pickup_point(
            code, self.mb_provider_service_code or "", query=query
        )

    def _mb_get_return_label(self, pickings, tracking_number=None, origin_date=None):
        self.ensure_one()
        provider_type = provider_class(self.mb_provider_code or "")
        if not getattr(provider_type, "supports_return_label", False):
            raise UserError(_("This shipping provider does not support return labels."))
        if not self.mb_provider_enabled:
            raise UserError(_("This shipping provider is disabled."))
        if self.mb_provider_restricted:
            raise UserError(_("This shipping provider is restricted for new returns."))
        for picking in pickings:
            key = str(uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"mb-carrier:{self.env.cr.dbname}:{self.id}:{picking.id}:return:0",
            ))
            self.env["mb.carrier.shipment"].sudo().create_or_get({
                "company_id": picking.company_id.id,
                "carrier_id": self.id,
                "picking_id": picking.id,
                "direction": "return",
                "parcel_index": 0,
                "idempotency_key": key,
            })
            picking.message_post(body=_("Return-label purchase queued."))
        return True

import json

from odoo import _, fields, models
from odoo.exceptions import UserError, ValidationError

from ..provider import ProviderError, provider_class


class SaleOrder(models.Model):
    _inherit = "sale.order"

    mb_delivery_recipient_partner_id = fields.Many2one(
        "res.partner", copy=False, readonly=True, check_company=True
    )
    mb_delivery_recipient_snapshot = fields.Json(copy=False, readonly=True)

    def write(self, values):
        """Discard a relay selection when its delivery method changes.

        The website stores the selected point separately from the delivery
        line.  Keeping that JSON (or its immutable pickup partner) after a
        carrier switch can otherwise submit a point belonging to the previous
        provider.
        """
        changed = self.env["sale.order"]
        if "carrier_id" in values:
            new_carrier_id = values.get("carrier_id") or False
            changed = self.filtered(lambda order: order.carrier_id.id != new_carrier_id)
        result = super().write(values)
        for order in changed:
            cleanup = {
                "pickup_location_data": False,
                "mb_delivery_recipient_partner_id": False,
                "mb_delivery_recipient_snapshot": False,
            }
            if order.partner_shipping_id.mb_pickup_ref:
                cleanup["partner_shipping_id"] = order.partner_id.id
            super(SaleOrder, order.with_context(
                update_delivery_shipping_partner=True,
            )).write(cleanup)
        return result

    def _mb_resolve_selected_pickup(self):
        """Re-resolve and validate the browser's selected pickup point."""
        self.ensure_one()
        carrier = self.carrier_id.sudo()
        data = self.pickup_location_data or {}
        additional = data.get("additional_data") or {}
        code = data.get("id")
        if (
            not isinstance(code, str)
            or not code
            or len(code) > 128
            or additional.get("provider_code") != carrier.mb_provider_code
            or additional.get("service_code") != carrier.mb_provider_service_code
        ):
            raise ValidationError(_("Choose a valid pickup point for this delivery method."))
        try:
            point = carrier._mb_get_pickup_point(code, self.partner_shipping_id)
        except ProviderError as error:
            raise ValidationError(_("The selected pickup point is no longer available.")) from error
        submitted_address = (
            str(data.get("street") or "").strip().casefold(),
            str(data.get("zip_code") or "").strip().upper(),
            str(data.get("city") or "").strip().casefold(),
            str(data.get("country_code") or "").strip().upper(),
        )
        provider_address = (
            point.street.strip().casefold(),
            point.zip.strip().upper(),
            point.city.strip().casefold(),
            point.country_code.strip().upper(),
        )
        if submitted_address != provider_address:
            raise ValidationError(_("The selected pickup point is stale or invalid."))
        return point

    def _mb_pickup_rate_identity(self):
        self.ensure_one()
        # This method is overridden by the HTTP controller context with a
        # session/IP identity. Backend callers remain separately bounded.
        return self.env.context.get("mb_pickup_rate_identity") or f"backend:{self.env.uid}"

    def _get_pickup_locations(self, zip_code=None, country=None, **kwargs):
        self.ensure_one()
        carrier = self.carrier_id.sudo()
        if not carrier.mb_provider_code:
            return super()._get_pickup_locations(zip_code, country, **kwargs)
        self.env["mb.carrier.public.rate"].sudo().consume(
            self._mb_pickup_rate_identity(), "search", 30
        )
        if zip_code:
            partner_address = self.env["res.partner"].new({
                "active": False,
                "country_id": country.id,
                "zip": str(zip_code)[:16],
            })
        else:
            partner_address = self.partner_shipping_id
        try:
            locations = carrier._mb_get_close_locations(partner_address)
        except UserError as error:
            return {"error": str(error)}
        return {"pickup_locations": locations} if locations else {
            "error": _("No pick-up points are available for this delivery address.")
        }

    def _set_pickup_location(self, pickup_location_data):
        self.ensure_one()
        carrier = self.carrier_id.sudo()
        if not carrier.mb_provider_code:
            return super()._set_pickup_location(pickup_location_data)
        self.env["mb.carrier.public.rate"].sudo().consume(
            self._mb_pickup_rate_identity(), "select", 10
        )
        if not carrier._mb_uses_pickup_locations():
            raise ValidationError(_("This delivery service does not use pickup points."))
        try:
            submitted = json.loads(pickup_location_data) if pickup_location_data else None
        except (TypeError, ValueError) as error:
            raise ValidationError(_("The pickup-point selection is invalid.")) from error
        if not isinstance(submitted, dict) or not isinstance(submitted.get("id"), str):
            raise ValidationError(_("The pickup-point selection is invalid."))
        try:
            point = carrier._mb_get_pickup_point(
                submitted["id"], self.partner_shipping_id
            )
        except ProviderError as error:
            raise ValidationError(_("The selected pickup point is no longer available.")) from error
        if point.code != submitted["id"]:
            raise ValidationError(_("The pickup-point selection is invalid."))
        normalized = {
            "id": point.code,
            "name": point.name,
            "street": point.street,
            "city": point.city,
            "zip_code": point.zip,
            "state": "",
            "country_code": point.country_code,
            "latitude": str(point.latitude or 0),
            "longitude": str(point.longitude or 0),
            "openingHours": point.opening_hours,
            "additional_data": {
                "provider_code": carrier.mb_provider_code,
                "service_code": carrier.mb_provider_service_code,
            },
        }
        return super()._set_pickup_location(json.dumps(normalized))

    def _check_mb_pickup_consistency(self):
        for order in self:
            # Provider identity is deliberately hidden from ordinary users,
            # but confirming an otherwise unrelated order must still work.
            # Elevate only the technical carrier record used for validation;
            # the order and address remain under the caller's permissions.
            carrier = order.carrier_id.sudo()
            if not carrier.mb_provider_code:
                if order.partner_shipping_id.mb_pickup_ref:
                    raise ValidationError(_("A pickup address requires its matching delivery method."))
                continue
            provider_type = provider_class(carrier.mb_provider_code)
            uses_pickup = (
                getattr(provider_type, "supports_pickup_points", False)
                and carrier._mb_uses_pickup_locations()
            )
            if not uses_pickup:
                if order.partner_shipping_id.mb_pickup_ref:
                    raise ValidationError(_("This delivery service does not use pickup points."))
                continue
            order._mb_resolve_selected_pickup()

    def _check_cart_is_ready_to_be_paid(self):
        self._check_mb_pickup_consistency()
        return super()._check_cart_is_ready_to_be_paid()

    def action_confirm(self):
        # Several core payment flows intentionally call action_confirm() on
        # an empty filtered recordset.  Keep that operation a harmless no-op
        # instead of forwarding it to singleton-oriented downstream addons.
        if not self:
            return True
        self._check_mb_pickup_consistency()
        return super().action_confirm()

    def _action_confirm(self):
        resolved_points = {}
        for order in self.filtered(
            lambda candidate: candidate.carrier_id.sudo().mb_provider_code
        ):
            carrier = order.carrier_id.sudo()
            provider_type = provider_class(carrier.mb_provider_code)
            if (
                getattr(provider_type, "supports_pickup_points", False)
                and carrier._mb_uses_pickup_locations()
            ):
                resolved_points[order.id] = order._mb_resolve_selected_pickup()
                recipient = order.partner_shipping_id
                order.sudo().write({
                    "mb_delivery_recipient_partner_id": recipient.id,
                    "mb_delivery_recipient_snapshot": self.env[
                        "mb.carrier.shipment"
                    ]._partner_payload(recipient),
                })
        result = super()._action_confirm()
        for order in self.filtered(lambda candidate: candidate.id in resolved_points):
            order.picking_ids.filtered(
                lambda picking: picking.picking_type_code == "outgoing"
            ).sudo().write({
                "mb_delivery_recipient_partner_id": order.mb_delivery_recipient_partner_id.id,
                "mb_delivery_recipient_snapshot": order.mb_delivery_recipient_snapshot,
            })
        for order in self.filtered(lambda candidate: candidate.id in resolved_points):
            point = resolved_points[order.id]
            carrier = order.carrier_id
            current = order.partner_shipping_id
            owner = current.parent_id or order.partner_id
            pickup = self.env["res.partner"].sudo().search([
                ("parent_id", "=", owner.id),
                ("type", "=", "delivery"),
                ("mb_pickup_ref", "=", point.code),
                ("mb_pickup_provider", "=", carrier.mb_provider_code),
                ("mb_pickup_service", "=", carrier.mb_provider_service_code),
            ], limit=1)
            # Core may just have created an unclassified pickup address. Reuse
            # it, but never turn a customer's ordinary delivery address into
            # an immutable carrier location merely because its street matches.
            if (
                not pickup
                and current.is_pickup_location
                and not current.mb_pickup_ref
                and current.parent_id == owner
            ):
                pickup = current.sudo()
            country = self.env["res.country"].search([
                ("code", "=", point.country_code),
            ], limit=1)
            if not country:
                raise ValidationError(_("The pickup point country is unavailable."))
            values = {
                "parent_id": owner.id,
                "type": "delivery",
                "name": point.name,
                "street": point.street,
                "street2": False,
                "zip": point.zip,
                "city": point.city,
                "state_id": False,
                "country_id": country.id,
                "email": owner.email,
                "phone": owner.phone,
                "is_pickup_location": True,
                "mb_pickup_ref": point.code,
                "mb_pickup_provider": carrier.mb_provider_code,
                "mb_pickup_service": carrier.mb_provider_service_code,
            }
            if pickup:
                pickup.write(values)
            else:
                pickup = self.env["res.partner"].sudo().create(values)
            order.with_context(update_delivery_shipping_partner=True).write({
                "partner_shipping_id": pickup.id,
            })
        return result

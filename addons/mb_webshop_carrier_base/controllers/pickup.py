from odoo import _, http
from odoo.exceptions import AccessDenied, UserError
from odoo.http import request

from odoo.addons.website_sale.controllers.delivery import Delivery
from odoo.addons.website_sale.controllers.main import WebsiteSale


def _rate_identity():
    session_id = getattr(request.session, "sid", "") or "no-session"
    remote = request.httprequest.remote_addr or "unknown"
    return f"{session_id}:{remote}"


class MBPickupDelivery(Delivery):

    @http.route()
    def website_sale_get_pickup_locations(self, zip_code=None, **kwargs):
        order = request.cart
        if not order:
            return {"error": _("The shopping cart is unavailable.")}
        country = order.partner_shipping_id.country_id
        return order.with_context(
            mb_pickup_rate_identity=_rate_identity()
        )._get_pickup_locations(zip_code, country, **kwargs)

    @http.route()
    def website_sale_set_pickup_location(self, pickup_location_data):
        order = request.cart
        if not order:
            raise AccessDenied()
        order.with_context(
            mb_pickup_rate_identity=_rate_identity()
        )._set_pickup_location(pickup_location_data)

class MBPickupAddressGuard(WebsiteSale):

    def _prepare_address_update(self, *args, **kwargs):
        partner, address_type = super()._prepare_address_update(*args, **kwargs)
        if partner and partner.mb_pickup_ref:
            raise UserError(_("A carrier pickup-point address cannot be edited."))
        return partner, address_type

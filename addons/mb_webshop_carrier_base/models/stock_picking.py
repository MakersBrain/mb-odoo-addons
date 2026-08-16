from odoo import _, fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    mb_carrier_shipment_ids = fields.One2many(
        "mb.carrier.shipment", "picking_id", string="Provider shipments"
    )

    def send_to_shipper(self):
        self.ensure_one()
        if not self.carrier_id.mb_provider_code:
            return super().send_to_shipper()
        result = self.carrier_id.send_shipping(self)[0]
        self.carrier_price = self.carrier_id._apply_margins(
            result.get("exact_price", 0), self.sale_id
        )
        self.message_post(body=_("Carrier label purchase queued."))
        self._add_delivery_cost_to_so()
        return True

    def cancel_shipment(self):
        regular = self.filtered(lambda picking: not picking.carrier_id.mb_provider_code)
        custom = self - regular
        result = super(StockPicking, regular).cancel_shipment() if regular else None
        for picking in custom:
            picking.carrier_id.cancel_shipment(picking)
            picking.message_post(body=_("Carrier cancellation queued."))
        return result

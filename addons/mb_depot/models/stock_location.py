from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class StockLocation(models.Model):
    _inherit = "stock.location"

    is_depot = fields.Boolean(
        string="Dépôt-vente",
        help="Stock we own, physically held by someone else. It stays internal so "
             "unsold pieces stay on our balance sheet and no revenue is recognised "
             "until the depositary reports a sale.",
    )
    depot_partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Depositary",
        domain=[("is_company", "=", True)],
    )
    depot_commission = fields.Float(
        string="Commission (%)",
        digits="Discount",
        help="Recorded here for the statement. The figure that actually prices a "
             "sale is the depositary's pricelist.",
    )
    depot_route_id = fields.Many2one(
        comodel_name="stock.route",
        string="Depot route",
        help="Selected on a quotation to source the delivery from this depot "
             "instead of the warehouse.",
    )
    depot_pricelist_id = fields.Many2one(
        comodel_name="product.pricelist",
        string="Commission pricelist",
    )
    depot_qty = fields.Float(
        string="Pieces held",
        compute="_compute_depot_qty",
        help="On hand at this location right now.",
    )

    @api.depends("quant_ids.quantity")
    def _compute_depot_qty(self):
        grouped = {}
        depots = self.filtered("is_depot")
        if depots:
            for location, qty in self.env["stock.quant"]._read_group(
                [("location_id", "child_of", depots.ids)],
                ["location_id"],
                ["quantity:sum"],
            ):
                grouped[location.id] = qty
        for location in self:
            location.depot_qty = grouped.get(location.id, 0.0)

    @api.constrains("is_depot", "usage")
    def _check_depot_is_internal(self):
        for location in self:
            if location.is_depot and location.usage != "internal":
                raise ValidationError(_(
                    "A depot must be an internal location. Anything else takes the "
                    "stock off our books while it is still ours and unsold."
                ))

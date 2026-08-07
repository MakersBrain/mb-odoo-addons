from odoo import api, fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    depot_location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Depot",
        compute="_compute_depot_location_id",
        store=True,
        help="Set when this transfer places pieces at a depot or brings them back.",
    )
    is_depot_placement = fields.Boolean(
        compute="_compute_depot_location_id",
        store=True,
    )

    @api.depends("location_id.is_depot", "location_dest_id.is_depot")
    def _compute_depot_location_id(self):
        for picking in self:
            if picking.location_dest_id.is_depot:
                picking.depot_location_id = picking.location_dest_id
                picking.is_depot_placement = True
            elif picking.location_id.is_depot:
                picking.depot_location_id = picking.location_id
                picking.is_depot_placement = False
            else:
                picking.depot_location_id = False
                picking.is_depot_placement = False

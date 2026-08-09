from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class StockWarehouse(models.Model):
    """A dépôt-vente is a warehouse.

    It was a bare internal location outside every warehouse once, to keep an
    ordinary delivery from reserving a piece standing in a gallery. A warehouse
    gives that for nothing - a delivery sources from its own warehouse's stock -
    and gives back everything the location cost: on-hand and forecast figures
    that count the shelf being sold from, sourcing by selecting the warehouse on
    the quotation rather than a bespoke route and pull rule per gallery, and
    every warehouse-scoped report in Odoo reading the depot correctly instead of
    reading zero until someone patches it.

    The stock stays ours either way. A warehouse's stock location is internal, so
    unsold pieces stay on our balance sheet and no revenue is recognised until
    the depositary reports a sale, which is the legal situation of dépôt-vente.
    """
    _inherit = "stock.warehouse"

    is_depot = fields.Boolean(
        string="Dépôt-vente",
        help="Stock we own, physically held by someone else. Internal like any "
             "warehouse, so unsold pieces stay on our balance sheet until the "
             "depositary reports a sale.",
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
    depot_pricelist_id = fields.Many2one(
        comodel_name="product.pricelist",
        string="Commission pricelist",
    )
    depot_qty = fields.Float(
        string="Pieces held",
        compute="_compute_depot_qty",
        help="On hand at this depot right now.",
    )

    def _compute_depot_qty(self):
        # Grouped on location_id rather than stock.quant.warehouse_id: that one
        # is related without store, so it has no column to group on.
        grouped = {}
        depots = self.filtered("is_depot")
        if depots:
            for location, qty in self.env["stock.quant"]._read_group(
                [("location_id", "child_of", depots.view_location_id.ids)],
                ["location_id"],
                ["quantity:sum"],
            ):
                warehouse = location.warehouse_id
                grouped[warehouse.id] = grouped.get(warehouse.id, 0.0) + qty
        for warehouse in self:
            warehouse.depot_qty = grouped.get(warehouse.id, 0.0)

    @api.constrains("is_depot", "reception_steps", "delivery_steps")
    def _check_depot_is_one_step(self):
        """A gallery has a shelf, not a receiving bay.

        Multi-step would invent Input and Output rooms inside someone else's
        shop, and split one sale into two moves whose first leg leaves the
        depot's stock location for a sibling - which the statement would have to
        learn to ignore. One step keeps the paper and the stock agreeing.
        """
        for warehouse in self.filtered("is_depot"):
            if warehouse.reception_steps != "one_step" or \
                    warehouse.delivery_steps != "ship_only":
                raise ValidationError(_(
                    "A depot receives and delivers in one step. %(name)s is set "
                    "to more, which would put a receiving bay and a packing "
                    "table inside the depositary's shop.",
                    name=warehouse.display_name,
                ))

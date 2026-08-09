from odoo import models


class StockMove(models.Model):
    _inherit = "stock.move"

    def action_add_from_catalog_depot(self):
        """Entry point for the Catalogue button on the moves list.

        A button inside a one2many's <control> is called on the line model, not
        on the record the list belongs to, so it arrives here rather than on
        stock.picking and the picking comes from the context - the same detour
        mrp takes for the components of a manufacturing order.
        """
        picking = self.env["stock.picking"].browse(self.env.context.get("order_id"))
        return picking.action_add_from_catalog_depot()

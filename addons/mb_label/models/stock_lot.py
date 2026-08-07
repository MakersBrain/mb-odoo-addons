from odoo import _, models


class StockLot(models.Model):
    _inherit = "stock.lot"

    def action_mb_create_label(self):
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "name": _("Create Lot or Piece Label"),
            "tag": "mb_label.editor",
            "context": {
                "default_product_id": self.product_id.id,
                "default_lot_id": self.id,
            },
        }

    def action_mb_print_label(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Print Lot or Piece Label"),
            "res_model": "mb.label.print.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_product_id": self.product_id.id,
                "default_lot_id": self.id,
            },
        }

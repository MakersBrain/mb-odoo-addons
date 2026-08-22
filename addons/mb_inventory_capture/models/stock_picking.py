from odoo import _, models
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def action_mb_identify_from_photo(self):
        self.ensure_one()
        if self.picking_type_code != "incoming" or self.state in {"done", "cancel"}:
            raise UserError(_("Product photo capture is available only on an open receipt."))
        return {
            "type": "ir.actions.client",
            "tag": "mb_inventory_capture.capture",
            "name": _("Identify from photo"),
            "context": {"default_picking_id": self.id},
        }

    def action_cancel(self):
        result = super().action_cancel()
        captures = self.env["mb.inventory.capture"].search(
            [
                ("picking_id", "in", self.ids),
                ("state", "not in", ["applied", "cancelled"]),
            ]
        )
        if captures:
            captures.action_cancel()
        return result

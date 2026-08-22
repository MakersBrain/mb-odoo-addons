from odoo import fields, models


class StockPackage(models.Model):
    _inherit = "stock.package"

    mb_board_content_ids = fields.One2many("mb.board.content", "board_id", string="WIP history")
    mb_current_board_content_ids = fields.One2many(
        "mb.board.content",
        "board_id",
        string="Current WIP",
        domain=[("state", "=", "current")],
    )

    def action_mb_board(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.display_name,
            "res_model": "stock.package",
            "res_id": self.id,
            "view_mode": "form",
            "view_id": self.env.ref("mb_ceramics_workflow.mb_board_view_form").id,
        }

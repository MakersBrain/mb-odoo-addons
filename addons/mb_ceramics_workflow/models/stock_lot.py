from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_round


class StockLot(models.Model):
    _inherit = "stock.lot"

    mb_ceramics_stage = fields.Selection(related="product_id.product_tmpl_id.mb_ceramics_stage")
    mb_bom_revision_id = fields.Many2one(
        "mrp.bom",
        string="Recipe revision",
        copy=False,
        readonly=True,
        ondelete="restrict",
        check_company=True,
    )

    mb_production_ids = fields.Many2many(
        "mrp.production", compute="_compute_mb_ceramics_trace", string="Productions"
    )
    mb_firing_ids = fields.Many2many(
        "mb.firing", compute="_compute_mb_ceramics_trace", string="Firings"
    )
    mb_firing_count = fields.Integer(compute="_compute_mb_ceramics_trace")
    mb_board_ids = fields.Many2many(
        "stock.package", compute="_compute_mb_ceramics_trace", string="Boards"
    )
    mb_loss_ids = fields.Many2many(
        "mb.production.loss", compute="_compute_mb_ceramics_trace", string="Losses"
    )
    mb_related_lot_ids = fields.Many2many(
        "stock.lot",
        compute="_compute_mb_ceramics_trace",
        string="Material and output lots",
    )

    def _mb_connected_ceramics_trace(self):
        """Return the complete manufacturing component around one lot."""
        self.ensure_one()
        lots = self
        productions = self.env["mrp.production"]
        frontier = self
        while frontier:
            output_lines = self.env["stock.move.line"].search(
                [
                    ("lot_id", "in", frontier.ids),
                    ("move_id.production_id", "!=", False),
                ]
            )
            input_lines = self.env["stock.move.line"].search(
                [
                    ("lot_id", "in", frontier.ids),
                    ("move_id.raw_material_production_id", "!=", False),
                ]
            )
            connected_productions = (
                output_lines.move_id.production_id
                | input_lines.move_id.raw_material_production_id
                | self.env["mrp.production"].search(
                    [
                        ("lot_producing_ids", "in", frontier.ids),
                    ]
                )
            )
            new_productions = connected_productions - productions
            if not new_productions:
                break
            productions |= new_productions
            connected_lots = (
                new_productions.lot_producing_ids
                | new_productions.move_finished_ids.move_line_ids.lot_id
                | new_productions.move_raw_ids.move_line_ids.lot_id
            )
            frontier = connected_lots - lots
            lots |= connected_lots
        return productions, lots

    def _compute_mb_ceramics_trace(self):
        for lot in self:
            productions, related_lots = lot._mb_connected_ceramics_trace()
            lot.mb_production_ids = productions
            lot.mb_firing_ids = productions.workorder_ids.mb_firing_id
            lot.mb_firing_count = len(lot.mb_firing_ids)
            lot.mb_board_ids = productions.mb_board_content_ids.board_id
            lot.mb_loss_ids = productions.mb_loss_ids
            lot.mb_related_lot_ids = related_lots - lot

    def action_mb_ceramics_trace(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Ceramics trace - %(lot)s", lot=self.display_name),
            "res_model": "mrp.production",
            "view_mode": "list,form",
            "domain": [("id", "in", self.mb_production_ids.ids)],
            "context": {"create": False},
        }

    def action_mb_print_wip_label(self):
        self.ensure_one()
        stage = self.product_id.product_tmpl_id.mb_ceramics_stage
        if stage not in ("green", "bisque"):
            raise UserError(_("WIP labels are available only for green or bisque ware."))
        quantity = self.env.context.get("mb_wip_quantity")
        if quantity is None:
            quantity = sum(
                self.quant_ids.filtered(lambda quant: quant.location_id.usage == "internal").mapped(
                    "quantity"
                )
            )
        return {
            "type": "ir.actions.act_window",
            "name": _("Print WIP label"),
            "res_model": "mb.label.print.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_product_id": self.product_id.id,
                "default_lot_id": self.id,
                "default_template_id": self.env.ref("mb_label.template_wip_lot_30x20").id,
                "default_manual_values_json": {
                    "stage": stage.upper(),
                    "quantity": str(
                        float_round(
                            quantity,
                            precision_rounding=self.product_id.uom_id.rounding,
                        )
                    ),
                },
            },
        }

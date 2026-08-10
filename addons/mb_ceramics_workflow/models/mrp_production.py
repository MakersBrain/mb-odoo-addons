from odoo import _, fields, models
from odoo.exceptions import UserError


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    mb_workflow_kind = fields.Selection(
        [
            ("throwing", "Blank production"),
            ("bisque", "Bisque production"),
            ("glazing", "Glazing"),
            ("finishing", "Finishing (legacy)"),
        ],
        copy=False,
        index=True,
    )
    mb_throwing_session_id = fields.Many2one(
        "mb.throwing.session", copy=False, index=True, ondelete="set null",
        check_company=True)
    mb_finishing_session_id = fields.Many2one(
        "mb.finishing.session", copy=False, index=True, ondelete="set null",
        check_company=True)
    mb_bisque_session_id = fields.Many2one(
        "mb.bisque.session", copy=False, index=True, ondelete="set null",
        check_company=True)
    mb_glazing_session_id = fields.Many2one(
        "mb.glazing.session", copy=False, index=True, ondelete="set null",
        check_company=True)
    mb_board_content_ids = fields.One2many(
        "mb.board.content", "production_id", string="Board history")
    mb_loss_ids = fields.One2many(
        "mb.production.loss", "production_id", string="Process losses")
    mb_inspected = fields.Boolean(copy=False, readonly=True)
    mb_bisque_inspected = fields.Boolean(copy=False, readonly=True)

    def write(self, values):
        session_fields = {
            "mb_throwing_session_id",
            "mb_finishing_session_id",
            "mb_bisque_session_id",
            "mb_glazing_session_id",
        }
        changed = session_fields & set(values)
        if changed:
            for production in self:
                for field_name in changed:
                    sessions = production[field_name]
                    if values[field_name]:
                        sessions |= self.env[
                            self._fields[field_name].comodel_name
                        ].browse(values[field_name])
                    if any(
                        session.state in session._mb_terminal_states
                        for session in sessions
                    ):
                        raise UserError(_(
                            "A manufacturing order cannot be moved into or out of a "
                            "completed workshop session."
                        ))
        return super().write(values)

    def action_mb_inspect(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Unload and inspect",
            "res_model": "mb.inspection",
            "view_mode": "form",
            "target": "new",
            "context": {"default_production_id": self.id},
        }

    def action_mb_inspect_bisque(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Inspect bisque firing",
            "res_model": "mb.bisque.inspection",
            "view_mode": "form",
            "target": "new",
            "context": {"default_production_id": self.id},
        }

    def action_mb_print_wip_label(self):
        self.ensure_one()
        lot = self.lot_producing_ids[:1]
        if not lot:
            return False
        return lot.with_context(
            mb_wip_quantity=self.qty_produced,
        ).action_mb_print_wip_label()

    def _post_inventory(self, cancel_backorder=False):
        """Keep genealogy when a damp-box blank was consumed at session start.

        Odoo normally consumes every raw move in this method and then binds those
        move lines to the finished output. The workshop deliberately consumes its
        selected blank earlier, when it leaves available damp-box stock. Preserve
        those already-done raw lines in the same v19 `consume_line_ids` graph.
        """
        early_lines = {
            production.id: production.move_raw_ids.filtered(
                lambda move: move.state == "done").move_line_ids
            for production in self.filtered(
                lambda production: production.mb_workflow_kind
                in ("bisque", "glazing", "finishing"))
        }
        result = super()._post_inventory(cancel_backorder=cancel_backorder)
        for production in self:
            lines = early_lines.get(production.id)
            if lines:
                for output_line in production.move_finished_ids.filtered(
                        lambda move: move.state == "done").move_line_ids:
                    output_line.consume_line_ids = [
                        fields.Command.set((output_line.consume_line_ids | lines).ids)]
        return result

    def _cal_price(self, consumed_moves):
        """Include raw moves consumed when ware first leaves available stock.

        The board workflow completes its selected green/bisque input move at
        session start. Odoo 19 normally prices finished output from raw moves
        completed inside `_post_inventory`; without this union the genealogy is
        correct but the early input cost is absent from the next stock stage.
        """
        if self.mb_workflow_kind in ("bisque", "glazing", "finishing"):
            consumed_moves |= self.move_raw_ids.filtered(
                lambda move: move.state == "done"
            )
        return super()._cal_price(consumed_moves)

    def _get_backorder_mo_vals(self):
        """Keep ceramics workflow ownership on Odoo 19 MO splits."""
        values = super()._get_backorder_mo_vals()
        if self.mb_workflow_kind in ("bisque", "glazing", "finishing"):
            values.update({
                "mb_workflow_kind": self.mb_workflow_kind,
                "mb_bisque_session_id": self.mb_bisque_session_id.id,
                "mb_glazing_session_id": self.mb_glazing_session_id.id,
                "mb_finishing_session_id": self.mb_finishing_session_id.id,
            })
        return values

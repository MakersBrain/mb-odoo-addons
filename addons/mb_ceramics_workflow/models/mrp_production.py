from odoo import _, api, fields, models
from odoo.exceptions import UserError


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    mb_workflow_kind = fields.Selection(
        [
            ("throwing", "Blank production"),
            ("bisque", "Bisque production"),
            ("glazing", "Glazing"),
        ],
        copy=False,
        index=True,
    )
    mb_throwing_session_id = fields.Many2one(
        "mb.throwing.session", copy=False, index=True, ondelete="set null", check_company=True
    )
    mb_bisque_session_id = fields.Many2one(
        "mb.bisque.session", copy=False, index=True, ondelete="set null", check_company=True
    )
    mb_glazing_session_id = fields.Many2one(
        "mb.glazing.session", copy=False, index=True, ondelete="set null", check_company=True
    )
    mb_board_content_ids = fields.One2many(
        "mb.board.content", "production_id", string="Board history"
    )
    mb_loss_ids = fields.One2many("mb.production.loss", "production_id", string="Process losses")
    mb_inspected = fields.Boolean(copy=False, readonly=True)
    mb_bisque_inspected = fields.Boolean(copy=False, readonly=True)
    mb_bom_revision_id = fields.Many2one(
        "mrp.bom",
        string="Recipe revision",
        copy=False,
        readonly=True,
        ondelete="restrict",
        check_company=True,
        help="Immutable glaze recipe revision used for this manufacturing order.",
    )

    def action_confirm(self):
        for production in self:
            bom = production.bom_id
            if not bom.mb_is_glaze_recipe:
                continue
            if bom.mb_recipe_state != "approved":
                raise UserError(
                    _(
                        "Manufacturing order %(order)s needs an approved glaze recipe; "
                        "%(recipe)s is %(state)s.",
                        order=production.name,
                        recipe=bom.display_name,
                        state=bom.mb_recipe_state,
                    )
                )
            if production.mb_bom_revision_id and production.mb_bom_revision_id != bom:
                raise UserError(
                    _("The recipe revision snapshot on %s cannot be replaced.", production.name)
                )
            production.mb_bom_revision_id = bom
        return super().action_confirm()

    def action_mb_return_to_draft(self):
        """Safely reopen an untouched confirmed/cancelled MO for correction."""
        self._check_company()
        for production in self:
            if production.state not in ("confirmed", "cancel"):
                raise UserError(
                    _(
                        "%s can return to draft only while confirmed or cancelled.",
                        production.name,
                    )
                )
            progressed = production.workorder_ids.filtered(
                lambda wo: wo.state in ("progress", "done")
            )
            loaded = production.workorder_ids.filtered("mb_firing_id")
            if progressed or loaded:
                raise UserError(
                    _(
                        "%s cannot return to draft because work has started or entered "
                        "a physical firing.",
                        production.name,
                    )
                )
            production.workorder_ids.filtered("mb_firing_planned_id").with_context(
                mb_firing_terminal_cleanup=True
            ).write({"mb_firing_planned_id": False})
            production.workorder_ids.mapped("leave_id").unlink()
            moves = production.move_raw_ids | production.move_finished_ids
            moves._action_cancel()
            moves.write({"state": "draft"})
            production.workorder_ids.write({"state": "waiting"})
            production.mb_bom_revision_id = False
        return True

    def action_mb_recipe_documents(self):
        self.ensure_one()
        if not self.bom_id:
            raise UserError(_("This manufacturing order has no bill of materials."))
        return self.bom_id.action_mb_recipe_documents()

    @api.depends("move_raw_ids.state", "move_finished_ids.state")
    def _compute_state(self):
        super()._compute_state()
        for production in self:
            raw_draft = all(move.state == "draft" for move in production.move_raw_ids)
            finished_draft = all(move.state == "draft" for move in production.move_finished_ids)
            if production.state == "cancel" and raw_draft and finished_draft:
                production.state = "draft"
            elif (
                production.state == "confirmed"
                and not production.move_raw_ids
                and production.move_finished_ids
                and finished_draft
            ):
                production.state = "draft"

    def write(self, values):
        session_fields = {
            "mb_throwing_session_id",
            "mb_bisque_session_id",
            "mb_glazing_session_id",
        }
        changed = session_fields & set(values)
        if changed:
            for production in self:
                for field_name in changed:
                    sessions = production[field_name]
                    if values[field_name]:
                        sessions |= self.env[self._fields[field_name].comodel_name].browse(
                            values[field_name]
                        )
                    if any(session.state in session._mb_terminal_states for session in sessions):
                        raise UserError(
                            _(
                                "A manufacturing order cannot be moved into or out of a "
                                "completed workshop session."
                            )
                        )
        return super().write(values)

    def action_mb_inspect(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Unload and inspect"),
            "res_model": "mb.inspection",
            "view_mode": "form",
            "target": "new",
            "context": {"default_production_id": self.id},
        }

    def action_mb_inspect_bisque(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Inspect bisque firing"),
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
                lambda move: move.state == "done"
            ).move_line_ids
            for production in self.filtered(
                lambda production: production.mb_workflow_kind in ("bisque", "glazing")
            )
        }
        result = super()._post_inventory(cancel_backorder=cancel_backorder)
        for production in self:
            lines = early_lines.get(production.id)
            if lines:
                for output_line in production.move_finished_ids.filtered(
                    lambda move: move.state == "done"
                ).move_line_ids:
                    output_line.consume_line_ids = [
                        fields.Command.set((output_line.consume_line_ids | lines).ids)
                    ]
            if production.mb_bom_revision_id:
                output_product = production.product_id
                recipe_revision = production.mb_bom_revision_id
                lots = (
                    production.lot_producing_ids
                    | production.move_finished_ids.filtered(
                        lambda move, output_product=output_product: (
                            move.product_id == output_product
                        )
                    ).move_line_ids.lot_id
                )
                conflicts = lots.filtered(
                    lambda lot, recipe_revision=recipe_revision: (
                        lot.mb_bom_revision_id and lot.mb_bom_revision_id != recipe_revision
                    )
                )
                if conflicts:
                    raise UserError(
                        _(
                            "Produced lots already carry a different recipe revision: %s",
                            ", ".join(conflicts.mapped("name")),
                        )
                    )
                lots.mb_bom_revision_id = recipe_revision
        return result

    def _mb_check_food_contact(self):
        result = super()._mb_check_food_contact()
        for production in self.filtered(lambda mo: mo.product_id.mb_food_contact):
            glaze_lots = production._mb_consumed_glaze_lots()
            internally_produced = (
                self.env["stock.move.line"]
                .search(
                    [
                        ("lot_id", "in", glaze_lots.ids),
                        ("move_id.production_id", "!=", False),
                        ("move_id.state", "=", "done"),
                    ]
                )
                .lot_id
            )
            missing = internally_produced.filtered(
                lambda lot: not lot.mb_bom_revision_id or not lot.mb_bom_revision_id.mb_approved_at
            )
            if missing:
                raise UserError(
                    _(
                        "These glaze lots have no approved recipe revision, so %(order)s "
                        "cannot be released as food contact: %(lots)s",
                        order=production.name,
                        lots=", ".join(missing.mapped("name")),
                    )
                )
        return result

    def button_mark_done(self):
        for production in self.filtered(lambda mo: mo.bom_id.mb_is_glaze_recipe):
            if (
                not production.mb_bom_revision_id
                or production.mb_bom_revision_id != production.bom_id
                or not production.mb_bom_revision_id.mb_approved_at
            ):
                raise UserError(
                    _(
                        "%s cannot be completed without its exact approved recipe revision.",
                        production.name,
                    )
                )
        return super().button_mark_done()

    def _cal_price(self, consumed_moves):
        """Include raw moves consumed when ware first leaves available stock.

        The board workflow completes its selected green/bisque input move at
        session start. Odoo 19 normally prices finished output from raw moves
        completed inside `_post_inventory`; without this union the genealogy is
        correct but the early input cost is absent from the next stock stage.
        """
        if self.mb_workflow_kind in ("bisque", "glazing"):
            consumed_moves |= self.move_raw_ids.filtered(lambda move: move.state == "done")
        return super()._cal_price(consumed_moves)

    def _get_backorder_mo_vals(self):
        """Keep ceramics workflow ownership on Odoo 19 MO splits."""
        values = super()._get_backorder_mo_vals()
        if self.mb_workflow_kind in ("bisque", "glazing"):
            values.update(
                {
                    "mb_workflow_kind": self.mb_workflow_kind,
                    "mb_bisque_session_id": self.mb_bisque_session_id.id,
                    "mb_glazing_session_id": self.mb_glazing_session_id.id,
                    "mb_bom_revision_id": self.mb_bom_revision_id.id,
                }
            )
        return values

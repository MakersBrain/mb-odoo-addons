from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare


class MbInspection(models.TransientModel):
    _name = "mb.inspection"
    _description = "Unload and inspect finished ceramics"

    production_id = fields.Many2one(
        "mrp.production",
        required=True,
        domain=[("mb_workflow_kind", "in", ("glazing", "finishing"))],
    )
    selected_quantity = fields.Float(
        related="production_id.product_qty", string="Selected blanks", readonly=True)
    accepted_quantity = fields.Float(digits="Product Unit")
    second_quantity = fields.Float(digits="Product Unit")
    loss_quantity = fields.Float(digits="Product Unit")
    loss_reason = fields.Text()
    second_product_id = fields.Many2one(
        "product.product", compute="_compute_second_product", readonly=True)
    seconds_location_id = fields.Many2one(
        "stock.location", domain=[("usage", "=", "internal")])
    loss_operation_id = fields.Many2one(
        "mrp.workorder", domain="[('production_id', '=', production_id)]")
    board_id = fields.Many2one(
        "stock.package", compute="_compute_context_links", readonly=True)
    firing_id = fields.Many2one(
        "mb.firing", compute="_compute_context_links", readonly=True)

    @api.model
    def default_get(self, field_list):
        values = super().default_get(field_list)
        production = self.env["mrp.production"].browse(values.get("production_id"))
        if production:
            values["accepted_quantity"] = production.product_qty
            final_order = production.workorder_ids.filtered(
                lambda workorder: workorder.state not in ("done", "cancel"))[-1:]
            values["loss_operation_id"] = final_order.id or False
        return values

    @api.depends("production_id")
    def _compute_second_product(self):
        for wizard in self:
            template = wizard.production_id.product_id.mb_second_product_tmpl_id
            wizard.second_product_id = template.product_variant_id

    @api.depends("production_id", "loss_operation_id")
    def _compute_context_links(self):
        for wizard in self:
            current = wizard.production_id.mb_board_content_ids.filtered(
                lambda line: line.state == "current")[:1]
            wizard.board_id = current.board_id
            wizard.firing_id = wizard.loss_operation_id.mb_firing_id

    @api.constrains("accepted_quantity", "second_quantity", "loss_quantity")
    def _check_nonnegative(self):
        for wizard in self:
            if min(wizard.accepted_quantity, wizard.second_quantity, wizard.loss_quantity) < 0:
                raise ValidationError(_("Inspection quantities cannot be negative."))

    def _create_lots(self, product, quantity):
        if product.tracking == "none" or not quantity:
            return self.env["stock.lot"]
        count = 1 if product.tracking == "lot" else int(quantity)
        if product.tracking == "serial" and quantity != count:
            raise UserError(_("A serial-tracked inspection quantity must be a whole number."))
        return self.env["stock.lot"].create([{
            "name": self.env["ir.sequence"].next_by_code("mb.finished.identity"),
            "product_id": product.id,
            "company_id": self.production_id.company_id.id,
        } for _index in range(count)])

    def _create_second_move(self):
        if not self.second_quantity:
            return self.env["stock.move"]
        if not self.second_product_id:
            raise UserError(_("Configure a seconds product before recording seconds."))
        if not self.seconds_location_id:
            raise UserError(_("Choose the internal location that receives seconds."))
        production = self.production_id
        values = production._get_move_finished_values(
            self.second_product_id.id,
            self.second_quantity,
            self.second_product_id.uom_id.id,
        )
        values.update({
            "location_dest_id": self.seconds_location_id.id,
            "additional": True,
        })
        move = self.env["stock.move"].create(values)
        move._action_confirm()
        lots = self._create_lots(self.second_product_id, self.second_quantity)
        if lots:
            move.lot_ids = lots
        move.quantity = self.second_quantity
        move.picked = True
        return move

    def _prepare_exact_material_consumption(self):
        """Validate and pick the exact reserved BOM quantities for Odoo 19."""
        production = self.production_id
        for move in production.move_raw_ids:
            lines = move.move_line_ids.filtered("quantity")
            quantity = sum(lines.mapped("quantity"))
            if float_compare(
                quantity,
                move.product_uom_qty,
                precision_rounding=move.product_uom.rounding,
            ) != 0:
                raise UserError(_(
                    "%(product)s must be reserved in the exact "
                    "bill-of-material quantity.",
                    product=move.product_id.display_name,
                ))
            if move.product_id.tracking != "none" and any(
                not line.lot_id for line in lines
            ):
                raise UserError(_(
                    "%(product)s requires a lot or serial number before "
                    "inspection.",
                    product=move.product_id.display_name,
                ))
            if move.state != "done":
                move.picked = True

    def action_confirm(self):
        self.ensure_one()
        production = self.production_id
        if production.state in ("done", "cancel") or production.mb_inspected:
            raise UserError(_("This manufacturing order has already been closed."))
        rounding = production.product_uom_id.rounding
        total = self.accepted_quantity + self.second_quantity + self.loss_quantity
        if float_compare(total, production.product_qty, precision_rounding=rounding) != 0:
            raise UserError(_("First-quality, second and process-loss quantities must equal selected blanks."))
        firing_orders = production.workorder_ids.filtered(
            lambda workorder: workorder.operation_id.mb_kiln_program_id
        )
        if any(order.mb_firing_id.state != "done" for order in firing_orders):
            raise UserError(_("Every firing operation must be unloaded before inspection."))
        final_order = production.workorder_ids[-1:]
        unfinished_predecessors = (production.workorder_ids - final_order).filtered(
            lambda workorder: workorder.state not in ("done", "cancel")
        )
        if unfinished_predecessors:
            raise UserError(_("Complete every operation before final inspection."))
        if self.loss_quantity and not self.loss_reason:
            raise UserError(_("Record why the pieces were lost."))
        self._prepare_exact_material_consumption()
        main_lots = self._create_lots(production.product_id, self.accepted_quantity)
        production.lot_producing_ids = [fields.Command.set(main_lots.ids)]
        production.qty_producing = self.accepted_quantity
        production._set_qty_producing()
        self._create_second_move()
        if self.loss_quantity:
            self.env["mb.production.loss"].create({
                "production_id": production.id,
                "quantity": self.loss_quantity,
                "operation_id": self.loss_operation_id.id,
                "reason": self.loss_reason,
                "board_id": self.board_id.id,
                "firing_id": self.firing_id.id,
            })
        production.workorder_ids.filtered(
            lambda workorder: workorder.state not in ("done", "cancel")
        ).button_finish()
        production.with_context(
            skip_backorder=True,
            skip_consumption=True,
            skip_redirection=True,
        ).button_mark_done()
        if production.state != "done":
            raise UserError(_("The manufacturing order needs manual review before completion."))
        production.write({"mb_inspected": True})
        production.mb_board_content_ids.filtered(
            lambda content: content.state == "current").action_remove()
        session = production.mb_finishing_session_id
        if session and all(order.state == "done" for order in session.production_ids):
            session.state = "done"
        glazing_session = production.mb_glazing_session_id
        if glazing_session and all(
            order.state == "done" for order in glazing_session.production_ids
        ):
            glazing_session.state = "done"
        return {"type": "ir.actions.act_window_close"}

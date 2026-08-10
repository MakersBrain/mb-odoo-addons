from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare


class MbBisqueInspection(models.TransientModel):
    _name = "mb.bisque.inspection"
    _description = "Inspect bisque firing output"

    production_id = fields.Many2one(
        "mrp.production",
        required=True,
        domain=[("mb_workflow_kind", "=", "bisque")],
    )
    selected_quantity = fields.Float(
        related="production_id.product_qty", readonly=True
    )
    accepted_quantity = fields.Float(digits="Product Unit")
    loss_quantity = fields.Float(digits="Product Unit")
    loss_reason = fields.Text()
    loss_operation_id = fields.Many2one(
        "mrp.workorder", domain="[('production_id', '=', production_id)]"
    )
    board_id = fields.Many2one(
        "stock.package", compute="_compute_context_links", readonly=True
    )
    firing_id = fields.Many2one(
        "mb.firing", compute="_compute_context_links", readonly=True
    )
    destination_location_id = fields.Many2one(
        related="production_id.location_dest_id", readonly=True
    )

    @api.model
    def default_get(self, field_list):
        values = super().default_get(field_list)
        production = self.env["mrp.production"].browse(values.get("production_id"))
        if production:
            values["accepted_quantity"] = production.product_qty
            firing_order = production.workorder_ids.filtered(
                lambda workorder: workorder.operation_id.mb_kiln_program_id.kind
                == "bisque"
            )[-1:]
            values["loss_operation_id"] = firing_order.id or False
        return values

    @api.depends("production_id", "loss_operation_id")
    def _compute_context_links(self):
        for wizard in self:
            current = wizard.production_id.mb_board_content_ids.filtered(
                lambda line: line.state == "current"
            )[:1]
            wizard.board_id = current.board_id
            wizard.firing_id = wizard.loss_operation_id.mb_firing_id

    @api.constrains("accepted_quantity", "loss_quantity")
    def _check_nonnegative(self):
        for wizard in self:
            if min(wizard.accepted_quantity, wizard.loss_quantity) < 0:
                raise ValidationError("Inspection quantities cannot be negative.")

    def _prepare_exact_material_consumption(self):
        for move in self.production_id.move_raw_ids:
            lines = move.move_line_ids.filtered("quantity")
            quantity = sum(lines.mapped("quantity"))
            if float_compare(
                quantity,
                move.product_uom_qty,
                precision_rounding=move.product_uom.rounding,
            ) != 0:
                raise UserError(
                    "%s must be reserved in the exact bill-of-material quantity."
                    % move.product_id.display_name
                )
            if move.product_id.tracking != "none" and any(
                not line.lot_id for line in lines
            ):
                raise UserError(
                    "%s requires a lot or serial number before inspection."
                    % move.product_id.display_name
                )
            if move.state != "done":
                move.picked = True

    def _create_output_lots(self, quantity=None):
        product = self.production_id.product_id
        quantity = self.accepted_quantity if quantity is None else quantity
        if not quantity or product.tracking == "none":
            return self.env["stock.lot"]
        count = 1 if product.tracking == "lot" else int(quantity)
        if product.tracking == "serial" and quantity != count:
            raise UserError("A serial-tracked bisque quantity must be a whole number.")
        return self.env["stock.lot"].create([{
            "name": self.env["ir.sequence"].next_by_code("mb.bisque.lot"),
            "product_id": product.id,
            "company_id": self.production_id.company_id.id,
        } for _index in range(count)])

    def _complete_total_loss(self):
        """Complete through public MRP, then scrap the entire failed output.

        This keeps Odoo's normal manufacturing valuation, genealogy and
        terminal transitions intact. The failed ware is then removed with the
        public stock.scrap workflow instead of reproducing private MRP state.
        """
        production = self.production_id
        lots = self._create_output_lots(production.product_qty)
        production.lot_producing_ids = [fields.Command.set(lots.ids)]
        production.qty_producing = production.product_qty
        production.set_qty_producing()
        production.with_context(
            skip_backorder=True,
            skip_consumption=True,
            skip_redirection=True,
        ).button_mark_done()
        if production.state != "done":
            raise UserError(
                "The bisque order needs manual review before its loss can be scrapped."
            )
        if production.product_id.tracking == "serial":
            quantities = [(lot, 1.0) for lot in lots]
        else:
            quantities = [(lots, production.product_qty)]
        for lot, quantity in quantities:
            scrap = self.env["stock.scrap"].create({
                "company_id": production.company_id.id,
                "origin": production.name,
                "product_id": production.product_id.id,
                "product_uom_id": production.product_uom_id.id,
                "scrap_qty": quantity,
                "lot_id": lot[:1].id,
                "location_id": production.location_dest_id.id,
            })
            result = scrap.action_validate()
            if result is not True:
                raise UserError(
                    "The manufactured loss is not available in the destination "
                    "location for scrapping."
                )

    def action_confirm(self):
        self.ensure_one()
        production = self.production_id
        if production.state in ("done", "cancel") or production.mb_bisque_inspected:
            raise UserError("This bisque manufacturing order has already been closed.")
        if float_compare(
            self.accepted_quantity + self.loss_quantity,
            production.product_qty,
            precision_rounding=production.product_uom_id.rounding,
        ) != 0:
            raise UserError(
                "Accepted and process-loss quantities must equal the selected green ware."
            )
        firing_orders = production.workorder_ids.filtered(
            lambda workorder: workorder.operation_id.mb_kiln_program_id.kind == "bisque"
        )
        if not firing_orders or any(
            order.mb_firing_id.state != "done" for order in firing_orders
        ):
            raise UserError("Every bisque firing operation must be unloaded before inspection.")
        unfinished = production.workorder_ids.filtered(
            lambda workorder: workorder.state not in ("done", "cancel")
        )
        if unfinished:
            raise UserError("Complete every bisque operation before inspection.")
        if self.loss_quantity and not self.loss_reason:
            raise UserError("Record why the pieces were lost.")
        self._prepare_exact_material_consumption()
        lots = self._create_output_lots()
        production.lot_producing_ids = [fields.Command.set(lots.ids)]
        production.qty_producing = self.accepted_quantity
        production._set_qty_producing()
        if self.loss_quantity:
            self.env["mb.production.loss"].create({
                "production_id": production.id,
                "quantity": self.loss_quantity,
                "operation_id": self.loss_operation_id.id,
                "reason": self.loss_reason,
                "board_id": self.board_id.id,
                "firing_id": self.firing_id.id,
            })
        if self.accepted_quantity:
            production.with_context(
                skip_backorder=True,
                skip_consumption=True,
                skip_redirection=True,
            ).button_mark_done()
        else:
            self._complete_total_loss()
        if production.state != "done":
            raise UserError("The bisque order needs manual review before completion.")
        production.mb_bisque_inspected = True
        production.mb_board_content_ids.filtered(
            lambda content: content.state == "current"
        ).action_remove()
        session = production.mb_bisque_session_id
        if session and all(order.state == "done" for order in session.production_ids):
            session.state = "done"
        if lots:
            return lots[:1].with_context(
                mb_wip_quantity=self.accepted_quantity
            ).action_mb_print_wip_label()
        return {"type": "ir.actions.act_window_close"}

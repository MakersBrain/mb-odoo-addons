from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare


class MbBoardContent(models.Model):
    _name = "mb.board.content"
    _description = "Ware board WIP content"
    _order = "state, date_loaded desc, id desc"

    board_id = fields.Many2one(
        "stock.package",
        required=True,
        ondelete="restrict",
        index=True,
        domain="[('package_type_id.package_use', '=', 'reusable')]",
    )
    production_id = fields.Many2one(
        "mrp.production",
        required=True,
        ondelete="restrict",
        index=True,
        domain=[("mb_workflow_kind", "in", ("bisque", "glazing", "finishing"))],
    )
    product_id = fields.Many2one(
        related="production_id.product_id", store=True, index=True)
    quantity = fields.Float(required=True, digits="Product Unit")
    current_workorder_id = fields.Many2one(
        "mrp.workorder", string="Current operation", ondelete="restrict")
    state = fields.Selection(
        [("current", "Current"), ("removed", "Removed")],
        required=True,
        default="current",
        index=True,
    )
    date_loaded = fields.Datetime(
        required=True, default=fields.Datetime.now, readonly=True)
    date_unloaded = fields.Datetime(readonly=True)
    previous_content_id = fields.Many2one(
        "mb.board.content", readonly=True, ondelete="restrict")
    company_id = fields.Many2one(
        related="production_id.company_id", store=True, index=True)

    _positive_quantity = models.Constraint(
        "CHECK(quantity > 0)", "A board-content quantity must be positive.")

    @api.constrains(
        "board_id", "production_id", "quantity", "state", "current_workorder_id")
    def _check_content(self):
        for content in self:
            if content.board_id.package_type_id.package_use != "reusable":
                raise ValidationError("Ware may only be assigned to a reusable package.")
            if (content.board_id.company_id
                    and content.board_id.company_id != content.production_id.company_id):
                raise ValidationError("The board and manufacturing order must share a company.")
            if (content.current_workorder_id
                    and content.current_workorder_id.production_id != content.production_id):
                raise ValidationError("The current operation must belong to the manufacturing order.")
            current = self.search([
                ("production_id", "=", content.production_id.id),
                ("state", "=", "current"),
            ])
            total = sum(current.mapped("quantity"))
            if float_compare(
                    total,
                    content.production_id.product_qty,
                    precision_rounding=content.production_id.product_uom_id.rounding) > 0:
                raise ValidationError(
                    "Current board quantities cannot exceed the manufacturing quantity.")

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if not values.get("current_workorder_id") and values.get("production_id"):
                production = self.env["mrp.production"].browse(values["production_id"])
                operation = production.workorder_ids.filtered(
                    lambda workorder: workorder.state not in ("done", "cancel"))[:1]
                values["current_workorder_id"] = operation.id or False
        return super().create(vals_list)

    def action_remove(self):
        current = self.filtered(lambda line: line.state == "current")
        current.write({"state": "removed", "date_unloaded": fields.Datetime.now()})
        return True

    def transfer_to(self, board):
        self.ensure_one()
        board.ensure_one()
        if self.state != "current":
            raise UserError("Only current board content can be transferred.")
        self.action_remove()
        replacement = self.create({
            "board_id": board.id,
            "production_id": self.production_id.id,
            "quantity": self.quantity,
            "current_workorder_id": self.current_workorder_id.id,
            "previous_content_id": self.id,
        })
        return replacement

    def action_split_for_later(self):
        """Move this complete board line to its own Odoo 19 MO backorder."""
        self.ensure_one()
        if self.state != "current":
            raise UserError("Only current board content can be split.")
        production = self.production_id
        remaining = production.product_qty - self.quantity
        if float_compare(
                remaining, 0, precision_rounding=production.product_uom_id.rounding) <= 0:
            raise UserError("There is no other quantity to keep on the original order.")
        previous_operation = self.current_workorder_id.operation_id
        split = production._split_productions(
            amounts={production: [remaining, self.quantity]},
            cancel_remaining_qty=True,
            set_consumed_qty=True,
        )
        deferred = (split - production)[:1]
        if not deferred:
            raise UserError("Odoo did not create the expected split manufacturing order.")
        deferred_operation = deferred.workorder_ids.filtered(
            lambda workorder: workorder.operation_id == previous_operation)[:1]
        self.write({
            "production_id": deferred.id,
            "current_workorder_id": deferred_operation.id or False,
        })
        return deferred

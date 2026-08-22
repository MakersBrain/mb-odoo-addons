from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class PosOrder(models.Model):
    _inherit = "pos.order"

    mb_commercial_operation_id = fields.Many2one(
        "mb.commercial.operation",
        check_company=True,
        copy=False,
        index=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            session = self.env["pos.session"].browse(values.get("session_id"))
            if session.mb_commercial_operation_id:
                values.setdefault(
                    "mb_commercial_operation_id",
                    session.mb_commercial_operation_id.id,
                )
        return super().create(vals_list)

    def write(self, values):
        if "mb_commercial_operation_id" in values:
            operations = self.mb_commercial_operation_id | self.env[
                "mb.commercial.operation"
            ].browse(values.get("mb_commercial_operation_id"))
            if operations.filtered(lambda operation: operation.state == "financially_closed"):
                raise UserError(
                    _("Reopen the financially closed operation before changing POS links.")
                )
            if self.filtered(lambda order: order.state not in ("draft", "cancel")):
                raise UserError(_("A processed POS order cannot be moved to another operation."))
        return super().write(values)

    def _prepare_refund_values(self, current_session):
        values = super()._prepare_refund_values(current_session)
        if self.mb_commercial_operation_id:
            if current_session.mb_commercial_operation_id != self.mb_commercial_operation_id:
                raise ValidationError(
                    _(
                        "Refund this sale from a POS session configured for the original market operation."
                    )
                )
            values["mb_commercial_operation_id"] = self.mb_commercial_operation_id.id
        return values

    def _prepare_invoice_vals(self):
        values = super()._prepare_invoice_vals()
        operations = self.mb_commercial_operation_id
        if len(operations) == 1:
            values["mb_commercial_operation_id"] = operations.id
        return values

    @api.model
    def _get_invoice_lines_values(self, line_values, pos_line, move_type):
        values = super()._get_invoice_lines_values(line_values, pos_line, move_type)
        operation = pos_line.order_id.mb_commercial_operation_id
        if operation and not values.get("display_type"):
            values["analytic_distribution"] = {
                str(operation.analytic_account_id.id): 100.0,
            }
        return values

    def _prepare_product_aml_dict(self, base_line_vals, update_base_line_vals, rate, sign):
        values = super()._prepare_product_aml_dict(
            base_line_vals,
            update_base_line_vals,
            rate,
            sign,
        )
        operation = base_line_vals["record"].order_id.mb_commercial_operation_id
        if operation:
            values["analytic_distribution"] = {
                str(operation.analytic_account_id.id): 100.0,
            }
        return values

    def _create_order_picking(self):
        result = super()._create_order_picking()
        for order in self.filtered("mb_commercial_operation_id"):
            stockable = order.lines.filtered(
                lambda line: (
                    line.product_id.is_storable and not line.product_uom_id.is_zero(line.qty)
                )
            )
            if stockable and (
                not order.picking_ids
                or order.picking_ids.filtered(lambda picking: picking.state != "done")
            ):
                raise ValidationError(
                    _(
                        "The market sale could not consume its exact event stock. "
                        "Resolve the stock shortage before validating the order."
                    )
                )
        return result


class PosOrderLine(models.Model):
    _inherit = "pos.order.line"

    mb_commercial_operation_id = fields.Many2one(
        related="order_id.mb_commercial_operation_id",
        store=True,
    )

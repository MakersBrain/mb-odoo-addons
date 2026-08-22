from odoo import _, fields, models
from odoo.exceptions import ValidationError


class StockRule(models.Model):
    _inherit = "stock.rule"

    def _get_stock_move_values(
        self,
        product_id,
        product_qty,
        product_uom,
        location_dest_id,
        name,
        origin,
        company_id,
        values,
    ):
        move_values = super()._get_stock_move_values(
            product_id,
            product_qty,
            product_uom,
            location_dest_id,
            name,
            origin,
            company_id,
            values,
        )
        operation = values.get("mb_commercial_operation_id")
        if operation:
            if not isinstance(operation, models.BaseModel):
                operation = self.env["mb.commercial.operation"].browse(operation)
            operation.ensure_one()
            move_values.update(
                {
                    "location_id": operation.market_location_id.id,
                    "mb_commercial_operation_id": operation.id,
                }
            )
        return move_values


class StockMove(models.Model):
    _inherit = "stock.move"

    mb_commercial_operation_id = fields.Many2one(
        "mb.commercial.operation",
        check_company=True,
        copy=False,
        index=True,
    )

    def _get_new_picking_values(self):
        values = super()._get_new_picking_values()
        operations = self.mb_commercial_operation_id
        if len(operations) == 1:
            values.update(
                {
                    "mb_commercial_operation_id": operations.id,
                    "project_id": operations.project_id.id,
                }
            )
        return values


class StockReturnPicking(models.TransientModel):
    _inherit = "stock.return.picking"

    def _prepare_picking_default_values_based_on(self, picking):
        values = super()._prepare_picking_default_values_based_on(picking)
        if picking.mb_commercial_operation_id:
            return_type = picking.picking_type_id.return_picking_type_id or picking.picking_type_id
            if not return_type.analytic_costs:
                raise ValidationError(
                    _(
                        "Enable Analytic Costs on return operation type %(operation_type)s before returning market sales.",
                        operation_type=return_type.display_name,
                    )
                )
            values.update(
                {
                    "mb_commercial_operation_id": picking.mb_commercial_operation_id.id,
                    "project_id": picking.project_id.id,
                }
            )
        return values

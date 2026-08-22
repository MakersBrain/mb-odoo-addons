from odoo import fields, models


class StockPickingType(models.Model):
    _inherit = "stock.picking.type"

    mb_commercial_operation_id = fields.Many2one(
        "mb.commercial.operation",
        check_company=True,
        copy=False,
        index=True,
    )


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _prepare_picking_vals(self, partner, picking_type, location_id, location_dest_id):
        values = super()._prepare_picking_vals(
            partner,
            picking_type,
            location_id,
            location_dest_id,
        )
        operation = picking_type.mb_commercial_operation_id
        if operation:
            values.update(
                {
                    "mb_commercial_operation_id": operation.id,
                    "project_id": operation.project_id.id,
                }
            )
        return values

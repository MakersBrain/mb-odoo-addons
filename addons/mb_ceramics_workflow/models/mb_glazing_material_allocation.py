from odoo import api, fields, models
from odoo.exceptions import ValidationError


class MbGlazingMaterialAllocation(models.Model):
    _name = "mb.glazing.material.allocation"
    _description = "Exact tracked material allocation for glazing"
    _order = "product_id, lot_id, id"

    session_line_id = fields.Many2one(
        "mb.glazing.session.line", required=True, ondelete="cascade", index=True
    )
    product_id = fields.Many2one(
        "product.product", required=True, domain=[("tracking", "!=", "none")]
    )
    lot_id = fields.Many2one(
        "stock.lot", required=True, domain="[('product_id', '=', product_id)]"
    )
    quantity = fields.Float(required=True, digits="Product Unit", default=1.0)
    available_quantity = fields.Float(
        compute="_compute_available_quantity", digits="Product Unit", readonly=True
    )
    uom_id = fields.Many2one("uom.uom", required=True)
    company_id = fields.Many2one(
        related="session_line_id.session_id.company_id", store=True, index=True
    )
    raw_move_id = fields.Many2one("stock.move", readonly=True, copy=False)

    _positive_quantity = models.Constraint(
        "CHECK(quantity > 0)", "An allocated material quantity must be positive."
    )

    @api.depends(
        "product_id",
        "lot_id",
        "session_line_id.session_id.material_location_id",
    )
    def _compute_available_quantity(self):
        for allocation in self:
            location = allocation.session_line_id.session_id.material_location_id
            if not (allocation.product_id and allocation.lot_id and location):
                allocation.available_quantity = 0
                continue
            allocation.available_quantity = self.env[
                "stock.quant"
            ]._get_available_quantity(
                allocation.product_id,
                location,
                lot_id=allocation.lot_id,
                strict=True,
            )

    @api.onchange("product_id")
    def _onchange_product_id(self):
        self.uom_id = self.product_id.uom_id
        if self.lot_id.product_id != self.product_id:
            self.lot_id = False

    @api.constrains("product_id", "lot_id", "uom_id", "company_id")
    def _check_allocation(self):
        for allocation in self:
            if allocation.product_id.tracking == "none":
                raise ValidationError("Only tracked components need an exact lot allocation.")
            if allocation.lot_id.product_id != allocation.product_id:
                raise ValidationError("The allocated lot belongs to another product.")
            if not allocation.uom_id._has_common_reference(
                allocation.product_id.uom_id
            ):
                raise ValidationError("The allocation UoM is incompatible with the product UoM.")
            if (
                allocation.lot_id.company_id
                and allocation.lot_id.company_id != allocation.company_id
            ):
                raise ValidationError("The allocated lot belongs to another company.")

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class MbGlazingMaterialAllocation(models.Model):
    _name = "mb.glazing.material.allocation"
    _description = "Exact tracked material allocation for glazing"
    _order = "product_id, lot_id, id"
    _check_company_auto = True

    session_line_id = fields.Many2one(
        "mb.glazing.session.line",
        required=True,
        ondelete="cascade",
        index=True,
        check_company=True,
    )
    product_id = fields.Many2one(
        "product.product",
        required=True,
        domain=[("tracking", "!=", "none")],
        check_company=True,
    )
    lot_id = fields.Many2one(
        "stock.lot",
        required=True,
        domain="[('product_id', '=', product_id)]",
        check_company=True,
    )
    quantity = fields.Float(required=True, digits="Product Unit", default=1.0)
    available_quantity = fields.Float(
        compute="_compute_available_quantity", digits="Product Unit", readonly=True
    )
    uom_id = fields.Many2one("uom.uom", required=True)
    company_id = fields.Many2one(
        related="session_line_id.session_id.company_id",
        store=True,
        required=True,
        index=True,
        precompute=True,
    )
    raw_move_id = fields.Many2one("stock.move", readonly=True, copy=False, check_company=True)

    _positive_quantity = models.Constraint(
        "CHECK(quantity > 0)", "An allocated material quantity must be positive."
    )

    def _check_session_open(self):
        if any(
            allocation.session_line_id.session_id.state
            in allocation.session_line_id.session_id._mb_terminal_states
            for allocation in self
        ):
            raise UserError(
                _(
                    "Materials of a completed glazing session are immutable. "
                    "Create a correcting session instead."
                )
            )

    @api.model_create_multi
    def create(self, vals_list):
        lines = self.env["mb.glazing.session.line"].browse(
            [values.get("session_line_id") for values in vals_list if values.get("session_line_id")]
        )
        if any(line.session_id.state in line.session_id._mb_terminal_states for line in lines):
            raise UserError(
                _(
                    "Materials cannot be added to a completed or cancelled glazing "
                    "session. Create a correcting session instead."
                )
            )
        return super().create(vals_list)

    def write(self, values):
        self._check_session_open()
        return super().write(values)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_open_session(self):
        self._check_session_open()

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
            allocation.available_quantity = self.env["stock.quant"]._get_available_quantity(
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
                raise ValidationError(_("Only tracked components need an exact lot allocation."))
            if allocation.lot_id.product_id != allocation.product_id:
                raise ValidationError(_("The allocated lot belongs to another product."))
            if not allocation.uom_id._has_common_reference(allocation.product_id.uom_id):
                raise ValidationError(_("The allocation UoM is incompatible with the product UoM."))
            if (
                allocation.lot_id.company_id
                and allocation.lot_id.company_id != allocation.company_id
            ):
                raise ValidationError(_("The allocated lot belongs to another company."))

from odoo import _, fields, models
from odoo.exceptions import ValidationError


class MbCommercialOperationPlanWizard(models.TransientModel):
    _inherit = "mb.commercial.operation.plan.wizard"

    source_warehouse_id = fields.Many2one("stock.warehouse", check_company=True)
    source_location_id = fields.Many2one("stock.location", check_company=True)
    stock_preparation_deadline = fields.Datetime()

    def default_get(self, field_list):
        values = super().default_get(field_list)
        operation = self.env["mb.commercial.operation"].browse(values.get("operation_id"))
        if operation:
            values.update({
                "source_warehouse_id": operation.source_warehouse_id.id,
                "source_location_id": operation.source_location_id.id,
                "stock_preparation_deadline": operation.stock_preparation_deadline,
            })
        return values

    def _operation_values(self):
        values = super()._operation_values()
        values.update({
            "source_warehouse_id": self.source_warehouse_id.id,
            "source_location_id": self.source_location_id.id,
            "stock_preparation_deadline": self.stock_preparation_deadline,
        })
        return values

    def _after_operation_saved(self, operation, scenario):
        result = super()._after_operation_saved(operation, scenario)
        self._sync_deadline_activity(
            operation, _("Prepare commercial stock"), self.stock_preparation_deadline,
        )
        return result

    def action_refresh_stock(self):
        self.ensure_one()
        if not self.source_warehouse_id:
            raise ValidationError(_("Choose a source warehouse before refreshing stock."))
        location = self.source_location_id or self.source_warehouse_id.lot_stock_id
        for line in self.line_ids.filtered("product_id"):
            target = line.source_stock_plan_line_id
            if target:
                target._refresh_availability()
                line.on_hand_now = target.on_hand_now
                line.reserved_now = target.reserved_now
                line.forecast_available = target.forecast_available
                line.shortage_qty = target.shortage_qty
                line.readiness = target.readiness
                continue
            groups = self.env["stock.quant"]._read_group(
                [("product_id", "=", line.product_id.id), ("location_id", "child_of", location.id)],
                [], ["quantity:sum", "reserved_quantity:sum"],
            )
            quantity, reserved = groups[0] if groups else (0.0, 0.0)
            available = quantity - reserved
            line.on_hand_now = quantity
            line.reserved_now = reserved
            line.forecast_available = available
            line.shortage_qty = max(0.0, line.desired_opening_qty + line.safety_qty - available)
            line.readiness = "shortage" if line.shortage_qty else "planned"
        return {
            "type": "ir.actions.act_window", "name": _("Complete Planning"),
            "res_model": self._name, "res_id": self.id, "view_mode": "form", "target": "new",
        }


class MbCommercialOperationPlanWizardLine(models.TransientModel):
    _inherit = "mb.commercial.operation.plan.wizard.line"

    on_hand_now = fields.Float(readonly=True)
    reserved_now = fields.Float(readonly=True)
    forecast_available = fields.Float(readonly=True)
    shortage_qty = fields.Float(readonly=True)
    readiness = fields.Selection(
        selection=lambda self: self.env["mb.market.stock.plan.line"]._fields["readiness"].selection,
        readonly=True,
    )

from odoo import api, fields, models


class MbCommercialOperationPlanWizard(models.TransientModel):
    _inherit = "mb.commercial.operation.plan.wizard"

    depot_warehouse_id = fields.Many2one("stock.warehouse", check_company=True)
    recovery_scope = fields.Selection(
        [
            ("operation_only", "Operation-linked evidence only"),
            ("until_next_refill", "Depot sales until next approved refill"),
            ("contract_period", "Selected contract period"),
            ("informational", "Planning only"),
        ],
        default="until_next_refill",
    )
    recovery_date_from = fields.Datetime()
    recovery_date_to = fields.Datetime()

    def default_get(self, field_list):
        values = super().default_get(field_list)
        operation = self.env["mb.commercial.operation"].browse(values.get("operation_id"))
        if operation:
            values.update(
                {
                    "depot_warehouse_id": operation.depot_warehouse_id.id,
                    "recovery_scope": operation.recovery_scope,
                    "recovery_date_from": operation.recovery_date_from,
                    "recovery_date_to": operation.recovery_date_to,
                }
            )
        return values

    @api.onchange("contract_id")
    def _onchange_depot_contract_id(self):
        if self.contract_id.depot_warehouse_id:
            self.depot_warehouse_id = self.contract_id.depot_warehouse_id
            self.source_warehouse_id = self.contract_id.source_warehouse_id

    def _operation_values(self):
        values = super()._operation_values()
        if self.operation_type in ("depot_refill", "depot_permanence"):
            values.update(
                {
                    "depot_warehouse_id": self.depot_warehouse_id.id,
                    "recovery_scope": self.recovery_scope,
                    "recovery_date_from": self.recovery_date_from,
                    "recovery_date_to": self.recovery_date_to,
                    "profitability_required": True,
                }
            )
            if self.contract_id.project_id:
                values["project_id"] = self.contract_id.project_id.id
        return values

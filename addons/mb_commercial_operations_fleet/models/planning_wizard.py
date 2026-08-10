from odoo import fields, models


class MbCommercialOperationPlanWizard(models.TransientModel):
    _inherit = "mb.commercial.operation.plan.wizard"

    vehicle_id = fields.Many2one("fleet.vehicle", check_company=True)
    vehicle_conflict_acknowledged = fields.Boolean()

    def default_get(self, field_list):
        values = super().default_get(field_list)
        operation = self.env["mb.commercial.operation"].browse(values.get("operation_id"))
        contract = self.env["mb.commercial.contract"].browse(values.get("contract_id"))
        values["vehicle_id"] = (operation.vehicle_id or contract.default_vehicle_id).id
        if operation:
            values["vehicle_conflict_acknowledged"] = operation.vehicle_conflict_acknowledged
        return values

    def _operation_values(self):
        values = super()._operation_values()
        values.update({
            "vehicle_id": self.vehicle_id.id,
            "vehicle_conflict_acknowledged": self.vehicle_conflict_acknowledged,
        })
        return values

from odoo import _, fields, models
from odoo.exceptions import UserError, ValidationError


class MbCommercialContract(models.Model):
    _inherit = "mb.commercial.contract"

    default_vehicle_id = fields.Many2one("fleet.vehicle", check_company=True, tracking=True)


class MbCommercialOperation(models.Model):
    _inherit = "mb.commercial.operation"

    vehicle_id = fields.Many2one("fleet.vehicle", check_company=True, tracking=True)
    vehicle_conflict_acknowledged = fields.Boolean(copy=False, tracking=True)

    def write(self, vals):
        if {"vehicle_id", "vehicle_conflict_acknowledged"}.intersection(vals):
            if self.filtered(lambda operation: operation.state in ("done", "financially_closed", "cancelled")):
                raise UserError(_("Completed or closed operations cannot change vehicle assignment."))
            if "vehicle_id" in vals and self.filtered(lambda operation: operation.state not in ("draft", "quoted")):
                raise UserError(_("Reopen the approved operation before changing its vehicle."))
        return super().write(vals)

    def _check_user_conflicts(self):
        super()._check_user_conflicts()
        for operation in self.filtered("vehicle_id"):
            conflict = self.search([
                ("id", "!=", operation.id),
                ("company_id", "=", operation.company_id.id),
                ("vehicle_id", "=", operation.vehicle_id.id),
                ("state", "not in", ("cancelled", "financially_closed")),
                ("planned_start", "<", operation.planned_end),
                ("planned_end", ">", operation.planned_start),
            ], limit=1)
            if conflict and not operation.vehicle_conflict_acknowledged:
                raise ValidationError(_(
                    "Vehicle %(vehicle)s is already assigned to %(operation)s in this time window.",
                    vehicle=operation.vehicle_id.display_name,
                    operation=conflict.display_name,
                ))

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class MbTravelEstimate(models.Model):
    _inherit = "mb.travel.estimate"

    vehicle_id = fields.Many2one("fleet.vehicle", check_company=True, tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            operation = self.env["mb.commercial.operation"].browse(vals.get("operation_id"))
            vehicle = self.env["fleet.vehicle"].browse(vals.get("vehicle_id"))
            if not vehicle and operation:
                vehicle = operation.vehicle_id or operation.contract_id.default_vehicle_id
                if vehicle:
                    vals["vehicle_id"] = vehicle.id
            if vehicle:
                vals.setdefault("vehicle_class", vehicle.mb_tollquote_vehicle_class)
                vals.setdefault("payment_option", vehicle.mb_tollquote_payment_option)
                vals.setdefault("fuel_consumption_l_per_100km", vehicle.mb_fuel_consumption_l_per_100km)
                vals.setdefault("driver_cost_eur_per_hour", vehicle.mb_driver_cost_eur_per_hour)
        return super().create(vals_list)

    def write(self, vals):
        if "vehicle_id" in vals and self.filtered(lambda estimate: estimate.state in ("accepted", "superseded")):
            raise UserError(_("Accepted travel estimates are immutable; calculate a new revision."))
        return super().write(vals)

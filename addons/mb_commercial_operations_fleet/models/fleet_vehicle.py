from odoo import fields, models


class FleetVehicle(models.Model):
    _inherit = "fleet.vehicle"

    mb_tollquote_vehicle_class = fields.Integer(default=1)
    mb_tollquote_payment_option = fields.Integer(default=1)
    mb_fuel_consumption_l_per_100km = fields.Float(default=7.0)
    mb_driver_cost_eur_per_hour = fields.Monetary(
        currency_field="currency_id",
        default=0.0,
    )
    mb_cost_per_km = fields.Monetary(currency_field="currency_id", default=0.0)

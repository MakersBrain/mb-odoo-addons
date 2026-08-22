from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCommercialFleet(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        brand = cls.env["fleet.vehicle.model.brand"].create({"name": "Test Brand"})
        model = cls.env["fleet.vehicle.model"].create({"name": "Van", "brand_id": brand.id})
        cls.vehicle = cls.env["fleet.vehicle"].create(
            {
                "model_id": model.id,
                "license_plate": "MARKET-1",
                "mb_tollquote_vehicle_class": 2,
                "mb_tollquote_payment_option": 3,
                "mb_fuel_consumption_l_per_100km": 9.5,
                "mb_driver_cost_eur_per_hour": 22.0,
            }
        )
        cls.partner = cls.env["res.partner"].create({"name": "Market"})
        cls.connector = cls.env["mb.tollquote.connector"].create(
            {
                "name": "Stage",
                "api_token": "test",
            }
        )

    def _operation(self, start, name="Market"):
        return self.env["mb.commercial.operation"].create(
            {
                "name": name,
                "partner_id": self.partner.id,
                "planned_start": start,
                "planned_end": start + timedelta(hours=6),
                "vehicle_id": self.vehicle.id,
            }
        )

    def test_vehicle_defaults_are_frozen_on_travel_estimate(self):
        start = fields.Datetime.now() + timedelta(days=10)
        operation = self._operation(start)
        estimate = self.env["mb.travel.estimate"].create(
            {
                "operation_id": operation.id,
                "connector_id": self.connector.id,
                "origin_latitude": 48.8,
                "origin_longitude": 2.3,
                "destination_latitude": 49.2,
                "destination_longitude": 4.0,
            }
        )
        self.assertEqual(estimate.vehicle_id, self.vehicle)
        self.assertEqual(estimate.vehicle_class, 2)
        self.assertEqual(estimate.payment_option, 3)
        self.assertEqual(estimate.fuel_consumption_l_per_100km, 9.5)
        self.assertEqual(estimate.driver_cost_eur_per_hour, 22.0)

    def test_vehicle_conflict_requires_acknowledgement(self):
        start = fields.Datetime.now() + timedelta(days=10)
        self._operation(start, "First").action_approve()
        second = self._operation(start + timedelta(hours=1), "Second")
        with self.assertRaises(ValidationError):
            second.action_approve()
        second.vehicle_conflict_acknowledged = True
        second.action_approve()

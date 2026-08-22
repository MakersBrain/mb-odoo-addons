from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSupplierLot(TransactionCase):
    """Retaining a supplier's batch is a workshop policy, not a food policy.

    The distinctness from food contact is asserted in mb_ceramics_compliance,
    which is the only place both fields exist. Here the point is narrower and
    the reason this addon still has a model at all: the rule holds with no
    vertical installed.
    """

    def test_supplier_lot_requirement_requires_tracking(self):
        material = self.env["product.template"].create(
            {
                "name": "Supplier material",
                "is_storable": True,
                "tracking": "lot",
                "mb_supplier_lot_required": True,
            }
        )
        with self.assertRaises(ValidationError):
            material.tracking = "none"

    def test_untracked_material_may_leave_the_flag_off(self):
        material = self.env["product.template"].create(
            {
                "name": "Bulk sand",
                "is_storable": True,
                "tracking": "none",
            }
        )
        self.assertFalse(material.mb_supplier_lot_required)

    def test_the_continuous_calendar_is_here_and_is_continuous(self):
        calendar = self.env.ref("mb_workshop_base.mb_calendar_continuous")
        self.assertEqual(calendar.tz, "UTC")
        self.assertEqual(len(calendar.attendance_ids), 7)
        self.assertEqual(sum(calendar.attendance_ids.mapped("hour_to")), 7 * 24.0)

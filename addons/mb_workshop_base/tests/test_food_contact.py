from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestFoodContact(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mug = cls.env["product.template"].create({
            "name": "Mug Poulpe",
            "is_storable": True,
        })
        cls.plate = cls.env["product.template"].create({
            "name": "Plat decoratif Poulpe",
            "is_storable": True,
        })

    def test_food_contact_requires_tracking(self):
        """The constraint holds where the onchange never runs."""
        with self.assertRaises(ValidationError):
            self.mug.write({"mb_food_contact": True, "tracking": "none"})

    def test_food_contact_accepts_lot_or_serial(self):
        self.mug.write({"mb_food_contact": True, "tracking": "lot"})
        self.assertTrue(self.mug.mb_food_contact)
        self.mug.write({"tracking": "serial"})
        self.assertEqual(self.mug.tracking, "serial")

    def test_limit_class_refused_on_decorative_ware(self):
        """84/500/EEC does not reach an article not intended for food."""
        with self.assertRaises(ValidationError):
            self.plate.write({"mb_migration_limit_class": "cat2"})

    def test_decorative_tableware_gets_a_warning(self):
        self.plate.write({"mb_tableware_form": True})
        self.assertTrue(self.plate.mb_label_food_warning)

    def test_food_contact_ware_gets_no_warning(self):
        self.mug.write({
            "mb_food_contact": True,
            "tracking": "lot",
            "mb_tableware_form": True,
        })
        self.assertFalse(self.mug.mb_label_food_warning)


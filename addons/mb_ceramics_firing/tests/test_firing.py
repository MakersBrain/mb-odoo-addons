from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestFiring(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.kiln = cls.env["mb.kiln"].create({"name": "Rohde Ecotop 80"})
        cls.firing = cls.env["mb.firing"].create({
            "kiln_id": cls.kiln.id,
            "kind": "glaze",
        })

    def test_sequence_names_the_firing(self):
        self.assertNotEqual(self.firing.name, "New")

    def test_unload_refused_while_cooling(self):
        self.firing.write({
            "state": "cooling",
            "cooling_end": fields.Datetime.now() + timedelta(hours=6),
        })
        with self.assertRaises(UserError):
            self.firing.action_unload()

    def test_unload_allowed_once_cool(self):
        self.firing.write({
            "state": "cooling",
            "cooling_end": fields.Datetime.now() - timedelta(minutes=1),
        })
        self.firing.action_unload()
        self.assertEqual(self.firing.state, "done")

    def test_forcing_needs_a_reason(self):
        self.firing.write({
            "state": "cooling",
            "cooling_end": fields.Datetime.now() + timedelta(hours=6),
        })
        with self.assertRaises(UserError):
            self.firing.action_force_unload()
        self.firing.interruption_reason = "Customer collection could not wait"
        self.firing.action_force_unload()
        self.assertTrue(self.firing.cooling_interrupted)
        self.assertEqual(self.firing.state, "done")

    def test_provider_firing_imported_once(self):
        """The idempotency key that makes a replayed sync converge."""
        values = {
            "kiln_id": self.kiln.id,
            "kind": "bisque",
            "provider": "rohde_mykiln",
            "external_id": "mykiln-4417",
        }
        self.env["mb.firing"].create(values)
        with self.assertRaises(Exception):
            self.env["mb.firing"].create(values)
            self.env.flush_all()

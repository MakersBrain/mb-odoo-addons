import importlib.util
from pathlib import Path

from odoo.tests.common import TransactionCase, tagged


def _load_migration():
    path = (
        Path(__file__).parents[1]
        / "migrations"
        / "19.0.2.0.0"
        / "pre-migrate.py"
    )
    spec = importlib.util.spec_from_file_location("mb_workshop_split_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MIGRATION = _load_migration()


@tagged("post_install", "-at_install")
class TestSplitMigrationConflicts(TransactionCase):
    def _xmlid(self, module, name, partner):
        return self.env["ir.model.data"].create({
            "module": module,
            "name": name,
            "model": partner._name,
            "res_id": partner.id,
        })

    def test_same_record_duplicate_is_collapsed(self):
        partner = self.env["res.partner"].create({"name": "Same split record"})
        source = self._xmlid("mb_workshop_base", "test_split_same", partner)
        target = self._xmlid("mb_ceramics_base", "test_split_same", partner)

        MIGRATION._resolve_conflicts(
            self.env.cr, ("test_split_same",), "mb_ceramics_base"
        )

        self.env.cr.execute(
            "SELECT id FROM ir_model_data WHERE id IN %s ORDER BY id",
            ((source.id, target.id),),
        )
        self.assertEqual(self.env.cr.fetchall(), [(target.id,)])

    def test_different_record_duplicate_aborts(self):
        source_partner = self.env["res.partner"].create({"name": "Old split record"})
        target_partner = self.env["res.partner"].create({"name": "New split record"})
        source = self._xmlid(
            "mb_workshop_base", "test_split_divergent", source_partner
        )
        target = self._xmlid(
            "mb_ceramics_base", "test_split_divergent", target_partner
        )

        with self.assertRaisesRegex(RuntimeError, "test_split_divergent"):
            MIGRATION._resolve_conflicts(
                self.env.cr, ("test_split_divergent",), "mb_ceramics_base"
            )

        self.env.cr.execute(
            "SELECT id FROM ir_model_data WHERE id IN %s ORDER BY id",
            ((source.id, target.id),),
        )
        self.assertEqual(self.env.cr.fetchall(), [(source.id,), (target.id,)])

    def test_same_record_rename_duplicate_is_collapsed(self):
        partner = self.env["res.partner"].create({"name": "Same renamed record"})
        source = self._xmlid("mb_workshop_base", "test_old_name", partner)
        target = self._xmlid("mb_workshop_base", "test_new_name", partner)

        self.assertEqual(
            MIGRATION._rename(self.env.cr, "test_old_name", "test_new_name"),
            0,
        )

        self.env.cr.execute(
            "SELECT id FROM ir_model_data WHERE id IN %s ORDER BY id",
            ((source.id, target.id),),
        )
        self.assertEqual(self.env.cr.fetchall(), [(target.id,)])

    def test_different_record_rename_duplicate_aborts(self):
        source_partner = self.env["res.partner"].create({"name": "Old menu"})
        target_partner = self.env["res.partner"].create({"name": "New menu"})
        source = self._xmlid("mb_workshop_base", "test_old_menu", source_partner)
        target = self._xmlid("mb_workshop_base", "test_new_menu", target_partner)

        with self.assertRaisesRegex(RuntimeError, "test_old_menu"):
            MIGRATION._rename(self.env.cr, "test_old_menu", "test_new_menu")

        self.env.cr.execute(
            "SELECT id FROM ir_model_data WHERE id IN %s ORDER BY id",
            ((source.id, target.id),),
        )
        self.assertEqual(self.env.cr.fetchall(), [(source.id,), (target.id,)])

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import check_addons


class TestCheckAddons(unittest.TestCase):
    def tearDown(self):
        check_addons.failures.clear()

    def test_missing_spec_is_a_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            addons = Path(directory) / "addons"
            addons.mkdir()
            with patch.object(check_addons, "ADDONS", addons):
                check_addons.failures.clear()
                check_addons.check_spec_versions({})

        self.assertEqual(
            check_addons.failures,
            ["SPEC.md: is missing; addon version documentation cannot be verified"],
        )

    def test_deprecated_qweb_output_directive_is_a_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            addon = Path(directory) / "fixture_addon"
            addon.mkdir()
            (addon / "template.xml").write_text(
                '<templates><t t-name="fixture"><span t-esc="value"/></t></templates>',
                encoding="utf-8",
            )

            check_addons.check_xml(addon)

        self.assertEqual(
            check_addons.failures,
            ["fixture_addon: template.xml uses deprecated t-esc; use t-out"],
        )

    def test_production_console_log_is_a_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            addon = Path(directory) / "fixture_addon"
            source = addon / "static" / "src"
            source.mkdir(parents=True)
            (source / "protocol.js").write_text('console.log("packet", bytes);\n', encoding="utf-8")

            check_addons.check_javascript(addon)

        self.assertEqual(
            check_addons.failures,
            ["fixture_addon: static/src/protocol.js uses console.log in production code"],
        )

    def test_privileged_public_bridge_method_is_a_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            addon = Path(directory) / "mb_control_bridge"
            models = addon / "models"
            models.mkdir(parents=True)
            (models / "service.py").write_text(
                "class Service:\n"
                "    def mutate_tenant(self):\n"
                "        return self.sudo().write({})\n",
                encoding="utf-8",
            )

            check_addons.check_sensitive_service_methods(addon)

        self.assertEqual(len(check_addons.failures), 1)
        self.assertIn("mutate_tenant lacks @api.private", check_addons.failures[0])

    def _company_security_fixture(self, directory, acl_groups, rules):
        addon = Path(directory) / "fixture_addon"
        models = addon / "models"
        security = addon / "security"
        models.mkdir(parents=True)
        security.mkdir()
        (models / "fixture.py").write_text(
            "from odoo import fields, models\n\n"
            "class FixtureRecord(models.Model):\n"
            "    _name = 'fixture.record'\n"
            "    company_id = fields.Many2one('res.company', required=True)\n",
            encoding="utf-8",
        )
        rows = ["id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink"]
        rows.extend(
            f"access_fixture_{number},fixture,model_fixture_record,{group},1,1,0,0"
            for number, group in enumerate(acl_groups)
        )
        (security / "ir.model.access.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
        (security / "rules.xml").write_text(
            '<?xml version="1.0"?><odoo>' + "".join(rules) + "</odoo>",
            encoding="utf-8",
        )
        return addon, {"data": ["security/rules.xml", "security/ir.model.access.csv"]}

    def test_global_company_rule_covers_every_acl_group(self):
        with tempfile.TemporaryDirectory() as directory:
            addon, manifest = self._company_security_fixture(
                directory,
                ["fixture.group_user", "fixture.group_manager"],
                [
                    "<record id='rule' model='ir.rule'>"
                    "<field name='model_id' ref='model_fixture_record'/>"
                    "<field name='domain_force'>[('company_id', 'in', company_ids)]</field>"
                    "<field name='groups' eval='[(5, 0, 0)]'/>"
                    "</record>"
                ],
            )
            check_addons.check_company_rule_completeness(addon, manifest)

        self.assertEqual(check_addons.failures, [])

    def test_group_company_rules_must_cover_each_acl_group_and_permission(self):
        with tempfile.TemporaryDirectory() as directory:
            addon, manifest = self._company_security_fixture(
                directory,
                ["fixture.group_user", "fixture.group_manager"],
                [
                    "<record id='rule' model='ir.rule'>"
                    "<field name='model_id' ref='model_fixture_record'/>"
                    "<field name='domain_force'>[('company_id', 'in', company_ids)]</field>"
                    "<field name='groups' eval=\"[(4, ref('fixture.group_user'))]\"/>"
                    "</record>"
                ],
            )
            check_addons.check_company_rule_completeness(addon, manifest)

        self.assertEqual(len(check_addons.failures), 1)
        self.assertIn(
            "fixture.group_manager without an applicable company rule", check_addons.failures[0]
        )

    def test_rule_on_implied_group_covers_manager_acl(self):
        with tempfile.TemporaryDirectory() as directory:
            addon, manifest = self._company_security_fixture(
                directory,
                ["fixture_addon.group_manager"],
                [
                    "<record id='rule' model='ir.rule'>"
                    "<field name='model_id' ref='model_fixture_record'/>"
                    "<field name='domain_force'>[('company_id', 'in', company_ids)]</field>"
                    "<field name='groups' eval=\"[(4, ref('group_user'))]\"/>"
                    "</record>"
                ],
            )
            check_addons.check_company_rule_completeness(
                addon,
                manifest,
                {"fixture_addon.group_manager": {"fixture_addon.group_user"}},
            )

        self.assertEqual(check_addons.failures, [])

    def test_non_company_domain_does_not_count_as_company_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            addon, manifest = self._company_security_fixture(
                directory,
                ["fixture.group_user"],
                [
                    "<record id='rule' model='ir.rule'>"
                    "<field name='model_id' ref='model_fixture_record'/>"
                    "<field name='domain_force'>[('user_id', '=', user.id)]</field>"
                    "</record>"
                ],
            )
            check_addons.check_company_rule_completeness(addon, manifest)

        self.assertEqual(len(check_addons.failures), 1)
        self.assertIn("company-owned model fixture.record", check_addons.failures[0])

    def test_rent_periods_and_webshop_holds_have_complete_company_rules(self):
        manifests = {}
        for path in check_addons.ADDONS.glob("*/__manifest__.py"):
            manifest = check_addons.check_manifest(path)
            if manifest is not None:
                manifests[path.parent.name] = manifest
        implications = check_addons._group_implications(manifests)
        for addon_name in ("mb_commercial_operations_depot", "mb_webshop"):
            addon = check_addons.ADDONS / addon_name
            check_addons.check_company_rule_completeness(addon, manifests[addon_name], implications)

        self.assertEqual(check_addons.failures, [])


if __name__ == "__main__":
    unittest.main()

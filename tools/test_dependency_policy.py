import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import dependency_policy


class TestDirectXmlDependencies(unittest.TestCase):
    def test_missing_direct_dependency_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            addons = Path(directory)
            consumer = addons / "consumer"
            consumer.mkdir()
            (consumer / "views.xml").write_text(
                '<odoo><record id="view" model="ir.ui.view">'
                '<field name="inherit_id" ref="owner.parent_view"/>'
                "</record></odoo>",
                encoding="utf-8",
            )
            manifests = {
                "consumer": {"depends": ["transitive"]},
                "owner": {"depends": []},
                "transitive": {"depends": ["owner"]},
            }

            with patch.object(dependency_policy, "ADDONS", addons):
                with self.assertRaisesRegex(ValueError, r"consumer: \['owner'\]"):
                    dependency_policy.check_direct_xml_dependencies(manifests)

    def test_explicit_direct_dependency_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            addons = Path(directory)
            consumer = addons / "consumer"
            consumer.mkdir()
            (consumer / "templates.xml").write_text(
                '<templates><t t-name="consumer.child" t-call="owner.parent"/></templates>',
                encoding="utf-8",
            )
            manifests = {
                "consumer": {"depends": ["owner"]},
                "owner": {"depends": []},
            }

            with patch.object(dependency_policy, "ADDONS", addons):
                dependency_policy.check_direct_xml_dependencies(manifests)


if __name__ == "__main__":
    unittest.main()

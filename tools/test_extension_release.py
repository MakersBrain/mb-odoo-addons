import json
import pathlib
import tempfile
import unittest

from tools.extension_manifest import tree_inventory
from tools.release_metadata import canonical_digest, checked_ref, selected_runtime

D1 = "sha256:" + "1" * 64
D2 = "sha256:" + "2" * 64
D3 = "sha256:" + "3" * 64


class TestExtensionRelease(unittest.TestCase):
    def test_tree_inventory_is_stable_and_content_sensitive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "a").write_text("first", encoding="utf-8")
            first_entries, first = tree_inventory((("python", root),))
            second_entries, second = tree_inventory((("python", root),))
            self.assertEqual(first_entries, second_entries)
            self.assertEqual(first, second)
            (root / "a").write_text("second", encoding="utf-8")
            _, changed = tree_inventory((("python", root),))
            self.assertNotEqual(first, changed)

    def test_runtime_qualification_requires_complete_exact_identity(self):
        qualified = {
            "official_source_ref": f"docker.io/library/odoo@{D1}",
            "deployment_ref": f"docker.io/library/odoo@{D1}",
            "subject_digest": D1,
            "subject_kind": "image_index",
            "manifest_digest": D2,
            "config_digest": D3,
            "platform": {"os": "linux", "architecture": "amd64"},
        }
        runtime = {
            "official_source_ref": qualified["official_source_ref"],
            "deployment_ref": qualified["official_source_ref"],
            "subject_digest": D1,
            "subject_kind": "image_index",
            "platforms": [
                {
                    "platform": qualified["platform"],
                    "manifest_digest": D2,
                    "config_digest": D3,
                }
            ],
        }
        self.assertEqual(selected_runtime(runtime, qualified), runtime["platforms"][0])
        wrong = json.loads(json.dumps(qualified))
        wrong["config_digest"] = D2
        with self.assertRaises(ValueError):
            selected_runtime(runtime, wrong)

    def test_release_identity_helpers_are_canonical_and_digest_pinned(self):
        self.assertEqual(
            canonical_digest({"b": 2, "a": 1}),
            canonical_digest({"a": 1, "b": 2}),
        )
        self.assertEqual(checked_ref(f"registry.test/bundle@{D1}", "fixture"), D1)
        with self.assertRaises(ValueError):
            checked_ref("registry.test/bundle:latest", "fixture")


if __name__ == "__main__":
    unittest.main()

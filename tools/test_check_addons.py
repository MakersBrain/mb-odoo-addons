import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import check_addons


class TestCheckAddons(unittest.TestCase):
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
        check_addons.failures.clear()


if __name__ == "__main__":
    unittest.main()

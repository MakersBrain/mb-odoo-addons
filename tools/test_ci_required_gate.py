from __future__ import annotations

import unittest

from tools.ci_required_gate import LANES, validate


def values(selected="false", result="skipped"):
    environment = {}
    for selected_key, result_key in LANES.values():
        environment[selected_key] = selected
        environment[result_key] = result
    return environment


class RequiredGateTest(unittest.TestCase):
    def test_selected_successes_pass(self):
        self.assertEqual(validate("success", "success", values("true", "success")), [])

    def test_unselected_skips_pass(self):
        self.assertEqual(validate("success", "success", values()), [])

    def test_selected_skip_failure_cancellation_and_missing_fail(self):
        for result in ("skipped", "failure", "cancelled", ""):
            with self.subTest(result=result):
                environment = values("true", "success")
                environment["SERVER_RESULT"] = result
                self.assertTrue(validate("success", "success", environment))

    def test_base_job_failure_fails(self):
        self.assertTrue(validate("failure", "success", values()))
        self.assertTrue(validate("success", "cancelled", values()))

    def test_invalid_or_missing_classifier_output_fails(self):
        environment = values()
        environment["SERVER_SELECTED"] = ""
        self.assertTrue(validate("success", "success", environment))


if __name__ == "__main__":
    unittest.main()

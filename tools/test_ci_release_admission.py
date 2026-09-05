from __future__ import annotations

import unittest

from tools.ci_release_admission import required_gate_succeeded, select_run_id

SHA = "a" * 40


def run(**overrides):
    value = {
        "id": 10,
        "run_number": 20,
        "head_sha": SHA,
        "head_branch": "main",
        "event": "push",
        "status": "completed",
        "conclusion": "success",
    }
    value.update(overrides)
    return value


def job(**overrides):
    value = {
        "id": 100,
        "run_attempt": 1,
        "name": "Required CI",
        "status": "completed",
        "conclusion": "success",
    }
    value.update(overrides)
    return value


class ReleaseAdmissionTest(unittest.TestCase):
    def test_exact_sha_full_push_and_dispatch_are_eligible(self):
        self.assertEqual(select_run_id([run()], SHA), 10)
        self.assertEqual(select_run_id([run(id=11, event="workflow_dispatch")], SHA), 11)

    def test_same_sha_partial_pull_request_is_rejected(self):
        self.assertIsNone(select_run_id([run(event="pull_request")], SHA))

    def test_cancelled_failed_pending_wrong_branch_and_wrong_sha_are_rejected(self):
        cases = (
            run(status="completed", conclusion="cancelled"),
            run(status="completed", conclusion="failure"),
            run(status="in_progress", conclusion=None),
            run(head_branch="feature"),
            run(head_sha="b" * 40),
        )
        for candidate in cases:
            with self.subTest(candidate=candidate):
                self.assertIsNone(select_run_id([candidate], SHA))

    def test_newest_eligible_run_wins_regardless_of_response_order(self):
        self.assertEqual(
            select_run_id([run(id=30, run_number=30), run(id=20, run_number=40)], SHA),
            20,
        )

    def test_required_gate_must_be_completed_and_successful(self):
        self.assertTrue(required_gate_succeeded([job()]))
        self.assertFalse(required_gate_succeeded([]))
        self.assertFalse(required_gate_succeeded([job(name="Server tests")]))
        self.assertFalse(required_gate_succeeded([job(status="in_progress", conclusion=None)]))
        self.assertFalse(required_gate_succeeded([job(conclusion="failure")]))

    def test_failed_latest_rerun_cannot_hide_behind_old_success(self):
        self.assertFalse(
            required_gate_succeeded(
                [job(id=100, run_attempt=1), job(id=200, run_attempt=2, conclusion="failure")]
            )
        )


if __name__ == "__main__":
    unittest.main()

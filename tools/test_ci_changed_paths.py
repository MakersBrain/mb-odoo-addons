from __future__ import annotations

import unittest

from tools.ci_changed_paths import LANES, classify


class ChangedPathClassifierTest(unittest.TestCase):
    def assert_lanes(
        self,
        paths,
        expected,
        *,
        event="pull_request",
        ref="refs/pull/7/merge",
        expected_full=False,
    ):
        result = classify(paths, event=event, ref=ref)
        self.assertEqual({lane for lane in LANES if result[lane]}, set(expected))
        self.assertEqual(result["full"], expected_full)

    def test_documentation_only_is_static_only(self):
        self.assert_lanes(["README.md", "docs/frontend-testing.md"], set())

    def test_model_change_is_conservative(self):
        self.assert_lanes(
            ["addons/mb_label/models/label_template.py"],
            {"server", "upgrade", "i18n", "lifecycle"},
        )

    def test_frontend_and_hoot_changes(self):
        self.assert_lanes(
            ["addons/mb_label/static/src/editor/label_editor.js"],
            {"frontend", "i18n"},
        )
        self.assert_lanes(
            ["addons/mb_label/static/tests/label_editor.test.js"], {"frontend", "i18n"}
        )

    def test_manifest_runs_every_lane(self):
        self.assert_lanes(["addons/mb_label/__manifest__.py"], LANES)

    def test_migration_matrix_runs_upgrade(self):
        self.assert_lanes(["docs/migration-matrix.json"], {"upgrade"})

    def test_catalogue_only_runs_i18n(self):
        self.assert_lanes(["addons/mb_label/i18n/fr.po"], {"i18n"})

    def test_data_csv_covers_translation_and_lifecycle(self):
        self.assert_lanes(
            ["addons/mb_label/data/labels.csv"],
            {"server", "upgrade", "i18n", "lifecycle"},
        )

    def test_mixed_changes_union_lanes(self):
        self.assert_lanes(
            ["addons/mb_label/i18n/fr.po", "addons/mb_brand/static/src/theme.scss"],
            {"frontend", "i18n"},
        )

    def test_unknown_addon_and_tool_paths_fail_open(self):
        self.assert_lanes(["addons/mb_label/new-format.widget"], LANES, expected_full=True)
        self.assert_lanes(["tools/new_ci_helper.py"], LANES, expected_full=True)

    def test_workflow_and_makefile_changes_run_every_lane(self):
        self.assert_lanes([".github/workflows/ci.yml"], LANES, expected_full=True)
        self.assert_lanes(["Makefile"], LANES, expected_full=True)

    def test_main_and_dispatch_always_run_every_lane(self):
        self.assert_lanes(
            ["README.md"], LANES, event="push", ref="refs/heads/main", expected_full=True
        )
        self.assert_lanes(
            ["README.md"],
            LANES,
            event="workflow_dispatch",
            ref="refs/heads/topic",
            expected_full=True,
        )

    def test_empty_or_uncertain_pull_request_fails_open(self):
        self.assert_lanes([], LANES, expected_full=True)
        result = classify(["README.md"], event="pull_request", uncertain=True)
        self.assertTrue(result["full"])
        self.assertTrue(all(result[lane] for lane in LANES))


if __name__ == "__main__":
    unittest.main()

import json
from unittest.mock import patch

from odoo.tests.common import TransactionCase, new_test_user, tagged

from . import fixtures


class FakeClient:
    """Stands in for MykilnClient. Records that nothing is ever written."""

    def __init__(
        self, detail=None, samples=None, token="fake-token", token_changed=True, details=None
    ):
        # `details` for the cases that need more than one firing in a page -
        # newest-wins across programme snapshots needs at least two.
        self.details = list(details) if details else [detail or fixtures.FIRING_DETAIL]
        self.detail = self.details[0]
        self.samples = samples or fixtures.FIRING_SAMPLES
        self.calls = []
        # Mirrors MykilnClient. Kept in step deliberately: the suite went red
        # once because the double lagged behind the real interface.
        self.token = token
        self.token_changed = token_changed

    def login(self):
        self.calls.append("login")

    def list_kilns(self):
        self.calls.append("list_kilns")
        return fixtures.KILNS

    def list_controllers(self):
        self.calls.append("list_controllers")
        return fixtures.CONTROLLERS

    def list_kiln_types(self):
        self.calls.append("list_kiln_types")
        return fixtures.KILN_TYPES

    def list_firings(self, limit=100, offset=0):
        self.calls.append("list_firings")
        return [
            {
                "id": detail["id"],
                "kiln": detail.get("kiln"),
                "program_number": detail.get("program_number"),
                "start_date_time": detail.get("start_date_time"),
            }
            for detail in self.details[offset : offset + limit]
        ]

    def get_firing(self, firing_id):
        self.calls.append("get_firing")
        for detail in self.details:
            if detail["id"] == firing_id:
                return detail
        return self.detail

    def get_firing_samples(self, firing_id):
        self.calls.append("get_firing_samples")
        return self.samples


@tagged("post_install", "-at_install")
class TestKilnSync(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.connection = cls.env["mb.kiln.connection"].create(
            {
                "name": "myKiln test",
                "username": "someone",
                "password": "not-a-real-password",
            }
        )

    def _sync(self, client):
        with patch.object(type(self.connection), "_client", return_value=client):
            self.connection._sync_one()

    def test_connection_counts_invalidate_for_related_record_lifecycle(self):
        other_connection = self.env["mb.kiln.connection"].create(
            {
                "name": "other provider connection",
                "username": "someone-else",
                "password": "not-a-real-password",
            }
        )
        kiln = self.env["mb.kiln"].create(
            {"name": "Counted kiln", "connection_id": self.connection.id}
        )
        firing = self.env["mb.firing"].create({"kiln_id": kiln.id, "state": "draft"})
        program = self.env["mb.kiln.program"].create(
            {"kiln_id": kiln.id, "name": "Counted programme", "kind": "bisque"}
        )

        self.assertEqual(
            (
                self.connection.kiln_count,
                self.connection.firing_count,
                self.connection.program_count,
            ),
            (1, 1, 1),
        )

        kiln.connection_id = other_connection
        self.assertEqual(
            (
                self.connection.kiln_count,
                self.connection.firing_count,
                self.connection.program_count,
            ),
            (0, 0, 0),
        )
        self.assertEqual(
            (
                other_connection.kiln_count,
                other_connection.firing_count,
                other_connection.program_count,
            ),
            (1, 1, 1),
        )

        kiln.active = False
        self.assertEqual(
            (
                other_connection.kiln_count,
                other_connection.firing_count,
                other_connection.program_count,
            ),
            (0, 0, 0),
        )
        kiln.active = True
        program.active = False
        self.assertEqual(other_connection.program_count, 0)
        program.active = True
        firing.unlink()
        self.assertEqual(other_connection.firing_count, 0)
        program.unlink()
        kiln.unlink()
        self.assertEqual(
            (other_connection.kiln_count, other_connection.program_count),
            (0, 0),
        )

    def test_routine_sync_cron_is_active(self):
        self.assertTrue(self.env.ref("mb_kiln_bridge.ir_cron_mb_kiln_sync").active)

    def test_import_creates_kilns_and_firing(self):
        client = FakeClient()
        self._sync(client)
        kilns = self.env["mb.kiln"].search([("connection_id", "=", self.connection.id)])
        self.assertEqual(len(kilns), 2)
        firing = self.env["mb.firing"].search([("external_id", "=", "4417")])
        self.assertEqual(len(firing), 1)
        self.assertEqual(firing.peak_temperature, 998.25)
        self.assertEqual(firing.program_name, "Bisque 1000")
        self.assertEqual(firing.state, "done")
        self.assertEqual(self.connection.state, "ok")

    def test_replay_is_a_no_op(self):
        """The Increment 4 gate: replaying produces no duplicates."""
        self._sync(FakeClient())
        self._sync(FakeClient())
        self.assertEqual(
            self.env["mb.kiln"].search_count([("connection_id", "=", self.connection.id)]), 2
        )
        self.assertEqual(self.env["mb.firing"].search_count([("external_id", "=", "4417")]), 1)
        firing = self.env["mb.firing"].search([("external_id", "=", "4417")])
        attachments = self.env["ir.attachment"].search(
            [("res_model", "=", "mb.firing"), ("res_id", "=", firing.id)]
        )
        # One curve and one provider payload, however many times it is polled.
        self.assertEqual(len(attachments), 2)

    def test_updated_fixture_advances_the_same_firing(self):
        running = dict(fixtures.FIRING_DETAIL, end_date_time=None)
        self._sync(FakeClient(detail=running))
        firing = self.env["mb.firing"].search([("external_id", "=", "4417")])
        self.assertEqual(firing.state, "firing")

        self._sync(FakeClient())
        self.assertEqual(self.env["mb.firing"].search_count([("external_id", "=", "4417")]), 1)
        self.assertEqual(firing.state, "done")

    def test_renaming_a_kiln_survives_the_next_poll(self):
        """The artisan's name for a kiln is theirs, not the provider's."""
        self._sync(FakeClient())
        kiln = self.env["mb.kiln"].search([("provider_external_id", "=", "41")], limit=1)
        kiln.name = "Grand four"
        self._sync(FakeClient())
        self.assertEqual(kiln.name, "Grand four")

    def test_firing_for_an_unknown_kiln_is_skipped(self):
        orphan = dict(fixtures.FIRING_DETAIL, id=9999, kiln={"id": 999})
        client = FakeClient(detail=orphan)
        self._sync(client)
        self.assertFalse(self.env["mb.firing"].search([("external_id", "=", "9999")]))

    def test_nothing_is_written_to_the_provider(self):
        """Every call a sync makes is a read. Asserted as a subset rather than
        an equality so that adding a read does not read as a regression - what
        must never appear is a write, and there is no write to appear."""
        client = FakeClient()
        self._sync(client)
        self.assertTrue(client.calls)
        self.assertLessEqual(
            set(client.calls),
            {
                "list_kilns",
                "list_controllers",
                "list_kiln_types",
                "list_firings",
                "get_firing",
                "get_firing_samples",
            },
        )

    def test_kiln_specification_is_imported(self):
        self._sync(FakeClient())
        kiln = self.env["mb.kiln"].search([("provider_external_id", "=", "41")], limit=1)
        self.assertEqual(kiln.manufacturer, "Rohde")
        self.assertEqual(kiln.model_number, "TE 80 S")
        self.assertEqual(kiln.chamber_litres, 80.0)
        self.assertEqual(kiln.max_temperature, 1320.0)
        self.assertEqual(kiln.power_kw, 6.0)
        self.assertEqual(kiln.zone_count, 1)
        self.assertEqual(kiln.heating_method, "electric")
        # From the model catalogue rather than from the kiln itself.
        self.assertEqual(kiln.series, "TE-S")
        self.assertEqual(kiln.configuration, "top_loader")
        self.assertEqual(kiln.voltage, 400)
        # Mirrored where Odoo keeps an asset's identity.
        self.assertEqual(kiln.equipment_id.model, "Rohde TE 80 S")
        self.assertEqual(kiln.equipment_id.serial_no, "80275")

    def test_a_kiln_the_provider_says_nothing_about_is_left_blank(self):
        """An account with the kiln details never filled in is an ordinary
        account, not a failure - and must not wipe what someone typed here."""
        self._sync(FakeClient())
        kiln = self.env["mb.kiln"].search([("provider_external_id", "=", "42")], limit=1)
        self.assertFalse(kiln.manufacturer)
        self.assertFalse(kiln.chamber_litres)
        kiln.chamber_litres = 140.0
        self._sync(FakeClient())
        self.assertEqual(kiln.chamber_litres, 140.0)

    def test_the_catalogue_is_fetched_once_and_not_again(self):
        """Three hundred rows that describe models, not kilns. Once a kiln has
        been matched against them there is nothing left to look up."""
        first = FakeClient()
        self._sync(first)
        self.assertIn("list_kiln_types", first.calls)
        second = FakeClient()
        self._sync(second)
        self.assertNotIn("list_kiln_types", second.calls)


@tagged("post_install", "-at_install")
class TestProgramImport(TransactionCase):
    """Programmes are derived from firings, because myKiln has no library."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.connection = cls.env["mb.kiln.connection"].create(
            {
                "name": "myKiln programmes",
                "username": "someone",
                "password": "not-a-real-password",
            }
        )

    def _sync(self, client):
        with patch.object(type(self.connection), "_client", return_value=client):
            self.connection._sync_one()

    def _programs(self):
        return self.env["mb.kiln.program"].search([("kiln_id.provider_external_id", "=", "41")])

    def test_a_firing_creates_the_programme_it_ran(self):
        self._sync(FakeClient())
        program = self._programs()
        self.assertEqual(len(program), 1)
        self.assertEqual(program.program_number, 3)
        self.assertEqual(program.name, "Bisque 1000")
        self.assertEqual(program.source, "provider")
        self.assertEqual(len(program.segment_ids), 2)
        self.assertEqual(program.peak_temperature, 1000.0)
        # 100 deg/h from ambient to 1000, then a 90 minute hold at full power.
        self.assertAlmostEqual(program.scheduled_hours, 11.3, places=2)
        # Set once, on a programme that had no duration to protect.
        self.assertAlmostEqual(program.firing_hours, 11.3, places=2)

    def test_the_firing_links_to_the_programme_it_created(self):
        """The ordering that matters: a firing is written after the programme
        it revealed, so the very first sync links them rather than leaving the
        link to be repaired later."""
        self._sync(FakeClient())
        firing = self.env["mb.firing"].search([("external_id", "=", "4417")])
        self.assertEqual(firing.program_id, self._programs())
        self.assertEqual(firing.kind, "bisque")

    def test_kind_is_inferred_from_the_peak_it_asks_for(self):
        self._sync(FakeClient(detail=fixtures.FIRING_DETAIL_GLAZE))
        program = self._programs()
        self.assertEqual(program.name, "Programme 4")
        self.assertEqual(program.kind, "glaze")

    def test_the_newest_firing_wins_within_one_page(self):
        """The same slot appears once per firing that ran it, and the profiles
        differ because a potter edits in place. The current programme is the
        one most recently fired, whatever order the page arrives in."""
        self._sync(FakeClient(details=[fixtures.FIRING_DETAIL_OLDER, fixtures.FIRING_DETAIL]))
        program = self._programs()
        self.assertEqual(len(program), 1)
        self.assertEqual(program.peak_temperature, 1000.0)
        self.assertEqual(program.segment_ids[0].ramp_rate, 100.0)

    def test_an_older_firing_never_overwrites_a_newer_profile(self):
        """A backfill walks the archive. Without this it would leave every
        programme showing the oldest profile it ever had."""
        self._sync(FakeClient())
        self._sync(FakeClient(detail=fixtures.FIRING_DETAIL_OLDER))
        program = self._programs()
        self.assertEqual(program.peak_temperature, 1000.0)
        self.assertEqual(program.segment_ids[0].ramp_rate, 100.0)

    def test_a_revised_programme_is_taken_up(self):
        self._sync(FakeClient(detail=fixtures.FIRING_DETAIL_OLDER))
        program = self._programs()
        self.assertEqual(program.peak_temperature, 1040.0)
        newer = dict(
            fixtures.FIRING_DETAIL_OLDER,
            id=4420,
            start_date_time="2026-08-05T06:00:00Z",
            program=fixtures.BISQUE_PROGRAM,
        )
        self._sync(FakeClient(detail=newer))
        self.assertEqual(program.peak_temperature, 1000.0)
        self.assertEqual(len(program.segment_ids), 2)

    def test_what_the_potter_decided_survives_a_refresh(self):
        """A controller knows a rate and a target. It does not know that this
        is the glaze schedule, or that the load stands two days - so a refresh
        must not touch either."""
        self._sync(FakeClient())
        program = self._programs()
        program.write(
            {"name": "Biscuit lent", "kind": "other", "cooling_hours": 48.0, "firing_hours": 14.0}
        )
        newer = dict(
            fixtures.FIRING_DETAIL,
            id=4421,
            start_date_time="2026-08-09T06:00:00Z",
            program=fixtures.BISQUE_PROGRAM_REVISED,
        )
        self._sync(FakeClient(detail=newer))
        self.assertEqual(program.name, "Biscuit lent")
        self.assertEqual(program.kind, "other")
        self.assertEqual(program.cooling_hours, 48.0)
        self.assertEqual(program.firing_hours, 14.0)
        # The profile itself did move, which is the point of a refresh.
        self.assertEqual(program.peak_temperature, 1040.0)

    def test_a_renamed_programme_still_matches_its_firings(self):
        """The label is the one thing a potter is certain to change. The slot
        is not, so the mapping survives the rename."""
        self._sync(FakeClient())
        program = self._programs()
        program.name = "Gres 1230"
        newer = dict(fixtures.FIRING_DETAIL, id=4422, start_date_time="2026-08-10T06:00:00Z")
        self._sync(FakeClient(detail=newer))
        self.assertEqual(len(self._programs()), 1)
        firing = self.env["mb.firing"].search([("external_id", "=", "4422")])
        self.assertEqual(firing.program_id, program)

    def test_hand_typed_segments_are_never_replaced(self):
        kiln = self.env["mb.kiln"].create({"name": "Typed in"})
        program = self.env["mb.kiln.program"].create(
            {
                "kiln_id": kiln.id,
                "name": "Programme 3",
                "kind": "bisque",
                "segment_ids": [
                    (
                        0,
                        0,
                        {
                            "number": 1,
                            "ramp_rate": 80.0,
                            "target_temperature": 960.0,
                            "soak_time": 20.0,
                        },
                    )
                ],
            }
        )
        self.env["mb.kiln.program"]._apply_provider(
            kiln,
            {
                "program_number": 3,
                "name": "Programme 3",
                "segments": [
                    {
                        "number": 1,
                        "ramp_rate": 100.0,
                        "target_temperature": 1000.0,
                        "soak_time": 0.0,
                    }
                ],
                "fired_at": False,
            },
        )
        self.assertEqual(program.source, "manual")
        self.assertEqual(len(program.segment_ids), 1)
        self.assertEqual(program.segment_ids.ramp_rate, 80.0)
        # The slot is filled in even so: it costs nothing and it is what makes
        # a later rename survivable.
        self.assertEqual(program.program_number, 3)

    def test_programmes_can_be_switched_off(self):
        self.connection.sync_programs = False
        self._sync(FakeClient())
        self.assertFalse(self._programs())

    def test_refresh_reads_one_firing_per_slot_not_one_per_firing(self):
        """Seventy-two firings on three slots is three detail calls, not
        seventy-two. The listing already says which slot each firing ran."""
        details = []
        for index in range(6):
            details.append(
                dict(
                    fixtures.FIRING_DETAIL,
                    id=7000 + index,
                    start_date_time="2026-08-0%dT06:00:00Z" % (index + 1),
                )
            )
        for index in range(4):
            details.append(
                dict(
                    fixtures.FIRING_DETAIL_GLAZE,
                    id=7100 + index,
                    start_date_time="2026-08-0%dT20:00:00Z" % (index + 1),
                )
            )
        client = FakeClient(details=details)
        with patch.object(type(self.connection), "_client", return_value=client):
            self.connection.action_refresh_programs()

        self.assertEqual(client.calls.count("get_firing"), 2)
        self.assertEqual(client.calls.count("get_firing_samples"), 0)
        programs = self._programs()
        self.assertEqual(len(programs), 2)
        self.assertEqual(sorted(programs.mapped("program_number")), [3, 4])
        # The newest on each slot, not whichever came back first.
        bisque = programs.filtered(lambda p: p.program_number == 3)
        self.assertEqual(bisque.peak_temperature, 1000.0)

    def test_refresh_reports_provider_failure_rather_than_raising(self):
        from ..models.mykiln_client import MykilnError

        class FailingClient(FakeClient):
            def list_kilns(self_inner):
                raise MykilnError("/api/v1/kilns/ timed out twice")

        with patch.object(type(self.connection), "_client", return_value=FailingClient()):
            action = self.connection.action_refresh_programs()
        self.assertEqual(action["params"]["type"], "danger")
        self.assertEqual(self.connection.state, "error")


@tagged("post_install", "-at_install")
class TestBackfill(TransactionCase):
    """The one-shot history import, and the failure paths that first bit us."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.connection = cls.env["mb.kiln.connection"].create(
            {
                "name": "myKiln backfill",
                "username": "someone",
                "password": "not-a-real-password",
                "backfill_page_size": 2,
            }
        )

    def test_backfill_pages_until_exhausted(self):
        firings = [dict(fixtures.FIRING_DETAIL, id=n) for n in range(5000, 5005)]

        class PagingClient(FakeClient):
            def count_firings(self_inner):
                return len(firings)

            def list_firings(self_inner, limit=100, offset=0):
                return [{"id": f["id"]} for f in firings[offset : offset + limit]]

            def get_firing(self_inner, firing_id):
                return next(f for f in firings if f["id"] == firing_id)

        client = PagingClient()
        with patch.object(type(self.connection), "_client", return_value=client):
            self.connection.action_start_backfill()
            self.assertEqual(self.connection.backfill_total, 5)
            self.connection._backfill_slice()

        self.assertEqual(self.connection.backfill_state, "done")
        self.assertEqual(self.connection.backfill_offset, 5)
        self.assertEqual(
            self.env["mb.firing"].search_count(
                [("external_id", "in", [str(n) for n in range(5000, 5005)])]
            ),
            5,
        )

    def test_manager_can_arm_backfill_without_scheduled_action_access(self):
        class CountClient(FakeClient):
            def count_firings(self_inner):
                return 1

        manager = new_test_user(
            self.env,
            login="kiln-backfill-manager",
            groups="mrp.group_mrp_manager",
        )
        cron = self.env.ref("mb_kiln_bridge.ir_cron_mb_kiln_backfill")
        cron.sudo().write({"active": False})

        with patch.object(type(self.connection), "_client", return_value=CountClient()):
            self.connection.with_user(manager).action_start_backfill()

        self.assertTrue(cron.active)

    def test_cron_slice_reports_progress_to_odoo(self):
        firings = [dict(fixtures.FIRING_DETAIL, id=5050)]

        class OnePageClient(FakeClient):
            def list_firings(self_inner, limit=100, offset=0):
                return [{"id": firing["id"]} for firing in firings[offset : offset + limit]]

            def get_firing(self_inner, firing_id):
                return firings[0]

        self.connection.write(
            {
                "backfill_state": "running",
                "backfill_total": 1,
                "backfill_offset": 0,
            }
        )
        with (
            patch.object(type(self.connection), "_client", return_value=OnePageClient()),
            patch.object(
                type(self.env["ir.cron"]),
                "_commit_progress",
                return_value=0,
            ) as commit_progress,
        ):
            self.connection.with_context(cron_id=99)._backfill_slice()

        commit_progress.assert_called_once_with(processed=1, remaining=0)

    def test_backfill_is_replay_safe(self):
        firings = [dict(fixtures.FIRING_DETAIL, id=n) for n in range(6000, 6003)]

        class PagingClient(FakeClient):
            def count_firings(self_inner):
                return len(firings)

            def list_firings(self_inner, limit=100, offset=0):
                return [{"id": f["id"]} for f in firings[offset : offset + limit]]

            def get_firing(self_inner, firing_id):
                return next(f for f in firings if f["id"] == firing_id)

        for _ in range(2):
            client = PagingClient()
            with patch.object(type(self.connection), "_client", return_value=client):
                self.connection.action_start_backfill()
                self.connection._backfill_slice()

        self.assertEqual(
            self.env["mb.firing"].search_count(
                [("external_id", "in", [str(n) for n in range(6000, 6003)])]
            ),
            3,
        )

    def test_provider_timeout_is_recorded_not_raised_raw(self):
        """The first live attempt surfaced a bare ReadTimeout and lost the
        failure record, because raising rolled the write back. A provider
        failure must be recorded and reported, not thrown."""
        from ..models.mykiln_client import MykilnError

        class FailingClient(FakeClient):
            def list_kilns(self_inner):
                raise MykilnError("/api/v1/firings/ timed out twice")

        with patch.object(type(self.connection), "_client", return_value=FailingClient()):
            action = self.connection.action_sync()

        self.assertEqual(self.connection.state, "error")
        self.assertIn("timed out twice", self.connection.last_error)
        self.assertEqual(action["params"]["type"], "danger")


@tagged("post_install", "-at_install")
class TestTokenReuse(TransactionCase):
    """A stored token means the cron stops logging in on every wake."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.connection = cls.env["mb.kiln.connection"].create(
            {
                "name": "myKiln token",
                "username": "someone",
                "password": "not-a-real-password",
            }
        )

    def test_first_sync_stores_the_token(self):
        from ..models.mykiln_client import MykilnClient

        client = MykilnClient("u", "p", token=None)
        client._token = "fresh-token"
        client._token_changed = True
        self.connection._remember_token(client)
        self.assertEqual(self.connection.sudo().provider_token, "fresh-token")
        self.assertTrue(self.connection.sudo().provider_token_at)

    def test_a_reused_token_is_not_rewritten(self):
        from ..models.mykiln_client import MykilnClient

        self.connection.sudo().provider_token = "stored-token"
        client = MykilnClient("u", "p", token="stored-token")
        self.assertFalse(client.token_changed)
        self.connection._remember_token(client)
        self.assertEqual(self.connection.sudo().provider_token, "stored-token")

    def test_client_is_built_with_the_stored_token(self):
        self.connection.sudo().provider_token = "stored-token"
        client = self.connection._client()
        self.assertEqual(client.token, "stored-token")
        self.assertFalse(client.token_changed)

    def test_auth_failure_drops_the_token(self):
        from ..models.mykiln_client import MykilnAuthError

        self.connection.sudo().provider_token = "revoked-token"

        class RejectingClient(FakeClient):
            def list_kilns(self_inner):
                raise MykilnAuthError("provider returned 401")

        with patch.object(type(self.connection), "_client", return_value=RejectingClient()):
            # Caught by hand, not with assertRaises: Odoo wraps that in a
            # savepoint, which rolls back the very write being asserted on.
            with self.assertLogs(level="WARNING"):
                try:
                    self.connection._sync_one()
                except MykilnAuthError:
                    pass
                else:
                    self.fail("expected MykilnAuthError")
        self.assertFalse(self.connection.sudo().provider_token)
        self.assertEqual(self.connection.state, "error")


@tagged("post_install", "-at_install")
class TestProgramMapping(TransactionCase):
    """A controller reports a slot; only the potter knows it is a glaze."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.connection = cls.env["mb.kiln.connection"].create(
            {
                "name": "myKiln programmes",
                "username": "someone",
                "password": "not-a-real-password",
            }
        )

    def _sync(self, client):
        with patch.object(type(self.connection), "_client", return_value=client):
            self.connection._sync_one()

    def _program(self):
        return self.env["mb.kiln.program"].search(
            [("kiln_id.provider_external_id", "=", "41")], limit=1
        )

    def test_a_programme_the_provider_does_not_report_is_not_invented(self):
        """The invariant the old 'unmapped programme' test protected: with no
        programme there is nothing to say what a firing was for, and a peak
        temperature is not allowed to stand in for the potter."""
        blank = dict(
            fixtures.FIRING_DETAIL,
            id=8888,
            program_number=None,
            library_program_name=None,
            program=None,
        )
        self._sync(FakeClient(detail=blank))
        firing = self.env["mb.firing"].search([("external_id", "=", "8888")])
        self.assertFalse(firing.program_id)
        self.assertEqual(firing.kind, "other")
        self.assertFalse(firing.cooling_end)

    def test_mapping_sets_kind_and_cooling_hold(self):
        self._sync(FakeClient())
        program = self._program()
        self.assertEqual(program.name, "Bisque 1000")
        program.write({"kind": "bisque", "cooling_hours": 10.0})
        self._sync(FakeClient())

        firing = self.env["mb.firing"].search([("external_id", "=", "4417")])
        self.assertEqual(firing.kind, "bisque")
        self.assertTrue(firing.cooling_end)
        # Ended 18:30, ten hours of cooling.
        self.assertEqual(firing.cooling_end.isoformat(sep=" "), "2026-08-05 04:30:00")

    def test_cooling_runs_from_the_last_sample_when_still_open(self):
        """A firing the provider has not closed still gets a hold, measured
        from when heating actually stopped."""
        self._sync(FakeClient())
        self._program().write({"kind": "glaze", "cooling_hours": 6.0})
        running = dict(fixtures.FIRING_DETAIL, id=7777, end_date_time=None)
        self._sync(FakeClient(detail=running))

        firing = self.env["mb.firing"].search([("external_id", "=", "7777")])
        self.assertEqual(firing.kind, "glaze")
        # Started 06:30, last sample at +5400s = 08:00, plus six hours.
        self.assertEqual(firing.cooling_end.isoformat(sep=" "), "2026-08-04 14:00:00")

    def test_a_programme_is_mapped_once_per_kiln(self):
        from psycopg2 import IntegrityError

        self._sync(FakeClient())
        kiln = self.env["mb.kiln"].search([("provider_external_id", "=", "41")], limit=1)
        self.assertEqual(self._program().name, "Bisque 1000")
        with self.assertRaises(IntegrityError):
            self.env["mb.kiln.program"].create(
                {"kiln_id": kiln.id, "name": "Bisque 1000", "kind": "glaze"}
            )
            self.env.flush_all()


@tagged("post_install", "-at_install")
class TestRawPayload(TransactionCase):
    """The provider's own JSON, kept for diagnostics."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.connection = cls.env["mb.kiln.connection"].create(
            {
                "name": "myKiln raw",
                "username": "someone",
                "password": "not-a-real-password",
            }
        )

    def _sync(self, client):
        with patch.object(type(self.connection), "_client", return_value=client):
            self.connection._sync_one()

    def _firing(self):
        return self.env["mb.firing"].search([("external_id", "=", "4417")])

    def test_raw_payload_is_attached(self):
        self._sync(FakeClient())
        firing = self._firing()
        self.assertTrue(firing.raw_attachment_id)
        self.assertEqual(firing.raw_attachment_id.name, "firing-4417-raw.json")
        body = json.loads(firing.raw_attachment_id.raw.decode())
        self.assertEqual(body["detail"]["id"], 4417)
        self.assertEqual(len(body["samples"]["elapsed_seconds"]), 4)

    def test_replay_does_not_accumulate_attachments(self):
        self._sync(FakeClient())
        self._sync(FakeClient())
        firing = self._firing()
        attachments = self.env["ir.attachment"].search(
            [("res_model", "=", "mb.firing"), ("res_id", "=", firing.id)]
        )
        # One curve and one raw payload, however many times it is polled.
        self.assertEqual(len(attachments), 2)

    def test_the_switch_turns_it_off(self):
        self.connection.store_raw_payload = False
        self._sync(FakeClient())
        firing = self._firing()
        self.assertFalse(firing.raw_attachment_id)
        self.assertTrue(firing.curve_attachment_id)

    def test_no_credential_reaches_the_attachment(self):
        self._sync(FakeClient())
        body = self._firing().raw_attachment_id.raw.decode().lower()
        for word in ("token", "password", "authorization", "secret"):
            self.assertNotIn(word, body)

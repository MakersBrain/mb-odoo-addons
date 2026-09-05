import uuid
from datetime import datetime
from queue import Queue
from threading import Barrier, BrokenBarrierError, Event, Thread

from psycopg2.errors import SerializationFailure

from odoo import SUPERUSER_ID, api
from odoo.exceptions import ValidationError
from odoo.modules.registry import Registry
from odoo.tests import BaseCase, get_db_name, tagged
from odoo.tests.common import release_test_lock


@tagged("post_install", "-at_install")
class TestFiringConcurrency(BaseCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # TransactionCase deliberately shares a cursor. Real lock contention
        # needs independent PostgreSQL sessions and fixtures visible to both.
        cls.registry = Registry(get_db_name())
        with cls.registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            suffix = uuid.uuid4().hex
            kiln = env["mb.kiln"].create({"name": f"Concurrent kiln {suffix}"})
            program = env["mb.kiln.program"].create(
                {
                    "kiln_id": kiln.id,
                    "name": f"Concurrent programme {suffix}",
                    "kind": "glaze",
                    "firing_hours": 11.0,
                    "cooling_hours": 13.0,
                }
            )
            cls.kiln_id = kiln.id
            cls.program_id = program.id
            cls.workcenter_id = kiln.workcenter_id.id
            cls.equipment_id = kiln.equipment_id.id
            cr.commit()

    @classmethod
    def tearDownClass(cls):
        try:
            with cls.registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                env["mb.firing"].search([("kiln_id", "=", cls.kiln_id)]).unlink()
                env["mb.kiln"].browse(cls.kiln_id).unlink()
                env["maintenance.equipment"].browse(cls.equipment_id).exists().unlink()
                env["mrp.workcenter"].browse(cls.workcenter_id).exists().unlink()
                cr.commit()
        finally:
            super().tearDownClass()

    def _values(self, start):
        return {
            "kiln_id": self.kiln_id,
            "program_id": self.program_id,
            "kind": "glaze",
            "date_planned_start": start,
        }

    def _assert_serialized_conflict(self, holder_action, contender_action, retry_action):
        holder_ready = Barrier(2)
        release_holder = Barrier(2)
        contender_done = Event()
        outcomes = Queue()
        transaction_envs = {
            role: api.Environment(self.registry.cursor(), SUPERUSER_ID, {})
            for role in ("holder", "contender")
        }
        backend_pids = {}
        for role, env in transaction_envs.items():
            env.cr.execute("SET LOCAL lock_timeout = '10s'")
            env.cr.execute("SELECT pg_backend_pid()")
            backend_pids[role] = env.cr.fetchone()[0]

        def run_holder():
            env = transaction_envs["holder"]
            try:
                record = holder_action(env)
                holder_ready.wait(timeout=10)
                release_holder.wait(timeout=10)
                env.cr.commit()
                outcomes.put(("holder", "committed", record.id))
            except Exception as error:  # pragma: no cover - surfaced in main thread
                env.cr.rollback()
                outcomes.put(("holder", "error", repr(error)))

        def run_contender():
            env = transaction_envs["contender"]
            try:
                record = contender_action(env)
                env.cr.commit()
                outcomes.put(("contender", "committed", record.id))
            except SerializationFailure as error:
                env.cr.rollback()
                outcomes.put(("contender", "serialization", str(error)))
            except ValidationError as error:
                env.cr.rollback()
                outcomes.put(("contender", "validation", str(error)))
            except Exception as error:  # pragma: no cover - surfaced in main thread
                env.cr.rollback()
                outcomes.put(("contender", "error", repr(error)))
            finally:
                contender_done.set()

        holder = Thread(target=run_holder, daemon=True)
        contender = Thread(target=run_contender, daemon=True)
        blocked = False
        try:
            with release_test_lock():
                holder.start()
                holder_ready.wait(timeout=10)
                self.assertTrue(holder.is_alive(), "holder failed before keeping its lock")
                contender.start()

                for _attempt in range(200):
                    with self.registry.cursor() as cr:
                        cr.execute("SELECT pg_blocking_pids(%s)", [backend_pids["contender"]])
                        if backend_pids["holder"] in cr.fetchone()[0]:
                            blocked = True
                            break
                    if contender_done.wait(0.01):
                        break
                release_holder.wait(timeout=10)
                holder.join(timeout=10)
                contender.join(timeout=10)
        finally:
            try:
                release_holder.abort()
                holder_ready.abort()
            except BrokenBarrierError:
                pass
            if holder.ident is not None:
                holder.join(timeout=10)
            if contender.ident is not None:
                contender.join(timeout=10)
            for env in transaction_envs.values():
                env.cr.close()

        self.assertFalse(holder.is_alive(), "holder transaction did not finish")
        self.assertFalse(contender.is_alive(), "contender transaction did not finish")
        self.assertTrue(blocked, "contender never waited on the kiln row")
        result = {}
        while not outcomes.empty():
            role, status, detail = outcomes.get_nowait()
            result[role] = (status, detail)
        self.assertEqual(result.get("holder", (None,))[0], "committed", result)
        self.assertEqual(result.get("contender", (None,))[0], "serialization", result)

        # Odoo retries serialization failures at the request boundary. The
        # fresh transaction must see the winner and reject the overlap.
        with self.registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            with self.assertRaisesRegex(ValidationError, "already occupied"):
                retry_action(env)
            cr.rollback()

    def test_concurrent_overlapping_creates_commit_only_one_firing(self):
        start = datetime(2095, 1, 1, 6, 0)
        values = self._values(start)
        try:
            self._assert_serialized_conflict(
                lambda env: env["mb.firing"].create(values),
                lambda env: env["mb.firing"].create(values),
                lambda env: env["mb.firing"].create(values),
            )
            with self.registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                self.assertEqual(
                    env["mb.firing"].search_count(
                        [("kiln_id", "=", self.kiln_id), ("date_planned_start", "=", start)]
                    ),
                    1,
                )
        finally:
            self._cleanup_start(start)

    def test_reschedule_serializes_against_concurrent_create(self):
        original_start = datetime(2095, 2, 1, 6, 0)
        contested_start = datetime(2095, 3, 1, 6, 0)
        with self.registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            firing_id = env["mb.firing"].create(self._values(original_start)).id
            cr.commit()
        try:
            self._assert_serialized_conflict(
                lambda env: (
                    env["mb.firing"]
                    .browse(firing_id)
                    .write({"date_planned_start": contested_start})
                    and env["mb.firing"].browse(firing_id)
                ),
                lambda env: env["mb.firing"].create(self._values(contested_start)),
                lambda env: env["mb.firing"].create(self._values(contested_start)),
            )
            with self.registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                firing = env["mb.firing"].browse(firing_id)
                self.assertEqual(firing.date_planned_start, contested_start)
                self.assertEqual(
                    env["mb.firing"].search_count(
                        [
                            ("kiln_id", "=", self.kiln_id),
                            ("date_planned_start", "=", contested_start),
                        ]
                    ),
                    1,
                )
        finally:
            self._cleanup_start(original_start, contested_start)

    def _cleanup_start(self, *starts):
        with self.registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            env["mb.firing"].search(
                [("kiln_id", "=", self.kiln_id), ("date_planned_start", "in", list(starts))]
            ).unlink()
            cr.commit()

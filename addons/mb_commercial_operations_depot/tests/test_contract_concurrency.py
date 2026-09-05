import uuid
from datetime import date
from queue import Queue
from threading import Barrier, Event, Thread

from psycopg2.errors import SerializationFailure

from odoo import SUPERUSER_ID, api
from odoo.exceptions import ValidationError
from odoo.modules.registry import Registry
from odoo.tests import BaseCase, get_db_name, tagged
from odoo.tests.common import release_test_lock


@tagged("post_install", "-at_install")
class TestDepotContractConcurrency(BaseCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # TransactionCase shares its cursor. These checks need independent
        # PostgreSQL sessions with committed fixtures visible to both.
        cls.registry = Registry(get_db_name())
        with cls.registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            suffix = uuid.uuid4().hex
            company = env.ref("base.main_company")
            partners = env["res.partner"].create(
                [
                    {"name": f"Concurrent depot A {suffix}", "is_company": True},
                    {"name": f"Concurrent depot B {suffix}", "is_company": True},
                ]
            )
            warehouses = env["stock.warehouse"].create(
                [
                    {
                        "name": partner.name,
                        "code": f"{prefix}{suffix[:4]}".upper(),
                        "company_id": company.id,
                        "reception_steps": "one_step",
                        "delivery_steps": "ship_only",
                        "is_depot": True,
                        "mb_depot_legal_structure": "resale",
                        "depot_partner_id": partner.id,
                    }
                    for partner, prefix in zip(partners, ("A", "B"), strict=True)
                ]
            )
            project = env["project.project"].create(
                {
                    "name": f"Concurrent depot contracts {suffix}",
                    "company_id": company.id,
                    "partner_id": partners[0].id,
                    "allow_timesheets": True,
                }
            )
            cls.company_id = company.id
            cls.partner_by_warehouse = dict(zip(warehouses.ids, partners.ids, strict=True))
            cls.warehouse_ids = warehouses.ids
            cls.project_id = project.id
            cr.commit()

    @classmethod
    def tearDownClass(cls):
        try:
            with cls.registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                env["mb.commercial.contract"].search(
                    [("depot_warehouse_id", "in", cls.warehouse_ids)]
                ).unlink()
                env["project.project"].browse(cls.project_id).unlink()
                partners = env["res.partner"].browse(list(cls.partner_by_warehouse.values()))
                warehouses = env["stock.warehouse"].browse(cls.warehouse_ids)
                env["stock.rule"].with_context(active_test=False).search(
                    [("picking_type_id.warehouse_id", "in", cls.warehouse_ids)]
                ).unlink()
                warehouses.unlink()
                partners.unlink()
                cr.commit()
        finally:
            super().tearDownClass()

    def _values(self, warehouse_id, start, end):
        return {
            "name": f"Concurrent contract {warehouse_id} {start}",
            "company_id": self.company_id,
            "partner_id": self.partner_by_warehouse[warehouse_id],
            "project_id": self.project_id,
            "depot_warehouse_id": warehouse_id,
            "date_start": start,
            "date_end": end,
            "rent_billing_method": "information",
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
                records = holder_action(env)
                holder_ready.wait(timeout=10)
                release_holder.wait(timeout=10)
                env.cr.commit()
                outcomes.put(("holder", "committed", records.ids))
            except Exception as error:  # pragma: no cover - surfaced in main thread
                env.cr.rollback()
                outcomes.put(("holder", "error", repr(error)))

        def run_contender():
            env = transaction_envs["contender"]
            try:
                records = contender_action(env)
                env.cr.commit()
                outcomes.put(("contender", "committed", records.ids))
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
            release_holder.abort()
            holder_ready.abort()
            if holder.ident is not None:
                holder.join(timeout=10)
            if contender.ident is not None:
                contender.join(timeout=10)
            for env in transaction_envs.values():
                env.cr.close()

        self.assertFalse(holder.is_alive(), "holder transaction did not finish")
        self.assertFalse(contender.is_alive(), "contender transaction did not finish")
        self.assertTrue(blocked, "contender never waited on a depot warehouse row")
        result = {}
        while not outcomes.empty():
            role, status, detail = outcomes.get_nowait()
            result[role] = (status, detail)
        self.assertEqual(result.get("holder", (None,))[0], "committed", result)
        self.assertEqual(result.get("contender", (None,))[0], "serialization", result)

        # The request-level retry gets a new snapshot and must then see the
        # committed winner through the ordinary inclusive-overlap validation.
        with self.registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            with self.assertRaisesRegex(ValidationError, "overlapping active"):
                retry_action(env)
            cr.rollback()

    def test_concurrent_overlapping_creates_commit_only_one_contract(self):
        warehouse_id = self.warehouse_ids[0]
        values = self._values(warehouse_id, date(2095, 1, 1), date(2095, 1, 31))
        try:
            self._assert_serialized_conflict(
                lambda env: env["mb.commercial.contract"].create(values),
                lambda env: env["mb.commercial.contract"].create(values),
                lambda env: env["mb.commercial.contract"].create(values),
            )
            self._assert_contract_count(warehouse_id, date(2095, 1, 1), 1)
        finally:
            self._cleanup_future_contracts()

    def test_date_change_serializes_against_concurrent_create(self):
        warehouse_id = self.warehouse_ids[0]
        original_start = date(2095, 2, 1)
        contested_start = date(2095, 3, 1)
        with self.registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            contract_id = (
                env["mb.commercial.contract"]
                .create(self._values(warehouse_id, original_start, date(2095, 2, 28)))
                .id
            )
            cr.commit()

        def reschedule(env):
            contract = env["mb.commercial.contract"].browse(contract_id)
            contract.write({"date_start": contested_start, "date_end": date(2095, 3, 31)})
            return contract

        try:
            contender_values = self._values(warehouse_id, contested_start, date(2095, 3, 31))
            self._assert_serialized_conflict(
                reschedule,
                lambda env: env["mb.commercial.contract"].create(contender_values),
                lambda env: env["mb.commercial.contract"].create(contender_values),
            )
            self._assert_contract_count(warehouse_id, contested_start, 1)
        finally:
            self._cleanup_future_contracts()

    def test_reversed_batch_order_serializes_without_deadlock(self):
        first_id, second_id = self.warehouse_ids
        first = self._values(first_id, date(2095, 4, 1), date(2095, 4, 30))
        second = self._values(second_id, date(2095, 4, 1), date(2095, 4, 30))
        try:
            self._assert_serialized_conflict(
                lambda env: env["mb.commercial.contract"].create([first, second]),
                lambda env: env["mb.commercial.contract"].create([second, first]),
                lambda env: env["mb.commercial.contract"].create([second, first]),
            )
            self._assert_contract_count(first_id, date(2095, 4, 1), 1)
            self._assert_contract_count(second_id, date(2095, 4, 1), 1)
        finally:
            self._cleanup_future_contracts()

    def _assert_contract_count(self, warehouse_id, start, expected):
        with self.registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            self.assertEqual(
                env["mb.commercial.contract"].search_count(
                    [("depot_warehouse_id", "=", warehouse_id), ("date_start", "=", start)]
                ),
                expected,
            )

    def _cleanup_future_contracts(self):
        with self.registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            env["mb.commercial.contract"].search(
                [
                    ("depot_warehouse_id", "in", self.warehouse_ids),
                    ("date_start", ">=", date(2095, 1, 1)),
                ]
            ).unlink()
            cr.commit()

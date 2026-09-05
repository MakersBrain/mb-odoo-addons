import uuid
from queue import Queue
from threading import Barrier, BrokenBarrierError, Event, Thread

from psycopg2.errors import SerializationFailure

from odoo import SUPERUSER_ID, api
from odoo.exceptions import ValidationError
from odoo.modules.registry import Registry
from odoo.tests import BaseCase, get_db_name, tagged
from odoo.tests.common import release_test_lock


@tagged("post_install", "-at_install")
class TestBoardContentConcurrency(BaseCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.registry = Registry(get_db_name())
        with cls.registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            suffix = uuid.uuid4().hex
            product = env["product.product"].create(
                {"name": f"Board concurrency product {suffix}", "is_storable": True}
            )
            productions = env["mrp.production"].create(
                [
                    {
                        "product_id": product.id,
                        "product_qty": 10,
                        "product_uom_id": product.uom_id.id,
                        "mb_workflow_kind": "bisque",
                    },
                    {
                        "product_id": product.id,
                        "product_qty": 10,
                        "product_uom_id": product.uom_id.id,
                        "mb_workflow_kind": "bisque",
                    },
                ]
            )
            board_type = env["stock.package.type"].create(
                {"name": f"Concurrency board type {suffix}", "package_use": "reusable"}
            )
            boards = env["stock.package"].create(
                [
                    {
                        "name": f"Concurrency board {index} {suffix}",
                        "package_type_id": board_type.id,
                        "company_id": env.company.id,
                    }
                    for index in range(4)
                ]
            )
            cls.product_template_id = product.product_tmpl_id.id
            cls.production_ids = productions.ids
            cls.board_type_id = board_type.id
            cls.board_ids = boards.ids
            cr.commit()

    @classmethod
    def tearDownClass(cls):
        try:
            with cls.registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                env["mb.board.content"].search(
                    [("production_id", "in", cls.production_ids)]
                ).unlink()
                env["mrp.production"].browse(cls.production_ids).unlink()
                env["stock.package"].browse(cls.board_ids).unlink()
                env["stock.package.type"].browse(cls.board_type_id).unlink()
                env["product.template"].browse(cls.product_template_id).unlink()
                cr.commit()
        finally:
            super().tearDownClass()

    def _create(self, env, production_id, board_id, quantity):
        return env["mb.board.content"].create(
            {
                "board_id": board_id,
                "production_id": production_id,
                "quantity": quantity,
            }
        )

    def setUp(self):
        super().setUp()
        with self.registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            env["mb.board.content"].search([("production_id", "in", self.production_ids)]).unlink()
            cr.commit()

    def _assert_serialized_conflict(
        self,
        holder_action,
        contender_action,
        retry_action,
        retry_error="cannot exceed",
    ):
        holder_ready = Barrier(2)
        release_holder = Barrier(2)
        contender_done = Event()
        outcomes = Queue()
        envs = {
            role: api.Environment(self.registry.cursor(), SUPERUSER_ID, {})
            for role in ("holder", "contender")
        }
        backend_pids = {}
        for role, env in envs.items():
            env.cr.execute("SET LOCAL lock_timeout = '10s'")
            env.cr.execute("SELECT pg_backend_pid()")
            backend_pids[role] = env.cr.fetchone()[0]

        def holder_target():
            env = envs["holder"]
            try:
                record = holder_action(env)
                holder_ready.wait(timeout=10)
                release_holder.wait(timeout=10)
                env.cr.commit()
                outcomes.put(("holder", "committed", record.id))
            except Exception as error:  # pragma: no cover - surfaced below
                env.cr.rollback()
                outcomes.put(("holder", "error", repr(error)))

        def contender_target():
            env = envs["contender"]
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
            except Exception as error:  # pragma: no cover - surfaced below
                env.cr.rollback()
                outcomes.put(("contender", "error", repr(error)))
            finally:
                contender_done.set()

        holder = Thread(target=holder_target, daemon=True)
        contender = Thread(target=contender_target, daemon=True)
        blocked = False
        try:
            with release_test_lock():
                holder.start()
                holder_ready.wait(timeout=10)
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
            for thread in (holder, contender):
                if thread.ident is not None:
                    thread.join(timeout=10)
            for env in envs.values():
                env.cr.close()

        self.assertFalse(holder.is_alive(), "holder transaction did not finish")
        self.assertFalse(contender.is_alive(), "contender transaction did not finish")
        self.assertTrue(blocked, "contender never waited on the manufacturing-order row")
        result = {}
        while not outcomes.empty():
            role, status, detail = outcomes.get_nowait()
            result[role] = (status, detail)
        self.assertEqual(result.get("holder", (None,))[0], "committed", result)
        self.assertEqual(result.get("contender", (None,))[0], "serialization", result)
        with self.registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            if retry_error:
                with self.assertRaisesRegex(ValidationError, retry_error):
                    retry_action(env)
                cr.rollback()
            else:
                retry_action(env)
                cr.commit()

    def test_concurrent_additions_cannot_exceed_production_quantity(self):
        production_id = self.production_ids[0]
        self._assert_serialized_conflict(
            lambda env: self._create(env, production_id, self.board_ids[0], 6),
            lambda env: self._create(env, production_id, self.board_ids[1], 6),
            lambda env: self._create(env, production_id, self.board_ids[1], 6),
        )

    def test_move_serializes_against_addition(self):
        source_id, target_id = self.production_ids
        with self.registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            moving_id = self._create(env, source_id, self.board_ids[2], 6).id
            cr.commit()
        self._assert_serialized_conflict(
            lambda env: (
                env["mb.board.content"].browse(moving_id).write({"production_id": target_id})
                and env["mb.board.content"].browse(moving_id)
            ),
            lambda env: self._create(env, target_id, self.board_ids[3], 6),
            lambda env: self._create(env, target_id, self.board_ids[3], 6),
        )

    def test_reversed_moves_lock_old_and_new_productions_without_deadlock(self):
        first_id, second_id = self.production_ids
        with self.registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            first_content_id = self._create(env, first_id, self.board_ids[0], 4).id
            second_content_id = self._create(env, second_id, self.board_ids[1], 4).id
            cr.commit()

        def move(env, content_id, production_id):
            content = env["mb.board.content"].browse(content_id)
            content.write({"production_id": production_id})
            return content

        self._assert_serialized_conflict(
            lambda env: move(env, first_content_id, second_id),
            lambda env: move(env, second_content_id, first_id),
            lambda env: move(env, second_content_id, first_id),
            retry_error=None,
        )
        with self.registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            contents = env["mb.board.content"].browse([first_content_id, second_content_id])
            self.assertEqual(set(contents.mapped("production_id").ids), {first_id, second_id})

    def test_different_productions_do_not_share_the_aggregate_lock(self):
        holder_ready = Barrier(2)
        release_holder = Barrier(2)
        contender_done = Event()
        outcomes = Queue()
        envs = {
            role: api.Environment(self.registry.cursor(), SUPERUSER_ID, {})
            for role in ("holder", "contender")
        }

        def holder_target():
            env = envs["holder"]
            try:
                self._create(env, self.production_ids[0], self.board_ids[0], 1)
                holder_ready.wait(timeout=10)
                release_holder.wait(timeout=10)
                env.cr.commit()
            except Exception as error:  # pragma: no cover - surfaced below
                env.cr.rollback()
                outcomes.put(repr(error))

        def contender_target():
            env = envs["contender"]
            try:
                self._create(env, self.production_ids[1], self.board_ids[1], 1)
                env.cr.commit()
            except Exception as error:  # pragma: no cover - surfaced below
                env.cr.rollback()
                outcomes.put(repr(error))
            finally:
                contender_done.set()

        holder = Thread(target=holder_target, daemon=True)
        contender = Thread(target=contender_target, daemon=True)
        try:
            with release_test_lock():
                holder.start()
                holder_ready.wait(timeout=10)
                contender.start()
                self.assertTrue(
                    contender_done.wait(5),
                    "an unrelated manufacturing order waited on the aggregate lock",
                )
                release_holder.wait(timeout=10)
                holder.join(timeout=10)
                contender.join(timeout=10)
        finally:
            try:
                release_holder.abort()
                holder_ready.abort()
            except BrokenBarrierError:
                pass
            for thread in (holder, contender):
                if thread.ident is not None:
                    thread.join(timeout=10)
            for env in envs.values():
                env.cr.close()
        self.assertFalse(holder.is_alive(), "holder transaction did not finish")
        self.assertFalse(contender.is_alive(), "contender transaction did not finish")
        self.assertTrue(outcomes.empty(), list(outcomes.queue))

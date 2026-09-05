import uuid
from queue import Queue
from threading import Event, Thread

from psycopg2.errors import SerializationFailure

from odoo import SUPERUSER_ID, api
from odoo.modules.registry import Registry
from odoo.tests import BaseCase, get_db_name, tagged
from odoo.tests.common import release_test_lock


@tagged("post_install", "-at_install")
class TestOperationReceiptConcurrency(BaseCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.registry = Registry(get_db_name())

    def test_loser_rolls_back_business_work_then_replays_winner(self):
        operation_key = f"receipt-race:{uuid.uuid4()}"
        command = "test.receipt-race"
        digest = uuid.uuid4().hex
        holder_marker = f"Receipt holder {uuid.uuid4()}"
        contender_marker = f"Receipt contender {uuid.uuid4()}"
        canonical_response = {"winner": "holder"}
        contender_started = Event()
        contender_done = Event()
        contender_pid = Queue()
        outcomes = Queue()
        holder_cr = self.registry.cursor()
        contender_cr = self.registry.cursor()

        try:
            holder_env = api.Environment(holder_cr, SUPERUSER_ID, {})
            holder_env["res.partner"].create({"name": holder_marker})
            holder_env["mb.control.operation.receipt"].record(
                operation_key, command, digest, canonical_response
            )
            holder_env.flush_all()
            holder_cr.execute("SELECT pg_backend_pid()")
            holder_pid = holder_cr.fetchone()[0]
            contender_env = api.Environment(contender_cr, SUPERUSER_ID, {})
            contender_cr.execute("SET LOCAL lock_timeout = '10s'")
            contender_cr.execute("SELECT pg_backend_pid()")
            contender_backend_pid = contender_cr.fetchone()[0]

            def contend_then_retry():
                try:
                    contender_pid.put(contender_backend_pid)
                    contender_started.set()

                    def action():
                        contender_env["res.partner"].create({"name": contender_marker})
                        return {"winner": "contender"}

                    try:
                        contender_env["mb.control.operation.receipt"]._execute_once(
                            operation_key, command, digest, action
                        )
                    except SerializationFailure as error:
                        contender_cr.rollback()
                        outcomes.put(("serialization", error.pgcode))
                    else:  # pragma: no cover - reported through the queue
                        outcomes.put(("error", "contender did not request a retry"))
                        return
                    finally:
                        contender_cr.close()
                except Exception as error:  # pragma: no cover - reported in main thread
                    outcomes.put(("error", repr(error)))
                finally:
                    contender_done.set()

            contender = Thread(target=contend_then_retry, daemon=True)
            blocked = False
            with release_test_lock():
                contender.start()
                self.assertTrue(contender_started.wait(10))
                contender_backend_pid = contender_pid.get(timeout=10)
                for _attempt in range(200):
                    with self.registry.cursor() as observer_cr:
                        observer_cr.execute("SELECT pg_blocking_pids(%s)", [contender_backend_pid])
                        if holder_pid in observer_cr.fetchone()[0]:
                            blocked = True
                            break
                    if contender_done.wait(0.01):
                        break
                holder_cr.commit()
                contender.join(timeout=10)

            self.assertFalse(contender.is_alive())
            self.assertTrue(blocked, "contender never waited on the receipt unique index")
            self.assertEqual(outcomes.get_nowait(), ("serialization", "40001"))
            with self.registry.cursor() as assertion_cr:
                assertion_env = api.Environment(assertion_cr, SUPERUSER_ID, {})

                def must_not_run():
                    raise AssertionError("replay ran the business action")

                replay = assertion_env["mb.control.operation.receipt"]._execute_once(
                    operation_key, command, digest, must_not_run
                )
                self.assertEqual(replay, canonical_response)
                self.assertEqual(
                    assertion_env["mb.control.operation.receipt"].search_count(
                        [("operation_key", "=", operation_key)]
                    ),
                    1,
                )
                self.assertTrue(assertion_env["res.partner"].search([("name", "=", holder_marker)]))
                self.assertFalse(
                    assertion_env["res.partner"].search([("name", "=", contender_marker)])
                )
        finally:
            holder_cr.close()
            contender_cr.close()
            with self.registry.cursor() as cleanup_cr:
                cleanup_env = api.Environment(cleanup_cr, SUPERUSER_ID, {})
                cleanup_env["mb.control.operation.receipt"].search(
                    [("operation_key", "=", operation_key)]
                ).unlink()
                cleanup_env["res.partner"].search(
                    [("name", "in", [holder_marker, contender_marker])]
                ).unlink()
                cleanup_cr.commit()

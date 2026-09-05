import uuid
from datetime import timedelta
from queue import Queue
from threading import Event, Thread

from psycopg2 import IntegrityError

from odoo import SUPERUSER_ID, api, fields
from odoo.exceptions import UserError, ValidationError
from odoo.modules.registry import Registry
from odoo.tests import BaseCase, TransactionCase, get_db_name, tagged
from odoo.tests.common import release_test_lock

ALLOCATION_UNIQUE_MESSAGE = "A lot or serial number can satisfy only one target in an operation."
ALLOCATION_UNIQUE_CONSTRAINT = "mb_market_stock_allocation_unique_operation_lot"


@tagged("post_install", "-at_install")
class TestCommercialStockConcurrency(BaseCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Real unique-index contention needs independent PostgreSQL sessions.
        cls.registry = Registry(get_db_name())
        with cls.registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            cls.company_id = env.ref("base.main_company").id
            cls.warehouse_id = (
                env["stock.warehouse"].search([("company_id", "=", cls.company_id)], limit=1).id
            )

    def test_concurrent_duplicate_lot_allocation_allows_one_create(self):
        holder_cr = self.registry.cursor()
        fixture_ids = None
        contender_done = Event()
        contender_started = Event()
        contender_pid = Queue()
        outcomes = Queue()
        try:
            env = api.Environment(holder_cr, SUPERUSER_ID, {})
            suffix = uuid.uuid4().hex
            partner = env["res.partner"].create({"name": f"Concurrent Market {suffix}"})
            product = env["product.product"].create(
                {
                    "name": f"Concurrent Vase {suffix}",
                    "type": "consu",
                    "is_storable": True,
                    "tracking": "serial",
                }
            )
            lot = env["stock.lot"].create({"name": f"LOT-{suffix}", "product_id": product.id})
            start = fields.Datetime.now() + timedelta(days=3650)
            operation = env["mb.commercial.operation"].create(
                {
                    "name": f"Concurrent Market {suffix}",
                    "partner_id": partner.id,
                    "planned_start": start,
                    "planned_end": start + timedelta(hours=8),
                    "stock_preparation_deadline": start - timedelta(days=2),
                    "source_warehouse_id": self.warehouse_id,
                }
            )
            lines = env["mb.market.stock.plan.line"].create(
                [
                    {
                        "operation_id": operation.id,
                        "target_type": "product",
                        "product_id": product.id,
                        "desired_opening_qty": 1,
                    },
                    {
                        "operation_id": operation.id,
                        "target_type": "bucket",
                        "category_id": product.categ_id.id,
                        "desired_opening_qty": 1,
                    },
                ]
            )
            env["mb.market.stock.allocation"].create(
                {
                    "plan_line_id": lines[0].id,
                    "product_id": product.id,
                    "lot_id": lot.id,
                    "quantity": 1,
                }
            )
            env.flush_all()
            holder_cr.execute("SELECT pg_backend_pid()")
            holder_pid = holder_cr.fetchone()[0]
            fixture_ids = (operation.id, lot.id, product.id, partner.id)

            insert_values = (
                lines[1].id,
                operation.id,
                self.company_id,
                product.id,
                lot.id,
                1,
                SUPERUSER_ID,
                SUPERUSER_ID,
            )

            def create_contender():
                try:
                    with self.registry.cursor() as cr:
                        cr.execute("SET LOCAL lock_timeout = '10s'")
                        cr.execute("SELECT pg_backend_pid()")
                        contender_pid.put(cr.fetchone()[0])
                        contender_started.set()
                        try:
                            cr.execute(
                                """
                                INSERT INTO mb_market_stock_allocation
                                       (plan_line_id, operation_id, company_id,
                                        product_id, lot_id, quantity,
                                        create_uid, write_uid, create_date, write_date)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                                RETURNING id
                                """,
                                insert_values,
                            )
                            created_id = cr.fetchone()[0]
                            cr.commit()
                            outcomes.put(("committed", created_id))
                        except IntegrityError as error:
                            cr.rollback()
                            outcomes.put(("integrity", error.diag.constraint_name))
                except Exception as error:  # pragma: no cover - reported in main thread
                    outcomes.put(("error", repr(error)))
                finally:
                    contender_done.set()

            contender = Thread(target=create_contender, daemon=True)
            with release_test_lock():
                contender.start()
                self.assertTrue(contender_started.wait(10))
                contender_backend_pid = contender_pid.get(timeout=10)
                blocked = False
                for _attempt in range(200):
                    with self.registry.cursor() as cr:
                        cr.execute("SELECT pg_blocking_pids(%s)", [contender_backend_pid])
                        if holder_pid in cr.fetchone()[0]:
                            blocked = True
                            break
                    if contender_done.wait(0.01):
                        break
                holder_cr.commit()
                contender.join(timeout=10)

            self.assertFalse(contender.is_alive())
            self.assertTrue(blocked, "contender never waited on the holder transaction")
            self.assertEqual(outcomes.get_nowait(), ("integrity", ALLOCATION_UNIQUE_CONSTRAINT))
            with self.registry.cursor() as cr:
                cr.execute(
                    """
                    SELECT count(*)
                      FROM mb_market_stock_allocation
                     WHERE operation_id = %s AND lot_id = %s
                    """,
                    [operation.id, lot.id],
                )
                self.assertEqual(cr.fetchone()[0], 1)
        finally:
            holder_cr.close()
            if fixture_ids is not None:
                with self.registry.cursor() as cr:
                    env = api.Environment(cr, SUPERUSER_ID, {})
                    operation_id, lot_id, product_id, partner_id = fixture_ids
                    env["mb.commercial.operation"].browse(operation_id).unlink()
                    env["stock.lot"].browse(lot_id).unlink()
                    env["product.product"].browse(product_id).unlink()
                    env["res.partner"].browse(partner_id).unlink()
                    cr.commit()


@tagged("post_install", "-at_install")
class TestCommercialStock(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.warehouse = cls.env["stock.warehouse"].search(
            [
                ("company_id", "=", cls.company.id),
            ],
            limit=1,
        )
        cls.partner = cls.env["res.partner"].create({"name": "Summer Market"})
        cls.product = cls.env["product.product"].create(
            {
                "name": "Market Mug",
                "type": "consu",
                "is_storable": True,
                "tracking": "none",
            }
        )
        cls.env["stock.quant"]._update_available_quantity(
            cls.product,
            cls.warehouse.lot_stock_id,
            10,
        )

    def _operation(self, required=20):
        start = fields.Datetime.now() + timedelta(days=20)
        operation = self.env["mb.commercial.operation"].create(
            {
                "name": "Summer Market",
                "partner_id": self.partner.id,
                "planned_start": start,
                "planned_end": start + timedelta(hours=8),
                "stock_preparation_deadline": start - timedelta(days=2),
                "source_warehouse_id": self.warehouse.id,
            }
        )
        line = self.env["mb.market.stock.plan.line"].create(
            {
                "operation_id": operation.id,
                "target_type": "product",
                "product_id": self.product.id,
                "desired_opening_qty": required,
                "supply_method": "stock",
            }
        )
        return operation, line

    def _move(self, quantity, source, destination, state="confirmed"):
        move = self.env["stock.move"].create(
            {
                "product_id": self.product.id,
                "product_uom_qty": quantity,
                "product_uom": self.product.uom_id.id,
                "location_id": source.id,
                "location_dest_id": destination.id,
                "date": fields.Datetime.now() + timedelta(days=5),
            }
        )
        if state != "draft":
            move._action_confirm()
        return move

    def _validate(self, picking):
        picking.move_line_ids.picked = True
        result = picking.button_validate()
        self.assertFalse(isinstance(result, dict))

    def test_availability_counts_reserved_demand_once_and_excludes_draft(self):
        operation, line = self._operation()
        supplier = self.env.ref("stock.stock_location_suppliers")
        customer = self.env.ref("stock.stock_location_customers")
        self._move(2, supplier, self.warehouse.lot_stock_id)
        self._move(4, self.warehouse.lot_stock_id, customer)
        self._move(100, supplier, self.warehouse.lot_stock_id, state="draft")
        operation.action_check_stock_availability()
        self.assertEqual(line.on_hand_now, 10)
        self.assertEqual(line.incoming_before_cutoff, 2)
        self.assertEqual(line.outgoing_before_cutoff, 4)
        self.assertEqual(line.forecast_available, 8)
        self.assertEqual(line.shortage_qty, 12)

    def test_preparation_uses_standard_transfer_and_return_reconciles(self):
        operation, line = self._operation(required=4)
        operation.action_approve()
        action = operation.action_prepare_market_stock()
        picking = operation.preparation_picking_id
        self.assertEqual(action["res_id"], picking.id)
        self.assertEqual(picking.state, "assigned")
        self.assertEqual(picking.location_dest_id, operation.market_location_id)
        self.assertEqual(picking.move_ids.mb_market_stock_plan_line_id, line)
        self._validate(picking)

        customer = self.env.ref("stock.stock_location_customers")
        sold = self.env["stock.picking"].create(
            {
                "picking_type_id": self.warehouse.out_type_id.id,
                "location_id": operation.market_location_id.id,
                "location_dest_id": customer.id,
            }
        )
        self.env["stock.move"].create(
            {
                "product_id": self.product.id,
                "product_uom_qty": 1,
                "product_uom": self.product.uom_id.id,
                "location_id": operation.market_location_id.id,
                "location_dest_id": customer.id,
                "picking_id": sold.id,
            }
        )
        sold.action_confirm()
        sold.action_assign()
        self._validate(sold)

        return_action = operation.action_prepare_market_return()
        returned = self.env["stock.picking"].browse(return_action["res_id"])
        self.assertEqual(returned.move_ids.product_uom_qty, 3)
        self._validate(returned)
        operation.action_done()
        self.assertTrue(operation.stock_reconciled)
        operation.action_stock_close()
        self.assertTrue(operation.stock_closed)
        with self.assertRaises(UserError):
            line.desired_opening_qty = 5

    def test_preparation_refuses_over_reserved_stock(self):
        operation, _line = self._operation(required=11)
        operation.action_approve()
        with self.assertRaises(ValidationError):
            operation.action_prepare_market_stock()

    def test_tracked_piece_cannot_be_allocated_twice(self):
        tracked = self.env["product.product"].create(
            {
                "name": "Unique Vase",
                "type": "consu",
                "is_storable": True,
                "tracking": "serial",
            }
        )
        lot = self.env["stock.lot"].create({"name": "VASE-001", "product_id": tracked.id})
        self.env["stock.quant"]._update_available_quantity(
            tracked,
            self.warehouse.lot_stock_id,
            1,
            lot_id=lot,
        )
        operation, _line = self._operation(required=1)
        first = self.env["mb.market.stock.plan.line"].create(
            {
                "operation_id": operation.id,
                "product_id": tracked.id,
                "desired_opening_qty": 1,
            }
        )
        second = self.env["mb.market.stock.plan.line"].create(
            {
                "operation_id": operation.id,
                "target_type": "bucket",
                "category_id": tracked.categ_id.id,
                "desired_opening_qty": 1,
            }
        )
        allocation_model = self.env["mb.market.stock.allocation"]
        allocation_model.create(
            {
                "plan_line_id": first.id,
                "product_id": tracked.id,
                "lot_id": lot.id,
                "quantity": 1,
            }
        )
        allocation_model.flush_model(["operation_id", "lot_id"])
        with self.assertRaises(IntegrityError) as caught:
            with self.env.cr.savepoint():
                allocation_model.create(
                    {
                        "plan_line_id": second.id,
                        "product_id": tracked.id,
                        "lot_id": lot.id,
                        "quantity": 1,
                    }
                )
        self.assertEqual(
            allocation_model._sql_error_to_message(caught.exception),
            ALLOCATION_UNIQUE_MESSAGE,
        )

    def test_distinct_lots_can_be_allocated_in_one_operation(self):
        tracked = self.env["product.product"].create(
            {
                "name": "Distinct Lot Vase",
                "type": "consu",
                "is_storable": True,
                "tracking": "serial",
            }
        )
        lots = self.env["stock.lot"].create(
            [
                {"name": "DISTINCT-001", "product_id": tracked.id},
                {"name": "DISTINCT-002", "product_id": tracked.id},
            ]
        )
        operation, _line = self._operation(required=2)
        lines = self.env["mb.market.stock.plan.line"].create(
            [
                {
                    "operation_id": operation.id,
                    "target_type": "bucket",
                    "category_id": tracked.categ_id.id,
                    "desired_opening_qty": 1,
                },
                {
                    "operation_id": operation.id,
                    "target_type": "bucket",
                    "category_id": tracked.categ_id.id,
                    "desired_opening_qty": 1,
                },
            ]
        )
        allocations = self.env["mb.market.stock.allocation"].create(
            [
                {
                    "plan_line_id": line.id,
                    "product_id": tracked.id,
                    "lot_id": lot.id,
                    "quantity": 1,
                }
                for line, lot in zip(lines, lots, strict=True)
            ]
        )
        allocations.flush_recordset(["operation_id", "lot_id"])
        self.assertEqual(allocations.lot_id, lots)

    def test_multiple_null_lot_allocations_are_permitted(self):
        operation, line = self._operation(required=2)
        allocations = self.env["mb.market.stock.allocation"].create(
            [
                {
                    "plan_line_id": line.id,
                    "product_id": self.product.id,
                    "quantity": 1,
                },
                {
                    "plan_line_id": line.id,
                    "product_id": self.product.id,
                    "quantity": 1,
                },
            ]
        )
        allocations.flush_recordset(["operation_id", "lot_id"])
        self.assertEqual(len(allocations), 2)
        self.assertFalse(allocations.lot_id)

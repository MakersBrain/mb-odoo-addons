from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCommercialStock(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.warehouse = cls.env["stock.warehouse"].search([
            ("company_id", "=", cls.company.id),
        ], limit=1)
        cls.partner = cls.env["res.partner"].create({"name": "Summer Market"})
        cls.product = cls.env["product.product"].create({
            "name": "Market Mug",
            "type": "consu",
            "is_storable": True,
            "tracking": "none",
        })
        cls.env["stock.quant"]._update_available_quantity(
            cls.product, cls.warehouse.lot_stock_id, 10,
        )

    def _operation(self, required=20):
        start = fields.Datetime.now() + timedelta(days=20)
        operation = self.env["mb.commercial.operation"].create({
            "name": "Summer Market",
            "partner_id": self.partner.id,
            "planned_start": start,
            "planned_end": start + timedelta(hours=8),
            "stock_preparation_deadline": start - timedelta(days=2),
            "source_warehouse_id": self.warehouse.id,
        })
        line = self.env["mb.market.stock.plan.line"].create({
            "operation_id": operation.id,
            "target_type": "product",
            "product_id": self.product.id,
            "desired_opening_qty": required,
            "supply_method": "stock",
        })
        return operation, line

    def _move(self, quantity, source, destination, state="confirmed"):
        move = self.env["stock.move"].create({
            "product_id": self.product.id,
            "product_uom_qty": quantity,
            "product_uom": self.product.uom_id.id,
            "location_id": source.id,
            "location_dest_id": destination.id,
            "date": fields.Datetime.now() + timedelta(days=5),
        })
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
        sold = self.env["stock.picking"].create({
            "picking_type_id": self.warehouse.out_type_id.id,
            "location_id": operation.market_location_id.id,
            "location_dest_id": customer.id,
        })
        self.env["stock.move"].create({
            "product_id": self.product.id,
            "product_uom_qty": 1,
            "product_uom": self.product.uom_id.id,
            "location_id": operation.market_location_id.id,
            "location_dest_id": customer.id,
            "picking_id": sold.id,
        })
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
        tracked = self.env["product.product"].create({
            "name": "Unique Vase",
            "type": "consu",
            "is_storable": True,
            "tracking": "serial",
        })
        lot = self.env["stock.lot"].create({"name": "VASE-001", "product_id": tracked.id})
        self.env["stock.quant"]._update_available_quantity(
            tracked, self.warehouse.lot_stock_id, 1, lot_id=lot,
        )
        operation, _line = self._operation(required=1)
        first = self.env["mb.market.stock.plan.line"].create({
            "operation_id": operation.id,
            "product_id": tracked.id,
            "desired_opening_qty": 1,
        })
        second = self.env["mb.market.stock.plan.line"].create({
            "operation_id": operation.id,
            "target_type": "bucket",
            "category_id": tracked.categ_id.id,
            "desired_opening_qty": 1,
        })
        self.env["mb.market.stock.allocation"].create({
            "plan_line_id": first.id,
            "product_id": tracked.id,
            "lot_id": lot.id,
            "quantity": 1,
        })
        with self.assertRaises(ValidationError):
            self.env["mb.market.stock.allocation"].create({
                "plan_line_id": second.id,
                "product_id": tracked.id,
                "lot_id": lot.id,
                "quantity": 1,
            })

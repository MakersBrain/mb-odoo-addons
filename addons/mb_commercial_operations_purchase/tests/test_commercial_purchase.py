from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCommercialPurchase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search([
            ("company_id", "=", cls.env.company.id),
        ], limit=1)
        cls.venue = cls.env["res.partner"].create({"name": "Winter Market"})
        cls.vendor = cls.env["res.partner"].create({
            "name": "Mug Supplier", "supplier_rank": 1,
        })
        cls.product = cls.env["product.product"].create({
            "name": "Purchased Mug",
            "type": "consu",
            "is_storable": True,
            "purchase_ok": True,
        })
        cls.env["product.supplierinfo"].create({
            "partner_id": cls.vendor.id,
            "product_tmpl_id": cls.product.product_tmpl_id.id,
            "price": 12.0,
        })
        cls.env["stock.quant"]._update_available_quantity(
            cls.product, cls.warehouse.lot_stock_id, 2,
        )

    def _operation(self):
        start = fields.Datetime.now() + timedelta(days=20)
        operation = self.env["mb.commercial.operation"].create({
            "name": "Winter Market",
            "partner_id": self.venue.id,
            "planned_start": start,
            "planned_end": start + timedelta(hours=8),
            "stock_preparation_deadline": start - timedelta(days=2),
            "source_warehouse_id": self.warehouse.id,
        })
        line = self.env["mb.market.stock.plan.line"].create({
            "operation_id": operation.id,
            "product_id": self.product.id,
            "desired_opening_qty": 10,
            "supply_method": "purchase",
            "vendor_id": self.vendor.id,
        })
        operation.action_approve()
        return operation, line

    def test_draft_rfq_is_idempotent_and_confirmed_receipt_is_incoming(self):
        operation, line = self._operation()
        operation.action_prepare_supply()
        purchase_line = line.purchase_line_ids
        order = purchase_line.order_id
        self.assertEqual(order.state, "draft")
        self.assertEqual(purchase_line.product_qty, 8)
        self.assertEqual(purchase_line.price_unit, 12)
        self.assertFalse(order.project_id, "Purchased inventory must not be charged before it is sold")
        operation.action_prepare_supply()
        self.assertEqual(len(line.purchase_line_ids), 1)
        operation.action_check_stock_availability()
        self.assertEqual(line.incoming_before_cutoff, 0)
        self.assertEqual(line.readiness, "supply_proposed")

        order.button_confirm()
        operation.action_check_stock_availability()
        line._update_supply_readiness()
        self.assertEqual(line.incoming_before_cutoff, 8)
        self.assertIn(line.readiness, ("supply_confirmed", "in_progress", "at_risk"))

    def test_cancelled_rfq_can_be_replaced(self):
        operation, line = self._operation()
        operation.action_prepare_supply()
        first = line.purchase_line_ids.order_id
        first.button_cancel()
        operation.action_prepare_supply()
        self.assertEqual(len(line.purchase_line_ids), 2)
        self.assertEqual(len(line.purchase_line_ids.filtered(lambda item: item.order_id.state != "cancel")), 1)

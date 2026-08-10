from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCommercialMrp(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search([
            ("company_id", "=", cls.env.company.id),
        ], limit=1)
        cls.partner = cls.env["res.partner"].create({"name": "Craft Fair"})
        cls.component = cls.env["product.product"].create({
            "name": "Clay Blank", "type": "consu", "is_storable": True,
        })
        cls.product = cls.env["product.product"].create({
            "name": "Repeatable Mug", "type": "consu", "is_storable": True,
        })
        cls.bom = cls.env["mrp.bom"].create({
            "product_tmpl_id": cls.product.product_tmpl_id.id,
            "product_qty": 1,
            "bom_line_ids": [fields.Command.create({
                "product_id": cls.component.id, "product_qty": 1,
            })],
        })
        cls.env["stock.quant"]._update_available_quantity(
            cls.product, cls.warehouse.lot_stock_id, 2,
        )

    def _operation(self):
        start = fields.Datetime.now() + timedelta(days=20)
        operation = self.env["mb.commercial.operation"].create({
            "name": "Craft Fair",
            "partner_id": self.partner.id,
            "planned_start": start,
            "planned_end": start + timedelta(hours=8),
            "stock_preparation_deadline": start - timedelta(days=2),
            "source_warehouse_id": self.warehouse.id,
        })
        line = self.env["mb.market.stock.plan.line"].create({
            "operation_id": operation.id,
            "product_id": self.product.id,
            "desired_opening_qty": 10,
            "supply_method": "manufacture",
            "manufacturing_bom_id": self.bom.id,
        })
        operation.action_approve()
        return operation, line

    def test_draft_mo_is_idempotent_and_not_incoming_until_confirmed(self):
        operation, line = self._operation()
        operation.action_prepare_supply()
        production = line.production_ids
        self.assertEqual(len(production), 1)
        self.assertEqual(production.state, "draft")
        self.assertEqual(production.product_qty, 8)
        self.assertEqual(production.mb_commercial_operation_id, operation)
        self.assertFalse(production.project_id, "Supply inventory must not be charged before it is sold")
        operation.action_prepare_supply()
        self.assertEqual(len(line.production_ids), 1)
        operation.action_check_stock_availability()
        self.assertEqual(line.incoming_before_cutoff, 0)
        self.assertEqual(line.readiness, "supply_proposed")

        production.action_confirm()
        operation.action_check_stock_availability()
        line._update_supply_readiness()
        self.assertEqual(line.incoming_before_cutoff, 8)
        self.assertIn(line.readiness, ("supply_confirmed", "at_risk"))

    def test_cancelled_proposal_can_be_replaced_without_duplication(self):
        operation, line = self._operation()
        operation.action_prepare_supply()
        first = line.production_ids
        first.action_cancel()
        operation.action_prepare_supply()
        self.assertEqual(len(line.production_ids), 2)
        self.assertEqual(len(line.production_ids.filtered(lambda order: order.state != "cancel")), 1)

    def test_bucket_requires_explicit_manufacturable_mapping(self):
        start = fields.Datetime.now() + timedelta(days=20)
        operation = self.env["mb.commercial.operation"].create({
            "name": "Bucket Fair",
            "partner_id": self.partner.id,
            "planned_start": start,
            "planned_end": start + timedelta(hours=8),
            "stock_preparation_deadline": start - timedelta(days=2),
            "source_warehouse_id": self.warehouse.id,
        })
        bucket = self.env["mb.market.stock.plan.line"].create({
            "operation_id": operation.id,
            "target_type": "bucket",
            "category_id": self.product.categ_id.id,
            "desired_opening_qty": 3,
            "supply_method": "manufacture",
        })
        operation.action_approve()
        with self.assertRaises(ValidationError):
            bucket._prepare_supply()

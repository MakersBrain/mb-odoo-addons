from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCommercialSale(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not cls.env["account.journal"].search_count(
            [
                ("company_id", "=", cls.env.company.id),
                ("type", "=", "sale"),
            ]
        ):
            cls.env["account.chart.template"].sudo().try_loading(
                "generic_coa",
                company=cls.env.company,
                install_demo=False,
            )
        cls.warehouse = cls.env["stock.warehouse"].search(
            [
                ("company_id", "=", cls.env.company.id),
            ],
            limit=1,
        )
        cls.venue = cls.env["res.partner"].create({"name": "Sales Market"})
        cls.customer = cls.env["res.partner"].create({"name": "Market Customer"})
        cls.product = cls.env["product.product"].create(
            {
                "name": "Market Cup",
                "type": "consu",
                "is_storable": True,
                "sale_ok": True,
                "invoice_policy": "delivery",
                "list_price": 50.0,
                "standard_price": 10.0,
            }
        )
        cls.env["stock.quant"]._update_available_quantity(
            cls.product,
            cls.warehouse.lot_stock_id,
            5,
        )

    def _validate(self, picking):
        picking.move_line_ids.picked = True
        result = picking.button_validate()
        self.assertFalse(isinstance(result, dict))

    def _prepared_operation(self):
        start = fields.Datetime.now() + timedelta(days=2)
        operation = self.env["mb.commercial.operation"].create(
            {
                "name": "Sales Market",
                "partner_id": self.venue.id,
                "planned_start": start,
                "planned_end": start + timedelta(hours=8),
                "stock_preparation_deadline": start - timedelta(days=1),
                "source_warehouse_id": self.warehouse.id,
                "stock_plan_line_ids": [
                    fields.Command.create(
                        {
                            "product_id": self.product.id,
                            "desired_opening_qty": 2,
                            "supply_method": "stock",
                        }
                    )
                ],
            }
        )
        operation.action_approve()
        operation.action_prepare_market_stock()
        self._validate(operation.preparation_picking_id)
        self.warehouse.out_type_id.analytic_costs = True
        return operation

    def _order(self, operation, quantity=1):
        return self.env["sale.order"].create(
            {
                "partner_id": self.customer.id,
                "warehouse_id": self.warehouse.id,
                "date_order": operation.planned_start,
                "mb_commercial_operation_id": operation.id,
                "order_line": [
                    fields.Command.create(
                        {
                            "product_id": self.product.id,
                            "product_uom_qty": quantity,
                            "price_unit": 50.0,
                        }
                    )
                ],
            }
        )

    def test_market_sale_sources_event_stock_and_records_revenue_and_cogs_once(self):
        operation = self._prepared_operation()
        order = self._order(operation)
        order.action_confirm()
        picking = order.picking_ids
        self.assertEqual(picking.location_id, operation.market_location_id)
        self.assertEqual(picking.mb_commercial_operation_id, operation)
        self.assertEqual(picking.project_id, operation.project_id)
        self._validate(picking)
        cost_lines = picking.move_ids.analytic_account_line_ids
        self.assertEqual(len(cost_lines), 1)
        self.assertEqual(cost_lines.amount, -10.0)
        self.assertFalse(operation.preparation_picking_id.move_ids.analytic_account_line_ids)

        invoice = order._create_invoices()
        invoice.invoice_date = fields.Date.today()
        operation.documents_expected = True
        self.assertFalse(operation.documents_complete)
        self.assertEqual(operation.actual_revenue, 0.0)
        invoice.action_post()
        self.assertEqual(invoice.mb_commercial_operation_id, operation)
        self.assertTrue(operation.documents_complete)
        product_line = invoice.invoice_line_ids.filtered(
            lambda line: line.display_type == "product"
        )
        self.assertEqual(
            product_line.analytic_distribution,
            {str(operation.analytic_account_id.id): 100.0},
        )
        analytic_lines = self.env["account.analytic.line"].search(
            [
                (
                    operation.analytic_account_id.plan_id._column_name(),
                    "=",
                    operation.analytic_account_id.id,
                )
            ]
        )
        revenue_lines = analytic_lines.filtered(lambda line: line.move_line_id.move_id == invoice)
        self.assertEqual(
            sum(revenue_lines.mapped("amount")),
            50.0,
            analytic_lines.read(["name", "amount", "move_line_id", "category"]),
        )
        self.assertEqual(operation.actual_revenue, 50.0)
        self.assertEqual(operation.actual_cost, 10.0)

    def test_unprepared_or_insufficient_market_stock_is_rejected(self):
        operation = self._prepared_operation()
        with self.assertRaises(ValidationError):
            self._order(operation, quantity=3).action_confirm()

    def test_analytic_cost_configuration_is_explicit(self):
        operation = self._prepared_operation()
        self.warehouse.out_type_id.analytic_costs = False
        with self.assertRaises(ValidationError):
            self._order(operation).action_confirm()

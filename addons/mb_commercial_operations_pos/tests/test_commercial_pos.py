from datetime import timedelta

from odoo import fields
from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.common import CommonPosTest


@tagged("post_install", "-at_install")
class TestCommercialPos(CommonPosTest):
    def _prepare_market(self):
        config = self.pos_config_usd
        warehouse = config.picking_type_id.warehouse_id
        product = self.ten_dollars_no_tax.product_variant_id
        product.write({
            "is_storable": True,
            "available_in_pos": True,
            "standard_price": 4,
        })
        self.env["stock.quant"]._update_available_quantity(
            product, warehouse.lot_stock_id, 2,
        )
        start = fields.Datetime.now() + timedelta(days=3)
        operation = self.env["mb.commercial.operation"].sudo().create({
            "name": "POS Market",
            "partner_id": self.env.company.partner_id.id,
            "planned_start": start,
            "planned_end": start + timedelta(hours=8),
            "source_warehouse_id": warehouse.id,
        })
        self.env["mb.market.stock.plan.line"].sudo().create({
            "operation_id": operation.id,
            "product_id": product.id,
            "desired_opening_qty": 2,
        })
        operation.sudo().action_approve()
        operation.sudo().action_prepare_market_stock()
        operation.preparation_picking_id.move_line_ids.picked = True
        operation.preparation_picking_id.button_validate()
        config.sudo().mb_commercial_operation_id = operation
        return operation, config, product

    def test_pos_uses_exact_market_stock_and_analytic_links(self):
        operation, config, product = self._prepare_market()
        self.assertEqual(config.picking_type_id.default_location_src_id, operation.market_location_id)
        self.assertTrue(config.picking_type_id.analytic_costs)
        self.assertIn(product, config.mb_market_product_ids)

        order, _refund = self.create_backend_pos_order({
            "pos_config": config,
            "line_data": [{"product_id": product.id, "qty": 1}],
            "payment_data": [{
                "payment_method_id": self.cash_payment_method.id,
                "amount": product.lst_price,
            }],
        })
        self.assertEqual(order.mb_commercial_operation_id, operation)
        self.assertEqual(order.picking_ids.location_id, operation.market_location_id)
        self.assertEqual(order.picking_ids.project_id, operation.project_id)
        self.assertEqual(order.picking_ids.state, "done")

        invoice_command = order._prepare_invoice_lines("out_invoice")[0]
        self.assertEqual(
            invoice_command[2]["analytic_distribution"],
            {str(operation.analytic_account_id.id): 100.0},
        )
        refund_values = order._prepare_refund_values(order.session_id)
        self.assertEqual(refund_values["mb_commercial_operation_id"], operation.id)

    def test_market_pos_loader_excludes_other_storable_products(self):
        operation, config, product = self._prepare_market()
        other = self.env["product.template"].create({
            "name": "Not at market",
            "is_storable": True,
            "available_in_pos": True,
        })
        domain = self.env["product.template"]._load_pos_data_domain({}, config)
        loaded = self.env["product.template"].search(domain)
        self.assertIn(product.product_tmpl_id, loaded)
        self.assertNotIn(other, loaded)
        self.assertEqual(config.mb_commercial_operation_id, operation)

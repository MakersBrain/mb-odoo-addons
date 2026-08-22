from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.common import CommonPosTest


@tagged("post_install", "-at_install")
class TestLabelPosStockFlow(CommonPosTest):
    def test_resolved_serial_payment_creates_standard_done_stock_move(self):
        prefix = "https://instagram.com/username"
        product = self.ten_dollars_no_tax.product_variant_id
        product.write(
            {
                "default_code": "FLOW-CUP",
                "tracking": "serial",
                "is_storable": True,
                "available_in_pos": True,
            }
        )
        location = self.pos_config_usd.picking_type_id.default_location_src_id
        lot = self.env["stock.lot"].create(
            {
                "name": "FLOW-SERIAL-1",
                "product_id": product.id,
                "company_id": self.env.company.id,
            }
        )
        self.env["stock.quant"]._update_available_quantity(product, location, 1, lot_id=lot)
        template = self.env["mb.label.template"].create(
            {
                "name": "POS stock-flow URL label",
                "width_mm": 40,
                "height_mm": 30,
                "dpi": 203,
                "qr_url_prefix": prefix,
            }
        )
        version = template.save_version({"schema": 1, "elements": []})
        alias = self.env["mb.label.qr.alias"].mint(
            "%s#FLOW-CUP/FLOW-SERIAL-1" % prefix,
            product.id,
            lot.id,
            version["id"],
        )
        resolution = self.env["mb.label.qr.alias"].pos_resolve(alias.value, self.pos_config_usd.id)
        self.assertEqual(resolution["status"], "resolved")
        self.assertEqual(resolution["available_quantity"], 1)

        order, _refund = self.create_backend_pos_order(
            {
                "pos_config": self.pos_config_usd,
                "line_data": [
                    {
                        "product_id": resolution["product_id"],
                        "qty": 1,
                        "pack_lot_ids": [Command.create({"lot_name": resolution["lot_name"]})],
                    }
                ],
                "payment_data": [
                    {
                        "payment_method_id": self.cash_payment_method.id,
                        "amount": product.lst_price,
                    }
                ],
            }
        )
        self.assertEqual(order.state, "paid")
        move_lines = order.picking_ids.move_line_ids.filtered(
            lambda line: line.product_id == product and line.lot_id == lot
        )
        self.assertTrue(move_lines)
        self.assertEqual(move_lines.mapped("state"), ["done"])

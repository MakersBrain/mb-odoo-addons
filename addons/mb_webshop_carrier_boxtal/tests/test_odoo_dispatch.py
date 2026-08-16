from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.stock_delivery.models.stock_picking import (
    StockPicking as CoreStockPicking,
)


@tagged("post_install", "-at_install")
class TestBoxtalOdooDispatch(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        country = cls.env.ref("base.fr")
        cls.recipient = cls.env["res.partner"].create({
            "name": "Dispatch recipient",
            "street": "2 rue Oberkampf",
            "zip": "75011",
            "city": "Paris",
            "country_id": country.id,
        })
        cls.warehouse = cls.env["stock.warehouse"].search([
            ("company_id", "=", cls.env.company.id),
        ], limit=1)
        product = cls.env["product.product"].create({
            "name": "Boxtal dispatch",
            "type": "service",
        })
        cls.carrier = cls.env["delivery.carrier"].create({
            "name": "Boxtal dispatch fixture",
            "delivery_type": "mb_boxtal",
            "product_id": product.id,
            "company_id": cls.env.company.id,
            "mb_provider_service_code": "MONR-CpourToi",
        })

    def _picking(self, carrier):
        return self.env["stock.picking"].create({
            "partner_id": self.recipient.id,
            "picking_type_id": self.warehouse.out_type_id.id,
            "location_id": self.warehouse.lot_stock_id.id,
            "location_dest_id": self.env.ref("stock.stock_location_customers").id,
            "company_id": self.env.company.id,
            "carrier_id": carrier.id,
            "shipping_weight": 1.0,
        })

    def test_odoo_delivery_dispatch_queues_exactly_one_provider_shipment(self):
        picking = self._picking(self.carrier)

        first = self.carrier.send_shipping(picking)
        second = self.carrier.send_shipping(picking)

        shipments = self.env["mb.carrier.shipment"].search([
            ("carrier_id", "=", self.carrier.id),
            ("picking_id", "=", picking.id),
            ("direction", "=", "outbound"),
        ])
        self.assertEqual(len(shipments), 1)
        self.assertEqual(first[0]["tracking_number"], False)
        self.assertEqual(second[0]["tracking_number"], False)

    def test_provider_picking_posts_queued_message(self):
        picking = self._picking(self.carrier)

        self.assertTrue(picking.send_to_shipper())

        shipment = self.env["mb.carrier.shipment"].search([
            ("picking_id", "=", picking.id),
        ])
        self.assertEqual(len(shipment), 1)
        bodies = " ".join(str(body) for body in picking.message_ids.mapped("body"))
        self.assertIn("Carrier label purchase queued", bodies)

    def test_non_makersbrain_carrier_still_uses_core_dispatch(self):
        product = self.env["product.product"].create({
            "name": "Native fixed delivery",
            "type": "service",
        })
        native = self.env["delivery.carrier"].create({
            "name": "Native fixed carrier",
            "delivery_type": "fixed",
            "product_id": product.id,
            "fixed_price": 5,
            "company_id": self.env.company.id,
        })
        picking = self._picking(native)

        with patch.object(
            CoreStockPicking, "send_to_shipper", autospec=True, return_value="native-result"
        ) as dispatch:
            result = picking.send_to_shipper()

        self.assertEqual(result, "native-result")
        dispatch.assert_called_once()

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSendcloudOdooDispatch(TransactionCase):
    def test_sendcloud_dispatch_methods_are_registered(self):
        carrier = self.env["delivery.carrier"]
        self.assertTrue(hasattr(carrier, "mb_sendcloud_send_shipping"))
        self.assertTrue(hasattr(carrier, "mb_sendcloud_cancel_shipment"))
        self.assertTrue(hasattr(carrier, "mb_sendcloud_get_return_label"))
        self.assertTrue(hasattr(carrier, "mb_sendcloud_get_tracking_link"))

    def test_production_purchase_requires_verified_signed_webhook(self):
        product = self.env["product.product"].create({
            "name": "Sendcloud readiness carrier", "type": "service",
        })
        carrier = self.env["delivery.carrier"].create({
            "name": "Sendcloud readiness",
            "delivery_type": "mb_sendcloud",
            "product_id": product.id,
            "prod_environment": True,
            "mb_provider_service_code": "tracked-option",
            "mb_sendcloud_sender_address_id": 7,
        })
        with self.assertRaises(UserError):
            carrier.mb_sendcloud_send_shipping(self.env["stock.picking"])
        with self.assertRaises(UserError):
            carrier.mb_sendcloud_get_return_label(self.env["stock.picking"])

    def test_rotation_invalidates_readiness_and_changes_callback_route(self):
        product = self.env["product.product"].create({
            "name": "Sendcloud rotation carrier", "type": "service",
        })
        carrier = self.env["delivery.carrier"].create({
            "name": "Sendcloud rotation",
            "delivery_type": "mb_sendcloud",
            "product_id": product.id,
            "mb_sendcloud_webhook_ready": True,
            "mb_sendcloud_last_webhook_at": "2026-08-18 10:00:00",
        })
        previous = carrier.mb_subscription_id
        replacement = carrier._mb_prepare_secret_rotation({
            "public_key": "sendcloud-public-key",
            "private_key": "sendcloud-private-key-that-is-long-enough",
        })
        self.assertNotEqual(replacement, previous)
        self.assertFalse(carrier.mb_sendcloud_webhook_ready)
        self.assertFalse(carrier.mb_sendcloud_last_webhook_at)

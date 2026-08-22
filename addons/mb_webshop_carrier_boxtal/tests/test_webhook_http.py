import hashlib
import hmac
import json
from unittest.mock import patch

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestBoxtalWebhookHttp(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.secret = "webhook-secret-that-is-long-enough"
        cls.env.company.mb_control_workshop_id = "00000000-0000-4000-8000-000000000099"
        product = cls.env["product.product"].create(
            {
                "name": "Boxtal webhook delivery",
                "type": "service",
            }
        )
        cls.carrier = cls.env["delivery.carrier"].create(
            {
                "name": "Boxtal webhook fixture",
                "delivery_type": "mb_boxtal",
                "product_id": product.id,
                "company_id": cls.env.company.id,
                "mb_provider_service_code": "MONR-CpourToi",
                "mb_secret_ref": "opaque-webhook-fixture",
            }
        )
        cls.url = f"/mb_carrier/webhook/boxtal/{cls.carrier.mb_subscription_id}"

    @staticmethod
    def _event():
        return json.dumps(
            {
                "id": "evt-http-1",
                "type": "TRACKING_CHANGED",
                "shippingOrderId": "provider-order-http-1",
                "timestamp": "2026-08-16T12:00:00Z",
                "payload": {
                    "trackings": [
                        {
                            "trackingNumber": "TRACK-HTTP-1",
                            "packageTrackingUrl": "https://carrier.example/track/TRACK-HTTP-1",
                        }
                    ]
                },
            },
            separators=(",", ":"),
        ).encode()

    def _post(self, raw, signature):
        with patch.object(
            type(self.carrier),
            "_mb_resolve_credentials",
            autospec=True,
            return_value={
                "access_key": "access",
                "secret_key": "secret",
                "webhook_secret": self.secret,
            },
        ):
            return self.url_open(
                self.url,
                data=raw,
                headers={
                    "Content-Type": "application/json",
                    "X-Bxt-Signature": signature,
                },
                allow_redirects=False,
            )

    def test_signed_webhook_is_acknowledged_and_replay_is_deduplicated(self):
        raw = self._event()
        signature = hmac.new(self.secret.encode(), raw, hashlib.sha256).hexdigest()

        first = self._post(raw, signature)
        second = self._post(raw, signature)

        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.env.invalidate_all()
        self.assertEqual(
            self.env["mb.carrier.webhook.event"].search_count(
                [
                    ("carrier_id", "=", self.carrier.id),
                    ("event_key", "=", "evt-http-1"),
                ]
            ),
            1,
        )

    def test_invalid_signature_is_rejected_before_inbox_write(self):
        response = self._post(self._event(), "0" * 64)

        self.assertEqual(response.status_code, 401)
        self.env.invalidate_all()
        self.assertFalse(
            self.env["mb.carrier.webhook.event"].search(
                [
                    ("carrier_id", "=", self.carrier.id),
                    ("event_key", "=", "evt-http-1"),
                ]
            )
        )

    def test_unknown_subscription_is_not_disclosed(self):
        raw = self._event()
        signature = hmac.new(self.secret.encode(), raw, hashlib.sha256).hexdigest()
        url = self.url
        self.url = "/mb_carrier/webhook/boxtal/unknown_subscription_000000"
        self.addCleanup(setattr, self, "url", url)

        response = self._post(raw, signature)

        self.assertEqual(response.status_code, 404)

import hashlib
import hmac
import json
from unittest.mock import patch

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestSendcloudWebhookHttp(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.secret = "sendcloud-webhook-key-that-is-long-enough"
        cls.env.company.mb_control_workshop_id = "00000000-0000-4000-8000-000000000098"
        product = cls.env["product.product"].create(
            {
                "name": "Sendcloud webhook delivery",
                "type": "service",
            }
        )
        cls.carrier = cls.env["delivery.carrier"].create(
            {
                "name": "Sendcloud webhook fixture",
                "delivery_type": "mb_sendcloud",
                "product_id": product.id,
                "company_id": cls.env.company.id,
                "mb_provider_service_code": "sendcloud:letter",
                "mb_sendcloud_sender_address_id": 7,
                "mb_secret_ref": "opaque-sendcloud-webhook-fixture",
            }
        )
        cls.url = f"/mb_carrier/webhook/sendcloud/{cls.carrier.mb_subscription_id}"

    @staticmethod
    def _event():
        return json.dumps(
            {
                "source_id": "journal-sendcloud-http",
                "updated_at": "2026-08-18T10:00:00Z",
                "tracking_numbers": [
                    {
                        "tracking_number": "TRACK-SENDCLOUD-HTTP",
                        "tracking_url": "https://tracking.sendcloud.sc/track",
                    }
                ],
                "events": [
                    {
                        "event_at": "2026-08-18T10:00:00Z",
                        "status_code": "driver-on-route",
                        "status_description": "Out for delivery",
                    }
                ],
            },
            separators=(",", ":"),
        ).encode()

    def _post(self, raw, signature):
        with patch.object(
            type(self.carrier),
            "_mb_resolve_credentials",
            autospec=True,
            return_value={
                "public_key": "sendcloud-public-key",
                "private_key": "sendcloud-private-key-that-is-long-enough",
                "webhook_signature_key": self.secret,
            },
        ):
            return self.url_open(
                self.url,
                data=raw,
                headers={
                    "Content-Type": "application/json",
                    "Sendcloud-Signature": signature,
                },
                allow_redirects=False,
            )

    def test_signed_event_is_deduplicated_and_marks_webhook_ready(self):
        raw = self._event()
        signature = hmac.new(self.secret.encode(), raw, hashlib.sha256).hexdigest()

        first = self._post(raw, signature)
        second = self._post(raw, signature)

        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.env.invalidate_all()
        event_key = hashlib.sha256(raw).hexdigest()
        self.assertEqual(
            self.env["mb.carrier.webhook.event"].search_count(
                [
                    ("carrier_id", "=", self.carrier.id),
                    ("event_key", "=", event_key),
                ]
            ),
            1,
        )
        self.assertTrue(self.carrier.mb_sendcloud_webhook_ready)

    def test_invalid_signature_is_rejected(self):
        response = self._post(self._event(), "0" * 64)

        self.assertEqual(response.status_code, 401)

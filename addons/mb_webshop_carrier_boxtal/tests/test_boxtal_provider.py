from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import Mock, patch

import requests

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.mb_webshop_carrier_base.provider import (
    Parcel,
    PickupQuery,
    ProviderAuthError,
    ProviderTransientError,
    ProviderValidationError,
    ShipmentRequest,
)

from ..models import delivery_carrier as delivery_carrier_model
from ..provider import BoxtalProvider


class Response:
    def __init__(self, status=200, payload=None, content=None, headers=None):
        self.status_code = status
        self._payload = payload
        self.content = content if content is not None else json.dumps(payload or {}).encode()
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError
        return self._payload


@tagged("post_install", "-at_install")
class TestBoxtalProvider(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        product = cls.env["product.product"].create(
            {
                "name": "Boxtal delivery",
                "type": "service",
            }
        )
        cls.carrier = cls.env["delivery.carrier"].create(
            {
                "name": "Boxtal fixture",
                "delivery_type": "mb_boxtal",
                "product_id": product.id,
                "mb_provider_service_code": "MONR-CpourToi",
                "mb_boxtal_use_locations": True,
                "mb_boxtal_length_cm": 30,
                "mb_boxtal_width_cm": 20,
                "mb_boxtal_height_cm": 15,
                "mb_boxtal_content_category": "content:v1:10150",
                "mb_boxtal_content_description": "Handmade ceramic bowl",
            }
        )

    def setUp(self):
        super().setUp()
        self.session = Mock()
        self.provider = BoxtalProvider(
            {"access_key": "access", "secret_key": "secret"},
            carrier=self.carrier,
            session=self.session,
        )

    @staticmethod
    def _request(pickup="POINT-1"):
        contact = {
            "name": "Jeanne Martin",
            "company": "Atelier Jeanne",
            "street": "1 rue de Paris",
            "street2": "",
            "zip": "75011",
            "city": "Paris",
            "country_code": "FR",
            "phone": "+33601020304",
            "email": "jeanne@example.test",
        }
        return ShipmentRequest(
            idempotency_key="stable-client-reference",
            service_code="MONR-CpourToi",
            sender=contact,
            recipient=dict(contact, name="Camille Durand", street="2 rue Oberkampf"),
            parcels=(Parcel(weight_kg=1.25, value=85),),
            pickup_code=pickup,
        )

    def test_order_payload_matches_current_v31_contract(self):
        self.session.request.return_value = Response(
            payload={
                "status": 200,
                "content": {
                    "id": "2440000050MONR4IA9FR",
                    "deliveryPriceExclTax": {"value": 4.3, "currency": "EUR"},
                },
            }
        )

        submission = self.provider.create_shipment(self._request())

        self.assertEqual(submission.provider_ref, "2440000050MONR4IA9FR")
        self.assertEqual(submission.state, "pending")
        args, kwargs = self.session.request.call_args
        self.assertEqual(
            args[:2], ("POST", "https://api.boxtal.build/shipping/v3.1/shipping-order")
        )
        payload = kwargs["json"]
        self.assertEqual(payload["shippingOfferCode"], "MONR-CpourToi")
        self.assertEqual(payload["shipment"]["externalId"], "stable-client-reference")
        self.assertEqual(payload["shipment"]["pickupPointCode"], "POINT-1")
        package = payload["shipment"]["packages"][0]
        self.assertEqual(package["weight"], 1.25)
        self.assertEqual(package["content"]["id"], "content:v1:10150")

    def test_mutating_timeout_is_ambiguous_and_never_retried(self):
        self.session.request.side_effect = requests.Timeout()

        with self.assertRaises(ProviderTransientError):
            self.provider.create_shipment(self._request())

        self.assertEqual(self.session.request.call_count, 1)

    def test_authentication_failure_has_the_contract_error_type(self):
        self.session.request.return_value = Response(status=401, payload={"error": "no"})

        with self.assertRaises(ProviderAuthError):
            self.provider.check_credentials()

    def test_connection_check_requires_a_configured_shipping_offer(self):
        carrier = Mock(mb_provider_service_code="", mb_boxtal_use_locations=False)
        provider = BoxtalProvider(
            {"access_key": "access", "secret_key": "secret"},
            carrier=carrier,
            session=self.session,
        )
        self.session.request.return_value = Response(payload={"content": []})

        with self.assertRaisesRegex(ProviderValidationError, "shipping_offer_required"):
            provider.check_credentials()

    def test_boxtal_rejects_unsupported_label_formats(self):
        with self.assertRaises(ValidationError):
            self.carrier.mb_label_format = "A5"

    def test_production_connection_requires_manual_commercial_readiness(self):
        self.carrier.write(
            {
                "prod_environment": True,
                "mb_boxtal_commercial_readiness_confirmed": False,
            }
        )

        with self.assertRaisesRegex(UserError, "deferred-payment"):
            self.carrier.action_mb_test_connection()

    def test_pickup_point_search_uses_v32_offer_filter(self):
        self.session.request.return_value = Response(
            payload={
                "content": [
                    {
                        "distanceFromSearchLocation": 450,
                        "parcelpoint": {
                            "code": "POINT-1",
                            "name": "Minute Phone",
                            "location": {
                                "number": "4",
                                "street": "boulevard des Capucines",
                                "postalCode": "75009",
                                "city": "Paris",
                                "countryIsoCode": "FR",
                                "position": {"latitude": "48.87", "longitude": "2.33"},
                            },
                            "openingDays": {"MONDAY": [{"start": "09:00", "end": "18:00"}]},
                        },
                    }
                ],
            }
        )
        query = PickupQuery("FR", "75009", "Paris", "MONR-CpourToi")

        points = self.provider.search_pickup_points(query)

        self.assertEqual(points[0].code, "POINT-1")
        self.assertEqual(points[0].street, "4 boulevard des Capucines")
        self.assertEqual(points[0].distance_m, 450)
        self.assertEqual(
            self.session.request.call_args.kwargs["params"]["operationType"], "ARRIVAL"
        )

    def test_signed_webhook_is_verified_over_exact_raw_bytes(self):
        raw = b'{"type":"DOCUMENT_CREATED", "shippingOrderId":"order-1"}'
        secret = "webhook-secret-that-is-long-enough"
        signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()

        self.assertTrue(self.provider.verify_webhook(raw, {"x-bxt-signature": signature}, secret))
        self.assertFalse(
            self.provider.verify_webhook(raw + b"\n", {"x-bxt-signature": signature}, secret)
        )
        self.assertFalse(self.provider.verify_webhook(raw, {}, secret))

    def test_tracking_webhook_requires_a_safe_https_link(self):
        event = {
            "id": "event-1",
            "type": "TRACKING_CHANGED",
            "shippingOrderId": "order-1",
            "timestamp": "2026-08-16T12:00:00Z",
            "payload": {
                "trackings": [
                    {
                        "trackingNumber": "TRACK-1",
                        "packageTrackingUrl": "https://carrier.example/track/TRACK-1",
                    }
                ]
            },
        }
        parsed = self.provider.parse_webhook(json.dumps(event).encode())
        self.assertEqual(parsed.tracking_number, "TRACK-1")

        event["payload"]["trackings"][0]["packageTrackingUrl"] = "javascript:alert(1)"
        with self.assertRaises(ProviderValidationError):
            self.provider.parse_webhook(json.dumps(event).encode())

    def test_document_download_rejects_ssrf_and_non_pdf(self):
        with self.assertRaises(ProviderValidationError):
            self.provider._download_document("http://127.0.0.1/private")

        self.session.get.return_value = Response(
            content=b"<html>not a label</html>", headers={"Content-Type": "text/html"}
        )
        with self.assertRaises(ProviderValidationError):
            self.provider._download_document("https://document.boxtal.com/label")

    def test_dispatch_type_is_bound_to_shared_runtime(self):
        self.assertEqual(self.carrier.mb_provider_code, "boxtal")
        self.assertTrue(self.carrier.mb_subscription_id)
        self.assertTrue(self.carrier.mb_boxtal_use_locations)

    def test_capability_suspension_deletes_only_matching_webhook_subscriptions(self):
        self.session.request.side_effect = [
            Response(
                payload={
                    "content": [
                        {"id": "subscription-1", "callbackUrl": "https://shop.test/callback"},
                        {"id": "subscription-2", "callbackUrl": "https://other.test/callback"},
                    ]
                }
            ),
            Response(status=204, content=b""),
        ]

        self.provider.suspend_subscriptions("https://shop.test/callback")

        self.assertEqual(self.session.request.call_count, 2)
        self.assertEqual(
            self.session.request.call_args.args[:2],
            ("DELETE", "https://api.boxtal.build/shipping/v3.1/subscription/subscription-1"),
        )

    def test_subscription_health_requires_both_active_event_types(self):
        self.session.request.return_value = Response(
            payload={
                "content": [
                    {
                        "eventType": "DOCUMENT_CREATED",
                        "callbackUrl": "https://shop.test/callback",
                        "status": "ACTIVE",
                    },
                    {
                        "eventType": "TRACKING_CHANGED",
                        "callbackUrl": "https://shop.test/callback",
                        "status": "ACTIVE",
                    },
                ]
            }
        )
        self.assertTrue(self.provider.check_subscriptions("https://shop.test/callback"))

    def test_subscription_reconciliation_rotates_the_webhook_secret(self):
        self.session.request.side_effect = [
            Response(
                payload={
                    "content": [
                        {
                            "id": "subscription-document",
                            "eventType": "DOCUMENT_CREATED",
                            "callbackUrl": "https://shop.test/callback",
                            "status": "ACTIVE",
                        },
                        {
                            "id": "subscription-tracking",
                            "eventType": "TRACKING_CHANGED",
                            "callbackUrl": "https://shop.test/callback",
                            "status": "ACTIVE",
                        },
                        {
                            "id": "subscription-other",
                            "eventType": "DOCUMENT_CREATED",
                            "callbackUrl": "https://other.test/callback",
                            "status": "ACTIVE",
                        },
                    ]
                }
            ),
            Response(status=204, content=b""),
            Response(status=204, content=b""),
            Response(payload={"content": {"id": "new-document"}}),
            Response(payload={"content": {"id": "new-tracking"}}),
        ]

        self.provider.reconcile_subscriptions(
            "https://shop.test/callback", "new-webhook-secret-that-is-long-enough"
        )

        calls = self.session.request.call_args_list
        self.assertEqual(len(calls), 5)
        self.assertEqual(
            calls[1].args[:2],
            (
                "DELETE",
                "https://api.boxtal.build/shipping/v3.1/subscription/subscription-document",
            ),
        )
        self.assertEqual(
            calls[2].args[:2],
            (
                "DELETE",
                "https://api.boxtal.build/shipping/v3.1/subscription/subscription-tracking",
            ),
        )
        created = [call.kwargs["json"] for call in calls[3:]]
        self.assertEqual(
            {payload["eventType"] for payload in created},
            {"DOCUMENT_CREATED", "TRACKING_CHANGED"},
        )
        self.assertTrue(
            all(
                payload["webhookSecret"] == "new-webhook-secret-that-is-long-enough"
                for payload in created
            )
        )

    def test_capability_restriction_keeps_webhook_cleanup_path_available(self):
        runtime = Mock()
        self.carrier.write(
            {
                "mb_secret_ref": "carrier-secret-boxtal",
                "mb_provider_enabled": True,
            }
        )
        with patch.object(
            type(self.carrier), "_mb_provider", autospec=True, return_value=runtime
        ) as provider_resolver:
            self.env.company._mb_apply_capability_restriction(
                "shipping-boxtal", "entitlement_inactive"
            )
            self.carrier.invalidate_recordset(["mb_provider_restricted"])
            self.assertTrue(self.carrier.mb_provider_restricted)
            self.carrier._mb_provider(purpose="webhook_processing")
            self.env.company._mb_remove_capability_restriction("shipping-boxtal")

        self.assertTrue(self.carrier.mb_provider_enabled)
        self.assertFalse(self.carrier.mb_provider_restricted)
        provider_resolver.assert_called_once_with(self.carrier, purpose="webhook_processing")
        runtime.suspend_subscriptions.assert_not_called()

    def test_secret_rotation_prepares_a_fresh_signed_callback(self):
        runtime = Mock()
        provider_type = Mock(return_value=runtime)
        credentials = {
            "access_key": "new-access-key",
            "secret_key": "new-secret-key-that-is-long-enough",
            "webhook_secret": "new-webhook-secret-that-is-long-enough",
        }
        parameters = self.env["ir.config_parameter"].sudo()
        previous_url = parameters.get_param("web.base.url")
        parameters.set_param("web.base.url", "https://shop.test")
        self.addCleanup(parameters.set_param, "web.base.url", previous_url)

        with patch.object(delivery_carrier_model, "provider_class", return_value=provider_type):
            subscription_id = self.carrier._mb_prepare_secret_rotation(credentials)

        provider_type.assert_called_once_with(
            credentials=credentials,
            production=bool(self.carrier.prod_environment),
            carrier=self.carrier,
        )
        runtime.reconcile_subscriptions.assert_called_once_with(
            f"https://shop.test/mb_carrier/webhook/boxtal/{subscription_id}",
            credentials["webhook_secret"],
        )
        self.assertNotEqual(subscription_id, self.carrier.mb_subscription_id)

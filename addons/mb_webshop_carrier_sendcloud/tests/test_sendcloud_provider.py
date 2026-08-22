import hashlib
import hmac
import json
from types import SimpleNamespace

import requests

from odoo.tests import TransactionCase, tagged

from odoo.addons.mb_webshop_carrier_base.provider import (
    Parcel,
    PickupQuery,
    ProviderTransientError,
    ProviderValidationError,
    ShipmentRequest,
    ShippingOptionQuery,
)

from ..provider import SendcloudProvider


class Response:
    def __init__(self, status=200, payload=None, content=None, content_type="application/json"):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.content = content if content is not None else json.dumps(self._payload).encode()
        self.headers = {"Content-Type": content_type, "Content-Length": str(len(self.content))}

    def json(self):
        return self._payload


class Session:
    def __init__(self, *responses, documents=()):
        self.responses = list(responses)
        self.documents = list(documents)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    def get(self, url, **kwargs):
        self.calls.append(("GET_DOCUMENT", url, kwargs))
        return self.documents.pop(0)


def address(name="Recipient", number="3"):
    return {
        "name": name,
        "company": "",
        "street": f"{number} rue du Test",
        "street_name": "rue du Test",
        "house_number": number,
        "house_number_addition": "",
        "street2": "",
        "zip": "75011",
        "city": "Paris",
        "country_code": "FR",
        "phone": "+33102030405",
        "email": "recipient@example.test",
    }


def sender_payload():
    return {
        "data": {
            "id": 7,
            "name": "Workshop",
            "company_name": "Workshop",
            "address_line_1": "rue de l'Atelier",
            "house_number": "1",
            "postal_code": "75011",
            "city": "Paris",
            "country_code": "FR",
            "phone_number": "+33102030405",
            "email": "workshop@example.test",
        }
    }


def request(direction="outbound", service="sendcloud:letter"):
    return ShipmentRequest(
        idempotency_key=f"journal-{direction}",
        service_code=service,
        sender=address("Workshop", "1") if direction == "outbound" else address("Customer", "3"),
        recipient=address("Customer", "3") if direction == "outbound" else address("Workshop", "1"),
        parcels=(Parcel(1.2, 30, 20, 15, 25, "EUR"),),
        metadata={"picking": "WH/OUT/0001", "direction": direction},
        items=(
            {
                "description": "Ceramic cup",
                "quantity": 1,
                "weight_kg": 1.2,
                "value": 25,
                "currency": "EUR",
                "hs_code": "691200",
                "origin_country": "FR",
                "sku": "CUP",
                "product_id": "1",
            },
        ),
    )


@tagged("post_install", "-at_install")
class TestSendcloudProvider(TransactionCase):
    def carrier(self, **overrides):
        values = {
            "mb_sendcloud_sender_address_id": 7,
            "mb_sendcloud_contract_id": 0,
            "mb_sendcloud_brand_id": 0,
            "mb_sendcloud_carrier_code": "",
            "mb_sendcloud_length_cm": 30,
            "mb_sendcloud_width_cm": 20,
            "mb_sendcloud_height_cm": 15,
            "mb_label_format": "10x15",
            "mb_provider_service_code": "sendcloud:letter",
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def provider(self, session, production=False, **carrier):
        return SendcloudProvider(
            {"public_key": "public-key", "private_key": "p" * 24},
            production=production,
            carrier=self.carrier(**carrier),
            session=session,
        )

    def test_outbound_payload_uses_v3_reference_sender_and_document(self):
        shipment = {
            "data": {
                "id": "shipment-1",
                "parcels": [
                    {
                        "id": 8,
                        "tracking_number": "TRACK-1",
                        "tracking_url": "https://tracking.sendcloud.sc/test",
                        "documents": [
                            {
                                "type": "label",
                                "link": "https://panel.sendcloud.sc/api/v3/parcels/8/documents/label",
                            }
                        ],
                    }
                ],
            }
        }
        session = Session(
            Response(payload=sender_payload()),
            Response(status=201, payload=shipment),
            documents=[Response(content=b"%PDF-1.4 label", content_type="application/pdf")],
        )

        result = self.provider(session).create_shipment(request())

        self.assertEqual(result.provider_ref, "shipment-1")
        self.assertEqual(result.tracking_number, "TRACK-1")
        self.assertEqual(result.documents[0].format, "PDF")
        create_call = session.calls[1]
        self.assertTrue(create_call[1].endswith("/api/v3/shipments/announce"))
        payload = create_call[2]["json"]
        self.assertEqual(payload["external_reference_id"], "journal-outbound")
        self.assertEqual(payload["from_address"]["house_number"], "1")
        self.assertEqual(payload["to_address"]["house_number"], "3")
        self.assertEqual(payload["parcels"][0]["source_id"], "journal-outbound")
        self.assertEqual(payload["parcels"][0]["parcel_items"][0]["hs_code"], "691200")

    def test_test_mode_refuses_every_billable_option_in_adapter(self):
        provider = self.provider(Session(), production=False)
        with self.assertRaises(ProviderValidationError):
            provider.create_shipment(request(service="dpd:home"))

    def test_outbound_is_retry_safe_but_return_is_not(self):
        provider = self.provider(Session())
        self.assertTrue(provider.operation_safety("create_shipment").automatic_retry)
        self.assertFalse(provider.operation_safety("create_return").automatic_retry)

    def test_return_uses_customer_to_selected_sender_and_return_endpoint(self):
        returned = {"return_id": 42, "parcel_id": 9, "multi_collo_ids": []}
        session = Session(
            Response(payload=sender_payload()),
            Response(status=201, payload=returned),
            documents=[Response(content=b"%PDF-1.4 return", content_type="application/pdf")],
        )
        result = self.provider(session, production=True).create_return_label(
            request(direction="return", service="dpd:return/return")
        )

        self.assertEqual(result.provider_ref, "42")
        self.assertEqual(result.documents[0].kind, "return_label")
        payload = session.calls[1][2]["json"]
        self.assertEqual(payload["from_address"]["name"], "Customer")
        self.assertEqual(payload["to_address"]["name"], "Workshop")
        self.assertEqual(payload["external_reference"], "journal-return")

    def test_return_mutation_timeout_is_ambiguous(self):
        class TimeoutSession(Session):
            def request(self, method, url, **kwargs):
                if method == "POST":
                    raise requests.Timeout()
                return super().request(method, url, **kwargs)

        provider = self.provider(
            TimeoutSession(Response(payload=sender_payload())), production=True
        )
        with self.assertRaises(ProviderTransientError):
            provider.create_return_label(request(direction="return", service="dpd:return/return"))

    def test_tracking_endpoint_normalizes_terminal_status(self):
        session = Session(
            Response(
                payload={
                    "tracking_numbers": [
                        {
                            "tracking_number": "TRACK-1",
                            "tracking_url": "https://tracking.sendcloud.sc/track",
                        }
                    ],
                    "details": {"expected_delivery_date": "2026-08-18"},
                    "events": [
                        {
                            "status_code": "delivered",
                            "status_description": "Delivered",
                            "event_at": "2026-08-18T10:00:00Z",
                        }
                    ],
                }
            )
        )
        snapshot = self.provider(session).retrieve_tracking("TRACK-1")
        self.assertEqual(snapshot.category, "delivered")
        self.assertEqual(snapshot.status_code, "DELIVERED")
        self.assertEqual(snapshot.tracking_number, "TRACK-1")
        self.assertEqual(snapshot.tracking_url, "https://tracking.sendcloud.sc/track")

    def test_shipping_options_use_multicollo_v3_shape_and_quote_total(self):
        options = {
            "data": [
                {
                    "code": "postnl:standard",
                    "name": "PostNL Standard",
                    "carrier": {"code": "postnl"},
                    "quotes": [{"price": {"total": {"value": "6.25", "currency": "EUR"}}}],
                    "requirements": {"is_service_point_required": False},
                    "functionalities": {"returns": True},
                }
            ]
        }
        session = Session(Response(payload=sender_payload()), Response(payload=options))
        query = ShippingOptionQuery(
            sender=address("Workshop", "1"),
            recipient=address("Customer", "3"),
            parcels=(Parcel(1.2, 30, 20, 15),),
        )

        result = self.provider(session, production=True).shipping_options(query)

        payload = session.calls[1][2]["json"]
        self.assertIn("parcels", payload)
        self.assertNotIn("weight", payload)
        self.assertTrue(payload["calculate_quotes"])
        self.assertEqual(result[0].price, 6.25)

    def test_service_point_search_uses_structured_v3_parameters(self):
        points = {
            "data": {
                "results": [
                    {
                        "id": 1000001,
                        "name": "Parcel Shop",
                        "address": {
                            "street": "rue du Test",
                            "house_number": "12",
                            "postal_code": "75011",
                            "city": "Paris",
                            "country_code": "FR",
                        },
                        "position": {"latitude": 48.8, "longitude": 2.3},
                        "opening_times": {"monday": []},
                    }
                ]
            }
        }
        session = Session(Response(payload=points))

        result = self.provider(session, production=True).search_pickup_points(
            PickupQuery(country_code="FR", zip="75011", city="Paris")
        )

        params = session.calls[0][2]["params"]
        self.assertEqual(params["address_postal_code"], "75011")
        self.assertEqual(result[0].street, "rue du Test 12")

    def test_webhook_signature_uses_exact_raw_body(self):
        raw = b'{"parcel":{"shipment_id":"shipment-1","status":{"code":"IN_TRANSIT"}}}'
        secret = "w" * 24
        signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        self.assertTrue(
            SendcloudProvider.verify_webhook(raw, {"Sendcloud-Signature": signature}, secret)
        )
        self.assertFalse(
            SendcloudProvider.verify_webhook(raw + b" ", {"Sendcloud-Signature": signature}, secret)
        )

    def test_webhook_payload_uses_shared_tracking_category(self):
        event = SendcloudProvider.parse_webhook(
            json.dumps(
                {
                    "id": "event-1",
                    "source_id": "journal-outbound",
                    "tracking_numbers": [
                        {
                            "tracking_number": "TRACK-1",
                            "tracking_url": "https://tracking.sendcloud.sc/track",
                        }
                    ],
                    "events": [
                        {
                            "status_code": "driver-on-route",
                            "status_description": "On its way",
                            "event_at": "2026-08-18T10:00:00Z",
                        }
                    ],
                }
            ).encode()
        )
        self.assertEqual(event.provider_ref, "journal-outbound")
        self.assertEqual(event.tracking_number, "TRACK-1")
        self.assertEqual(event.status_category, "out_for_delivery")

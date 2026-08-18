from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import time
from urllib.parse import urlsplit

import requests

from odoo.addons.mb_webshop_carrier_base.provider import (
    CredentialStatus,
    OperationSafety,
    PickupPoint,
    ProviderAuthError,
    ProviderTransientError,
    ProviderUnavailableError,
    ProviderValidationError,
    ShipmentDocument,
    ShipmentSubmission,
    ShippingService,
    register_provider,
)


PRODUCTION_BASE = "https://api.boxtal.com"
SANDBOX_BASE = "https://api.boxtal.build"
JSON_LIMIT = 1024 * 1024
DOCUMENT_LIMIT = 12 * 1024 * 1024
SIGNATURE = re.compile(r"^[0-9a-fA-F]{64}$")


@register_provider
class BoxtalProvider:
    """Bounded adapter for Boxtal's current v3.1/v3.2 JSON API."""

    code = "boxtal"
    supports_pickup_points = True
    supports_own_contract = False
    supports_manifest = False
    supports_return_label = False
    supports_tracking_lookup = False
    supports_contextual_options = False
    # The current OpenAPI has neither an idempotency header nor lookup by
    # Shipment.externalId. An ambiguous POST must therefore remain unknown.
    supports_idempotency = False
    supports_reconciliation = False

    @staticmethod
    def operation_safety(operation):
        return OperationSafety()

    def __init__(self, credentials, production=False, carrier=None, session=None):
        self.credentials = credentials
        self.production = bool(production)
        self.carrier = carrier
        self.base_url = PRODUCTION_BASE if production else SANDBOX_BASE
        self.session = session or requests.Session()
        access_key = credentials.get("access_key")
        secret_key = credentials.get("secret_key")
        if not isinstance(access_key, str) or not isinstance(secret_key, str):
            raise ProviderAuthError("credentials_missing")
        if not access_key or not secret_key or len(access_key) > 256 or len(secret_key) > 512:
            raise ProviderAuthError("credentials_invalid")
        self.auth = (access_key, secret_key)

    @staticmethod
    def _bounded_json(response):
        length = response.headers.get("Content-Length")
        if length and length.isdigit() and int(length) > JSON_LIMIT:
            raise ProviderUnavailableError("response_too_large")
        content = response.content
        if len(content) > JSON_LIMIT:
            raise ProviderUnavailableError("response_too_large")
        try:
            value = response.json()
        except ValueError as error:
            raise ProviderUnavailableError("invalid_json") from error
        if not isinstance(value, dict):
            raise ProviderUnavailableError("invalid_json_shape")
        return value

    @staticmethod
    def _raise_status(response, operation):
        if response.status_code in (401, 403):
            raise ProviderAuthError("authentication_failed")
        if response.status_code == 429:
            raise ProviderTransientError("rate_limited")
        if response.status_code >= 500:
            raise ProviderUnavailableError("provider_unavailable")
        if response.status_code >= 400:
            if operation in ("shipping_document", "tracking") and response.status_code == 422:
                raise ProviderTransientError("resource_not_ready")
            raise ProviderValidationError("request_rejected")

    def _request(self, method, path, *, params=None, payload=None, operation="read"):
        mutation = method in ("POST", "PUT", "DELETE")
        attempts = 1 if mutation else 3
        for attempt in range(attempts):
            try:
                response = self.session.request(
                    method,
                    f"{self.base_url}{path}",
                    auth=self.auth,
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                    params=params,
                    json=payload,
                    timeout=(3.05, 15),
                    allow_redirects=False,
                )
            except (requests.Timeout, requests.ConnectionError) as error:
                if mutation:
                    raise ProviderTransientError("ambiguous_mutation") from error
                if attempt + 1 == attempts:
                    raise ProviderUnavailableError("network_unavailable") from error
                time.sleep(0.05 * (2**attempt))
                continue
            self._raise_status(response, operation)
            if response.status_code in (204, 205) or not response.content:
                return {}
            return self._bounded_json(response)
        raise ProviderUnavailableError("network_unavailable")

    def check_credentials(self):
        self._request("GET", "/shipping/v3.1/content-category", operation="credentials")
        services = tuple(service.code for service in self.list_services())
        if not services:
            raise ProviderValidationError("shipping_offer_required")
        return CredentialStatus(
            valid=True,
            environment="production" if self.production else "test",
            service_codes=services,
            # Boxtal's API does not expose deferred-payment/account readiness.
            # This result deliberately attests authentication only; production
            # activation has a separately labelled manual commercial gate.
            message="authentication_valid",
        )

    def list_services(self):
        code = getattr(self.carrier, "mb_provider_service_code", "") or ""
        if not code:
            return []
        uses_pickup = bool(getattr(self.carrier, "mb_boxtal_use_locations", False))
        return [ShippingService(code, code, supports_pickup_points=uses_pickup)]

    @staticmethod
    def _pickup_point(item):
        point = item.get("parcelpoint") or {}
        location = point.get("location") or {}
        position = location.get("position") or {}
        code = str(point.get("code") or "")
        if not code or len(code) > 128:
            raise ProviderValidationError("invalid_pickup_point")
        try:
            latitude = float(position["latitude"]) if position.get("latitude") is not None else None
            longitude = float(position["longitude"]) if position.get("longitude") is not None else None
        except (TypeError, ValueError) as error:
            raise ProviderValidationError("invalid_pickup_coordinates") from error
        number = str(location.get("number") or "").strip()
        street = " ".join(part for part in (number, str(location.get("street") or "").strip()) if part)
        return PickupPoint(
            code=code,
            name=str(point.get("name") or code)[:255],
            street=street[:255],
            zip=str(location.get("postalCode") or "")[:16],
            city=str(location.get("city") or "")[:128],
            country_code=str(location.get("countryIsoCode") or "")[:2].upper(),
            latitude=latitude,
            longitude=longitude,
            distance_m=int(item.get("distanceFromSearchLocation") or 0),
            opening_hours=point.get("openingDays") if isinstance(point.get("openingDays"), dict) else {},
        )

    def search_pickup_points(self, query):
        if not query.service_code:
            raise ProviderValidationError("shipping_offer_required")
        payload = self._request(
            "GET",
            "/shipping/v3.2/parcel-point-by-shipping-offer",
            params={
                "postalCode": query.zip,
                "city": query.city or None,
                "countryIsoCode": query.country_code,
                "operationType": "ARRIVAL",
                "shippingOfferCode": query.service_code,
            },
            operation="pickup_search",
        )
        items = payload.get("content")
        if not isinstance(items, list):
            raise ProviderUnavailableError("invalid_pickup_response")
        points = []
        for item in items[: min(max(query.limit, 1), 20)]:
            if isinstance(item, dict):
                points.append(self._pickup_point(item))
        return points

    def get_pickup_point(self, code, service_code="", query=None):
        if query is None or not query.country_code or not query.zip:
            raise ProviderValidationError("pickup_search_context_required")
        for point in self.search_pickup_points(query):
            if hmac.compare_digest(point.code, str(code)):
                return point
        raise ProviderValidationError("pickup_point_unavailable")

    @staticmethod
    def _contact(address):
        name = str(address.get("name") or "").strip()
        parts = name.split(maxsplit=1)
        first_name = parts[0] if parts else "Contact"
        last_name = parts[1] if len(parts) > 1 else "."
        email = str(address.get("email") or "").strip()
        phone = re.sub(r"[^0-9+]", "", str(address.get("phone") or ""))
        if not email or "@" not in email or not phone:
            raise ProviderValidationError("contact_email_and_phone_required")
        return {
            "firstName": first_name[:128],
            "lastName": last_name[:128],
            "email": email[:254],
            "phone": phone[:32],
            "company": str(address.get("company") or "")[:128] or None,
        }

    @staticmethod
    def _address(address, address_type):
        street = " ".join(filter(None, (
            str(address.get("street") or "").strip(),
            str(address.get("street2") or "").strip(),
        )))
        country = str(address.get("country_code") or "").upper()
        if not street or not address.get("city") or not country:
            raise ProviderValidationError("complete_address_required")
        return {
            "type": address_type,
            "contact": BoxtalProvider._contact(address),
            "location": {
                "street": street[:255],
                "city": str(address.get("city"))[:128],
                "postalCode": str(address.get("zip") or "")[:16],
                "countryIsoCode": country[:2],
            },
        }

    def _order_payload(self, request):
        if len(request.parcels) != 1:
            raise ProviderValidationError("one_parcel_per_shipment")
        parcel = request.parcels[0]
        dimensions = (
            parcel.length_cm or float(getattr(self.carrier, "mb_boxtal_length_cm", 0)),
            parcel.width_cm or float(getattr(self.carrier, "mb_boxtal_width_cm", 0)),
            parcel.height_cm or float(getattr(self.carrier, "mb_boxtal_height_cm", 0)),
        )
        if parcel.weight_kg <= 0 or any(value <= 0 or not math.isfinite(value) for value in dimensions):
            raise ProviderValidationError("positive_weight_and_dimensions_required")
        content_id = str(getattr(self.carrier, "mb_boxtal_content_category", "") or "")
        description = str(getattr(self.carrier, "mb_boxtal_content_description", "") or "")
        if not content_id or not description:
            raise ProviderValidationError("content_category_required")
        package = {
            "type": "PARCEL",
            "weight": round(parcel.weight_kg, 3),
            "length": math.ceil(dimensions[0]),
            "width": math.ceil(dimensions[1]),
            "height": math.ceil(dimensions[2]),
            "value": {"value": max(0, round(parcel.value, 2)), "currency": "EUR"},
            "content": {"id": content_id, "description": description[:255]},
            "externalId": f"{request.idempotency_key}:0"[:128],
        }
        shipment = {
            "externalId": request.idempotency_key[:128],
            "fromAddress": self._address(request.sender, "BUSINESS"),
            "toAddress": self._address(request.recipient, "RESIDENTIAL"),
            "packages": [package],
        }
        if request.pickup_code:
            shipment["pickupPointCode"] = request.pickup_code
        label_format = getattr(self.carrier, "mb_label_format", "A4")
        if label_format not in ("A4", "10x15"):
            raise ProviderValidationError("unsupported_label_format")
        return {
            "insured": False,
            "shippingOfferCode": request.service_code,
            "labelType": "PDF_10x15" if label_format == "10x15" else "PDF_A4",
            "shipment": shipment,
        }

    def create_shipment(self, request):
        payload = self._request(
            "POST",
            "/shipping/v3.1/shipping-order",
            payload=self._order_payload(request),
            operation="create_shipment",
        )
        content = payload.get("content")
        if not isinstance(content, dict) or not content.get("id"):
            raise ProviderUnavailableError("missing_order_reference")
        price = content.get("deliveryPriceExclTax") or {}
        exact_price = float(price.get("value") or 0) if isinstance(price, dict) else 0
        return ShipmentSubmission(
            provider_ref=str(content["id"]),
            state="pending",
            exact_price=exact_price,
        )

    def reconcile_shipment(self, request):
        # Current Boxtal v3 only retrieves by its own order id, which is not
        # available after an ambiguous create timeout.
        return None

    def cancel_shipment(self, provider_ref):
        self._request(
            "DELETE",
            f"/shipping/v3.1/shipping-order/{provider_ref}",
            operation="cancel_shipment",
        )

    def create_return_label(self, request):
        raise ProviderValidationError("return_labels_not_supported")

    def build_manifest(self, provider_refs):
        raise ProviderValidationError("official_manifest_not_supported")

    def verify_webhook(self, raw_body, headers, secret):
        supplied = headers.get("x-bxt-signature", "")
        if not isinstance(supplied, str) or not SIGNATURE.fullmatch(supplied):
            return False
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, supplied.lower())

    def parse_webhook(self, raw_body):
        try:
            payload = json.loads(raw_body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProviderValidationError("invalid_webhook_json") from error
        if not isinstance(payload, dict):
            raise ProviderValidationError("invalid_webhook_shape")
        event_id = payload.get("id")
        provider_ref = payload.get("shippingOrderId")
        event_type = payload.get("type")
        event_payload = payload.get("payload")
        if (
            not isinstance(event_id, str)
            or not isinstance(provider_ref, str)
            or not isinstance(event_payload, dict)
        ):
            raise ProviderValidationError("invalid_webhook_envelope")
        from odoo.addons.mb_webshop_carrier_base.provider import ProviderWebhookEvent

        if event_type == "DOCUMENT_CREATED":
            documents = event_payload.get("documents")
            if not isinstance(documents, list) or not any(
                isinstance(document, dict) and document.get("type") == "LABEL"
                for document in documents
            ):
                raise ProviderValidationError("label_document_missing")
            return ProviderWebhookEvent(
                event_id=event_id[:128],
                provider_ref=provider_ref[:128],
                kind="document",
                document_ref=provider_ref[:128],
                occurred_at=str(payload.get("timestamp") or "")[:64],
            )
        if event_type == "TRACKING_CHANGED":
            trackings = event_payload.get("trackings")
            tracking = trackings[0] if isinstance(trackings, list) and trackings else None
            if not isinstance(tracking, dict):
                raise ProviderValidationError("tracking_missing")
            tracking_number = str(tracking.get("trackingNumber") or "")[:128]
            tracking_url = str(tracking.get("packageTrackingUrl") or "")[:1024]
            parsed_tracking = urlsplit(tracking_url)
            if (
                not tracking_number
                or parsed_tracking.scheme != "https"
                or not parsed_tracking.hostname
                or parsed_tracking.username
                or parsed_tracking.password
            ):
                raise ProviderValidationError("invalid_tracking_data")
            return ProviderWebhookEvent(
                event_id=event_id[:128],
                provider_ref=provider_ref[:128],
                kind="tracking",
                tracking_number=tracking_number,
                tracking_url=tracking_url,
                occurred_at=str(payload.get("timestamp") or "")[:64],
            )
        raise ProviderValidationError("unsupported_webhook_event")

    def _download_document(self, url):
        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").lower()
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or not hostname.endswith((".boxtal.com", ".boxtal.build"))
        ):
            raise ProviderValidationError("untrusted_document_url")
        try:
            response = self.session.get(
                url,
                timeout=(3.05, 20),
                allow_redirects=False,
                headers={"Accept": "application/pdf"},
            )
        except (requests.Timeout, requests.ConnectionError) as error:
            raise ProviderTransientError("document_download_failed") from error
        self._raise_status(response, "shipping_document")
        length = response.headers.get("Content-Length")
        if length and length.isdigit() and int(length) > DOCUMENT_LIMIT:
            raise ProviderValidationError("document_too_large")
        content = response.content
        if len(content) > DOCUMENT_LIMIT or not content.startswith(b"%PDF-"):
            raise ProviderValidationError("invalid_pdf_document")
        return ShipmentDocument(content, "PDF", "label", "boxtal-label.pdf")

    def fetch_webhook_document(self, event):
        payload = self._request(
            "GET",
            f"/shipping/v3.1/shipping-order/{event.provider_ref}/shipping-document",
            operation="shipping_document",
        )
        documents = payload.get("content")
        if not isinstance(documents, list):
            raise ProviderUnavailableError("invalid_document_response")
        label = next((item for item in documents if isinstance(item, dict) and item.get("type") == "LABEL"), None)
        if not label or not isinstance(label.get("url"), str):
            raise ProviderTransientError("label_not_ready")
        return self._download_document(label["url"])

    def reconcile_subscriptions(self, callback_url, webhook_secret):
        subscriptions = self._request(
            "GET", "/shipping/v3.1/subscription", operation="subscriptions"
        ).get("content")
        if not isinstance(subscriptions, list):
            raise ProviderUnavailableError("invalid_subscription_response")
        # Boxtal does not return the configured signing secret.  An active
        # subscription therefore cannot prove that it uses the current secret.
        # Recreate every subscription for this callback so credential rotation
        # cannot leave Boxtal signing with the previous value.
        event_types = ("DOCUMENT_CREATED", "TRACKING_CHANGED")
        for item in subscriptions:
            if (
                isinstance(item, dict)
                and item.get("callbackUrl") == callback_url
                and item.get("eventType") in event_types
            ):
                subscription_id = item.get("id")
                if not isinstance(subscription_id, str) or not subscription_id:
                    raise ProviderUnavailableError("invalid_subscription_response")
                self._request(
                    "DELETE",
                    f"/shipping/v3.1/subscription/{subscription_id}",
                    operation="delete_subscription",
                )
        for event_type in event_types:
            self._request(
                "POST",
                "/shipping/v3.1/subscription",
                payload={
                    "eventType": event_type,
                    "callbackUrl": callback_url,
                    "webhookSecret": webhook_secret,
                },
                operation="create_subscription",
            )
        return True

    def check_subscriptions(self, callback_url):
        subscriptions = self._request(
            "GET", "/shipping/v3.1/subscription", operation="subscriptions"
        ).get("content")
        if not isinstance(subscriptions, list):
            raise ProviderUnavailableError("invalid_subscription_response")
        active_types = {
            item.get("eventType")
            for item in subscriptions
            if isinstance(item, dict)
            and item.get("callbackUrl") == callback_url
            and item.get("status") == "ACTIVE"
        }
        return {"DOCUMENT_CREATED", "TRACKING_CHANGED"}.issubset(active_types)

    def suspend_subscriptions(self, callback_url):
        subscriptions = self._request(
            "GET", "/shipping/v3.1/subscription", operation="subscriptions"
        ).get("content")
        if not isinstance(subscriptions, list):
            raise ProviderUnavailableError("invalid_subscription_response")
        for subscription in subscriptions:
            if not isinstance(subscription, dict) or subscription.get("callbackUrl") != callback_url:
                continue
            subscription_id = str(subscription.get("id") or "")
            if not subscription_id or len(subscription_id) > 128:
                raise ProviderUnavailableError("invalid_subscription_reference")
            self._request(
                "DELETE",
                f"/shipping/v3.1/subscription/{subscription_id}",
                operation="delete_subscription",
            )
        return True

import hashlib
import hmac
import json
import re
import time
from datetime import datetime
from urllib.parse import urlsplit

import requests

from odoo.addons.mb_webshop_carrier_base.provider import (
    CancellationResult,
    CredentialStatus,
    OperationSafety,
    PickupPoint,
    ProviderAuthError,
    ProviderTransientError,
    ProviderUnavailableError,
    ProviderValidationError,
    ProviderWebhookEvent,
    ShipmentDocument,
    ShipmentSubmission,
    ShippingOption,
    ShippingService,
    TrackingEvent,
    TrackingSnapshot,
    register_provider,
)

BASE_URL = "https://panel.sendcloud.sc"
JSON_LIMIT = 2 * 1024 * 1024
DOCUMENT_LIMIT = 16 * 1024 * 1024
SIGNATURE = re.compile(r"^[0-9a-fA-F]{64}$")
TERMINAL_CANCELLED = {"CANCELLED", "CANCELLATION_REQUESTED_AND_ACCEPTED"}
TERMINAL_CANCEL_REJECTED = {"CANCELLATION_FAILED", "CANCELLATION_REJECTED"}
EU_COUNTRIES = {
    "AT",
    "BE",
    "BG",
    "HR",
    "CY",
    "CZ",
    "DE",
    "DK",
    "EE",
    "ES",
    "FI",
    "FR",
    "GR",
    "HU",
    "IE",
    "IT",
    "LT",
    "LU",
    "LV",
    "MT",
    "NL",
    "PL",
    "PT",
    "RO",
    "SE",
    "SI",
    "SK",
}


STATUS_CATEGORIES = {
    "ANNOUNCED": "pre_transit",
    "READY_TO_SEND": "pre_transit",
    "ACCEPTED_BY_CARRIER": "in_transit",
    "IN_TRANSIT": "in_transit",
    "AT_SERVICE_POINT": "at_service_point",
    "OUT_FOR_DELIVERY": "out_for_delivery",
    "DELIVERED": "delivered",
    "DELIVERY_FAILED": "exception",
    "EXCEPTION": "exception",
    "RETURNING": "returning",
    "RETURNED": "returned",
    "CANCELLED": "cancelled",
    "ACCEPTED": "in_transit",
    "TO_SORTING": "in_transit",
    "SORTING": "in_transit",
    "SORTED": "in_transit",
    "SHIPMENT_ON_ROUTE": "in_transit",
    "PICKED_UP_BY_DRIVER": "in_transit",
    "DRIVER_ON_ROUTE": "out_for_delivery",
    "AWAITING_CUSTOMER_PICKUP": "at_service_point",
    "COLLECTED_BY_CUSTOMER": "delivered",
    "RETURNED_TO_SENDER": "returned",
    "CANCELLING": "pre_transit",
    "CANCELLING_UPSTREAM": "pre_transit",
    "CANCELLED_UPSTREAM": "cancelled",
    "ADDRESS_INVALID": "exception",
    "ANNOUNCEMENT_FAILED": "exception",
    "UNDELIVERABLE": "exception",
    "REFUSED_BY_RECIPIENT": "exception",
}


def _parse_datetime(value):
    if not isinstance(value, str) or not value:
        return None


def _status_key(value):
    return re.sub(r"[^A-Z0-9]+", "_", str(value or "").upper()).strip("_")


def _category(value):
    key = _status_key(value)
    if key in STATUS_CATEGORIES:
        return STATUS_CATEGORIES[key]
    if any(part in key for part in ("FAILED", "INVALID", "ERROR", "EXCEPTION")):
        return "exception"
    if "RETURN" in key:
        return "returning"
    return "unknown"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


@register_provider
class SendcloudProvider:
    code = "sendcloud"
    supports_pickup_points = True
    supports_own_contract = True
    supports_manifest = False
    supports_return_label = True
    supports_tracking_lookup = True
    supports_contextual_options = True

    def __init__(self, credentials, production=False, carrier=None, session=None):
        self.credentials = credentials or {}
        self.production = bool(production)
        self.carrier = carrier
        self.session = session or requests.Session()
        public_key = self.credentials.get("public_key")
        private_key = self.credentials.get("private_key")
        if not isinstance(public_key, str) or not isinstance(private_key, str):
            raise ProviderAuthError("credentials_missing")
        if not 8 <= len(public_key) <= 256 or not 16 <= len(private_key) <= 512:
            raise ProviderAuthError("credentials_invalid")
        self.auth = (public_key, private_key)

    @staticmethod
    def operation_safety(operation):
        if operation == "create_shipment":
            return OperationSafety(True, True, True)
        # Sendcloud documents no equivalent duplicate guarantee for Returns.
        return OperationSafety()

    @staticmethod
    def _bounded_json(response):
        length = response.headers.get("Content-Length")
        if length and length.isdigit() and int(length) > JSON_LIMIT:
            raise ProviderUnavailableError("response_too_large")
        if len(response.content) > JSON_LIMIT:
            raise ProviderUnavailableError("response_too_large")
        try:
            payload = response.json()
        except ValueError as error:
            raise ProviderUnavailableError("invalid_json") from error
        if not isinstance(payload, (dict, list)):
            raise ProviderUnavailableError("invalid_json_shape")
        return payload

    @staticmethod
    def _raise_status(response, operation):
        if response.status_code in (401, 403):
            raise ProviderAuthError("authentication_failed")
        if response.status_code == 429:
            raise ProviderTransientError("rate_limited")
        if response.status_code >= 500:
            raise ProviderUnavailableError("provider_unavailable")
        if response.status_code == 404 and operation in {
            "tracking",
            "shipment_lookup",
            "return_lookup",
            "document",
        }:
            raise ProviderTransientError("resource_not_ready")
        if response.status_code >= 400:
            raise ProviderValidationError("request_rejected")

    def _request(
        self, method, path, *, params=None, payload=None, operation="read", allow_409=False
    ):
        mutation = method in {"POST", "PUT", "PATCH", "DELETE"}
        attempts = 1 if mutation else 3
        for attempt in range(attempts):
            try:
                response = self.session.request(
                    method,
                    f"{BASE_URL}{path}",
                    auth=self.auth,
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                    params=params,
                    json=payload,
                    timeout=(3.05, 20),
                    allow_redirects=False,
                )
            except (requests.Timeout, requests.ConnectionError) as error:
                if mutation:
                    raise ProviderTransientError("ambiguous_mutation") from error
                if attempt + 1 >= attempts:
                    raise ProviderUnavailableError("network_unavailable") from error
                time.sleep(0.05 * (2**attempt))
                continue
            if allow_409 and response.status_code == 409:
                return response, self._bounded_json(response)
            try:
                self._raise_status(response, operation)
            except (ProviderTransientError, ProviderUnavailableError):
                if mutation or attempt + 1 >= attempts:
                    raise
                retry_after = response.headers.get("Retry-After", "")
                delay = (
                    min(float(retry_after), 1.0) if retry_after.isdigit() else 0.05 * (2**attempt)
                )
                time.sleep(delay)
                continue
            return response, self._bounded_json(response)
        raise ProviderUnavailableError("provider_unavailable")

    def _document(self, link, kind="label"):
        parsed = urlsplit(link)
        if parsed.scheme != "https" or parsed.hostname != "panel.sendcloud.sc":
            raise ProviderValidationError("unsafe_document_url")
        try:
            wanted = (
                "application/zpl"
                if getattr(self.carrier, "mb_label_format", "") == "ZPL"
                else "application/pdf"
            )
            response = self.session.get(
                link,
                auth=self.auth,
                headers={"Accept": wanted},
                timeout=(3.05, 20),
                allow_redirects=False,
            )
        except (requests.Timeout, requests.ConnectionError) as error:
            raise ProviderUnavailableError("document_unavailable") from error
        self._raise_status(response, "document")
        if len(response.content) > DOCUMENT_LIMIT:
            raise ProviderUnavailableError("document_too_large")
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
        if content_type == "application/pdf" and response.content.startswith(b"%PDF-"):
            return ShipmentDocument(response.content, "PDF", kind, f"{kind}.pdf")
        if content_type in {"text/plain", "application/zpl"} and response.content.startswith(b"^"):
            return ShipmentDocument(response.content, "ZPL", kind, f"{kind}.zpl")
        if content_type == "image/png" and response.content.startswith(b"\x89PNG\r\n\x1a\n"):
            return ShipmentDocument(response.content, "PNG", kind, f"{kind}.png")
        raise ProviderValidationError("invalid_document")

    @staticmethod
    def _address(value):
        required = ("name", "street_name", "house_number", "zip", "city", "country_code")
        if any(not str(value.get(key) or "").strip() for key in required):
            raise ProviderValidationError("structured_address_required")
        return {
            "name": str(value["name"])[:255],
            "company_name": str(value.get("company") or "")[:255],
            "address_line_1": str(value["street_name"])[:255],
            "address_line_2": str(value.get("street2") or value.get("house_number_addition") or "")[
                :255
            ],
            "house_number": str(value["house_number"])[:32],
            "postal_code": str(value["zip"])[:32],
            "city": str(value["city"])[:128],
            "country_code": str(value["country_code"]).upper()[:2],
            "phone_number": str(value.get("phone") or "")[:64],
            "email": str(value.get("email") or "")[:254],
        }

    def _selected_sender(self, fallback):
        sender_id = int(getattr(self.carrier, "mb_sendcloud_sender_address_id", 0) or 0)
        if not sender_id:
            raise ProviderValidationError("sender_address_required")
        _, payload = self._request(
            "GET", f"/api/v3/addresses/sender-addresses/{sender_id}", operation="sender_address"
        )
        data = payload.get("data", payload)
        if not isinstance(data, dict) or str(data.get("id", sender_id)) != str(sender_id):
            raise ProviderValidationError("sender_address_mismatch")
        address = {
            "name": data.get("name") or fallback.get("name"),
            "company": data.get("company_name") or fallback.get("company"),
            "street_name": data.get("address_line_1") or data.get("street") or "",
            "house_number": data.get("house_number") or "",
            "house_number_addition": data.get("house_number_addition") or "",
            "street2": data.get("address_line_2") or "",
            "zip": data.get("postal_code") or "",
            "city": data.get("city") or "",
            "country_code": data.get("country_code") or "",
            "phone": data.get("phone_number") or "",
            "email": data.get("email") or "",
        }
        return self._address(address)

    def _dimensions(self, parcel):
        return {
            "length": parcel.length_cm
            or float(getattr(self.carrier, "mb_sendcloud_length_cm", 0) or 0),
            "width": parcel.width_cm
            or float(getattr(self.carrier, "mb_sendcloud_width_cm", 0) or 0),
            "height": parcel.height_cm
            or float(getattr(self.carrier, "mb_sendcloud_height_cm", 0) or 0),
            "unit": "cm",
        }

    def check_credentials(self):
        self._request("GET", "/api/v3/user/auth/metadata", operation="credentials")
        _, addresses = self._request(
            "GET",
            "/api/v3/addresses/sender-addresses",
            operation="sender_addresses",
        )
        data = addresses.get("data", addresses if isinstance(addresses, list) else [])
        sender_id = int(getattr(self.carrier, "mb_sendcloud_sender_address_id", 0) or 0)
        sender_valid = any(
            str(item.get("id")) == str(sender_id) for item in data if isinstance(item, dict)
        )
        service = getattr(self.carrier, "mb_provider_service_code", "") or ""
        return CredentialStatus(
            bool(sender_valid and service),
            "production" if self.production else "test",
            (service,) if service else (),
            "ready" if sender_valid and service else "sender_address_or_service_missing",
        )

    def list_services(self):
        code = getattr(self.carrier, "mb_provider_service_code", "") or ""
        return (
            [ShippingService(code, code, supports_pickup_points=True, supports_returns=True)]
            if code
            else []
        )

    def shipping_options(self, query):
        payload = {
            "from_address": self._selected_sender(query.sender),
            "to_address": self._address(query.recipient),
            "parcels": [
                {
                    "weight": {"value": parcel.weight_kg, "unit": "kg"},
                    "dimensions": self._dimensions(parcel),
                }
                for parcel in query.parcels
            ],
            "calculate_quotes": True,
        }
        carrier_code = getattr(self.carrier, "mb_sendcloud_carrier_code", "") or ""
        contract_id = int(getattr(self.carrier, "mb_sendcloud_contract_id", 0) or 0)
        if carrier_code:
            payload["carrier_code"] = carrier_code
        if contract_id:
            payload["contract_id"] = contract_id
        if query.service_code:
            payload["shipping_option_code"] = query.service_code
        if query.pickup_code:
            payload["to_service_point"] = {"id": int(query.pickup_code)}
        _, response = self._request(
            "POST", "/api/v3/shipping-options", payload=payload, operation="shipping_options"
        )
        options = response.get("data", response if isinstance(response, list) else [])
        result = []
        for item in options:
            if not isinstance(item, dict) or not item.get("code"):
                continue
            quotes = item.get("quotes") or []
            quote = quotes[0] if quotes and isinstance(quotes[0], dict) else {}
            price = (quote.get("price") or {}).get("total") or quote.get("price") or {}
            functionalities = item.get("functionalities") or {}
            requirements = item.get("requirements") or {}
            result.append(
                ShippingOption(
                    code=str(item["code"]),
                    name=str(item.get("name") or item["code"]),
                    carrier_code=str((item.get("carrier") or {}).get("code") or ""),
                    price=float(price.get("value") or 0),
                    currency=str(price.get("currency") or "EUR"),
                    supports_pickup_points=bool(
                        requirements.get("is_service_point_required")
                        or functionalities.get("last_mile") == "service_point"
                    ),
                    supports_returns=bool(functionalities.get("returns")),
                )
            )
        return result

    def search_pickup_points(self, query):
        params = {
            "country_code": query.country_code,
            "address_postal_code": query.zip,
            "address_city": query.city,
            "limit": min(max(query.limit, 1), 50),
        }
        carrier_code = getattr(self.carrier, "mb_sendcloud_carrier_code", "") or ""
        if carrier_code:
            params["carrier_code"] = [carrier_code]
        _, response = self._request(
            "GET", "/api/v3/service-points", params=params, operation="service_points"
        )
        data = response.get("data", response if isinstance(response, list) else [])
        points = data.get("results", []) if isinstance(data, dict) else data
        return [self._pickup_point(item) for item in points if isinstance(item, dict)]

    @staticmethod
    def _pickup_point(item):
        address = item.get("address") or item
        location = item.get("position") or item.get("location") or {}
        return PickupPoint(
            code=str(item.get("id") or item.get("code") or ""),
            name=str(item.get("name") or address.get("company_name") or "Service point"),
            street=" ".join(
                filter(
                    None,
                    (
                        str(address.get("street") or address.get("address_line_1") or "").strip(),
                        str(address.get("house_number") or "").strip(),
                    ),
                )
            ),
            zip=str(address.get("postal_code") or ""),
            city=str(address.get("city") or ""),
            country_code=str(address.get("country_code") or ""),
            latitude=float(location.get("latitude"))
            if location.get("latitude") is not None
            else None,
            longitude=float(location.get("longitude"))
            if location.get("longitude") is not None
            else None,
            opening_hours=item.get("opening_times") or item.get("opening_hours") or {},
        )

    def get_pickup_point(self, code, service_code="", query=None):
        if not str(code).isdigit():
            raise ProviderValidationError("invalid_service_point")
        _, response = self._request(
            "GET", f"/api/v3/service-points/{code}", operation="service_points"
        )
        return self._pickup_point(response.get("data", response))

    def _shipment_payload(self, request):
        parcel = request.parcels[0]
        service = request.service_code
        if not self.production and service != "sendcloud:letter":
            raise ProviderValidationError("test_mode_option_not_allowed")
        parcel_items = [
            {
                "item_id": str(item.get("product_id") or item.get("sku") or "item")[:64],
                "description": str(item.get("description") or "Goods")[:255],
                "quantity": item.get("quantity") or 1,
                "weight": {"value": item.get("weight_kg") or 0, "unit": "kg"},
                "price": {
                    "value": item.get("value") or 0,
                    "currency": item.get("currency") or "EUR",
                },
                "hs_code": item.get("hs_code") or None,
                "origin_country": item.get("origin_country") or None,
                "sku": item.get("sku") or None,
                "product_id": item.get("product_id") or None,
            }
            for item in request.items
        ]
        international = (
            request.sender.get("country_code") not in EU_COUNTRIES
            or request.recipient.get("country_code") not in EU_COUNTRIES
        )
        if international and (
            not parcel_items
            or any(
                not item.get("hs_code") or not item.get("origin_country") for item in parcel_items
            )
        ):
            raise ProviderValidationError("shipment_customs_data_required")
        payload = {
            "external_reference_id": request.idempotency_key,
            "order_number": request.metadata.get("picking") or request.idempotency_key,
            "from_address": self._selected_sender(request.sender),
            "to_address": self._address(request.recipient),
            "ship_with": {
                "type": "shipping_option_code",
                "properties": {"shipping_option_code": service},
            },
            "parcels": [
                {
                    "source_id": request.idempotency_key,
                    "weight": {"value": parcel.weight_kg, "unit": "kg"},
                    "dimensions": self._dimensions(parcel),
                    "parcel_items": parcel_items,
                }
            ],
            "label_details": {
                "mime_type": "application/zpl"
                if getattr(self.carrier, "mb_label_format", "") == "ZPL"
                else "application/pdf",
                "size": {"A4": "a4", "A5": "a5", "10x15": "a6", "ZPL": "a6"}.get(
                    getattr(self.carrier, "mb_label_format", "A4"), "a4"
                ),
            },
        }
        contract = int(getattr(self.carrier, "mb_sendcloud_contract_id", 0) or 0)
        if contract:
            payload["ship_with"]["properties"]["contract_id"] = contract
        if request.pickup_code:
            payload["to_service_point"] = {"id": int(request.pickup_code)}
        brand = int(getattr(self.carrier, "mb_sendcloud_brand_id", 0) or 0)
        if brand:
            payload["brand_id"] = brand
        return payload

    def _submission(self, payload, kind="label"):
        data = payload.get("data", payload)
        if not isinstance(data, dict):
            raise ProviderUnavailableError("invalid_shipment")
        provider_ref = str(data.get("id") or data.get("shipment_id") or data.get("return_id") or "")
        if not provider_ref:
            raise ProviderValidationError("shipment_reference_missing")
        parcels = data.get("parcels") or []
        if not parcels and data.get("parcel_id"):
            parcels = [{"id": data["parcel_id"]}]
        tracking_number = ""
        tracking_url = ""
        documents = []
        for parcel in parcels:
            tracking_number = tracking_number or str(parcel.get("tracking_number") or "")
            tracking_url = tracking_url or str(parcel.get("tracking_url") or "")
            document_entries = parcel.get("documents") or []
            if not document_entries and parcel.get("id"):
                document_entries = [
                    {"link": f"{BASE_URL}/api/v3/parcels/{parcel['id']}/documents/label"}
                ]
            for entry in document_entries:
                if entry.get("type", "label") == "label" and entry.get("link"):
                    try:
                        documents.append(self._document(entry["link"], kind=kind))
                    except (ProviderTransientError, ProviderUnavailableError):
                        # The paid mutation already succeeded. Persist its
                        # reference and let the read-only repair cron recover
                        # the document instead of replaying the purchase.
                        pass
        return ShipmentSubmission(
            provider_ref=provider_ref,
            state="complete" if documents else "pending",
            tracking_number=tracking_number,
            tracking_url=tracking_url,
            documents=tuple(documents),
            exact_price=float(((data.get("price") or {}).get("value") or 0)),
        )

    def create_shipment(self, request):
        response, payload = self._request(
            "POST",
            "/api/v3/shipments/announce",
            payload=self._shipment_payload(request),
            operation="create_shipment",
            allow_409=True,
        )
        if response.status_code == 409:
            associated = payload.get("data") or payload.get("shipment")
            if isinstance(associated, dict):
                return self._submission(associated)
            reconciled = self.reconcile_shipment(request)
            if reconciled:
                return reconciled
            raise ProviderTransientError("duplicate_requires_reconciliation")
        return self._submission(payload)

    def reconcile_shipment(self, request):
        _, payload = self._request(
            "GET",
            "/api/v3/shipments",
            params={"external_reference_id": request.idempotency_key},
            operation="shipment_lookup",
        )
        rows = payload.get("data", [])
        for row in rows if isinstance(rows, list) else []:
            if row.get("external_reference_id") == request.idempotency_key:
                return self._submission(row)
        return None

    def retrieve_document_submission(self, provider_ref, direction="outbound"):
        path = (
            f"/api/v3/returns/{provider_ref}"
            if direction == "return"
            else f"/api/v3/shipments/{provider_ref}"
        )
        _, payload = self._request(
            "GET",
            path,
            operation="return_lookup" if direction == "return" else "shipment_lookup",
        )
        if direction == "return":
            data = payload.get("data", payload)
            label = data.get("label") or {}
            link = (
                label.get("normal_printer") or label.get("label_printer") or data.get("label_url")
            )
            shaped = dict(data)
            shaped["id"] = provider_ref
            if link:
                shaped["parcels"] = [{"documents": [{"type": "label", "link": link}]}]
            return self._submission(shaped, kind="return_label")
        return self._submission(payload)

    def cancel_shipment(self, provider_ref):
        response, payload = self._request(
            "POST",
            f"/api/v3/shipments/{provider_ref}/cancel",
            operation="cancel_shipment",
            allow_409=True,
        )
        if response.status_code == 409:
            return CancellationResult("pending")
        status = str((payload.get("data") or {}).get("status") or "").lower()
        return CancellationResult(
            "pending" if response.status_code == 202 or status == "queued" else "confirmed"
        )

    def create_return_label(self, request):
        if not self.production:
            raise ProviderValidationError("returns_disabled_in_test_mode")
        parcel = request.parcels[0]
        items = []
        for item in request.items:
            items.append(
                {
                    "description": item.get("description"),
                    "quantity": item.get("quantity"),
                    "weight": {"value": item.get("weight_kg"), "unit": "kg"},
                    "value": {"value": item.get("value"), "currency": item.get("currency", "EUR")},
                    "hs_code": item.get("hs_code") or None,
                    "origin_country": item.get("origin_country") or None,
                    "sku": item.get("sku") or None,
                    "product_id": item.get("product_id") or None,
                }
            )
        payload = {
            "from_address": self._address(request.sender),
            "to_address": self._selected_sender(request.recipient),
            "ship_with": {
                "type": "shipping_option_code",
                "shipping_option_code": request.service_code,
            },
            "weight": {"value": parcel.weight_kg, "unit": "kg"},
            "dimensions": self._dimensions(parcel),
            "parcel_items": items,
            "order_number": request.metadata.get("picking") or request.idempotency_key,
            "external_reference": request.idempotency_key,
            "delivery_option": "drop_off_point",
            "send_tracking_emails": False,
        }
        contract = int(getattr(self.carrier, "mb_sendcloud_contract_id", 0) or 0)
        if contract:
            payload["ship_with"]["contract"] = contract
        brand = int(getattr(self.carrier, "mb_sendcloud_brand_id", 0) or 0)
        if brand:
            payload["brand_id"] = brand
        international = (
            request.sender.get("country_code") not in EU_COUNTRIES
            or request.recipient.get("country_code") not in EU_COUNTRIES
        )
        if international and (
            not items
            or any(not item.get("hs_code") or not item.get("origin_country") for item in items)
        ):
            raise ProviderValidationError("return_customs_data_required")
        response, result = self._request(
            "POST",
            "/api/v3/returns/announce-synchronously",
            payload=payload,
            operation="create_return",
        )
        if response.status_code != 201:
            raise ProviderValidationError("return_rejected")
        return self._submission(result, kind="return_label")

    def cancel_return(self, provider_ref):
        self._request("PATCH", f"/api/v3/returns/{provider_ref}/cancel", operation="cancel_return")
        return CancellationResult("pending")

    def reconcile_cancellation(self, provider_ref, direction="outbound"):
        path = (
            f"/api/v3/returns/{provider_ref}"
            if direction == "return"
            else f"/api/v3/shipments/{provider_ref}"
        )
        _, payload = self._request(
            "GET",
            path,
            operation="return_lookup" if direction == "return" else "shipment_lookup",
        )
        data = payload.get("data", payload)
        if direction == "return":
            history = data.get("status_history") or []
            latest = history[-1] if history else {}
            code = _status_key(
                latest.get("parent_status") or data.get("parent_status") or data.get("status")
            )
        else:
            statuses = [
                str((parcel.get("status") or {}).get("code") or "").upper()
                for parcel in data.get("parcels", [])
            ]
            code = statuses[0] if statuses and len(set(statuses)) == 1 else ""
        if code in TERMINAL_CANCELLED or code in {"CANCELLED", "CANCELLED_UPSTREAM"}:
            return CancellationResult("confirmed")
        if code in TERMINAL_CANCEL_REJECTED:
            return CancellationResult("rejected")
        return CancellationResult("pending")

    def retrieve_tracking(self, tracking_number="", provider_ref=""):
        if not tracking_number:
            if not provider_ref:
                raise ProviderValidationError("tracking_reference_missing")
            _, shipment = self._request(
                "GET", f"/api/v3/shipments/{provider_ref}", operation="shipment_lookup"
            )
            parcels = shipment.get("data", shipment).get("parcels", [])
            tracking_number = next(
                (str(p.get("tracking_number")) for p in parcels if p.get("tracking_number")), ""
            )
            if not tracking_number:
                raise ProviderTransientError("tracking_not_available_yet")
        _, payload = self._request(
            "GET", f"/api/v3/parcels/tracking/{tracking_number}", operation="tracking"
        )
        data = payload.get("data", payload)
        timeline = data.get("events") or data.get("timeline") or []
        events = tuple(
            TrackingEvent(
                status_code=str(
                    (item.get("status") or {}).get("code") or item.get("status_code") or ""
                ),
                category=_category(
                    (item.get("status") or {}).get("code") or item.get("status_code")
                ),
                message=str(
                    (item.get("status") or {}).get("message")
                    or item.get("status_description")
                    or item.get("message")
                    or ""
                )[:512],
                occurred_at=_parse_datetime(
                    item.get("event_at") or item.get("timestamp") or item.get("occurred_at")
                ),
            )
            for item in timeline[:50]
            if isinstance(item, dict)
        )
        latest = max(
            events,
            key=lambda event: event.occurred_at or datetime.min,
            default=None,
        )
        code = _status_key(latest.status_code if latest else data.get("parent_status") or "UNKNOWN")
        tracking = next(
            (
                item
                for item in data.get("tracking_numbers", [])
                if str(item.get("tracking_number") or "") == tracking_number
            ),
            {},
        )
        event_at = latest.occurred_at if latest else _parse_datetime(data.get("updated_at"))
        return TrackingSnapshot(
            status_code=code,
            category=_category(code),
            message=(latest.message if latest else "")[:512],
            tracking_number=tracking_number,
            tracking_url=str(
                tracking.get("tracking_url")
                or data.get("tracking_url")
                or data.get("tracking_page_url")
                or ""
            ),
            event_at=event_at,
            expected_delivery_at=_parse_datetime(
                (data.get("details") or {}).get("expected_delivery_date")
                or data.get("expected_delivery_date")
            ),
            events=events,
        )

    @staticmethod
    def verify_webhook(raw_body, headers, secret):
        signature = headers.get("Sendcloud-Signature", "")
        if not isinstance(signature, str) or not SIGNATURE.fullmatch(signature):
            return False
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature.lower())

    @staticmethod
    def parse_webhook(raw_body):
        try:
            payload = json.loads(raw_body)
        except (TypeError, ValueError) as error:
            raise ProviderValidationError("invalid_webhook_json") from error
        parcel = payload.get("parcel") or payload.get("data") or payload
        if not isinstance(parcel, dict):
            raise ProviderValidationError("invalid_webhook_payload")
        shipment = parcel.get("shipment") or {}
        timeline = parcel.get("events") or parcel.get("timeline") or []
        latest = max(
            (item for item in timeline if isinstance(item, dict)),
            key=lambda item: (
                _parse_datetime(
                    item.get("event_at") or item.get("timestamp") or item.get("occurred_at")
                )
                or datetime.min
            ),
            default={},
        )
        status = parcel.get("status") or {}
        code = _status_key(
            (latest.get("status") or {}).get("code")
            or latest.get("status_code")
            or status.get("code")
            or parcel.get("parent_status")
            or parcel.get("status_code")
            or "UNKNOWN"
        )
        tracking_entry = next(
            (item for item in parcel.get("tracking_numbers", []) if isinstance(item, dict)),
            {},
        )
        tracking_number = str(
            parcel.get("tracking_number") or tracking_entry.get("tracking_number") or ""
        )
        provider_ref = str(
            shipment.get("id")
            or parcel.get("shipment_id")
            or parcel.get("return_id")
            or parcel.get("source_id")
            or tracking_number
        )
        if not provider_ref:
            raise ProviderValidationError("webhook_reference_missing")
        return ProviderWebhookEvent(
            event_id=str(payload.get("id") or payload.get("event_id") or ""),
            provider_ref=provider_ref,
            kind="tracking",
            tracking_number=tracking_number,
            tracking_url=str(
                parcel.get("tracking_url") or tracking_entry.get("tracking_url") or ""
            ),
            occurred_at=str(
                latest.get("event_at")
                or latest.get("timestamp")
                or payload.get("timestamp")
                or parcel.get("updated_at")
                or ""
            ),
            status_code=code,
            status_category=_category(code),
            status_message=str(
                (latest.get("status") or {}).get("message")
                or latest.get("status_description")
                or status.get("message")
                or ""
            )[:512],
        )

    def fetch_webhook_document(self, event):
        if not event.document_ref:
            raise ProviderValidationError("document_reference_missing")
        return self._document(event.document_ref)

    def build_manifest(self, provider_refs):
        raise ProviderValidationError("manifest_not_supported")

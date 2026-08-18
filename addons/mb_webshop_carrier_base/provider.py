"""Database-independent contract shared by shipping provider addons."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, Literal, Protocol


class ProviderError(Exception):
    """Base class for bounded, merchant-safe provider failures."""


class ProviderAuthError(ProviderError):
    pass


class ProviderValidationError(ProviderError):
    pass


class ProviderTransientError(ProviderError):
    pass


class ProviderUnavailableError(ProviderError):
    pass


@dataclass(frozen=True, slots=True)
class CredentialStatus:
    valid: bool
    environment: Literal["test", "production"]
    service_codes: tuple[str, ...] = ()
    message: str = ""


@dataclass(frozen=True, slots=True)
class ShippingService:
    code: str
    name: str
    supports_pickup_points: bool = False
    supports_returns: bool = False
    supports_manifest: bool = False


@dataclass(frozen=True, slots=True)
class ShippingOptionQuery:
    sender: dict[str, Any]
    recipient: dict[str, Any]
    parcels: tuple["Parcel", ...]
    service_code: str = ""
    pickup_code: str = ""


@dataclass(frozen=True, slots=True)
class ShippingOption:
    code: str
    name: str
    carrier_code: str = ""
    price: float = 0
    currency: str = "EUR"
    supports_pickup_points: bool = False
    supports_returns: bool = False


@dataclass(frozen=True, slots=True)
class OperationSafety:
    native_idempotency: bool = False
    reconciliation_lookup: bool = False
    automatic_retry: bool = False


@dataclass(frozen=True, slots=True)
class PickupQuery:
    country_code: str
    zip: str
    city: str = ""
    service_code: str = ""
    limit: int = 20


@dataclass(frozen=True, slots=True)
class PickupPoint:
    code: str
    name: str
    street: str
    zip: str
    city: str
    country_code: str
    latitude: float | None = None
    longitude: float | None = None
    distance_m: int | None = None
    opening_hours: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Parcel:
    weight_kg: float
    length_cm: float = 0
    width_cm: float = 0
    height_cm: float = 0
    value: float = 0
    currency: str = "EUR"


@dataclass(frozen=True, slots=True)
class ShipmentRequest:
    idempotency_key: str
    service_code: str
    sender: dict[str, Any]
    recipient: dict[str, Any]
    parcels: tuple[Parcel, ...]
    pickup_code: str = ""
    provider_ref: str = ""
    metadata: dict[str, str] = field(default_factory=dict)
    items: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class ShipmentDocument:
    content: bytes
    format: Literal["PDF", "ZPL", "PNG"]
    kind: Literal["label", "return_label", "manifest"] = "label"
    filename: str = "label.pdf"


@dataclass(frozen=True, slots=True)
class ShipmentSubmission:
    provider_ref: str
    state: Literal["complete", "pending"]
    tracking_number: str = ""
    tracking_url: str = ""
    documents: tuple[ShipmentDocument, ...] = ()
    exact_price: float = 0


@dataclass(frozen=True, slots=True)
class ManifestResult:
    provider_ref: str
    document: ShipmentDocument


@dataclass(frozen=True, slots=True)
class CancellationResult:
    state: Literal["confirmed", "pending", "rejected"]
    message: str = ""


@dataclass(frozen=True, slots=True)
class TrackingEvent:
    status_code: str
    category: str
    message: str = ""
    occurred_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class TrackingSnapshot:
    status_code: str
    category: Literal[
        "pre_transit",
        "in_transit",
        "at_service_point",
        "out_for_delivery",
        "delivered",
        "exception",
        "returning",
        "returned",
        "cancelled",
        "unknown",
    ]
    message: str = ""
    tracking_number: str = ""
    tracking_url: str = ""
    event_at: datetime | None = None
    expected_delivery_at: datetime | None = None
    events: tuple[TrackingEvent, ...] = ()


@dataclass(frozen=True, slots=True)
class ProviderWebhookEvent:
    event_id: str
    provider_ref: str
    kind: Literal["document", "tracking"]
    tracking_number: str = ""
    tracking_url: str = ""
    document_ref: str = ""
    occurred_at: str = ""
    status_code: str = ""
    status_category: str = ""
    status_message: str = ""


class ShippingProvider(Protocol):
    code: ClassVar[str]
    supports_pickup_points: ClassVar[bool]
    supports_own_contract: ClassVar[bool]
    supports_manifest: ClassVar[bool]
    supports_return_label: ClassVar[bool]
    supports_tracking_lookup: ClassVar[bool]
    supports_contextual_options: ClassVar[bool]

    def check_credentials(self) -> CredentialStatus: ...
    def list_services(self) -> list[ShippingService]: ...
    def shipping_options(self, query: ShippingOptionQuery) -> list[ShippingOption]: ...
    def operation_safety(self, operation: str) -> OperationSafety: ...
    def search_pickup_points(self, query: PickupQuery) -> list[PickupPoint]: ...
    def get_pickup_point(
        self, code: str, service_code: str = "", query: PickupQuery | None = None
    ) -> PickupPoint: ...
    def create_shipment(self, req: ShipmentRequest) -> ShipmentSubmission: ...
    def reconcile_shipment(self, req: ShipmentRequest) -> ShipmentSubmission | None: ...
    def cancel_shipment(self, provider_ref: str) -> CancellationResult | None: ...
    def reconcile_cancellation(
        self, provider_ref: str, direction: str = "outbound"
    ) -> CancellationResult: ...
    def create_return_label(self, req: ShipmentRequest) -> ShipmentSubmission: ...
    def build_manifest(self, provider_refs: list[str]) -> ManifestResult: ...
    def verify_webhook(self, raw_body: bytes, headers: Any, secret: str) -> bool: ...
    def parse_webhook(self, raw_body: bytes) -> ProviderWebhookEvent: ...
    def fetch_webhook_document(self, event: ProviderWebhookEvent) -> ShipmentDocument: ...
    def retrieve_tracking(
        self, tracking_number: str = "", provider_ref: str = ""
    ) -> TrackingSnapshot: ...
    def retrieve_document_submission(
        self, provider_ref: str, direction: str = "outbound"
    ) -> ShipmentSubmission: ...


def operation_safety(provider: ShippingProvider | type[ShippingProvider], operation: str) -> OperationSafety:
    """Return per-operation mutation guarantees with a legacy-safe fallback.

    Existing adapters keep their old behavior while they migrate, but return
    creation never inherits an outbound provider-wide idempotency declaration.
    """
    resolver = getattr(provider, "operation_safety", None)
    if resolver:
        return resolver(operation)
    if operation == "create_shipment":
        idempotent = bool(getattr(provider, "supports_idempotency", False))
        reconcilable = bool(getattr(provider, "supports_reconciliation", False))
        return OperationSafety(idempotent, reconcilable, idempotent)
    return OperationSafety()


_REGISTRY: dict[str, type[ShippingProvider]] = {}


def register_provider(provider_class: type[ShippingProvider]) -> type[ShippingProvider]:
    code = getattr(provider_class, "code", "")
    if not code or not code.replace("_", "").isalnum():
        raise ValueError("shipping provider code must be a bounded identifier")
    current = _REGISTRY.get(code)
    if current is not None and current is not provider_class:
        raise ValueError(f"shipping provider {code!r} is already registered")
    _REGISTRY[code] = provider_class
    return provider_class


def provider_class(code: str) -> type[ShippingProvider]:
    try:
        return _REGISTRY[code]
    except KeyError as error:
        raise ProviderValidationError(f"shipping provider {code!r} is unavailable") from error

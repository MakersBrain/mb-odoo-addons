# MakersBrain Webshop Carrier Module Plan

**Project:** MakersBrain on Odoo 19 Community
**Status:** Implemented for phases 1–4; external Boxtal production qualification remains gated on a merchant test/production account
**Date:** 16 August 2026
**Companion:** `makersbrain-webshop-domain-email-plan.md` sections 1.2, 6 and 12

## 1. Goal

Give a French artisan the shipping experience a WooCommerce merchant gets from
WCMultiShipping: pick a relay point in checkout, buy a label from the order,
hand the customer a tracking link, and print a handover slip at the end of the
day. For the carriers that matter in France — Mondial Relay, Colissimo and
Chronopost — plus the relay networks an aggregator brings along for free
(Colis Privé, Relais Colis).

The first shipping provider is **Boxtal**, an aggregator. The reasons are in
section 3, and they are commercial rather than technical: a one-person workshop
cannot get a Chronopost contract, may not get Colissimo API access, and cannot
justify a monthly shipping-software subscription.

But a workshop that grows will eventually want its own carrier contracts, and
Boxtal does not let a merchant bring one. So the module must not be a Boxtal
module with a Boxtal-shaped hole in the middle of it. It is a **provider-agnostic
shipping runtime with Boxtal as its first implementation**, and direct carriers
and other aggregators as later ones against the same seam.

## 2. What Odoo 19 Community already provides

Verified against the `odoo:19` image in this repository.

| Capability | Where | State |
|---|---|---|
| Carrier model, price rules, zip-prefix/weight/volume/tag availability, cash on delivery | `delivery` | Complete, reuse as-is |
| Provider dispatch protocol | `stock_delivery/models/delivery_carrier.py:35-100` | Complete |
| Label attachment, tracking ref, return labels, cancellation on pickings | `stock_delivery/models/stock_picking.py` | Complete |
| Mondial Relay Point Relais widget, backend and checkout | `delivery_mondialrelay`, `website_sale_mondialrelay` | Widget only |
| Mondial Relay label / expedition WebService | — | **Absent by design** |
| Colissimo, Chronopost, any aggregator | — | **Absent** |

The dispatch protocol is the seam everything hangs off. `rate_shipment`,
`send_shipping`, `cancel_shipment`, `get_tracking_link`, `get_return_label` and
`_get_default_custom_package_code` resolve provider methods by name from the
carrier's `delivery_type` where the capability applies:

```python
# stock_delivery/models/delivery_carrier.py:50
if hasattr(self, '%s_send_shipping' % self.delivery_type):
    return getattr(self, '%s_send_shipping' % self.delivery_type)(pickings)
```

So a shipping addon adds one `delivery_type` selection value and the applicable
dispatch methods. Rating, checkout, picking validation and portal tracking are
already wired.

`delivery_mondialrelay`'s manifest states its own limit plainly: *"This module
doesn't implement the WebService. It is only the integration of the widget."*
It ships carriers at `integration_level='rate'` with `delivery_type='base_on_rule'`,
identified by `product_id.default_code == "MR"` rather than by a delivery type
(`delivery_mondialrelay/models/delivery_carrier.py:16`).

### 2.1 The reusable pickup-point pattern

`delivery_mondialrelay` and `website_sale_mondialrelay` together implement a
pickup-point pattern that generalises to every relay carrier, and which the base
addon should lift rather than reinvent:

| Concern | Odoo's Mondial Relay implementation |
|---|---|
| Relay stored as an address | child `res.partner`, `type='delivery'`, `ref='MR#<id>'`, found or created by `_mondialrelay_search_or_create` |
| Relay address is immutable | `_can_be_edited_by_current_customer` returns False; `_prepare_address_update` raises |
| Carrier/address must agree | `sale_order.action_confirm` raises on mismatch; `_check_cart_is_ready_to_be_paid` raises in the webshop |
| Stale relay cleared on carrier change | `_compute_partner_shipping_id` override |
| Checkout affordance | `data-is-mondialrelay` on the delivery radio plus a frontend interaction |
| Tracking link | `base_on_rule_get_tracking_link` override |

## 3. Why Boxtal is the primary provider

| | Boxtal | Sendcloud | Direct carrier contracts |
|---|---|---|---|
| Fixed cost per tenant | €0 — no subscription, no label fee, no volume floor | Free plan per-label; Lite €35/mo, Growth €109/mo | €0, but see onboarding |
| Onboarding | Self-service signup; API orders additionally require an API application, a separate test account and deferred direct debit | Self-service signup, minutes | Mondial Relay days; Colissimo 1–3 weeks with a sales call; Chronopost 2–6 weeks and likely declined at artisan volume |
| Carriers from one integration | Mondial Relay, Colissimo, Chronopost, Colis Privé, Relais Colis, DPD, UPS, DHL, FedEx, TNT | 160+ across Europe | One per integration |
| Merchant's own contracts | Not supported | Supported | The whole point |
| Rates at artisan volume | Pooled negotiated, typically far better than list | Pooled negotiated | List price, since the artisan has no volume history |

Indicative 2026 rates through an aggregator: Mondial Relay under 500g around
€3–4, Colissimo 2kg around €6–8, Chronopost J+1 1kg around €10–14. Colissimo
raised list prices 1.8% and Colis Privé 2.8% on 1 January 2026.

For the tenant this product targets, the decisive number is the fixed cost.
Sendcloud's €35/month Lite floor exceeds what a workshop shipping ten parcels a
month spends on shipping in total. Boxtal is genuinely €0 until a label is
bought, but account and payment readiness must be proven before onboarding is
complete.

The direct-carrier path is not abandoned — it is the growth tier, and section 8
keeps its specification. Mondial Relay direct in particular stays attractive
because Odoo already ships the checkout half.

## 4. Architecture

```
mb_webshop
    └── mb_webshop_carrier_base          provider-agnostic runtime + registry
            ├── mb_webshop_carrier_boxtal            (primary, v1)
            ├── mb_webshop_carrier_sendcloud         (later, own-contract tenants)
            ├── mb_webshop_carrier_mondialrelay      (later, direct)
            ├── mb_webshop_carrier_colissimo         (later, direct, gated on §9.2)
            └── mb_webshop_carrier_chronopost        (later, direct)
```

The webshop plan forbids "an empty generic wrapper around Odoo `delivery`"
(`makersbrain-webshop-domain-email-plan.md:164`), and that prohibition still
stands. The base addon is not that. It adds nothing that `delivery` already
does — no rate engine, no carrier selection, no shipment state machine. It owns
only what every provider implementation would otherwise copy: an authenticated
HTTP client with redacted logging, a durable shipment journal with
provider-aware duplicate prevention, label storage as attachments, the
pickup-point partner pattern, and one checkout picker.

The generic seam is justified by having more than one real implementation on
the roadmap and by the certainty that at least one tenant will need to leave
Boxtal. A seam with one implementation and no second in sight would be
speculative; this one is not.

### 4.1 `mb_webshop_carrier_base`

**The provider interface.** Plain Python, not Odoo models, so it is testable
without a database:

```python
class ShippingProvider(Protocol):
    code: str                      # 'boxtal', 'sendcloud', 'mondialrelay', ...
    supports_pickup_points: bool
    supports_own_contract: bool    # merchant may bring their own carrier contract
    supports_manifest: bool
    supports_return_label: bool

    def check_credentials(self) -> CredentialStatus: ...
    def list_services(self) -> list[ShippingService]: ...
    def search_pickup_points(self, query: PickupQuery) -> list[PickupPoint]: ...
    def get_pickup_point(self, code: str) -> PickupPoint: ...
    def create_shipment(self, req: ShipmentRequest) -> ShipmentSubmission: ...
    def cancel_shipment(self, provider_ref: str) -> None: ...
    def create_return_label(self, req: ShipmentRequest) -> ShipmentSubmission: ...
    def build_manifest(self, provider_refs: list[str]) -> ManifestResult: ...
```

Supporting dataclasses — `PickupQuery`, `PickupPoint`, `ShipmentRequest`,
`Parcel`, `ShipmentSubmission`, `ShipmentDocument`, `ManifestResult` — and a
typed error hierarchy. `ShipmentSubmission` always carries the provider's order
reference and declares whether documents and tracking are available immediately
or will arrive asynchronously. A synchronous provider may include documents and
tracking in the submission; an asynchronous one returns `state='pending'` and
completes the shipment through authenticated webhook events. The error hierarchy:
`ProviderAuthError`, `ProviderValidationError` (never retried),
`ProviderTransientError` (eligible for bounded retry subject to the operation's
idempotency policy), `ProviderUnavailableError`. The error type determines
retry behaviour and the merchant-facing message; a provider that
raises the wrong one is a bug the fixture tests must catch.

Optional capabilities are declared by flag, not discovered by exception. A
provider without pickup points simply reports `supports_pickup_points = False`
and the checkout picker never appears.

**Registry.** `delivery.carrier` gains `mb_provider_code`; each addon registers
its class at import. The base resolves the provider, obtains short-lived
credentials through the carrier's secret reference, constructs the provider,
and runs the shared work around it. Secret values never become stored model
fields or request-log values.

**Models**

- `mb.carrier.pickup.point` — cached relay search results per (carrier, zip,
  service) with a short TTL, so a customer changing their mind in checkout does
  not re-hit the provider on every keystroke. Fields: `company_id`, `carrier_id`,
  `provider_code`, `service_code`, `query_zip`, `code`, `name`, `street`, `zip`,
  `city`, `country_id`, `latitude`, `longitude`, `opening_hours` (JSON),
  `distance_m`, `fetched_at`. Cache uniqueness includes the carrier account and
  service; results from two credentials or services must never be mixed.
- `res.partner` extension — generalises Odoo's `MR#` convention to
  `mb_pickup_ref` and `mb_pickup_provider`, keeping `is_mondialrelay` working
  for core compatibility. The immutability and address-update guards apply to
  every pickup partner, not just Mondial Relay's.
- `delivery.carrier` extension — `mb_provider_code`, `mb_provider_service_code`,
  `mb_credential_state` (`unconfigured` / `test` / `production`),
  `mb_label_format` (`A4` / `A5` / `10x15` / `ZPL`), `mb_secret_ref`,
  `mb_last_error`. `mb_secret_ref` is an opaque reference; provider credentials
  are not columns in the tenant database.
- `mb.carrier.shipment` — the durable local-to-provider mapping, one row per
  parcel or return parcel. Fields: `company_id`, `carrier_id`, `picking_id`,
  `direction`, `parcel_index`, `idempotency_key`, `state` (`draft`, `submitting`,
  `awaiting_document`, `label_ready`, `cancelled`, `failed`, `unknown`),
  `provider_ref`, `tracking_number`, materialized `tracking_url`, `last_error`,
  label/document attachments and timestamps. SQL uniqueness on
  `(carrier_id, idempotency_key)` serialises
  duplicate button presses and workers. This is an integration journal, not a
  replacement for `stock.picking`; the picking remains the fulfilment state
  machine.
- `mb.carrier.webhook.event` — company-scoped durable webhook inbox keyed by
  provider, opaque subscription id and provider event id (or a canonical payload
  digest when the provider supplies no event id). It records receipt and
  processing state so the HTTP request can acknowledge promptly and processing
  can be retried safely.
- `mb.carrier.request.log` — one row per outbound call: provider, operation,
  shipment/picking, HTTP status, duration, privacy-sanitized diagnostic summary,
  correlation id. Authentication material, labels and customer address/contact
  fields are never stored. 90-day retention, company-scoped,
  `base.group_system` read. This is what makes a support ticket answerable;
  without it every shipping failure is a mystery.
- `mb.carrier.manifest` — end-of-day handover slip: provider, date, pickings,
  provider-side manifest reference, generated PDF.

**Shared runtime around the provider**

- `CarrierClient` — requests-based transport, per-provider timeout, bounded
  retry on read-only calls and on mutation calls only when the provider documents
  an idempotency key. Credential redaction is mandatory before anything reaches
  the log. An ambiguous mutation timeout is never blindly replayed.
- Idempotency — label purchase runs as a queued operation after the
  `mb.carrier.shipment` row has committed. The worker locks the row, records
  `submitting`, and sends its stable key as the provider idempotency/client
  reference where supported. On an ambiguous timeout it records `unknown` and
  reconciles by that client reference or provider lookup before permitting a new
  purchase. A provider with neither native idempotency nor a reconciliation
  lookup must require explicit merchant resolution; it cannot claim automatic
  retry safety.
- `LabelStore` — writes documents as `ir.attachment` records on the picking.
  Outbound labels use `_get_delivery_label_prefix()`; return labels alone use
  `get_return_label_prefix()`. Portal access tokens are generated only for
  return-label attachments when `get_return_label_from_portal` is enabled.

**Carrier mixin.** Because Odoo dispatches by `delivery_type`, each addon still
declares its own type, but the method bodies are trivial:

```python
class DeliveryCarrier(models.Model):
    _inherit = 'delivery.carrier'

    delivery_type = fields.Selection(selection_add=[('mb_boxtal', "Boxtal")],
                                     ondelete={'mb_boxtal': 'set default'})

    def mb_boxtal_send_shipping(self, pickings):
        return self._mb_send_shipping(pickings)          # base does the work
    def mb_boxtal_cancel_shipment(self, pickings):
        return self._mb_cancel_shipment(pickings)
    def mb_boxtal_get_tracking_link(self, picking):
        return self._mb_get_tracking_link(picking)
    def mb_boxtal_rate_shipment(self, order):
        return self.base_on_rule_rate_shipment(order)    # native price rules
```

Rating delegates to `base_on_rule_rate_shipment` so merchants keep the native
weight and price-rule editor. Live provider-quoted rates are a v2 item; the
interface has room for them (`list_services`) but v1 does not call for them at
checkout, where a synchronous provider round-trip is a latency risk.

Provider mutations are queued, including for providers that can respond
synchronously. `_mb_send_shipping` creates the shipment journal row in the
current Odoo transaction and returns the Odoo dispatch shape with the configured
estimated price and no tracking number. The worker cannot see or act on that row
until the outer Odoo transaction commits; it then purchases the shipment and
attaches an immediate document or records `awaiting_document`, and updates
`carrier_tracking_ref` when tracking becomes available. The merchant UI shows
the pending/failed/unknown state and enables printing only at `label_ready`.
Because native `stock.picking.send_to_shipper` assumes synchronous completion
and posts a "shipment sent" message immediately, the base overrides it only for
`mb_*` carriers: it queues the journal row, posts "label purchase queued", and
lets the worker post the eventual success or failure. Non-MakersBrain carriers
continue through `super()` unchanged.
Cancellation cannot use Odoo's unmodified optimistic clearing behaviour: the
base picking override keeps the tracking reference until the provider confirms
cancellation and exposes retry/reconciliation for ambiguous outcomes.

**Frontend.** One provider-agnostic pickup picker (map plus list, keyboard
accessible) behind a `/mb_carrier/pickup_points` JSON route that returns
`PickupPoint` records whatever the provider. Where a provider mandates its own
hosted widget — Mondial Relay direct does — that addon overrides the picker.
The route derives company, carrier and service from the caller's current cart;
it never accepts those as trusted browser input. It requires an owned website
cart, applies per-session and per-IP rate limits, bounds radius/result count,
and returns only the minimum public fields. Point selection accepts a point code
rather than a partner id, re-resolves it for the selected carrier/service, and
creates or selects the immutable delivery partner server-side. Readiness is
checked again before payment and before label purchase, so a forged, stale or
closed point cannot be shipped.

### 4.2 What stays out of the base

No rate abstraction beyond `list_services`. No carrier-selection engine. No
duplicate fulfilment state machine beyond `stock.picking`: the shipment journal
tracks only the external purchase/document lifecycle. No customs documents
(CN23) in v1. If only one provider ever needs a thing, it lives in that
provider's addon.

## 5. `mb_webshop_carrier_boxtal`

### 5.1 Verified integration surface

| Item | Value |
|---|---|
| Public API base | `https://api.boxtal.com/shipping` (confirm the exact versioned path from the current OpenAPI document during phase 0) |
| Sandbox | `https://api.boxtal.build/shipping`; a separate test account and test credentials are required |
| v3 authentication | HTTP Basic with application access key + secret key, or a bearer token obtained from the authentication endpoint |
| v1 authentication | HTTP basic with account login/password; still used for rate quotes |
| v3 scope | Order/cancel; shipping documents and tracking are delivered asynchronously through subscribed webhook events |
| Identity stack | Keycloak at `iam.boxtal.com`, realm `boxtal-customer`, advertising `authorization_code` (PKCE) and `client_credentials` |
| Merchant admin | `shipping.boxtal.com` |
| Carriers | Mondial Relay, Colissimo, Chronopost, Colis Privé, Relais Colis, DPD, UPS, DHL Express, FedEx, TNT, Delivengo, Happy-Post |
| Pickup points | Boxtal parcel-point map plus API |
| Commercial terms | No subscription, no label fee, no volume condition; Boxtal's negotiated rates only. API order placement requires the account to be configured for deferred payment by direct debit |

### 5.2 Tracking by webhook

Boxtal delivers shipping documents and tracking by webhook rather than in the
order response. The base addon hosts a generic public endpoint such as
`/mb_carrier/webhook/<provider_code>/<opaque_subscription_id>`; the path value is
an identifier, never an authentication secret. Each subscription has a webhook
validation secret in the external secret store. For Boxtal, the controller must
verify `x-bxt-signature` as HMAC-SHA256 over the exact raw request body using a
constant-time comparison before parsing JSON. Unsigned or invalid events are
rejected.

The HTTP path does no carrier business processing: after authentication it
parses only an allowlisted event envelope, inserts the deduplicated
`mb.carrier.webhook.event` inbox row and returns 2xx within Boxtal's two-second
deadline. The raw body is used for signature verification and digesting, then
discarded; only the minimum normalized event fields needed by the worker are
stored, with bounded retention. A worker correlates the event through the durable
`provider_ref`, downloads and validates the document, updates tracking, and
attaches the label. Provider event id is the replay key when present; otherwise
the canonical payload digest is used. Raw bodies and secrets are excluded from
normal logs, and the opaque subscription id is safe to appear in proxy logs.
Subscription creation and reconciliation are part of onboarding; health checks
warn before or when Boxtal disables a failing subscription.

This is the one piece of infrastructure Boxtal needs that a direct carrier does
not, and it is worth building generically because Sendcloud works the same way.

### 5.3 Onboarding

Assume, until Boxtal says otherwise (section 9.1), that this is manual:

1. The artisan signs up at boxtal.com — self-service, no volume condition — and
   configures deferred payment by direct debit, which API order placement
   requires.
2. They create an API v3 application and generate its access key and secret key.
3. They enter the pair once in MakersBrain. The control plane writes it directly
   to the tenant-scoped external secret store and returns only `mb_secret_ref` to
   Odoo; neither value is persisted in the tenant database or echoed back.
4. MakersBrain calls `check_credentials`, registers/reconciles the signed webhook
   subscriptions, stores the non-secret `mb_credential_state`, and shows the
   merchant which carriers and services their account has.

One settings screen and a "test connection" button. Production readiness means
authentication succeeds, deferred payment is enabled, at least one configured
service is usable, and both document and tracking subscriptions are active. If
Boxtal will register MakersBrain as an OIDC client in the `boxtal-customer`
realm, steps 2 and 3 collapse into an authorisation redirect; the resulting
refresh credential still lives in the external secret store, so this is an
upgrade rather than a rewrite.

## 6. Provider fit against the interface

Recorded so the seam is designed against real requirements rather than one
provider's shape.

| Interface element | Boxtal | Sendcloud | Mondial Relay direct | Colissimo direct | Chronopost direct |
|---|---|---|---|---|---|
| Auth | application access key + secret via HTTP Basic, or bearer token | API key pair | Brand/marque/private key, MD5 signature (v1) or API V2 credentials | Contract number + password | Account number + Chronotrace password |
| Pickup points | Boxtal map + API | Service Points API | Hosted widget, mandated | `findRDVPointRetraitAcheminement` | `recherchePointChronopost` |
| Label transport | document-ready webhook, followed by document retrieval | REST JSON | REST/legacy, PDF by URL | MTOM multipart — PDF as a MIME part | SOAP-first |
| Tracking | Webhook | Webhook | Poll or tracking URL | Poll | Poll |
| Own contract | No | Yes | n/a | n/a | n/a |
| Manifest | **Unverified API capability; phase 0 gate** | Yes | Yes | Yes | Yes |

Two consequences for the interface. A completed `ShipmentSubmission` or later
document event yields `ShipmentDocument` objects containing bytes plus a
declared format, never a provider URL. Mondial Relay's URL and Colissimo's MIME
part are downloaded/decoded at the provider boundary, while Boxtal's pending
submission is completed by its document event; `LabelStore` therefore receives
the same object in every case. And `search_pickup_points` takes a service code
in `PickupQuery`, because Chronopost's relay search requires the product code
before it will return points.

## 7. Configuration and credentials

Credential ownership is per `delivery.carrier`, not per `res.company`: a
workshop can legitimately hold a production and a test Boxtal application, or
two Chronopost sub-accounts. Secret values nevertheless remain outside the
tenant database, as required by the companion webshop security plan.

- `delivery.carrier.mb_secret_ref` is an opaque, non-secret identifier with
  `groups="base.group_system"` and `copy=False`. It is safe in a tenant backup
  because it is useless without both control-plane authorisation and access to
  the tenant-scoped secret store.
- The control plane accepts credentials over an authenticated, audited settings
  operation and writes them directly to its existing secret-delivery mechanism.
  Odoo receives credentials only in memory for the bounded provider operation;
  values are never returned by a read endpoint, stored in request logs, chatter,
  exception text or tracing attributes.
- Secret resolution enforces tenant, company, carrier and environment identity;
  one tenant cannot present another tenant's reference. Rotation replaces the
  secret version behind the reference and records an audit event.
- Module disable/reinstall removes or suspends the reference without deleting
  historical shipments. Tenant erasure deletes the external secret through the
  existing lifecycle workflow.
- `data/neutralize.sql` clears `mb_secret_ref`, disables webhook subscriptions
  and sets carriers to test/unconfigured. Thus a restored production backup
  cannot resolve production credentials or buy real labels from staging.

Odoo's existing `prod_environment` boolean selects test versus production per
carrier. For Boxtal the API bases are `https://api.boxtal.build/shipping` and
`https://api.boxtal.com/shipping`; credentials from one environment do not work
in the other.

## 8. Direct carrier specifications (growth tier)

Retained so the later addons are specified rather than re-researched. Every
endpoint must be re-confirmed against the technical documentation delivered with
the actual contract — carriers version these per contract and the public PDFs
lag.

### 8.1 Mondial Relay

Credentials: API V2 (Brand ID API, Login API, API password) from
`connect.mondialrelay.com` → Administration → Configuration des API; or legacy
WSI2 (Code Enseigne, Code Marque, Clé privée, MD5 signature) under Mon profil →
Mes paramètres de connexion. Test brand `BDTEST  ` (two trailing spaces), already
Odoo's default. Delivery modes `24R` relay, `24L` home, `LD1`/`LDS` bulky.

**The one place this design bends to core.** Odoo identifies Mondial Relay
carriers by `product_id.default_code == 'MR'` and types them `base_on_rule`;
both the checkout widget and `_check_cart_is_ready_to_be_paid` key off
`is_mondialrelay`. Giving those records a new `delivery_type` would buy labels
correctly and silently break the relay picker. So this addon overrides
`base_on_rule_send_shipping` and dispatches on `is_mondialrelay`, exactly as
core already does for `base_on_rule_get_tracking_link` — with a test that fails
loudly if core changes the identification rule.

### 8.2 Colissimo

Credentials: contract number + password, the same pair that signs in to
`colissimo.fr/entreprise`. Label REST
`https://ws.colissimo.fr/sls-ws/SlsServiceWSRest/2.0/generateLabel`; SOAP
`https://ws.colissimo.fr/sls-ws/SlsServiceWS?wsdl`. Pickup points
`https://ws.colissimo.fr/pointretrait-ws-cxf/rest/v2/pointretrait/findRDVPointRetraitAcheminement`,
detail by `findPointRetraitAcheminementByID`. Products `DOM` (home, signature),
`DOS` (home, no signature), `BPR` (bureau de poste), `A2P` (relay/consigne),
`CDI` (international).

The response is MTOM: the PDF arrives as a MIME part, not base64 in JSON. The
multipart parser is real work. A pickup point must also be re-resolved at label
time, since a point can close between checkout and shipping; the base picker
stores the point code and re-resolves in `create_shipment`, failing with a clear
merchant message rather than shipping to a closed point.

### 8.3 Chronopost

Credentials: account number + Chronotrace password, usually a dedicated
sub-account per site. Label
`https://ws.chronopost.fr/shipping-cxf/ShippingServiceWS?wsdl`,
`shippingMultiParcelV2` for multi-parcel. Relay search
`https://ws.chronopost.fr/recherchebt-ws-cxf/PointRelaisServiceWS/recherchePointChronopost`,
detail `rechercheDetailPointChronopost`, taking accountNumber, password,
address, zipCode, city, countryCode, type, productCode, service, weight,
shippingDate, maxPointChronopost, maxDistanceSearch, holidayTolerant, language.
Products `13` Chrono 13, `16` Chrono 18/10h, `18` Chrono Classic, `86` Chrono
Relais, `2P` Shop2Shop.

Heaviest of the three: SOAP-first, a large product/service matrix, and a relay
search that needs the product code up front. Shop2Shop is a consumer
relay-to-relay service on a different commercial footing from merchant Chrono
Relais; confirm which the contract covers before building against `2P`.

## 9. Where to apply

### 9.1 Boxtal — self-service, days

1. Sign up at boxtal.com. No SIRET gate published, no volume condition, no
   subscription.
2. Create an API v3 application and its access-key/secret-key pair.
3. Create a separate test account and credentials; API calls use
   `https://api.boxtal.build/shipping`.

Their [partner page](https://www.boxtal.com/fr/fr/partenaires) exists but is a
referral programme aimed at web agencies: no published commission, revenue
share, white-label terms or sub-account model, and a contact form as the only
call to action. Questions worth putting to their partnership team, in order of
value to MakersBrain:

1. Can partner accounts pool shipment volume across a partner's client base, so
   every tenant gets rates none of them could reach alone? (This is the one with
   money in it.)
2. Can MakersBrain be registered as an OIDC client in the `boxtal-customer`
   realm, so tenants authorise by redirect instead of entering an application
   key pair?
3. Is there any API to create or invite a merchant account programmatically?
4. Does the agency partner programme carry a commission on referred accounts,
   and are the terms published?
5. Is creation of the separate API test account self-serve or
   partner-provisioned?

Questions 1–4 do not block phase 1. Test-account access in question 5 is part of
the phase 0 gate because the integration may not be developed against production.

### 9.2 Colissimo — one to three weeks, sales contact required

Create the professional space at `colissimo.entreprise.laposte.fr` with SIRET
and a professional email; activate a payment method. Then choose **Contrat
Facilité** (no commitment, aimed at under roughly 500 parcels a year — the
artisan profile) or **Contrat Privilège** (volume commitment, negotiated rates).
Contract number and web-service password arrive by email at contract opening or
from the La Poste commercial contact.

**Unresolved, and it decides whether this addon is ever worth building.** The
SLS documentation says the web service URLs are reserved for Entreprise offers,
while Facilité is marketed as a "no technical development" contract. Ask in
writing:

> Does the Contrat Facilité include access to the SLS affranchissement web
> service (`generateLabel`) and the Point Retrait web service, or is a Contrat
> Privilège required for API access?

If the answer is Privilège, direct Colissimo is unavailable to artisan tenants
and Boxtal remains their only route to it — which is fine, and is precisely why
Boxtal is primary. Also request the current "Spécifications Web Service
d'Affranchissement" PDF, a sandbox account, and the product codes enabled on the
contract.

### 9.3 Chronopost — two to six weeks, sales contact required

No self-service path to API credentials; contact Chronopost sales via
chronopost.fr. Contracts carry a volume expectation, so a single-person workshop
will likely be quoted poorly or declined — again, the reason Boxtal is primary.
Credentials are the account number plus Chronotrace password; ask for a
dedicated web-service sub-account rather than reusing a human login, plus the
current "Web Services Chronopost" specification, the recette account, and which
product codes are open.

### 9.4 Mondial Relay — days, self-service

Open a professional account from the Solutions Pro section of mondialrelay.fr; a
SIRET is required and a personal account never exposes API parameters. Sign in
at `connect.mondialrelay.com` for credentials. Ask support for the API V2
technical documentation, whether the account is enabled for label generation as
well as relay search, and the test brand code.

## 10. Testing

Nothing here may make a live provider call in CI.

- **Provider contract tests** — one fixture suite per provider, run against the
  same interface assertions: success, authentication failure, malformed address,
  weight over limit, relay closed, provider 500, timeout. A new provider is
  "done" when it passes the shared suite.
- **Error-mapping tests** — each provider maps its failures onto the right error
  class. A validation failure retried as transient buys two parcels.
- **Asynchronous document tests** — order submission returns a provider reference
  but no label; a signed document event later attaches the outbound label and a
  tracking event updates the picking. Events may arrive twice or out of order.
- **Odoo dispatch tests** — assert Odoo actually reaches our methods, including
  a test that fails if core stops identifying Mondial Relay carriers by
  `product_id.default_code`. Validation of an `mb_*` picking posts a queued
  message rather than native's premature "shipment sent" message; other carrier
  types still use `super()`. Cancellation preserves tracking until confirmed.
- **Checkout journey test** (HTTP, in the style of the 20 existing `mb_webshop`
  tests): choose a relay, confirm the cart, verify the shipping partner is the
  immutable pickup partner and that switching carrier clears it. Add forged
  carrier/service/partner input, another session's cart, stale/closed point and
  route rate-limit cases.
- **Idempotence and concurrency tests** — a submission that times out after the
  provider created it, an Odoo transaction rollback, two simultaneous workers,
  and repeated merchant clicks all result in at most one provider purchase.
  Providers without safe reconciliation enter `unknown` and never auto-retry.
- **Webhook tests** — HMAC over the exact raw body, constant-time signature
  validation, invalid/unsigned rejection, replay rejection by event id and
  digest, unknown subscription rejection, inbox durability, sub-two-second
  acknowledgement and retry after worker failure. Reconciliation detects a
  disabled or missing subscription.
- **Label classification tests** — outbound labels use
  `_get_delivery_label_prefix()` and never appear as portal return labels;
  return labels use `get_return_label_prefix()` and receive a portal token only
  when explicitly enabled.
- **Secret-boundary tests** — credentials never appear in tenant database fields,
  logs, chatter, traces, exports or exceptions; cross-tenant and wrong-environment
  secret references fail closed; rotation works without changing the carrier.
- **Neutralisation test** — restoring a database clears secret references and
  subscriptions, leaving carriers unable to resolve production credentials or
  buy labels.

## 11. Control-plane registration

Each provider is separately switchable, so a tenant is not exposed to one it
does not use. Files to touch per provider:

| File | Change |
|---|---|
| `control-plane/deploy/capability-registry-v2.json` | new row, `"dependencies":["webshop"]` |
| `control-plane/deploy/release-contract.json` | recompute `capability_registry.sha256` — the registry is hash-pinned at line 6 |
| `control-plane/src/modules.rs` | matching `ModuleBundle` (pattern at line 113) plus its assertion test |
| control-plane provider-credential API, persistence and deployment driver | add tenant/carrier/environment-scoped create, rotate, resolve-for-operation and delete operations; store only opaque references in Odoo and audit every mutation |
| `tools/check_addons.py` | add `delivery_mondialrelay`, `website_sale_mondialrelay`, `stock_delivery` to `KNOWN_EXTERNAL` |
| `addons/mb_webshop_carrier_*/models/capability_policy.py` | `_requires_owned_model_rules` per `addons/mb_webshop/models/capability_policy.py:8` |

Proposed keys: `shipping-boxtal`, later `shipping-sendcloud`,
`shipping-mondialrelay`, `shipping-colissimo`, `shipping-chronopost`. Keyed by
provider rather than by carrier, because that is what a tenant actually turns on.

Disabling a provider first suspends webhook subscriptions and secret resolution,
then stops new mutations. It must leave `mb.carrier.shipment` rows, historical
pickings, attachments, tracking numbers and a materialized tracking URL readable;
history must not depend on calling methods from an uninstalled provider addon.
The shared base addon cannot be uninstalled while any provider capability or
historical shipment depends on it. Capability deactivation tests must cover two
providers sharing the base and reactivation after one is disabled.

## 12. Phasing and estimate

Implementation note (16 August 2026): phases 1–4 are present in
`mb_webshop_carrier_base`, `mb_webshop_carrier_boxtal` and the MakersBrain
control plane. V1 deliberately uses one parcel per shipment. The current Boxtal
OpenAPI exposes no official manifest operation, so v1 prints a document headed
“Local handover worksheet” and “Not a carrier-accepted manifest.” Boxtal also
does not expose a safe client-reference lookup or documented idempotency key;
ambiguous purchases therefore remain `unknown` until the merchant verifies the
provider portal and explicitly resolves them. Phase 0's live low-value shipment,
payment, webhook, cancellation, rotation and restore-neutralisation evidence
cannot be produced without workshop-owned Boxtal sandbox and production
credentials and remains the release gate. Phase 5+ providers remain the
contract-gated growth roadmap, not part of the Boxtal v1 release.

One engineer.

| Phase | Scope | Duration |
|---|---|---|
| 0 | Production/test Boxtal accounts; deferred-payment readiness; current OpenAPI captured; prove auth, order, signed document/tracking webhooks, cancellation, client-reference reconciliation/idempotency and manifest availability; partnership questions sent | 3–5 engineering days plus any account approval wait; implementation gate |
| 1 | `mb_webshop_carrier_base`: provider interface, durable shipment/inbox models, queued mutation and reconciliation, request log, label classification, external-secret boundary, neutralisation, capability wiring | 2–2.5 weeks |
| 2 | `mb_webshop_carrier_boxtal`: services, pending shipment submission, document/tracking webhooks, cancellation, subscription reconciliation, onboarding/readiness screen | 2–2.5 weeks |
| 3 | Generic pickup picker and pickup-partner pattern, extracted from what phases 1–2 proved, wired to Boxtal parcel points | 1 week |
| 4 | Manifest if phase 0 proves provider support (otherwise clearly labelled local handover worksheet), return labels, merchant exception handling, and multi-parcel only if open question 4 selects it for v1 | 1–1.5 weeks |
| 5 | Second provider to prove the seam — Sendcloud for own-contract tenants, or Mondial Relay direct | 1–1.5 weeks |
| 6+ | Colissimo direct (gated on §9.2), Chronopost direct | 2–3 and 3–4 weeks |

Phases 1–4 are roughly **6–7.5 weeks after the phase 0 integration gate to a
production shipping capability covering
Mondial Relay, Colissimo, Chronopost, Colis Privé and Relais Colis**, with no
direct-carrier contract wait blocking the Boxtal path. Production qualification
still requires a real low-value shipment, signed document and tracking events,
cancellation/reconciliation, secret rotation and backup-neutralisation evidence.
The direct addons are engineering-bounded but contract-gated and belong to the
growth tier.

This satisfies Phase 5 of the webshop plan
(`makersbrain-webshop-domain-email-plan.md:629`), whose exit criterion is that
*"the artisan can purchase a shipping label, send tracking and handle a delivery
exception"* (line 715).

## 13. Open questions

1. Does Boxtal pool volume across a partner's client base? (§9.1 q1. Changes the
   commercial pitch, not the code.)
2. Does Colissimo Contrat Facilité grant web-service access? (§9.2. Decides
   whether `mb_webshop_carrier_colissimo` is ever built.)
3. Does each tenant hold its own provider account, or does MakersBrain
   intermediate? The credential design assumes per-tenant, which is the safer
   default and the harder one to reverse.
4. **Decided for v1:** one parcel per shipment. Multi-parcel remains a later
   provider-specific extension.
5. Label printing: PDF download only, or ZPL to a thermal printer? The `mb_label`
   addon in this repository already handles thermal printing and should be
   reused rather than duplicated.
6. Live rates at checkout: v1 uses native price rules. Revisit once a tenant has
   enough volume that a wrong flat rate costs real money.
7. **Resolved for the current v3.1 OpenAPI:** no provider-accepted manifest
   operation is documented. `supports_manifest` is false and the generated
   document is explicitly labelled as a local worksheet, never an official
   carrier manifest.

Sources consulted for sections 3, 5, 8 and 9:
[Boxtal transporteurs](https://www.boxtal.com/fr/fr/preuves/transporteurs),
[Boxtal partenaires](https://www.boxtal.com/fr/fr/partenaires),
[Boxtal tarifs 2026](https://www.boxtal.com/fr/fr/blog/2025/12/offres-transporteurs-ce-qui-change-en-2026),
[Boxtal developer portal](https://developer.boxtal.com/),
[Boxtal v3 authentication](https://developer.boxtal.com/fr/fr/apiv3/guide/auth-api-v3),
[Boxtal v3 test environment](https://developer.boxtal.com/fr/fr/apiv3/guide/sandbox-api-v3),
[Boxtal v3 order flow](https://developer.boxtal.com/fr/en/apiv3/guide/order-api-v3),
[Boxtal v3 webhook subscriptions](https://developer.boxtal.com/fr/fr/apiv3/guide/subscriptions-api-v3),
[Boxtal PHP library](https://github.com/boxtal/php-library),
[Sendcloud pricing](https://www.sendcloud.com/pricing/),
[Sendcloud decentralized integration](https://www.sendcloud.dev/docs/marketplaces/decentralized-integration/),
[Mondial Relay FAQ pro](https://www.mondialrelay.fr/faq-pro/votre-compte/ou-trouver-mes-parametres-code-enseigne-code-marque-cle-privee-pour-configurer-mon-module/),
[Colissimo contrats](https://www.colissimo.entreprise.laposte.fr/fr/page-contrats),
[Colissimo Web Service d'Affranchissement](https://www.colissimo.entreprise.laposte.fr/sites/default/files/2021-12/DT_Flexibilite_Expedition_Web-Service-Affranchissement_202112_FR.pdf),
[Colissimo points de retrait](https://www.colissimo.entreprise.laposte.fr/sites/default/files/2021-10/WebService-points-retrait_FR.pdf),
[Chronopost ShippingServiceWS](https://www.chronopost.fr/shipping-cxf/ShippingServiceWS).

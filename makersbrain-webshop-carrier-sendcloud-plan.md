# MakersBrain Sendcloud Carrier Integration Plan

**Project:** MakersBrain on Odoo 19 Community
**Status:** Planned; no Sendcloud mutation has been run
**Date:** 18 August 2026
**Companion:** `makersbrain-webshop-carrier-plan.md`

## 1. Outcome

Add tenant-owned Sendcloud shipping to the existing provider-neutral carrier
runtime. A workshop supplies its own public and private API keys; MakersBrain
stores them outside Odoo and binds only an opaque secret reference. The completed
integration supports:

- outbound labels and validated PDF/ZPL attachments;
- Sendcloud shipping-option discovery while retaining Odoo price rules by
  default;
- website service-point selection;
- tracking webhooks plus authenticated endpoint repair;
- cancellation without prematurely erasing provider truth;
- genuine customer-to-workshop return labels;
- tenant-safe credential rotation, restriction and restore neutralisation.

Every workshop owns its Sendcloud account, carrier contracts, charges and
support relationship. MakersBrain does not pool credentials or rebill labels.

## 2. Existing Odoo integrations and reuse decision

Sendcloud's App Store lists two Odoo choices:

- **Odoo**, developed by Odoo, with label creation, rate calculation, inventory,
  checkout service points and invoicing;
- **Odoo by Onestein**, with labels, return labels and webshop integration.

Odoo 19 documentation also describes a `delivery_sendcloud` connector with
shipping products, service points, outbound and return labels, customs
documents, tracking, multiple packages and test-mode cancellation. This is the
functional baseline; do not recreate inferior Odoo workflows.

However, the MakersBrain Community image and configured addon paths contain no
`delivery_sendcloud` module. Odoo's current implementation lives outside the
public Community addon tree, so the plan cannot assume it can be installed or
redistributed. The older Onestein connector is proprietary through Odoo 16. The
OCA successor `delivery_sendcloud_oca` is LGPL and Community-compatible, but as
of this plan has an 18.0 implementation and no 19.0 module; it also states that
it primarily implements Sendcloud API v2. New Sendcloud development must not be
built around parcel creation v2, which is closed to accounts created after
13 April 2026.

**Decision:** implement the focused v3 adapter against the existing MakersBrain
runtime. Use the two connectors as behavior, fixture and UX references; do not
depend on or wholesale-port either connector. Porting the OCA module would bring
a second shipment model and callback lifecycle while its creation transport
still needs a v3 replacement, and it would not satisfy the existing external
secret boundary without substantial redesign.

Increment 0 still includes a short, documented reuse audit:

1. Obtain the exact Odoo 19 `delivery_sendcloud` license and availability terms.
   Do not copy Enterprise/proprietary source into MakersBrain.
2. Run an OCA 18.0 architecture and security review, including its global ACLs,
   credential storage, callbacks, service-point identity, logging and v2 calls.
3. Inventory reusable LGPL address, package and service-point tests or mappings;
   reimplement nothing merely because it already exists under a compatible
   license.
4. Reuse LGPL code only with attribution and license compliance, and only where
   it preserves MakersBrain's external-secret and tenant-isolation rules.
5. Record attribution for anything reused and verify that no proprietary source
   or v2 creation dependency enters the addon.

The focused adapter must pass the completion criteria in this plan. The
official/OCA connectors are prior art and test or UX references, not evidence
that our deployed Community system already supports Sendcloud.

References:

- <https://app-store.sendcloud.com/odoo>
- <https://app-store.sendcloud.com/odoo-by-onestein>
- <https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/inventory/shipping_receiving/setup_configuration/sendcloud_shipping.html>
- <https://github.com/OCA/delivery-carrier/tree/18.0/delivery_sendcloud_oca>

## 3. Decisions

| Concern | Decision |
|---|---|
| Addon | Focused `mb_webshop_carrier_sendcloud`; existing connectors are reference implementations, not dependencies |
| Capability | `shipping-sendcloud`, depending on `webshop` |
| Authentication | HTTP Basic, public key as username and private/secret key as password |
| API | v3 for options, shipments, parcel documents, cancellation, tracking and returns |
| Sender | Select and persist a Sendcloud sender-address ID; never infer it only from the Odoo warehouse name |
| Outbound duplicate guard | `external_reference_id`, documented unique duplicate `409`, plus lookup/reconciliation |
| Return duplicate guard | Local row uniqueness only; Returns API `external_reference` is correlation, not proven remote idempotency |
| Service points | Existing MakersBrain picker; qualify v3 beta and retain a bounded v2 read-only fallback |
| Tracking | Signed webhook first, authenticated Parcel Tracking endpoint as repair path |
| Manifest | Unsupported until an official carrier-accepted Sendcloud operation is qualified |
| Test mode | Same Sendcloud account/host, enforced option allowlist; it is not a charge-free sandbox |

## 4. Credentials and trust boundary

### 4.1 User flow

1. The workshop enables **Sendcloud shipping**.
2. It selects an Odoo delivery method and supplies `SENDCLOUD_PUBLIC_KEY` and
   `SENDCLOUD_PRIVATE_KEY`.
3. If its integration type exposes a distinct Webhook Signature Key, it supplies
   that optional key too. Do not assume the API private key signs every
   integration type.
4. The control plane writes the provider-tagged secret to the tenant-scoped
   external store and gives Odoo only `mb_secret_ref`.
5. The user selects an active Sendcloud sender-address ID returned by the account.
6. Rotation replaces the secret atomically and a signed **Test API Webhook** must
   succeed before webhook readiness returns healthy.

The UI labels the credentials as workshop-owned and never returns either secret.

### 4.2 Local `sendcloud.env`

The ignored repository-root file contains the expected variable names and is
qualification material only. Never copy its values to source, fixtures, images,
plans, logs or Odoo. CI uses hand-built sanitized fixtures.

The harness defaults to read-only. Mutations require explicit flags and are
enforced in the adapter, not just the CLI:

- policy-test mode permits only the exact `sendcloud:letter` outbound option;
- policy-test mode rejects Returns API creation;
- a tracked carrier label, real cancellation or return requires
  `--live --approve-live-charge`, an exact option-code allowlist and a maximum of
  one object for the approved operation;
- no harness command prints headers, bodies, addresses or credential values.

`sendcloud:letter` is not a full sandbox. It may still incur a processing fee,
does not prove real carrier tracking/cancellation, cannot qualify returns and is
automatically treated as delivered after Sendcloud's defined delay. Never claim
that a `test` environment label prevents charges.

### 4.3 Generic secret refactor

Generalize the current Boxtal-only validation before exposing Sendcloud:

- accept tagged `{public_key, private_key, webhook_signature_key?}` for
  Sendcloud; allow the optional key only for a documented integration type;
- derive `shipping-{provider}` from a closed provider registry;
- bind and resolve only when tenant, workshop, company, carrier, provider and
  environment all match;
- use a server-derived operation purpose for secret resolution;
- never trust a provider or operation purpose supplied by Odoo;
- keep `Cache-Control: no-store`, strict key allowlists, restrictive filesystem
  permissions and audit events;
- add cross-provider, cross-tenant, wrong-environment and disabled-capability
  tests.

## 5. Provider contract

```python
code = "sendcloud"
supports_pickup_points = True
supports_own_contract = True
supports_manifest = False
supports_return_label = True
supports_tracking_lookup = True
supports_contextual_options = True

operation_safety = {
    "create_shipment": OperationSafety(
        native_idempotency=True,
        reconciliation_lookup=True,
        automatic_retry=True,
    ),
    "create_return": OperationSafety(
        native_idempotency=False,
        reconciliation_lookup=False,
        automatic_retry=False,
    ),
}
```

Replace the base runtime's provider-wide `supports_idempotency` and
`supports_reconciliation` retry decisions with `operation_safety(operation)`.
Outbound uniqueness does not make return creation safe to replay.

The client uses `https://panel.sendcloud.sc`, bounded timeouts and response
sizes, strict JSON/document MIME validation, redacted logging and `Retry-After`
for read-only retries. A mutation is replayed only when that exact operation's
contract proves remote deduplication or an authoritative lookup finds the
existing object.

Add a contextual `shipping_options(query)` contract. Keep `list_services()` for
diagnostics. `shipping_options` validates origin, destination, structured
address, parcel size/weight, carrier, service point and functionality. Its quote
is volatile; cache for at most one hour and revalidate immediately before label
purchase. Native Odoo price rules remain the customer price by default.

## 6. Configuration and address mapping

`delivery.carrier` gains or reuses:

- provider option code and separate return option code;
- Sendcloud sender-address ID;
- optional direct-contract and carrier filters;
- service-point toggle;
- parcel dimensions, content description, brand and output format;
- webhook key source, last successful signed event and readiness state.

`check_credentials()` is read-only: authenticate, list options, retrieve sender
addresses and inspect integration metadata. It distinguishes **keys valid** from
**ready to buy**. Production readiness requires billing acceptance, a usable
option, a selected active sender address and a verified webhook key.

Retrieve the selected sender address before purchase and map Sendcloud's explicit
street, house number and addition fields. Do not assume the Odoo company address
or warehouse name matches it.

Add provider-neutral structured recipient fields to `ShipmentRequest`:
`street_name`, `house_number`, and `house_number_addition`. Populate explicit
partner fields when present. A deterministic country-aware parser may propose a
split for old records, but the user must be shown the result and purchase fails
on ambiguity or a missing required house number. Never copy the whole Odoo
`street` value into both provider fields.

## 7. Outbound labels and cancellation

Keep Inventory delivery → **Send to Shipper**. The queued worker:

1. creates/reuses and locks one local shipment journal row;
2. revalidates entitlement, option, sender, recipient, parcel and service point;
3. sends the stable journal key as `external_reference_id`;
4. calls synchronous `POST /api/v3/shipments/announce` for the one-parcel v1;
5. treats documented duplicate `409` as reconciliation, never a second purchase;
6. persists shipment ID, parcel IDs, tracking, status and cost when supplied;
7. retrieves authenticated parcel documents and validates PDF/ZPL/PNG;
8. attaches labels to the picking and marks `label_ready` only after validation.

If announcement succeeds but document retrieval fails, retain the provider
reference in `awaiting_document` and retry only the document read. If a mutation
times out, reconcile by external reference before retrying.

Cancel with the documented shipment cancellation endpoint. Preserve tracking
and provider references through pending/rejected outcomes, poll asynchronous
cancellation to a final state and never promise a refund.

## 8. Service-point recipient identity

Reuse `/mb_carrier/pickup_points` and the immutable pickup partner, but do not
make the pickup business the Sendcloud recipient.

Before checkout replaces `partner_shipping_id`, store a company-scoped
`mb_delivery_recipient_partner_id` and snapshot the shopper name, email and phone
onto the picking. At label time:

- build `to_address` from that shopper/contact and structured address fields;
- separately re-resolve the selected point and send its ID as
  `to_service_point`;
- require option and point carrier compatibility;
- fail if the recipient snapshot is absent, cross-company, belongs to another
  cart or changed after payment.

The pickup partner remains Odoo's physical routing destination only. Search and
revalidation are tenant-scoped, rate-limited and adapter-isolated. Service Points
v3 remains behind a feature flag with sanitized v3 and read-only v2 fixtures.

## 9. Returns

Before enabling **Generate Return Label**:

1. Fix the shared request direction: customer origin, workshop destination.
2. Select a separate compatible return option; never carry the outbound pickup
   point or assume the outbound option supports returns.
3. Send `order_number` and stable `external_reference` for correlation only.
4. Make exactly one return-creation attempt. On an ambiguous result, preserve
   `unknown` and require merchant portal/API evidence plus explicit resolution;
   never auto-retry.
5. Validate customs descriptions, quantities, weights, values, HS codes, origin
   countries and invoice data for non-EU returns.
6. Persist return ID and incoming parcel ID, retrieve its label and use Odoo's
   return-label attachment/access-token policy.
7. Cancel using `PATCH /api/v3/returns/{id}/cancel`; keep `cancel_pending` on
   202 and retrieve the return until final.
8. Track the incoming parcel through the shared tracking path.

Start with print-at-home drop-off returns. Label-less, pickup returns and a
customer returns portal remain out of scope.

## 10. Webhooks and tracking

Use the documented signing material for the selected Sendcloud integration type:
the API secret/private key where applicable or a distinct Webhook Signature Key.
Verify HMAC-SHA256 over the exact raw body and compare `Sendcloud-Signature` in
constant time. If the signing-key source cannot be established, readiness fails.

The generic webhook route resolves the carrier by opaque routing token, verifies
before parsing, writes a minimal durable inbox event, acknowledges quickly and
processes asynchronously. It rejects wrong-provider/environment/tenant events,
deduplicates, tolerates out-of-order events and never authenticates only by a
matching shipment reference.

Implement `retrieve_tracking(tracking_number)` with authenticated
`GET /api/v3/parcels/tracking/{tracking_number}`. Before a number exists,
retrieve the stored shipment/return reference until parcel tracking appears.
Webhook and endpoint payloads share one normalization table and preserve the raw
bounded provider status code.

Add manual **Refresh tracking** and bounded scheduled reconciliation for
non-terminal parcels. Read polling honors `Retry-After`, backs off with jitter,
treats an early 404 as not-yet-available, rate-limits manual refresh and stops at
terminal states. Event timestamps prevent a stale webhook or poll from
regressing delivered, returned or confirmed-cancelled state. Tracking reads
never alter purchase, cancellation or accounting state.

## 11. Restricted capability lifecycle

Restriction blocks **new** outbound purchases, new returns and configuration
changes. It must not strand already chargeable objects. While restricted, allow
only these server-derived existing-object purposes:

- cancellation;
- document recovery;
- shipment/return reconciliation;
- authenticated tracking lookup;
- webhook signature verification and inbox processing.

Do not set a blanket provider-disabled boolean that makes `_mb_provider()` reject
all of them. Secret resolution enforces the allowlist. Explicit credential
deletion/revocation is a separate action with a warning that provider cleanup
will stop. A restored database clears secret refs and readiness so it cannot buy
labels or authenticate callbacks.

## 12. Testing and live qualification

Offline tests cover:

- key redaction and cross-boundary secret rejection;
- sender-address ownership and structured house-number mapping;
- option discovery/revalidation and Odoo price-rule behavior;
- outbound `409`, timeout reconciliation and exactly-one purchase;
- return timeout entering `unknown` with no automatic replay;
- final/pending/rejected shipment and return cancellation;
- shopper identity plus separate service-point mapping;
- signed/invalid/duplicate/out-of-order webhooks and both key sources;
- endpoint repair after a dropped webhook, backoff and terminal non-regression;
- restricted-mode rejection of new purchases but successful cancellation,
  document recovery, tracking and webhook processing;
- Boxtal regressions and restored-database neutralisation.

Live stages run separately with `sendcloud.env`:

1. read-only authentication, integration metadata, options, sender addresses and
   service points;
2. `sendcloud:letter` document/idempotency smoke test under the adapter allowlist,
   accepting that it is not a real tracking/return qualification;
3. signed Test API Webhook;
4. with merchant approval, one paid tracked option to qualify real tracking and
   carrier cancellation;
5. separately, one approved return option to qualify direction, document,
   tracking and return cancellation.

The harness stops rather than substituting another option. Production is not
advertised until the paid qualification evidence exists.

## 13. Delivery increments

| Increment | Scope | Exit criterion |
|---|---|---|
| 0 | Official/OCA reuse audit, read-only v3 qualification, license/security record | Reuse inventory and account assumptions documented; no proprietary code or secrets copied |
| 1 | Generic operation safety, secret schema and restricted-operation policy | Boxtal and cross-provider tests pass |
| 2 | Odoo 19 focused addon, sender/options, outbound label, document and cancellation | One allowlisted smoke label; ambiguous recovery proven offline |
| 3 | Service points, recipient snapshot, signed webhooks and tracking endpoint | Home/point journeys pass and polling repairs a missed event |
| 4 | Correct-direction returns with one-attempt safety and cancellation | Approved customer-to-workshop return passes |
| 5 | Control-plane UI, translations, lifecycle, runbook and restore test | Workshop can self-connect, rotate, restrict and delete safely |

## 14. Completion criteria

Complete means tenant-owned credentials stay outside Odoo; Odoo 19 Community has
a licensed, maintained connector path; outbound creation is remotely deduplicated
and recoverable; return creation is not over-retried; sender and recipient
addresses are explicit; pickup identity is correct; labels, returns, tracking
and cancellations work through existing Odoo interfaces; restricted mode still
cleans up existing objects; live charges require explicit approval; and all
provider-neutral plus Boxtal regressions pass.

## 15. Primary API references

- Authentication: <https://sendcloud.dev/docs/authentication/>
- Decentralized integration: <https://sendcloud.dev/docs/marketplaces/decentralized-integration/>
- Shipments v3: <https://sendcloud.dev/api/v3/shipments/index>
- Create and announce synchronously: <https://sendcloud.dev/api/v3/shipments/create-and-announce-a-shipment-synchronously>
- Shipping options: <https://sendcloud.dev/api/v3/shipping-options/return-a-list-of-available-shipping-options>
- Sender addresses: <https://sendcloud.dev/api/v3/sender-addresses/retrieve-a-list-of-sender-addresses>
- Parcel documents: <https://sendcloud.dev/api/v3/parcel-documents/retrieve-a-parcel-document>
- Shipment cancellation: <https://sendcloud.dev/api/v3/shipments/cancel-a-shipment>
- Returns: <https://sendcloud.dev/api/v3/returns>
- Create return: <https://sendcloud.dev/api/v3/returns/create-a-return>
- Return cancellation: <https://sendcloud.dev/api/v3/returns/request-cancellation-of-a-return>
- Service points: <https://sendcloud.dev/api/v3/service-points>
- Webhooks: <https://sendcloud.dev/api/v3/webhooks/index>
- Parcel tracking: <https://sendcloud.dev/api/v3/parcel-tracking/retrieve-tracking-information-for-a-parcel>

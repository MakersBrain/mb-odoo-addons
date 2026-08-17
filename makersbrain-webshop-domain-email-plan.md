# MakersBrain Webshop, Domain and Email Module Plan

**Project:** MakersBrain on Odoo 19 Community
**Status:** Paid-release implementation complete locally; live provider, staged isolation and production-load qualification remain
**Date:** 17 August 2026

## 1. Goal

Allow an artisan to activate an optional Shopify-like webshop from MakersBrain, without making the webshop a permanent dependency of the core ERP.

When activated, the artisan receives:

- a ready-to-use address such as `atelier-ceramique.makersbrain.com`;
- an Odoo-backed product catalog, cart, checkout and order workflow;
- Odoo's native storefront editor with MakersBrain craft presets and blocks;
- optional connection of an existing custom domain;
- later, optional purchase of a new domain through MakersBrain;
- transactional email from MakersBrain or from the artisan's verified domain;
- optionally, a real business mailbox such as `bonjour@atelier-ceramique.fr`.

The feature must be installable and removable per tenant. Removing it must not damage ERP products, stock, customers, orders, invoices, production lots, domains or mailboxes.

In product language, “removable” means that the capability can be deactivated immediately and its MakersBrain-owned presentation layer can later be removed safely. It does not imply automatically uninstalling Odoo's standard `website` or `website_sale` modules. Destructive module removal is an exceptional, separately proven operator action.

### Product thesis

The first release is an **atelier storefront**, not a generic miniature Shopify.
Its differentiation should be the information and workflows already present in
MakersBrain:

- one-of-one work with exact stock and provenance;
- materials, dimensions, process and care information;
- ceramic firing, glaze and food-contact information when relevant;
- workshop pickup, small product drops and made-to-order or commission enquiries;
- a direct path from making and stock to publishing, fulfilment and after-sales.

Generic ecosystem breadth remains optional. A feature belongs in v1 when it
makes this focused artisan workflow safer, clearer or materially easier to run.

## 1.1 Committed product level

The committed target is a **good production SaaS v1**, not a storefront demo and not full Shopify parity.

| Product level | Status | Scope | Estimated duration |
|---|---|---|---:|
| Prototype webshop | Internal milestone only | Catalog, cart, one payment flow and default subdomain | 3–5 months |
| **Good SaaS v1** | **Committed target** | Domains, self-service onboarding, shipping, transactional emails, returns, multiple themes and production operations | **9–14 months** |
| Mature Shopify-like product for European artisans | Architecture horizon and optional backlog | Deeper international commerce, automation, ecosystem, advanced merchandising and integrations | Not committed; likely a further 12–24+ months |

The 9–14 month estimate assumes an experienced team of approximately four to five full-time engineers plus part-time product/design and QA. With only two engineers, the same production scope is more realistically 15–22 months. Adding people cannot fully compress early architecture and integration work, but a six-to-eight-person team could potentially deliver it in 7–10 months.

“Mature Shopify-like” features may be selected individually when they provide clear value to European artisans. They must not silently expand the v1 deadline.

## 1.2 Odoo 19 verification and implementation baseline

The repository and its running `odoo:19` image were verified against Odoo
`19.0-20260803`. The implementation should reuse these upstream seams:

| Need | Odoo 19 / existing addon decision | MakersBrain work still justified |
|---|---|---|
| Theme editor | Use Odoo Website Builder as the editor SDK: QWeb, snippets, SCSS value palettes, fonts, headers, footers and shapes | Curated craft presets, craft-specific blocks, safe defaults and onboarding |
| Themes | Three palettes now ship in `mb_webshop`: Ceramics, Jewellery and Woodwork; all broad Odoo web/portal/editor asset bundles compile after preserving both native base palettes | Local desktop/mobile browser and automated accessibility QA pass; staged content/theme qualification and more section presets remain |
| Catalog and checkout | Reuse `website_sale` | Guided setup and artisan-specific product storytelling |
| Stock visibility | Reuse `website_sale_stock` and its `free_qty` validation | Atomic expiring holds for one-of-one POS/webshop concurrency; upstream validation alone is not a reservation |
| Workshop pickup | Reuse `website_sale_collect` | MakersBrain onboarding and readiness checks only |
| Shipping rules | Reuse `delivery` | One production carrier label/API adapter; Mondial Relay core only selects pickup points and does not implement its label WebService |
| Payments/refunds | Reuse Odoo payment transactions/refunds and existing `mb_payment_sumup` | Provider onboarding and late-webhook exception handling |
| Transactional mail | Reuse Odoo templates, queue and SMTP plus the existing control mail gateway | Tenant sender projection, branded-domain verification and provider event operations |
| Domains | Reuse Odoo `website.domain` and the existing exact-host gateway | Persist multiple verified hostnames in the control plane and render exact gateway configuration; no per-request database lookup is needed for v1 |
| Returns | Reuse stock returns, account reversals, portal tokens and queued mail | Implemented thin request/approval/receipt/resolution workflow; partial-credit-note merchant UX and provider-delivery qualification remain |

OCA modules may be studied but are not runtime dependencies: the relevant
cart-expiry, acquirer-confirmation and available-stock addons are AGPL-3, while
MakersBrain addons are LGPL-3. Their semantics also do not replace atomic
one-of-one reservations.

The first implementation slice is present: registry v2 maps the `webshop`
capability to `mb_webshop` and `mb_email_bridge`; activation installs their native Odoo dependencies;
restriction closes the `/shop` storefront and checkout while preserving the
backend and historical commerce records; reactivation reopens it. This is the
pack-level switch required by the product lifecycle.

## 1.3 Implementation progress tracker

Status is evidence-based: **verified** means an automated install or behavior
test exists; **reused** means the named Odoo 19 feature was inspected and is a
declared dependency; **partial** and **planned** must not be presented as
shippable product capability.

| Product area | Status | Current evidence / next gap |
|---|---|---|
| Pack activation and restriction | **Verified** | Registry v2, release contract, bridge lifecycle test, storefront and checkout route gate |
| Native theme editor | **Verified foundation** | Three compiled palettes and two editor snippets; Chromium desktop/mobile rendering passes and Lighthouse accessibility is 100/100. Staged representative-content QA remains |
| Catalog, cart and checkout | **Reused** | Odoo `website_sale`; guided setup and end-to-end payment qualification remain |
| Atomic cart inventory | **Verified** | `mb.webshop.stock.hold` uses real Odoo stock moves and quant reservations; second-cart, competing stock/POS move, expiry, conversion and late-confirmation tests pass |
| Pickup | **Reused** | Odoo `website_sale_collect`; the launch-readiness card now detects published collection/delivery methods, while live pickup-address and checkout qualification remain |
| Shipping rates | **Verified foundation** | Provider-neutral shipment state machine and Boxtal v3 adapter are implemented. The Boxtal sandbox created/cancelled synthetic orders, returned valid PDF labels, delivered real document/tracking callbacks with valid HMAC signatures, and removed both test subscriptions. Exact-release staging and commercial-account qualification remain |
| Online payments | **Verified foundation** | SumUp sandbox hosted settlement/refund and a provider-delivered callback through ephemeral public HTTPS into a real scratch Odoo transaction pass. Post-processing produced one confirmed order, converted hold, stock move, posted invoice and payment; two public webhook replays stayed idempotent. The exact immutable staging-release journey remains a promotion gate |
| Returns and exchanges | **Verified foundation** | `mb_webshop` provides an access-token customer portal journey, queued status emails, a configurable post-delivery window, delivered/claimed quantity and ownership validation, a company-scoped merchant queue, native return pickings, posted credit-note validation and replacement orders. The fresh repository matrix includes 26 webshop tests with zero failures. Partial-credit-note merchant UX and provider email-delivery qualification remain |
| Platform hostname | **Verified foundation** | Workshop creation allocates a unique platform hostname separately from the opaque database ID; the deployment driver renders and validates an exact-host gateway route, the Odoo server-wide filter accepts only the trusted opaque mapping, reconciliation verifies the observed route, and tenant bootstrap now stores the immutable hostname and projects it into an empty Odoo website domain without replacing a custom domain. Deployment DNS/TLS and live two-tenant topology qualification remain release gates |
| Existing custom domain | **Verified foundation** | Global hostname claims, public-suffix/IDNA validation, live TXT ownership checks, Cloudflare custom-hostname/TLS reconciliation, exact-host routing, canonical redirects, Odoo projection, disconnect, observed-state UI and safe operation retry are implemented. Live provider and two-tenant HTTP/TLS qualification remain |
| Platform transactional mail | **Verified foundation** | `mb_email_bridge` relays approved rendered webshop messages through a tenant-authenticated durable outbox to the fixed Scaleway TEM boundary, preserving the artisan reply-to and using `Atelier via MakersBrain`; authenticated delivery events update delivered/deferred/bounce/complaint state and tenant suppressions. Live TEM deliverability and failure-drill evidence remain |
| Branded email domain | **Verified foundation** | Scaleway TEM registration/revocation, SPF/DKIM/DMARC observation, self-service DNS status, mandatory delivered test, branded sender selection, platform fallback and periodic reconciliation are implemented. Live DNS/provider and deliverability qualification remain |
| Merchant onboarding | **Verified foundation** | The Odoo-native readiness observation is tenant scoped; the control plane persists resumable progress and completion evidence, admits idempotent refresh/complete commands, and exposes merchant and operator dashboards with bounded direct recovery actions. The Svelte self-service journey passes type checking and production build |
| Pack lifecycle | **Verified** | Merchant deactivation uses the durable restriction operation and is immediately reversible; tests prove storefront gating while return-window/domain configuration and ERP history survive. Domains and mail remain independent. No overlay uninstall is supported in v1 because harmless removal cannot yet be proven |
| Production qualification | **In progress** | Local desktop/mobile browser QA and Lighthouse accessibility pass. SumUp sandbox payment/refund plus public callback-to-Odoo post-processing pass; Boxtal sandbox order, label, signed tracking/document events and cancellation pass. Exact-release staging evidence, live Cloudflare and Scaleway TEM/DNS, deployed two-tenant TLS/isolation and production-like multiworker load evidence remain |

The practical stop line for “near Shopify” is the first paid-release acceptance
criteria in section 14, not the existence of a theme screen. Work continues
until every row required by those criteria is verified or explicitly removed
from product scope by a product decision.

Latest regression evidence (2026-08-17): a fresh Odoo `19.0-20260803`
database installed all 40 repository addons, compiled the broad web, portal
and editor bundles, and ran 581 post-tests with zero failures or errors. The
same database then completed an in-place upgrade of all 40 addons. The
control-plane Rust suite passes 135 unit tests; all 17 PostgreSQL integration
tests pass against a disposable database. Strict Clippy and formatting,
OpenAPI compatibility, release/configuration contracts, all-addon structure,
40-addon French translation coverage, focused Ruff, Svelte checking (zero
errors/warnings), the production web build and `git diff --check` all pass.

### 1.4 Engineering checkpoint — 16 August 2026

Completed and verified in the current implementation cycle:

- added the optional `mb_webshop` pack to capability registry v2 and the
  release contract, with reversible storefront and checkout restriction;
- added three Odoo Website Builder craft palettes and two reusable artisan
  snippets, while preserving Odoo 19's native base palettes;
- implemented atomic expiring cart holds using native assigned stock moves,
  including release, reacquisition and conversion into sale reservations;
- implemented customer return requests, merchant approval/rejection,
  receiving, native return pickings, credit-note validation and replacement
  orders, with portal-token access and queued status email;
- added an Odoo-native launch-readiness card for catalogue, production online
  payment, shipping or collection, outgoing mail, public URL and returns;
- verified that Pay on Site is an offline fallback and cannot satisfy the
  production online-payment readiness check;
- reused the existing platform hostname registry and exact-host gateway rather
  than creating another domain layer;
- extended versioned tenant bootstrap so the trusted platform hostname is
  stored in Odoo and projected into an empty website domain, while an existing
  artisan custom domain remains untouched;
- updated `mb_webshop` to `19.0.1.3.0` and `mb_control_bridge` to
  `19.0.1.10.0`.

Verification checkpoint:

- fresh Odoo `19.0-20260803`: 35 selected post-test cases, zero failures and
  zero errors;
- Odoo module statistics: 21 `mb_webshop` and 20 `mb_control_bridge` test
  methods; the two optional OAuth tests remain documented skips;
- control-plane Rust library: 112 tests passed;
- Ruff, addon manifest/data/XML/dependency validation and `git diff --check`
  passed;
- deployment host `10.83.20.5` has not been changed.

Next bounded implementation target: connect an existing artisan-owned custom
domain through explicit ownership verification, desired/observed DNS and TLS
state, exact-host route reconciliation, canonical redirect selection and
self-service recovery diagnostics. Production carrier labels, payment webhook
qualification, transactional-email deliverability and staged browser/accessibility
qualification remain later paid-release blockers; they must not be reported as
complete.

### 1.5 Engineering checkpoint — 17 August 2026

The existing-custom-domain foundation is now implemented across the control
plane, edge and tenant boundary:

- migration `0035_webshop_custom_domains` owns globally unique claims and
  separate desired, DNS, certificate, routing and canonical state;
- hostname admission uses IDNA plus the public-suffix list, rejects reserved or
  MakersBrain-owned targets and verifies a random per-claim TXT challenge;
- a Cloudflare-for-SaaS adapter creates, discovers, observes and deletes custom
  hostnames without persisting provider error text or exposing credentials;
- durable five-minute reconciliation recovers lost callbacks and ambiguous
  creates, retains actionable certificate-validation records and never routes a
  hostname before ownership and provider TLS evidence are present;
- the exact-host gateway proxies only the canonical hostname and sends permanent
  redirects from every secondary platform or custom hostname;
- canonical changes are projected through the authenticated, idempotent Odoo
  bridge, while disconnect restores the platform hostname before retiring the
  provider resource;
- the workshop UI provides copyable DNS instructions, desired/observed health,
  canonical selection, safe disconnect and retry for dead-letter operations;
- Cloudflare runtime secrets and zone configuration are declared in Compose,
  bootstrap/migration scripts and the versioned deployment contract.

Verification checkpoint:

- 128 control-plane Rust library tests pass;
- the custom-domain registry migration passes against disposable PostgreSQL,
  including global claim, active-evidence and one-canonical constraints;
- the generated OpenAPI baseline/client, Svelte type checking and release
  configuration contract pass;
- the focused Odoo `19.0-20260803` domain-projection test passes after fresh
  module installation, including workshop scoping and idempotency;
- translation/source validation passes; the repository-wide `make check` still
  reports pre-existing `mb_brand` SCSS tokens that are absent from
  `@makersbrain/brand@0.1.0`.

This is not yet production-qualified: a real Cloudflare staging zone, public
DNS/TLS, two-tenant browser isolation and provider failure drills remain Phase
3 release evidence. The next implementation slice is transactional sender
projection and branded email-domain reconciliation.

### 1.6 Engineering checkpoint — 17 August 2026, transactional mail

The platform-sender transactional-mail foundation is now implemented:

- the optional `mb_email_bridge` intercepts only approved webshop order,
  invoice, shipment and return messages, preserves rendered Odoo content and
  attachments, and authenticates with the exact workshop credential;
- a stable source key makes submission idempotent before Odoo marks the mail
  sent, while a bounded control-plane outbox retains provider submission and
  delivery state;
- the isolated mail gateway accepts the visible artisan sender name and
  verified reply-to while retaining the fixed MakersBrain sending address and
  Scaleway TEM credential boundary;
- signed, project/domain-scoped provider events are journaled once and
  projected through a separate authenticated control route;
- delivered, deferred, bounced, complained and suppressed states are durable,
  and hard delivery failures create a tenant-scoped do-not-send record before
  another message can be queued to that recipient;
- runtime releases receive the exact tenant bridge token mount required for
  outbound Odoo submissions.

Verification checkpoint:

- 130 control-plane Rust library tests and strict Clippy pass;
- migrations through `0037_transactional_mail_events` pass against disposable
  PostgreSQL, including tenant/source idempotency and scope constraints;
- fresh Odoo `19.0-20260803` installation runs the two focused
  `mb_email_bridge` post-tests with zero failures;
- Ruff, addon graph, translation/source validation, Svelte checking and
  `git diff --check` pass;
- the repository-wide `make check` remains blocked only by the previously
  documented unrelated `mb_brand` SCSS token mismatch.

Production TEM delivery and bounce/complaint drills remain release gates. The
next implementation slice completed the branded sender-domain foundation
described below.

### 1.7 Engineering checkpoint — 17 August 2026, branded sender domains

The branded sender-domain foundation is now implemented:

- migration `0038_webshop_email_domains` owns globally unique sender-domain
  claims and separates desired state from provider, DNS, test-delivery and
  activation evidence;
- the Scaleway TEM adapter registers, checks, observes and revokes domains at
  the pinned Paris endpoint, and idempotently provisions/deletes the exact
  per-domain SNS webhook, without retaining provider error text;
- five-minute durable reconciliation publishes provider SPF, DKIM and DMARC
  records and refuses activation until all three are valid and an exact-domain
  test message has a delivered event;
- transactional sends select the active verified artisan address and provider
  domain ID, while every non-active or disconnected state automatically falls
  back to the fixed MakersBrain sender;
- delivery events are bound to the outbox message and provider domain before
  they can satisfy the test gate, and existing event journals remain readable;
- the workshop Domains screen now provides sender registration, copyable DNS
  records, per-record status, manual recheck, test evidence and safe disconnect.

Verification checkpoint:

- 133 control-plane Rust library tests and strict Clippy pass;
- migration `0038` and its active-evidence/global-claim constraints pass
  against disposable PostgreSQL;
- the generated browser client and Svelte check pass with zero errors or
  warnings;
- shell/JSON configuration validation and `git diff --check` pass.

This is production-shaped but not provider-qualified: staging Scaleway
credentials, public DNS propagation, inbox placement, bounce/complaint drills
and revocation failure tests remain
release evidence. At this checkpoint, the broader paid-release blockers were
the live payment journey, carrier account qualification, onboarding recovery
diagnostics and two-tenant browser/accessibility/load qualification; section
1.8 records the subsequent local onboarding and accessibility completion.

### 1.8 Engineering checkpoint — 17 August 2026, paid-release local completion

The remaining locally implementable paid-release slices are now present:

- SumUp settlement is read back from the provider before state transition;
  successful Odoo post-processing creates the order reservation and invoice
  once, while a payment arriving after hold expiry creates one durable
  merchant-visible fulfil-or-refund exception;
- migration `0039_webshop_onboarding` persists resumable onboarding state,
  observed readiness, Odoo issues, operation linkage and completion evidence;
- idempotent refresh and completion commands run through the standard durable
  command ledger and reconciliation worker, using a tenant-scoped Odoo status
  boundary rather than trusting browser assertions;
- merchant and operator webshop dashboards combine onboarding, payment,
  shipping, return, domain, sender-domain, transactional-mail and dead-letter
  issues into bounded recovery actions without exposing provider payloads;
- the module screen offers explicit merchant deactivation and reactivation.
  Restriction closes the storefront but retains Odoo configuration and history;
  external domains and mail remain separate control-plane resources;
- v1 deliberately supports no operator overlay-uninstall path. The webshop
  overlay owns historical return, stock-hold and payment-exception records, so
  the evidence-gated policy retains it restricted until harmless uninstall and
  reinstallation can be proven;
- local Chromium QA covers desktop and mobile layouts. Storefront accessibility
  fixes for heading order and the price-range control raise the automated
  Lighthouse accessibility score to 100/100.

Final local verification is the regression evidence recorded in section 1.3:
581 fresh-install Odoo tests and the all-addon upgrade pass; 135 Rust unit and
17 PostgreSQL integration tests pass; Svelte, OpenAPI, contract, lint,
translation and repository consistency gates pass.

This checkpoint completes implementation, not paid-release qualification. The
remaining evidence requires external state that is absent from this workspace:
real or staging Cloudflare, Scaleway TEM/DNS, SumUp and Boxtal accounts; a
deployed two-tenant exact-host TLS/isolation environment; and a
production-like multiworker load environment. Those checks remain mandatory
before the first paid release. The signed staging qualification contract now
requires five independent webshop evidence files rather than allowing a broad
provider attestation to cover them; the exact pass conditions are recorded in
`control-plane/docs/runbooks/webshop-paid-release-qualification.md`.

### 1.9 Engineering checkpoint — 17 August 2026, merchant SMTP

Merchant-owned SMTP is now a supported alternative to the MakersBrain relay:

- the Domains screen accepts an SMTP hostname, port, username, one-time
  password, From address and either STARTTLS or implicit SSL/TLS;
- both modes use Odoo's certificate-validating `*_strict` transports. Plaintext
  SMTP, certificate-skipping modes, IP literals, reserved names and SMTP hosts
  that resolve to non-public addresses are rejected;
- a candidate connection is tested through authentication, MAIL FROM, RCPT TO
  and DATA readiness before it becomes active. A failed rotation leaves the
  previous transport and credential untouched;
- the password crosses the authenticated tenant boundary only on configuration,
  is stored in Odoo's system-only SMTP password field, is excluded from command
  receipts and API responses, and all configuration responses are `no-store`;
- transport selection is explicit. Approved webshop mail uses either the durable
  MakersBrain relay or native Odoo SMTP, and readiness requires the selected
  route to be fully configured with certificate validation;
- resetting SMTP deletes the managed Odoo mail-server record and immediately
  restores the platform relay.

Verification adds six focused `mb_email_bridge` tests and passes the focused
`mb_webshop` suite on fresh Odoo installation. All 136 Rust tests, the generated
OpenAPI/client contract, Svelte check/build, addon and translation checks,
focused Ruff, all-addon Odoo upgrade and `git diff --check` pass.

A subsequent credential audit found usable SumUp and Boxtal sandbox accounts.
Read-only authentication returned HTTP 200 for both. The SumUp sandbox first
completed a hosted-checkout create/read/deactivate cycle, then a headless
browser used the provider's successful test card to reach authoritative
`PAID`/`SUCCESSFUL`. A €20 sandbox payment met the provider's minimum refund
threshold; the refund endpoint returned HTTP 201 and the transaction read-back
contained a refund event. These are simulated sandbox transactions, not real
funds. A subsequent scratch-topology journey placed a real Odoo webshop stock
hold and payment transaction behind an ephemeral public HTTPS tunnel. SumUp's
provider callback arrived without a manual poll and changed the Odoo
transaction to `done`; standard post-processing produced one confirmed order,
converted hold, stock move, posted invoice and payment with no exception. Two
public webhook replays retained those exact counts. The tunnel and live
credential projection were then removed, the provider disabled and its scratch
credential fields cleared. This is strong integration evidence, but not the
signed qualification artifact for an immutable deployed staging release.
The Boxtal sandbox subsequently used an official Colissimo offer code and the
adapter's exact v3.1 payload to create two synthetic, no-charge orders. It
returned valid PDF labels; a temporary public receiver obtained both
`DOCUMENT_CREATED` and `TRACKING_CHANGED` events whose HMAC-SHA256 signatures
verified against the scoped webhook secret. Both test subscriptions were
deleted and the provider accepted order cancellation. This proves provider
order/label/tracking mechanics, but not their projection through an immutable
deployed Odoo release or production commercial readiness.

Provider-access update on 17 August 2026: protected, expiring runtime
credentials now exist for staging Scaleway sender-domain/webhook enrolment and
for staging and production Cloudflare Custom Hostnames. All three files are
mode `0600`. Read-only calls to the exact scoped product APIs succeed: staging
Scaleway domain and webhook lists return HTTP 200, and each Cloudflare token can
list Custom Hostnames only through its intended zone endpoint. No provider
resource was created or changed during this check, and no secret value was
printed or copied into the repository. This removes the provider-credential
acquisition blocker; it does not constitute paid-release evidence because no
digest-pinned staging release, two synthetic tenants, public staging DNS/TLS or
qualification artifact currently exists.

## 2. Product boundary

The webshop is an optional **sales channel**, not a second commerce system.

Odoo remains authoritative for:

- products and variants;
- one-of-one ceramic pieces;
- prices and taxes;
- inventory and reservations;
- production-lot traceability;
- customers;
- quotations and sales orders;
- payments, refunds, delivery and invoicing.

The storefront reads and writes through high-level MakersBrain services. It must not maintain a separate authoritative product, stock or order database.

The MakersBrain control plane remains authoritative for:

- tenant identity and Odoo database routing;
- feature subscriptions and module lifecycle;
- subdomain allocation;
- custom-domain verification and hostname routing;
- certificate state;
- domain registration and renewal state;
- email-domain verification;
- mailbox subscriptions and provisioning;
- asynchronous provisioning jobs and audit logs.

## 3. Module architecture

Use several small `mb_*` add-ons rather than one module that mixes unrelated
responsibilities. Reuse the models and dependency direction already implemented
in this repository. Do not introduce parallel `makersbrain_core` or
`makersbrain_commerce` foundations.

| Module | Required | Purpose |
|---|---:|---|
| Existing Odoo commerce models | Yes | Authoritative products, stock, sales, payments, delivery and website-commerce behavior |
| `mb_workshop_base` | Existing | Craft-neutral workshop foundation; no webshop dependency may be added here |
| Existing `mb_commercial_operations*` modules | Existing where applicable | Reuse proven sale, stock and operational seams when the webshop has a concrete relationship to them; do not turn them into a second commerce system |
| `mb_webshop` | Optional | One switchable pack over Odoo Website Builder, commerce, stock, delivery and collection; owns craft presets, snippets and storefront gating |
| `mb_webshop_ceramics` | Add only when implemented | Ceramic traceability, food-contact and firing presentation that genuinely requires ceramics dependencies |
| `mb_webshop_payment` | Add only when needed | Payment onboarding not already supplied by Odoo or `mb_payment_sumup` |
| `mb_webshop_carrier_*` | One per implemented carrier | Carrier label/API integration; do not create an empty generic delivery wrapper around Odoo `delivery` |
| `mb_email_bridge` | Optional | Connects Odoo events/templates to the control-plane transactional-email boundary |

Do not split theme, pickup or ordinary shipping configuration into separate
addons merely to mirror product nouns. Odoo already provides those boundaries.
A new addon is earned by an independent dependency or lifecycle requirement.

### Dependency rule

`mb_workshop_base`, the ceramics foundation and existing commercial-operation
modules must never depend on `mb_webshop`.

All website-specific fields, views, controllers, templates and automation belong
in the optional webshop modules. This keeps deactivation and any later removal
of MakersBrain-owned overlays from cascading into core ERP functionality.

Do not create a generic sales-channel abstraction speculatively. Phase 0 must
first map the webshop onto Odoo sale/stock records and the existing
`mb_commercial_operations*` seams. Add a small shared abstraction only when at
least two implemented channels require the same invariant and native Odoo
models do not already provide it.

### Product capability mapping

The artisan activates stable product capabilities, never Odoo module names.
The implemented versioned capability registry maps each capability to its Odoo
modules, services, dependencies, minimum application release and enforcement
adapter.

| Capability key | Product meaning | Initial realization |
|---|---|---|
| `webshop` | Storefront, checkout, platform hostname and platform transactional mail | **Implemented in registry v2:** `mb_webshop` plus `mb_email_bridge`; their manifests bring the required native Odoo modules |
| `webshop-ceramics` | Ceramic-specific product storytelling | Future `mb_webshop_ceramics`; add only with the ceramics capability dependency |
| `webshop-carrier-*` | A production carrier label/API integration | Future carrier-specific addon; depends on `webshop` |
| `webshop-branded-email` | Verified-domain transactional sending | Future `mb_email_bridge` plus the email-domain service; depends on `webshop` |

The registry uses `available -> requested -> installing -> enabled`, with
`failed` and `restricted` lifecycle states. Deactivation normally transitions
the capability to `restricted` and applies verified enforcement adapters while
preserving records.

### External resources are not Odoo module data

Domains, certificates, DNS zones, provider accounts and mailboxes must not be created as ordinary Odoo records whose uninstall hook deletes the external resource. Odoo may keep a local read-only projection of their state, but the control plane owns their lifecycle.

## 4. Tenant activation flow

### Step 1 — Plan and prerequisites

The control plane checks:

- tenant subscription permits a webshop;
- tenant database is healthy and on a supported schema version;
- company identity, country, currency and tax configuration exist;
- at least one payment or offline checkout method can be configured;
- the requested shop slug is valid and available.

### Step 2 — Reserve a default hostname

The artisan selects or accepts a slug such as `atelier-luna`.

The control plane reserves:

`atelier-luna.makersbrain.com`

Reservation must be globally unique, case-insensitive and protected against look-alike, offensive, system and previously abused names. Keep a tombstone after release so a recently used hostname cannot immediately be claimed by another tenant.

### Step 3 — Install the optional module set

Create an idempotent provisioning job:

1. admit the versioned `webshop` capability request and pin entitlement, application release and registry version;
2. acquire the existing tenant module-operation lock;
3. create a database backup or recovery checkpoint;
4. install `mb_webshop` and the selected extensions through the release-pinned module orchestrator;
5. run configuration seeds;
6. create the website and storefront configuration;
7. attach the default theme preset;
8. configure public access and security rules;
9. run storefront and enforcement-adapter health checks;
10. mark the capability enabled only after every required check succeeds.

Installation must be resumable. Retrying the job must not create duplicate websites, channels, menus, payment providers or email templates.

### Step 4 — Guided shop setup

The MakersBrain UI asks only for:

- shop name and short description;
- logo and brand colors;
- contact details;
- shipping countries or local pickup only;
- workshop/pickup address;
- payment method;
- legal pages and policies;
- which products are initially published.

Generate a complete usable shop from those answers. The initial artisan editor
is Odoo 19 Website Builder with a constrained MakersBrain starting experience.
Do not build a parallel page editor. If user testing proves the upstream
interface too broad, add a thin guided launcher and curated block library while
keeping Odoo's document format and editing engine.

## 5. Default subdomain architecture

Configure a wildcard DNS record and wildcard certificate for:

`*.makersbrain.com`

Every incoming request passes through the existing exact-host tenant gateway,
fed from a control-plane hostname registry when configuration changes:

`hostname -> tenant_id -> Odoo database/deployment -> website_id`

The existing gateway already renders exact-host configuration. For v1, update
that configuration asynchronously when a hostname reaches an active state;
do not add a database lookup to every storefront request. A dynamic edge lookup
is warranted only if measured hostname churn or fleet size makes rendered
configuration operationally inadequate.

Do not infer an Odoo database directly from an untrusted `Host` or `X-Forwarded-Host` header. Only the trusted edge/gateway may resolve a hostname to a tenant. Unknown, disabled or conflicting hostnames return a neutral error page and never expose Odoo's database selector.

The registry should contain:

- normalized hostname;
- tenant ID;
- website ID;
- hostname type (`platform_subdomain`, `custom_domain`, `redirect`);
- desired and observed state;
- verification method and timestamp;
- certificate state;
- canonical-host flag;
- redirect target;
- last health-check result;
- creation, suspension and release timestamps.

## 6. Custom-domain onboarding

Support two different paths.

### Phase-one path: customer already owns the domain

Example: the artisan owns `atelier-luna.fr`.

1. Artisan enters the domain.
2. Normalize it with IDNA handling and reject public suffixes, reserved names, IP addresses and MakersBrain-owned zones.
3. Ask the artisan to create a TXT record proving control.
4. After ownership verification, show the routing record:
   - normally `www.atelier-luna.fr CNAME shops.makersbrain.com`;
   - optionally apex-domain instructions supported by the selected edge provider.
5. Create the custom hostname and certificate request.
6. Poll DNS and certificate status asynchronously.
7. Run HTTP, TLS and tenant-routing tests.
8. Let the artisan select the canonical hostname.
9. Redirect all secondary hostnames to the canonical hostname.

Cloudflare for SaaS is a suitable edge option because it supports API-managed custom hostnames routed to a fallback origin. Apex domains require special handling: initially, prefer `www` plus an apex redirect unless the chosen service/plan supports the customer's apex configuration cleanly.

### Later path: purchase a domain through MakersBrain

Add this only after bring-your-own-domain is stable.

The onboarding flow requires:

- availability and live price lookup;
- registrant contact and consent;
- purchase confirmation;
- automatic renewal choice;
- expiry and payment-failure handling;
- DNS zone creation;
- webshop and email record creation;
- transfer-out/auth-code workflow;
- clear legal ownership and refund terms.

Cloudflare introduced a Registrar API in 2026 that can search availability, return pricing and register supported domains. Before relying on it commercially, verify reseller/registrant-account terms. Domain registration must be an adapter interface so another registrar can be added without changing webshop code.

### Domain state machine

Use explicit states:

`requested -> ownership_pending -> dns_pending -> certificate_pending -> testing -> active`

Failure and lifecycle states:

`action_required`, `suspended`, `renewal_failed`, `disconnecting`, `disconnected`, `transferring_out`.

Do not represent provisioning as a single boolean.

## 7. Email onboarding

Treat three services separately in both the UI and implementation.

### A. Platform transactional email

Used for order confirmations, password resets, delivery updates and invoices.

Initial default:

- visible sender: `Atelier Luna via MakersBrain`;
- sending domain controlled by MakersBrain;
- reply-to: artisan's verified contact address;
- bounce, complaint and suppression handling centralized by MakersBrain.

This is available immediately and does not require the artisan to configure DNS.

### B. Custom-domain transactional email

Example sender: `commandes@atelier-luna.fr`.

Onboarding:

1. create the email domain at the sending provider;
2. display or automatically create DKIM/SPF records;
3. recommend and validate DMARC;
4. poll provider and public DNS verification;
5. send a test message;
6. activate the sender only after verification;
7. continuously monitor loss of verification.

Resend is one possible adapter because it exposes domain creation and verification APIs. Keep this behind `TransactionalEmailProvider`; do not hard-code its identifiers into Odoo business records.

### C. Real mailbox hosting

Example mailbox: `bonjour@atelier-luna.fr`, accessible through webmail or an email client.

A transactional sender is not a mailbox. A mailbox requires:

- MX records;
- mailbox/user provisioning;
- password setup or SSO link;
- aliases such as `contact@`, `commandes@` and `factures@`;
- inbound spam and malware handling;
- storage quotas;
- IMAP/SMTP or hosted webmail;
- account recovery;
- migration and export;
- suspension and termination rules.

Implement mailbox hosting as an optional paid add-on through a provider adapter. Migadu exposes APIs for domains and mailbox-related management and is a possible early provider, subject to commercial/account-isolation validation.

### Recommended email product tiers

| Tier | Included capability |
|---|---|
| Webshop Basic | MakersBrain transactional sender plus artisan reply-to address |
| Branded Email | Transactional sending from a verified custom domain |
| Business Mailbox | One real mailbox plus configurable aliases |

Do not promise a mailbox when the product only provides outbound email or forwarding.

### D. Merchant SMTP credential

An artisan may instead connect an existing outbound SMTP account. This remains
transactional sending, not mailbox provisioning. Require certificate-validated
STARTTLS or implicit SSL/TLS, test the credential before activation, never
return the password after submission, and retain the MakersBrain relay as the
explicit fallback transport.

## 8. Storefront functional scope

### Committed good SaaS v1

- responsive theme with several presets;
- at least three production-quality themes with controlled editable sections;
- catalog, collection and product pages;
- variants and one-of-one pieces;
- stock visibility and atomic reservation;
- cart and guest checkout;
- customer accounts as an optional setting;
- Stripe-compatible payment flow plus offline/local pickup option;
- shipping zones, package rules and fixed/weight/price-threshold rates;
- at least one production carrier/label integration for the initial market;
- shipment tracking and customer delivery notifications;
- workshop pickup;
- order confirmation and merchant notification;
- merchant order operations: accept, prepare, pack, ship, cancel and partially refund;
- customer and merchant return flows with reason, approval, receipt and refund states;
- exchanges represented safely as return plus replacement order rather than rewriting fiscal history;
- legal pages, cookie consent and basic SEO;
- platform subdomain;
- connect an existing custom domain;
- platform transactional email;
- branded custom-domain transactional email;
- bounce, complaint and delivery-event operations;
- merchant onboarding checklist, progress recovery and support diagnostics;
- operational dashboards for failed payments, stuck shipments, returns, DNS and email problems;
- activate, restrict, resume and evidence-gated overlay-removal workflows.

### Mature Shopify-like horizon — optional, not committed to v1

- real mailbox add-on;
- domain purchase and renewal;
- unrestricted or third-party theme ecosystem;
- discount codes and gift cards;
- advanced promotion composition and discount functions;
- multiple carriers per European country and negotiated live rates;
- multilingual and multi-currency storefronts beyond the initial supported markets;
- EU-wide tax, OSS and cross-border operational expansion beyond the initial v1 countries;
- product drops and scheduled publication;
- advanced analytics, attribution and abandoned-cart automation;
- marketing journeys, segmentation and newsletter tooling;
- B2B pricing, wholesale and purchasing workflows;
- subscriptions, bundles, gift registries and marketplace sales channels;
- public app/extension marketplace;
- Shopify connector for artisans who retain an existing Shopify store.

These items remain technically possible because the v1 uses provider adapters, stable sales-channel models and optional Odoo modules. They are estimated and prioritized separately rather than being treated as hidden v1 requirements.

## 9. Uninstall and deactivation design

The normal user-facing lifecycle is **Deactivate webshop** and later
**Reactivate webshop**, not destructive uninstall.

### Deactivate

- prevent new checkout sessions;
- allow payment webhooks for existing orders to finish;
- show a maintenance/closed page or redirect;
- stop product publication jobs;
- retain shop configuration, domain mappings and historical URLs;
- keep ERP orders, customers, payments, invoices and stock untouched;
- retain the module for a reversible grace period.

### Exceptional overlay removal

Automatic capability restriction must not uninstall an Odoo module. In
particular, MakersBrain must not automatically uninstall Odoo's standard
`website` or `website_sale` modules. They may contain records or dependencies
outside the MakersBrain overlay.

After the grace period, an explicit operator-only removal workflow may remove
MakersBrain-owned webshop modules only after a rehearsed compatibility check:

- export or snapshot website configuration;
- convert website-specific references needed by historical orders into durable snapshots;
- prove no installed module depends on the selected MakersBrain-owned modules;
- uninstall only the selected `mb_webshop*` overlays, never standard Odoo modules as an implicit side effect;
- remove generated views, snippets, menus, scheduled actions and public controllers;
- preserve all core commerce and fiscal records;
- mark hostnames disconnected at the edge;
- keep custom domain and mailbox subscriptions separate until the artisan chooses what to do with them.

If the proof cannot establish harmless uninstall, retain the modules in a
restricted state. A dormant module is preferable to destructive cleanup.

### Domain choices during removal

Offer explicit independent choices:

- keep the custom domain in MakersBrain for email only;
- redirect it to another website;
- disconnect it but leave registration managed by MakersBrain;
- transfer the domain to the artisan;
- cancel renewal at expiry.

Never delete, allow expiry, or release a registered domain merely because an Odoo module was uninstalled.

### Email choices during removal

- keep the mailbox and custom-domain email;
- export/migrate mailbox data;
- replace the webshop sender with another service;
- cancel only after a stated retention period and confirmation.

## 10. Control-plane services and APIs

### Required logical control-plane modules

1. **Capability/Module Orchestrator extension** — extends the existing versioned capability activation, queue, lock and reconciliation paths.
2. **Hostname Registry and gateway extension** — maps verified storefront hostnames to tenant databases and websites through the existing exact-host routing boundary.
3. **Domain Service** — verification, DNS, registrar and renewal adapters.
4. **Certificate/Edge Adapter** — custom-hostname creation and observed TLS state.
5. **Email Domain Service** — transactional-domain verification and health.
6. **Mailbox Service** — domains, mailboxes, aliases, quotas and lifecycle.
7. **Provisioning Worker** — executes resumable workflows and reconciliation.
8. **Audit Service** — records every administrative and provider-side change.

These are ownership boundaries, not a requirement for eight new deployable
services. Implement them as modules in the existing API/worker topology first.
Introduce a separate process only when credential isolation, scaling or failure
containment requires it.

### Provider interfaces

Define stable internal interfaces:

- `EdgeHostnameProvider`
- `DNSProvider`
- `DomainRegistrar`
- `TransactionalEmailProvider`
- `MailboxProvider`

Provider webhooks must be authenticated, stored before processing and handled idempotently. A scheduled reconciliation job compares desired control-plane state with observed provider state so lost webhooks do not leave a tenant permanently stuck.

## 11. Security and reliability requirements

- Never expose Odoo database selection publicly.
- Resolve tenant exclusively through a trusted hostname registry.
- Make checkout inventory reservation atomic, especially for unique pieces.
- Use idempotency keys for checkout creation, payment webhooks and provisioning jobs.
- Encrypt provider credentials and separate them from tenant databases.
- Require step-up authentication for domain transfer, mailbox reset and destructive actions.
- Verify DNS ownership before attaching any custom hostname or sender domain.
- Prevent one tenant from claiming a hostname already owned by another tenant.
- Maintain audit records for DNS, domain, email and module lifecycle changes.
- Rate-limit public authentication, cart, checkout and contact endpoints.
- Ensure module upgrades run in staging/canary tenants before fleet rollout.
- Back up tenant databases before module removal or major schema migration.

## 12. Delivery plan

The phases below form the committed good SaaS v1 unless explicitly labelled optional. Their durations overlap only after the core architecture is proven; they should not be added as if every phase were perfectly sequential.

### Phase 0 — Architecture proof, 2–3 weeks

- record ADRs for hostname routing, capability/module mapping, payment-account ownership, checkout reservation, external-resource ownership and storefront configuration storage;
- map the proposed modules onto current Odoo models and `mb_*` add-ons, documenting every new dependency edge;
- confirm Odoo 19 Community dependency/uninstall behavior;
- prove trusted hostname-to-database routing for both platform and custom domains;
- create an empty optional module and exercise install/uninstall repeatedly;
- define checkout hold creation, expiry, payment completion and late-webhook behavior;
- first technical spike: prove a one-of-one product cannot be oversold by POS and webshop concurrently, including simultaneous requests, abandoned checkout expiry and a late payment webhook;
- select edge and email providers behind interfaces.

**Exit:** the ADRs are accepted; two tenant databases serve isolated stores
through two subdomains; capability activation is release-pinned and repeatable;
and the concurrency suite proves that exactly one of competing POS/webshop
sales can reserve the last unique piece.

### Phase 1 — Installable webshop foundation, 4–6 weeks

- implement module boundaries;
- provisioning jobs, locks, state and audit trail;
- default website creation;
- sales-channel model and website publication controls;
- MakersBrain starter theme;
- default subdomain allocation;
- health and readiness checks.

**Exit:** an administrator can activate and deactivate a functional tenant shop without manual Odoo intervention.

### Phase 2 — Commerce MVP, 6–10 weeks

- catalog, product page and collections;
- ceramic-specific product presentation;
- cart, checkout and stock reservation;
- payment onboarding and webhooks;
- shipping zones and workshop pickup;
- order/email workflows;
- simplified merchant setup UI.

**Exit:** an artisan can publish products and complete a real end-to-end order.

### Phase 3 — Existing custom domains, 3–5 weeks

- ownership verification;
- DNS guidance;
- custom-hostname/certificate automation;
- canonical-host and redirect management;
- monitoring and recovery UI.

**Exit:** a non-technical artisan can connect an existing domain without support intervention in the normal case.

### Phase 4 — Branded email, 3–5 weeks

- platform sender/reply-to workflow;
- custom transactional-domain verification;
- DKIM/SPF/DMARC status UI;
- bounce, complaint and suppression processing;
- provider reconciliation.

**Exit:** order email is reliable and optionally uses the artisan's verified domain.

### Phase 5 — Shipping, returns and merchant operations, 6–10 weeks

**Current evidence (2026-08-16):** the returns foundation is implemented and
fresh-install tested against Odoo `19.0-20260803`. It deliberately reuses the
native `stock.return.picking`, account reversal, portal-token and mail-queue
workflows rather than duplicating stock, fiscal, access or email logic. This
advances, but does not complete, the phase exit: carrier labels/tracking,
delivery exceptions, partial-credit-note merchant UX and provider email
delivery qualification remain.

- shipping profiles, package rules and rate calculation;
- production carrier/label integration;
- tracking and delivery exceptions;
- merchant fulfilment queue and batch operations;
- cancellations and partial refunds;
- customer return request and merchant approval workflows;
- received-item inspection, restocking and refund decisions;
- operational alerts and support diagnostics.

**Exit:** routine fulfilment and return cases can be completed without support staff editing Odoo records manually.

### Phase 6 — Themes and onboarding hardening, 4–7 weeks

**Current evidence (2026-08-17):** `mb_webshop` 19.0.1.5.0 exposes a scoped,
non-authoritative observation over native Odoo configuration. Migration `0039`
and the standard operation worker persist resumable progress, require current
evidence before completion, and feed merchant/operator dashboards with direct
recovery actions. Chromium desktop/mobile rendering and Lighthouse
accessibility (100/100) pass locally. The readiness language deliberately does
not claim DNS/TLS, provider webhooks, mail delivery or carrier credentials have
been exercised; those remain deployment qualification.

- at least three tested themes;
- controlled homepage, collection and editorial sections;
- mobile and accessibility QA;
- onboarding checklist with save/resume;
- sample catalog and preview mode;
- domain, payment, shipping and email readiness tests;
- safe theme upgrades that preserve merchant configuration.

**Exit:** a new artisan can launch a credible branded shop through self-service onboarding.

### Phase 7 — Deactivation and portability hardening, 2–4 weeks

**Current evidence (2026-08-17):** merchant deactivation and reactivation use
the existing durable capability restriction/enable operations. Automated Odoo
tests prove the storefront closes and reopens while ERP history, return-window
configuration and domain configuration remain. External domain and mail state
is not mutated. No overlay removal/reinstallation path is supported in v1:
the harmless-removal proof is not met, so the policy correctly retains the
overlay in a restricted state.

- grace-period deactivation;
- configuration export;
- historical data checks;
- independent domain/mailbox retention choices;
- automated restriction/reactivation tests;
- evidence-gated overlay removal/reinstallation tests where harmless removal has been proven.

**Exit:** the webshop can be restricted and reactivated without corrupting the
artisan's ERP history or losing external assets; any supported overlay-removal
path proves the same property.

### Optional post-v1 — Domain sales and mailbox hosting, 5–8 weeks

- registrar adapter, registration and renewals;
- ownership/transfer policies;
- mailbox provider adapter;
- mailbox, alias, password and migration workflows;
- billing and service suspension rules.

**Exit:** MakersBrain can sell a domain and mailbox add-on with explicit ownership and portability.

## 13. Suggested initial team

- two Odoo/backend engineers, including at least one senior engineer responsible for sale, stock and payment invariants;
- one frontend/Owl engineer;
- one platform engineer for routing, DNS, TLS, domains and email;
- one additional engineer focused on integrations, test automation or merchant operations as the delivery phase requires;
- part-time product/design and QA support, with dedicated QA capacity during payment, fulfilment and rollout gates.

The committed good SaaS v1 represents approximately 9–14 months for the recommended experienced team, including production hardening, staged rollout and operational tooling. A demo can be produced much earlier, but domains, payments, shipping, returns, email deliverability and reversible lifecycle operations determine whether the product is safe to sell.

## 14. Acceptance criteria for the first paid release

Status below distinguishes implementation evidence from the live qualification
required to sell the product. **Local verified** is not a production sign-off.

| Criterion | Status on 17 August 2026 |
|---|---|
| A tenant activates the webshop without staff running commands | **Local verified** — self-service command/UI uses the durable capability workflow |
| The default `atelier-xxx.makersbrain.com` hostname becomes reachable automatically | **Qualification required** — allocation, exact-host rendering and reconciliation are tested; staged public DNS/TLS reachability is not |
| Products and stock come directly from the tenant's Odoo database | **Local verified** |
| POS and webshop mutually exclude sale of the last unique piece | **Local verified** with real stock moves and quant reservations |
| Abandoned holds expire; late payment is recoverable without negative stock or duplicate fulfilment | **Local verified** |
| Successful checkout creates the correct order, payment, stock movement and invoice workflow | **Integration verified on scratch** through SumUp hosted payment, provider callback and real Odoo post-processing; exact-release staging evidence remains |
| Failed/repeated payment webhooks do not duplicate orders or payments | **Integration verified on scratch** — two public callback replays retained one fulfilment, invoice and payment; exact-release staging evidence remains |
| An artisan can connect and verify an existing custom domain | **Qualification required** — workflow and live DNS observation code are tested, but no staging zone has been exercised |
| TLS issuance and routing status are visible and recoverable | **Qualification required** — UI/reconciliation implemented; live Cloudflare TLS evidence absent |
| Transactional email has monitored delivery, bounce and complaint handling | **Qualification required** — durable event/suppression paths implemented; live Scaleway TEM drills absent |
| The artisan can purchase a shipping label, send tracking and handle a delivery exception | **Provider integration verified** — Boxtal sandbox order, valid PDF label, signed document/tracking events and cancellation pass; exact-release Odoo projection and a delivery-exception drill remain |
| Customer return through approval, receipt, restock and refund | **Local verified** |
| Three upgrade-safe themes with responsive and accessibility validation | **Local verified** — all-addon upgrade, desktop/mobile Chromium and Lighthouse 100/100 pass |
| Onboarding can be paused, resumed and completed without ordinary support | **Local verified** — persisted state, evidence gate, commands and merchant UI pass |
| Merchant/support dashboard exposes failed workflows and a recovery action | **Local verified** |
| Deactivation is immediate and reversible | **Local verified** |
| Any supported operator-only overlay removal preserves history and external assets | **Not applicable in v1** — no removal path is supported until harmless uninstall is proven; restriction retains the overlay and external resources |
| Reactivation, and reinstallation where supported, restores retained configuration | **Local verified for reactivation**; reinstallation is not supported in v1 |

Paid-release qualification therefore remains open until the five live evidence
groups are complete: Cloudflare DNS/TLS, Scaleway TEM/DNS and delivery events,
the exact-release staged SumUp journey, exact-release Boxtal/Odoo projection
and a delivery-exception drill, and a deployed two-tenant isolation plus
production-like multiworker load exercise.

## 15. Immediate engineering decisions

Before implementation, record decisions for:

1. hostname-to-Odoo-database routing mechanism;
2. capability-to-module/service mapping and enforcement adapters;
3. checkout hold, expiry and late-payment behavior for unique stock;
4. module installation orchestration and the exact boundary of any operator-only uninstall;
5. storefront configuration ownership and upgrade-safe theme schema;
6. edge/custom-hostname provider;
7. payment-account model: platform account versus merchant-connected account;
8. transactional sender provider;
9. whether mailbox hosting is launch scope or a later add-on;
10. who legally owns and controls domains purchased through MakersBrain;
11. webshop deactivation grace period and retained configuration duration;
12. whether the first release supports only France/euro or broader EU commerce;
13. which records and durable snapshots are required if a MakersBrain webshop overlay is ever removed.

## 16. Recommended first-release choices

- Default hostname: `atelier-<slug>.makersbrain.com`.
- Existing custom domains: supported.
- Domain purchase: postpone until the storefront and custom-domain connection are stable.
- Email: platform transactional sending with verified reply-to at launch.
- Branded-domain transactional sending: included in the committed good SaaS v1.
- Returns, production shipping and merchant operational tooling: included in the committed good SaaS v1.
- Three production-quality themes and self-service onboarding: included in the committed good SaaS v1.
- Real mailbox: optional post-v1 paid add-on, never implied by webshop activation.
- Edge: adapter around a managed custom-hostname service such as Cloudflare for SaaS.
- Storefront: Odoo `website_sale` data and checkout, presented through MakersBrain themes and simplified administration.
- Lifecycle policy: deactivate into a verified restricted state, retain configuration for at least 30 days and allow reactivation; any later overlay removal is operator-only and evidence-gated. Standard Odoo website modules, domains and mailboxes are never removed implicitly.

## 17. Scope-control rule

Every requested capability must be classified before implementation:

1. **V1 required** — necessary for domains, onboarding, shipping, email, returns, themes or reliable merchant operations.
2. **V1 quality requirement** — security, accessibility, observability, recovery or compliance needed to operate the required feature safely.
3. **Mature-product candidate** — valuable Shopify-like enhancement that can be estimated independently.
4. **Not planned** — ecosystem parity or edge-case complexity without demonstrated artisan demand.

A mature-product candidate enters the v1 plan only by explicitly removing equivalent effort elsewhere or changing the committed delivery range. Architecture should leave room for mature features, but no placeholder framework should be built unless v1 uses it.

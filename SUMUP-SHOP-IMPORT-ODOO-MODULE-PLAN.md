# Shop Catalogue Import Odoo Module Plan

## Goal

Build a review-first Odoo import capability for a workshop's own shop catalogue.
The inputs are artifacts produced by the `catalogue-ceramics` scraper pipeline,
not official exports supplied by SumUp or another commerce platform. The first
supported inputs are the existing `ceramics.catalogue_item.v2` dump (`.ndjson`
or `.ndjson.gz`) and the scraper's flattened catalogue CSV. The design must allow
additional scraper output formats without putting provider-specific rules into
the product and stock ingestion code.

The import must never create products or change inventory during file parsing.
A user first uploads and reviews a staged batch, resolves errors, chooses which
rows and changes to accept, and then explicitly confirms ingestion.

## Architectural decision

The operational workflow belongs in an Odoo addon, provisionally named
`mb_shop_import`. Provider format support remains in this generic core. Optional
craft and operational integrations are separate addons:

- `mb_shop_import_ceramics` depends on `mb_shop_import` and `mb_ceramics_base`
  and supplies ceramic category defaults;
- `mb_shop_import_depot` depends on `mb_shop_import` and `mb_depot` and supplies
  dépôt-specific validation and integration tests.

The integration addons may auto-install when both sides are installed. The core
import capability must not force every workshop to install ceramics or
dépôt-vente.

Odoo owns:

- uploaded source files and import audit history;
- parsing, normalization, validation, and review state;
- product matching and product field policy;
- product, category, tag, image, and inventory writes;
- tenant-local permissions and business auditability.

The control plane owns only capability lifecycle:

- expose a stable `shop_catalogue_import` capability;
- install or restrict the addon through the capability registry;
- verify addon/version health;
- optionally report failed background work and enforce storage quotas.

The control plane must not parse workshop catalogues or write Odoo products. It
does not own the tenant's product, tax, stock, warehouse, or depot semantics.

Capability restriction must preserve audit data. `mb_shop_import` supplies a
capability-enforcement adapter that blocks new uploads, parsing, review edits,
confirmation, retries, and image downloads while restricted, but leaves existing
batches, lines, bindings, and attachments readable to otherwise authorized
users. Restriction never uninstalls the addon or deletes import history.

## User workflow

1. Open **Inventory > Products > Shop imports**.
2. Create an import batch and upload a supported file.
3. Choose or confirm the detected format and source shop.
4. Choose import policy:
   - target stock location;
   - target product category;
   - published-price tax basis;
   - applicable Odoo sales tax when the basis is taxable;
   - whether existing prices may be updated;
   - whether images may be downloaded or overwritten.
5. Parse the file. This creates staging lines only.
6. Review summary counts, warnings, errors, matches, and proposed changes.
7. Edit permitted normalized values and select which valid lines to ingest.
8. Run preflight validation again.
9. Confirm the import.
10. Open the affected products or download/view the permanent result report.

The batch remains available after logout and can be reviewed by a different
authorized user. It is not implemented solely as a `TransientModel` wizard.

## Data model

### `mb.shop.import.batch`

Persistent model representing one uploaded snapshot.

Suggested fields:

- `name`: generated sequence and optional user label;
- `company_id`: required, indexed, and used in every access rule;
- `attachment_id`: original file stored as an Odoo attachment;
- `file_name`, `file_size`, `file_sha256`;
- `adapter_key`, `adapter_version`;
- `source_id`, identifying one stable company-owned scraper source;
- `source_snapshot_at` when present in the input;
- `state`: `uploaded`, `parsed`, `review`, `ready`, `importing`, `done`, `failed`,
  or `cancelled`;
- `target_location_id`;
- `product_category_id`;
- `currency_id`;
- `price_tax_basis`: `tax_included`, `tax_excluded`, or `no_sales_tax`;
- `sales_tax_ids`, explicitly selected when taxes apply;
- `update_existing_prices`, `import_images`, `overwrite_images`;
- counters for total, selected, create, update, skip, warning, and error lines;
- `parsed_at`, `validated_at`, `imported_at`, `imported_by_id`;
- `warnings_acknowledged_at`, `warnings_acknowledged_by_id`;
- `result_summary` and a sanitized technical failure message;
- `line_ids` and `affected_product_tmpl_ids`.

Add chatter tracking for state changes, policy choices, and the final result.
The original attachment and normalized lines form the audit record.

Bind the attachment to the batch with `res_model` and `res_id`; do not rely on
an otherwise unrelated attachment record. Define a retention policy that keeps
the normalized result and checksum permanently while allowing an authorized
manager to purge the original attachment and bounded raw records after the
configured audit period.

### `mb.shop.source`

Persistent, company-owned identity for one scraper source/shop:

- `company_id`, required and indexed;
- `provider_key`, such as `sumup`;
- immutable `source_key` emitted by the scraper, such as `emily-alarcon`;
- `name`, homepage URL, active flag, and last-seen timestamp;
- unique `(company_id, provider_key, source_key)`.

Users select or confirm this record during review. Renaming its display label
does not change binding identity.

### `mb.shop.import.line`

Persistent model representing one sellable source variant.

Suggested fields:

- `batch_id`, `company_id`, sequence;
- `raw_record` as JSON, subject to a size bound;
- provider `external_id` and `parent_external_id`;
- normalized `name`, `variant_title`, `default_code`, and `product_url`;
- `description`, `category_path`, and proposed merchandising tag;
- `price`, `currency_id`, and published VAT status;
- `stock_quantity` plus `stock_is_tracked`;
- `reviewed_quantity` and `reviewed_reserved_quantity`, the target-location
  quant values observed by the last successful preflight;
- `availability`;
- `image_url` and optional image preview status;
- `is_service`;
- `matched_product_id` and match method;
- `action`: `create`, `update`, or `skip`;
- per-field booleans for accepted changes where needed;
- `status`: `valid`, `warning`, `error`, or `ingested`;
- validation messages and final product reference.

Normalized editable fields must be separate from the immutable raw record.
Source identity fields and raw records are readonly after parsing. Normalized
fields are editable only in review states, and every edit invalidates the prior
preflight and warning acknowledgement.

### External identity

Add a durable mapping model rather than relying only on a generated SKU:

`mb.shop.product.binding`

- unique `(source_id, external_id)`;
- `product_id`, because scraper rows and stock quantities identify sellable
  variants (`product.product`), not templates;
- last source URL, adapter version, and last-seen timestamp.

Matching order:

1. exact source binding;
2. exact generated/default code on a product owned by the batch company;
3. explicit user match during review;
4. otherwise propose creation.

Never automatically match on title alone. Duplicate titles occur in the Emily
Alarcon SumUp data and are normal for handmade pieces.

The first version deliberately creates one single-variant Odoo template per
scraper variant. Binding to `product.product` keeps the identity correct if a
template later acquires attributes. Supporting one source parent with multiple
Odoo variants requires a separate parent binding and is a future, explicit
feature rather than an accidental change in matching behavior.

## Adapter boundary

Define a pure Python adapter protocol with no product, stock, category, or other
business-record writes. The batch action persists its returned staging lines:

```python
class ShopImportAdapter:
    key = "provider_format"
    version = 1

    def detect(self, filename, media_type, sample): ...
    def parse(self, stream): ...
    def normalize(self, source_record): ...
```

Adapters return a common normalized record. The ingestion service consumes only
that normalized representation.

Initial adapters:

1. `catalogue_v2`: `.ndjson` and `.ndjson.gz` records in
   `ceramics.catalogue_item.v2` format;
2. `catalogue_csv`: the flattened CSV written by the scraper artifact pipeline;
3. `generic_csv`: a later mapping-based adapter, not part of the first delivery
   unless a real second format is available as a fixture.

Do not describe `catalogue_csv` as an official SumUp export. Its schema is owned
and versioned by `catalogue-ceramics`. Because the flattened CSV lacks the exact
variant external ID present in v2 NDJSON, its adapter must either consume a
future versioned external-ID column or derive and visibly flag a deterministic
fallback identity from source, product URL, and variant title. A fallback match
requires review and must never silently replace an existing exact binding.

Reject mixed sources, mixed currencies, unknown record versions, duplicate
external IDs, malformed compressed input, and files exceeding configured limits.
Detection must never silently choose an adapter when two adapters claim the file.

## Addon dependencies

Keep dependency direction explicit:

- `mb_shop_import`: `mail`, `stock`, `sale_stock`, and `account` for chatter,
  inventory, delivery invoicing policy, and sales taxes;
- `mb_shop_import_ceramics`: `mb_shop_import` and `mb_ceramics_base`;
- `mb_shop_import_depot`: `mb_shop_import` and `mb_depot`.

The generic addon must not import Python models or XML IDs from either optional
integration. Integration behavior is added by normal Odoo model inheritance in
the dependent addon.

## Product policy

### Physical shop products

Proposed and enforced on creation:

```text
type = consu
is_storable = true
sale_ok = true
purchase_ok = false
invoice_policy = delivery
company_id = batch.company_id
```

`invoice_policy = delivery` is a depot-sale invariant. Re-import may repair that
field on bound physical products after showing it in the review diff.

Do not automatically enable Make to Order, Buy, or another replenishment route.
These records represent finished stock already made by the workshop.

### Services

Categories configured as services, initially `Cours et ateliers`, propose:

```text
type = service
is_storable = false
sale_ok = true
purchase_ok = false
company_id = batch.company_id
```

They receive no inventory adjustment and are not eligible for depot placement.

### Lot and serial tracking

Default to `tracking = none`. The source snapshot has variant quantities but no
physical lot or serial identifiers. Dépôt-vente supports untracked products.

Serial tracking may be added as an explicit advanced policy only when the review
workflow can also create or select one serial per physical unit. Never turn on
serial tracking while importing quantity without corresponding serial records.

### Taxes and prices

Never infer tax treatment merely from the provider name or country.

- `no_sales_tax`: keep the published customer price and clear sales taxes;
- `tax_included`: use the explicitly selected Odoo sales tax to compute the net
  list price from the published customer price;
- `tax_excluded`: keep the published net value and apply the explicitly selected
  Odoo sales tax;

An Odoo `account.tax` selection, not a numeric VAT rate alone, controls taxable
imports. Validate that every selected tax belongs to the batch company, has sale
scope, and is compatible with the company currency and price basis. Use Odoo's
tax computation rather than hand-written division. Review shows source price,
stored list price, taxes, and resulting customer price before ingestion.

Refuse import when source and company currency disagree unless an explicit,
auditable conversion policy is implemented later.

On re-import, preserve artisan-edited names, categories, and prices by default.
Price replacement requires an explicit batch option and remains visible per line.

## Categories and tags

- Require an explicit batch `product_category_id` for physical products. Do not
  create or find accounting categories by translated names.
- When `mb_shop_import_ceramics` is installed, default that field through the
  stable XML ID `mb_ceramics_base.categ_finished_ceramics`.
- Treat source shop departments as product tags, because departments such as
  `vente flash` are merchandising dimensions rather than accounting categories.
- Preserve manually added tags; add the current source tag without replacing
  unrelated tags.
- Make service-category classification configurable rather than permanently
  embedding French labels in the ingestion service.

## Inventory ingestion

Treat imported stock as a snapshot, not as a purchase or production movement.

- Require an internal target location such as `AT/Stock/Finished`.
- Use Odoo's inventory adjustment mechanism and normal ORM methods.
- Update stock only after product ingestion succeeds.
- `stock_is_tracked = false` means leave stock unchanged, not set it to zero.
- A tracked source quantity of zero is an intentional zero and must be shown in
  review.
- Do not clear other atelier, work-in-progress, market, or depot locations.
- Never touch stock already held by a depot warehouse.
- Record before and after quantities in the import result.
- Store the target-location on-hand and reserved quantities observed by preflight
  on every selected tracked line.
- At confirmation, lock/re-read the relevant product and quant rows and refuse
  the batch if on-hand or reserved quantity changed after preflight. Lock the
  product row as the serialization point even when no quant row exists yet. The
  user must refresh, inspect the new difference, and approve it again.
- Warn or refuse when the scraper snapshot is older than a configurable maximum
  age. A stale external snapshot must not resurrect stock already sold in Odoo.

For v2 dumps, derive the effective batch snapshot from the records' `fetched_at`
values and retain the observed minimum/maximum range in the audit summary. Do
not substitute the upload time for an unknown source snapshot time.

The confirmation transaction is atomic for product and stock writes in the first
version. Run ingestion inside a database savepoint. Catch failures outside that
savepoint so its business writes roll back, then persist the sanitized `failed`
state and result on the batch in the outer request transaction. Do not commit
inside model methods. A future large-file mode may use bounded chunks, but only
with explicit partial completion state and safe retry semantics.

## Dépôt-vente integration

There is no per-product "depot" flag. A physical product is eligible when it is:

- saleable;
- storable;
- invoiced on delivered quantities;
- present as available stock in the selected depot warehouse when recording a
  depot sale.

The depot itself is a `stock.warehouse` with `is_depot = true`. Imported stock
starts at the atelier. A normal **Mise en dépôt** internal transfer moves selected
pieces to the gallery warehouse. The import module must not place products in a
depot automatically.

## Images and network safety

Image import is optional and happens only after product confirmation.

- Permit HTTPS only.
- Allow configured provider image hosts, initially the SumUp image host.
- Resolve and validate destinations to prevent loopback, link-local, private,
  metadata-service, and internal-network requests.
- Limit redirects, response bytes, duration, and accepted image media types.
- Decode and validate the image before assigning `image_1920`.
- Do not overwrite an existing image unless explicitly selected.
- Store per-line download failures without undoing an otherwise successful
  product import; images are a separate post-import phase.

If image volume later makes request-time processing unsuitable, move only the
download execution to a tenant-scoped worker. Odoo remains the owner of the job,
policy, review decision, and final attachment/product write.

Validate every redirect destination, not only the initial URL. Prevent DNS
rebinding by connecting to a resolved, validated public address while preserving
the expected HTTPS host name for TLS verification; do not validate one address
and then allow the HTTP client to resolve a different address for the request.

## Security and access

Create two groups:

- **Shop Import Reviewer**: upload, parse, edit staging lines, and review;
- **Shop Import Manager**: all reviewer rights plus confirm ingestion, change
  stock, and overwrite prices/images.

Rules and constraints:

- every batch, source, line, binding, imported product, location, and attachment
  is company-bound;
- reviewers cannot select a location outside their allowed company;
- only managers can ingest or retry a failed batch;
- imported files have bounded size and decompressed size;
- CSV formula-like values remain data and are never evaluated;
- raw errors shown to users must not expose credentials or internal endpoints;
- state transitions are server-enforced, not just hidden by views.
- imported templates explicitly receive `company_id = batch.company_id`; matching
  does not silently adopt a shared or another-company product;
- database uniqueness constraints, plus confirmation-time locking, arbitrate two
  concurrent batches attempting to create the same binding.

## Review interface

Provide batch kanban/list and a form containing:

- upload and policy header;
- summary cards for create, update, skip, warning, and error counts;
- editable staging list with selection and proposed action;
- filters for errors, warnings, new, matched, price changes, stock changes,
  untracked stock, services, duplicates, and missing images;
- source value, current Odoo value, and accepted value for material differences;
- image thumbnail where safely available;
- **Parse**, **Validate**, **Select valid**, **Import selected**, **Retry images**,
  and **Open affected products** actions.

The import button remains unavailable while any selected line has an error.
Warnings require acknowledgement but do not necessarily block ingestion.
Acknowledgement records the user and time and becomes invalid after a line or
policy edit, reparsing, or a changed preflight result.

## Reuse of the current script

Refactor, rather than discard, `scripts/import_shop_catalogue.py`:

- move pure dump reading, SKU generation, normalization, and validation into
  addon-owned testable helpers/adapters;
- keep the script temporarily as a thin maintenance CLI using the same
  normalized contract;
- replace generated `odoo shell` ingestion with the addon service once deployed;
- retain the Emily Alarcon normalized fixture for regression tests;
- deprecate the direct-write CLI only after the Odoo UI covers dry-run, review,
  stock, and images.

## Test plan

### Adapter unit tests

- detect catalogue NDJSON, NDJSON.GZ, and scraper CSV correctly;
- reject empty, corrupt, oversized, mixed-source, and mixed-currency files;
- preserve Unicode names and quoted CSV fields;
- produce distinct variants and stable external identities;
- distinguish tracked zero from untracked/null stock;
- classify configured service categories;
- reject duplicate external IDs and generated code collisions.

### Odoo transaction tests

- parsing creates no product, quant, category, or tag;
- importing selected lines only affects selected lines;
- physical and service flags match the policies above;
- created templates and variants belong to the batch company;
- physical products always use `invoice_policy = delivery`;
- imported products are not purchasable and have no MTO/Buy route;
- source binding makes re-import idempotent;
- bindings target the exact `product.product` variant;
- title changes do not duplicate a bound product;
- manual name/category changes survive re-import;
- price changes require opt-in;
- tax-inclusive and tax-exclusive previews use the selected company sales tax
  and reproduce the displayed customer price;
- the ceramics integration selects the canonical finished-ceramics XML-ID
  category without creating a parallel category;
- tracked stock is adjusted at the chosen location;
- untracked stock is untouched;
- depot and unrelated locations are untouched;
- an unexpected failure rolls back products and stock;
- a rolled-back ingestion persists the batch's sanitized failed result;
- confirmation refuses a stock line changed since preflight;
- confirmation refuses or warns about an expired source snapshot according to
  configured policy;
- concurrent batches cannot create duplicate source bindings;
- editing a normalized field invalidates preflight and warning acknowledgement;
- raw records and source identity cannot be edited after parsing;
- batch-bound attachments follow batch/company access rules;
- multi-company record rules prevent cross-tenant access.

### Capability restriction tests

- restriction blocks upload, parse, staging edits, confirmation, retry, and
  image retrieval;
- previously imported products and historical batches remain readable;
- restriction does not delete attachments, lines, bindings, or results;
- lifting restriction restores new-work actions without changing old data.

### Dépôt integration tests

- imported physical products appear in the placement catalogue;
- services do not appear there;
- a product moved into a depot can be selected for a depot sale;
- depot sale confirmation sources the depot warehouse;
- the product becomes invoiceable only after delivery;
- untracked and explicitly serial-tracked products both follow valid paths;
- the commission pricelist and statement use the imported list price.

### Image security tests

- reject non-HTTPS, private, loopback, link-local, oversized, redirect-loop, and
  non-image responses;
- reject a redirect or DNS-rebinding attempt that changes a validated public
  destination into an internal address;
- do not overwrite existing images without permission;
- image failure is recorded without corrupting product ingestion.

### Fixture acceptance test

Use
`../catalogue-ceramics/catalogue-dumps-new/emily-alarcon/emily-alarcon.ndjson.gz`
as the acceptance input. Expected staging summary at the time of this plan:

- 80 sellable source variant records;
- 76 `Ceramiques pour la maison`, 2 `vente flash`, 1 `Bijoux`, and 1 service;
- 77 physical products with counted stock;
- 94 counted physical units;
- 2 physical products whose stock is deliberately left unchanged;
- unique generated `EA-*` codes for all 80 records.

The fixture must be copied or reduced into a repository-safe test fixture rather
than making automated tests depend on a sibling working tree.

## Delivery phases

### Phase 1 — Domain and adapters

- scaffold `mb_shop_import` with manifest, security, menus, and persistent models;
- define the normalized record and adapter registry;
- implement catalogue v2 NDJSON/GZ and scraper CSV adapters;
- add file bounds, checksum, detection, parsing, and validation tests.

Exit criterion: Emily input parses into staging with the expected counts and no
Odoo product or stock writes.

### Phase 2 — Review and product ingestion

- implement batch and line review views;
- implement `mb.shop.source`, variant bindings, and deterministic matching;
- implement product/category/tag policies and review diffs;
- add atomic selected-line ingestion with savepoint failure recording and
  permanent summaries.

Exit criterion: reviewed products can be created and re-imported idempotently,
with correct sale, purchase, storage, and delivery-invoicing fields.

### Phase 3 — Inventory and dépôt integration

- add target-location policy and reviewed stock adjustments;
- add preflight baselines, locking, stale-snapshot policy, and lost-update
  protection;
- protect unrelated and depot locations;
- add `mb_shop_import_depot` placement and sale integration tests;
- expose before/after stock evidence.

Exit criterion: imported stock can move through atelier, depot placement, depot
sale, delivery, invoice, and statement without manual product-field repair.

### Phase 4 — Images and operational hardening

- implement safe image retrieval and retry;
- add audit/chatter details, retention controls, and failure recovery;
- add translation strings and French translations;
- add operator documentation and remove direct-write reliance from the CLI.

Exit criterion: a workshop manager can complete the Emily import through Odoo,
including review and optional images, without shell access.

### Phase 5 — Capability rollout

- add `shop_catalogue_import` to the capability registry;
- map it to `mb_shop_import` and its module dependencies;
- implement and test the read-preserving restriction adapter;
- verify install/restrict evidence through the existing control-plane bridge;
- roll out to a test tenant, then one production workshop, then general
  availability.

Exit criterion: the control plane can manage capability lifecycle without
handling catalogue data or performing product writes.

## Definition of done

- Uploading and parsing never mutates products or inventory.
- Every proposed mutation is reviewable before confirmation.
- All supported formats normalize through one ingestion contract.
- Re-import is idempotent through source bindings.
- Variant identities bind to `product.product`, under a stable company-owned
  scraper source.
- Physical and service products receive correct Odoo flags.
- Stock null and stock zero retain distinct meanings.
- Dépôt-vente works without product-field repair after import.
- Other locations and depot stock are never overwritten by the shop snapshot.
- Stock changed after review is never overwritten without a new preflight and
  approval.
- Source file, policies, reviewer, result, and affected products are auditable.
- Capability restriction stops new work without hiding or deleting audit data.
- Tests cover adapters, review, ingestion, stock, dépôt, security, and the Emily
  acceptance fixture.
- Control-plane work is limited to capability lifecycle and health.

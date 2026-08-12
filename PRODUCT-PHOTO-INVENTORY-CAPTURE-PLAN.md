# Product photo, barcode and supplier-lot capture for Odoo 19

- Status: development baseline completed; device validation, automatic crop
  selection and production provider approval remain release-gated
- Date: 12 August 2026
- Target: Odoo 19 Community, on-premise
- Addon: `mb_inventory_capture`
- Primary use case: receive glaze, clay and other workshop supplies from one or
  two phone photographs, identify the product, recover the supplier's batch/lot
  number and put the reviewed result into ordinary Odoo inventory

## Implementation record (12 August 2026)

Parts of the development baseline are implemented across this repository, the
ceramics catalogue, and `../makersbrain-infra`. This record describes only the
current code; later sections describe the target v19 design and release gates:

- `mb_inventory_capture` provides the Odoo 19 camera/upload action, worker-based
  near-live native decoding with two-frame consensus, still-image ZXing fallback,
  GS1/UPC-E parsing, quality guidance, reviewed rotated lot crops, image
  sanitization, non-destructive per-role retakes, immutable evidence, ambiguity
  review, retention, safe tracking cutover analysis, and verified application
  to exactly one native receipt move line.
- `mb_inventory_capture_catalogue` grounds exact GTIN and AI-suggested text
  searches through `mb_catalogue_sync`; the catalogue service exposes a
  checksum-validated exact barcode query.
- `mb_ai_bridge` provides the reusable provider-neutral Odoo boundary for
  bounded synchronous capabilities and idempotent descriptor-only jobs.
- the control plane provides the tenant-authenticated `inventory-capture`
  operation, digest-verified asset pull, idempotent callback, separate document
  extraction broker, fixed Azure model allowlist, schema-constrained multimodal
  fallback, native Azure-hosted/OpenAI/Gemini/Claude adapters with explicit
  primary/secondary routing, retry lineage, and separate Azure/AI monthly usage
  limits. Queue submission now returns the original operation for an identical
  idempotent replay, and durable callback checkpoints guarantee byte-equivalent
  OCR/multimodal callback replay after uncertain delivery. Its UPCitemDB adapter strips unsafe metadata before a shared
  PostgreSQL cache stores positive results for 30 days or negative results for
  24 hours; advisory locks coalesce concurrent misses.
- `../makersbrain-infra` already contains the development Document Intelligence
  account. Its secret-delivery move to the shared broker remains a reviewed
  infrastructure change; no Azure Vision resource should be created unless the
  conditional benchmark justifies one.
- the private six-photo ZIP is covered by a non-extracting sanitizer/evaluation
  harness and a committed ground-truth manifest; no photograph bytes are in Git.

The current Owl action samples bounded frames in a Web Worker, requires matching
recent reads, rejects stale lookup responses, keeps the preview open, and shows
quality/product/lot guidance. Local, catalogue and cached matches return in the
same scan action; a cache miss uses one bounded synchronous provider request
while the camera preview remains open. The user can continue with lot capture or
manual entry after a timeout or no-result. Moving cache misses to bus delivery is
a scale-up option, not part of the current baseline. It can also decode all codes returned for an
accepted still, require review when those codes resolve to different products,
create a
traceable user-selected color crop with a selected right-angle rotation,
optionally persist a linked black-and-white high-contrast OCR derivative, and
prefer reviewed crops for extraction while retaining the current front-label
image as product context. The color crop remains evidence sent to multimodal
models; the derivative is OCR-only. Automatic polygon detection/rectification,
manufacturer-specific overlays and automatic sharp-frame capture remain targets.
The extraction path is Azure Document Intelligence `prebuilt-read`, followed
conditionally by the configured multimodal primary/secondary route. The provider
adapters and cache are production code, but remain disabled until their external
service, terms, corpus accuracy, latency and device gates pass.

The 100-container discovery corpus, locked 600-decision validation set, live
cloud-provider benchmark, browser/device matrix, commercial-provider approval,
and any Azure apply/key rotation are operational release gates. They require
real samples, credentials, devices, procurement, or an infrastructure apply and
are intentionally not represented as completed by source code alone. Until a
provider passes those gates, deployments can enable local barcode/GS1 and
manual review while leaving external modules disabled.

## 1. Outcome

From an incoming receipt, an artisan taps **Identify from photo**, points a phone
at the container and takes a picture. The system:

1. decodes every visible 1D, QR, Data Matrix and GS1 code;
2. identifies an existing Odoo product, or proposes catalogue/online matches;
3. extracts likely lot, batch, manufacture and expiry values from printed text;
4. shows the photograph, evidence and confidence beside editable proposals;
5. on confirmation, creates or reuses the native `stock.lot`, fills the receipt
   move line and returns to Odoo's normal receipt; and
6. leaves receipt validation, quantity and stock valuation to Odoo.

The feature is an assisted data-entry surface, not an autonomous stock importer.
It must never guess a product or lot and silently validate inventory.

## 2. The boundary that makes the design honest

A retail barcode and a supplier lot number are different identities.

- An EAN, UPC or GTIN normally identifies a product and pack size. An online
  lookup can return a name, brand, manufacturer reference and image.
- A lot identifies the physical batch in the artisan's hand. It is normally
  ink-jetted or printed elsewhere on the container and is not recoverable from
  a public product-barcode database.
- A GS1 barcode is the valuable exception: Application Identifier `01` carries
  the GTIN and `10` carries the batch/lot, so one scan can identify both.

Odoo 19 documents this exact GS1 mapping: GTIN `01`, quantity `30`, and lot
`10`. GS1 likewise specifies that AI `10` is a variable-length batch/lot value
used with the trade item's GTIN. See [Odoo 19 GS1 barcode
usage](https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/barcode/operations/gs1_usage.html)
and the [GS1 General Specifications](https://ref.gs1.org/standards/genspecs/21.0.1/).

Consequently the promised behavior is **identify the product online, then read
the actual lot from this package**. It must not claim that the online lookup can
discover a lot that is absent from the photograph or encoded data.

## 3. User journeys

### 3.1 Known product, GS1 code

1. Open a draft incoming transfer and its glaze/clay line.
2. Tap **Identify from photo** and scan the GS1 Data Matrix or QR.
3. Decode GTIN and lot locally in the browser; also decode quantity and expiry
   if present.
4. Match the GTIN to `product.product.barcode` or an external identifier.
5. Show an exact product and exact encoded lot with their source marked
   **GS1 barcode**.
6. Confirm. The wizard creates/reuses the native lot and fills the move line.

No OCR or internet lookup is needed in this path.

### 3.2 Known product, retail barcode plus printed lot

1. Decode EAN/UPC from the image and match the Odoo product.
2. OCR the label and find strings adjacent to terms such as `LOT`, `BATCH`,
   `L`, `N° LOT`, `CHARGE`, `PARTIE`, `FAB`, or a configured manufacturer
   marker.
3. Rank candidates using the marker, text geometry, expected manufacturer
   pattern and OCR confidence.
4. Show the best candidate and alternatives. Require a tap to confirm the lot.

### 3.3 Unknown product, known barcode online

1. Decode and checksum-normalize the EAN/UPC/GTIN.
2. Search the local Odoo identifiers, then the Makersbrain ceramics catalogue,
   then enabled external providers.
3. Present candidates without creating anything. Show source, brand, reference,
   pack size, image and conflicts.
4. The user selects a candidate, maps it to an existing product, imports it
   through `mb_catalogue_sync`, or asks an inventory manager to create a product
   from the reviewed candidate. Until that confirmation, the candidate exists
   only on the capture: Odoo has no native draft state for products.
5. Lot framing, capture and extraction may continue while product lookup is in
   progress. Lot assignment and application to a receipt wait until exactly one
   product is resolved and confirmed.

### 3.4 Barcode unreadable or absent

The same photograph can still provide brand, product code, product name and pack
size through OCR. Search those terms in the local ceramics catalogue. This is a
lower-confidence path and must always show a chooser.

For a damaged label, offer **Retake**, **Crop barcode**, **Crop lot text**, and
manual entry. Do not use visual similarity alone to auto-select a glaze: nearby
colors and manufacturer label designs are too alike, and the consequence is a
false traceability record.

### 3.5 AI fallback when deterministic extraction fails

If barcode decoding, ordinary OCR and catalogue/provider matching do not produce
a reliable answer, the user can tap **Analyze with AI**. The multimodal model
receives the sanitized evidence image plus the deterministic evidence already
found and is asked to:

- transcribe difficult curved, faint, embossed or handwritten label text;
- identify brand, manufacturer, product name/code, pack size and likely product
  family from the whole label design;
- distinguish a lot/batch value from dates, prices, firing cones, color codes,
  weights and product references;
- return up to three product and lot candidates with an explanation and the
  image region supporting each answer; and
- suggest targeted catalogue/online search terms when it cannot identify the
  item directly.

The AI result is a proposal, never an inventory fact. It must say `unknown`
instead of filling a required field from general knowledge, and every AI-derived
product or lot requires explicit human confirmation. If the model names a
product that is not grounded by a decoded identifier, catalogue record,
manufacturer page or visible label text, the UI marks it **Unverified visual
match** and does not preselect it.

This fallback is part of the production scope rather than a future experiment.
It is invoked only after cheaper, faster deterministic methods fail, or manually
when the operator can see that the label is unusually difficult.

### 3.6 Fast two-photo mode

Although one photo should be accepted, the production UX should guide the user
to two shots when necessary:

- **Product/front:** barcode, brand, product code, name and pack size.
- **Lot/detail:** close-up of the ink-jetted lot/date area.

This is faster than repeatedly trying to fit a whole bucket or jar into a single
high-resolution image and materially improves OCR on curved, glossy packaging.

### 3.7 Standalone inventory identification

Inventory gains **Operations → Identify incoming product** for goods not yet on
a purchase receipt. The result may create a draft internal capture record and a
product/lot proposal, but it must not create on-hand quantity directly. The user
can attach it to a draft receipt or open an inventory adjustment and complete the
ordinary Odoo operation.

### 3.8 Target v19 near-live guided scan (core loop implemented; device gate open)

The current action keeps the camera open across product and lot identification;
the remaining automatic framing details below are acceptance targets.
Product feedback must not wait for a photograph upload or cloud OCR:

1. Decode frames locally at a throttled rate while showing the camera preview at
   full frame rate. Require the same checksum-valid value in two recent frames
   before locking it, so a transient partial read does not trigger lookup.
2. Immediately display the normalized digits, barcode type and a green
   **Barcode read** state; use optional vibration/beep only after the stable
   read. The user can tap the digits to reject and resume scanning.
3. Resolve local Odoo identifiers synchronously. In parallel, ask the server for
   the Makersbrain catalogue/provider cache. A cache miss starts one shared
   external lookup without blocking the camera.
4. Progressively replace **Looking up product…** with **Found locally**,
   **Found in catalogue**, **Found online—review**, or **No online match**. A
   late response carries a scan generation ID and is ignored if the user has
   already scanned another container.
5. As soon as the product or manufacturer is known, change the overlay to
   **Find the lot** and show profile guidance such as “turn the jar until LOT#
   is visible” or “capture both AMACO inkjet lines.” Product lookup and lot
   framing continue concurrently.
6. Run blur, glare, clipping and text-size checks on-device. Automatically
   freeze a candidate frame for preview when it remains sharp and stable, but
   require the operator to accept the frame before it becomes evidence or is
   uploaded.
7. Show the accepted crop immediately with **Reading lot…** while deterministic
   OCR and, only if needed, AI run asynchronously. The user can retake or type
   the lot without waiting.

Target interaction budgets, measured from the user's action rather than only
provider time:

| Feedback | Target |
| --- | ---: |
| Stable local barcode and check digit | p95 under 300 ms after the code is framed |
| Existing Odoo product | p95 under 150 ms after stable decode |
| Catalogue/provider cache hit | p95 under 400 ms |
| External product candidate | p95 under 2.5 s, with non-blocking progress UI |
| Lot crop quality/orientation feedback | p95 under 300 ms per accepted frame |
| Deterministic lot proposal | p95 under 2 s after crop acceptance |
| Configured multimodal crop fallback | Gemini pilot mean 1.88 s; every production primary must pass p95 under 4 s |

These are acceptance budgets, not reasons to hide a slow state. Every stage has
an explicit progress, timeout, retry and manual path. Never repeatedly submit
live video frames to a paid provider. UPCitemDB's public trial rate limit cannot
guarantee the external-lookup budget under concurrent use; it is a discovery
tool. Production must use an approved plan/provider with the required service
rate or visibly queue the lookup without blocking lot capture.

## 4. What Odoo 19 and existing addons already provide

Research was checked on 10 August 2026.

| Existing capability | What it proves | Decision |
| --- | --- | --- |
| [Odoo 19 product/location barcodes](https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/barcode/setup/software.html) | Native Barcode can scan an unknown UPC/EAN/ISBN, call a stock barcode database and create a product on a receipt. | Reuse native product and stock semantics, but do not enable uncontrolled product creation. This repository targets Community and needs review/provenance. |
| [Odoo 19 Barcode Lookup](https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/barcode/setup/barcodelookup.html) | Odoo has a direct Barcode Lookup API integration that can populate name, description, image, category, dimensions and other fields. It requires an API key. | Treat Barcode Lookup as an optional candidate provider. Do not let provider data overwrite curated ceramics fields automatically. |
| [Odoo 19 lots](https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/inventory/product_management/product_tracking/lots.html) | `stock.lot` and receipt move lines already own lot traceability. | Never create a parallel lot model. |
| [Odoo 19 GS1 usage](https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/barcode/operations/gs1_usage.html) | Native nomenclature understands product, quantity and lot AIs. | Use the same semantics and test vectors; avoid inventing a private combined code. |
| [Stock Barcode Scanning with Camera](https://apps.odoo.com/apps/modules/19.0/do_stock_barcode) | A commercial Odoo 19 Community addon provides camera scanning, GS1, receipts and lot capture. | Evidence that the camera/OWL UX is viable. It is OPL-1 and much broader than this use case; do not copy it or make it a dependency. |
| [Mobile Barcode Scanner](https://apps.odoo.com/apps/modules/19.0/mobile_barcode_scanner) | A small LGPL-3 addon inserts camera-scanned text into a focused field. | Useful reference for minimum camera UX, but it does not perform lookup, OCR, lot inference or review. Inspect license/source before considering vendoring; otherwise implement the narrow scanner locally. |
| [Lot/Serial Number Barcode Scanner](https://apps.odoo.com/apps/modules/18.0/sh_auto_serial_scanner) | Available through version 19 and assigns scanned lot values to detailed operations. | Confirms receipt integration, but assumes the lot itself is already a barcode. It does not solve printed-text OCR. |
| [OCA `stock_lot_image`](https://github.com/OCA/stock-logistics-warehouse/tree/18.0/stock_lot_image) and [`stock_lot_multi_image`](https://github.com/OCA/stock-logistics-warehouse/tree/18.0/stock_lot_multi_image) | OCA 18 has established patterns for images on lots. | Study the data/view pattern. There was no confirmed 19.0 port in this research, and this repository intentionally has no OCA dependency. |
| [Odoo OCR Data Fetch](https://apps.odoo.com/apps/modules/18.0/wk_ocr_data_fetch) | A generic Tesseract/template addon can extract image text into records. | Confirms generic OCR exists, but no verified Odoo 19 ceramics/lot workflow was found. A provider-neutral extraction contract fits this project better. |

No reviewed addon combined all five required properties: Odoo 19 Community,
phone capture, unknown-product online lookup, printed supplier-lot OCR, and a
confidence/evidence review before an ordinary inventory receipt.

## 5. Recommended architecture

```text
phone camera / upload
        |
        v
Owl capture wizard -- local barcode/GS1 decode
        |                         |
        |                         +--> exact local product + encoded lot
        v
mb.inventory.capture (draft, immutable sanitized evidence assets)
        |
        +--> provider chain: local Odoo -> ceramics catalogue -> online lookup
        |
        +--> OCR adapter -> tokens, boxes, confidences -> lot rule engine
        |                                      |
        |                         unresolved --+--> multimodal AI fallback
        |                                             |
        |                           grounded searches/candidates
        v
human review: product + lot + quantity + expiry + evidence
        |
        v
native product.product + stock.lot + stock.move.line on draft receipt
```

### 5.1 Odoo addons and shared AI boundary

The existing `addons/mb_inventory_capture` depends on:

- `stock` for receipts, move lines and `stock.lot`;
- `purchase_stock` for the purchase receipt entry point;
- `product_expiry` so an explicitly confirmed encoded expiry can use Odoo's
  native lot expiration fields rather than a competing field;
- `mail` only if captures use chatter/activity review; and
- `mb_ai_bridge` for typed, descriptor-only, idempotent AI job submission and
  shared callback-envelope validation. It depends on `mb_control_bridge` and
  never stores provider credentials or provider response bodies.

Do not depend directly on optional `mb_catalogue_sync`. Use a small abstract
provider registry/hook. A glue addon such as `mb_inventory_capture_catalogue`
can depend on both if direct catalogue import is required. This preserves the
repository's current statement that nothing depends on the undecided catalogue
connector.

`mb_ai_bridge` is reusable by invoice capture and future addons. Domain addons
register fixed task names and internal paths in server code; browsers and records
cannot supply an endpoint. The shared addon owns payload/operation-key bounds,
secret/image-byte rejection, tenant workshop resolution, safe timeout semantics,
and provider metadata validation. Each domain addon still owns its strict task
schema, normalized candidates, evidence, authorization, review, and business
writes. Azure/Gemini/OpenAI/Claude clients and routing remain in the Rust broker,
not in this Odoo library.

### 5.2 Browser capture and decoding

Extend the current Odoo 19 Owl still-image action into a dialog with:

- `getUserMedia` camera capture, rear camera preferred;
- torch and focus controls where the browser exposes them;
- file upload fallback for desktop and restrictive browsers;
- live framing guides and blur/glare/underexposure feedback;
- an explicit shutter so the evidence image is retained only when intended;
- client-side downscaling of the preview while retaining a sanitized evidence
  rendition at a configured maximum resolution; and
- a pinned, license-reviewed barcode decoder supporting EAN-8/13, UPC-A/E,
  Code 128, QR and Data Matrix.

Use Odoo's nomenclature semantics for GS1 parsing. Barcode decoding happens in
the browser first: it is fast, works before network upload and avoids spending
OCR calls on a machine-readable code.

Do not make Chrome's built-in LLM a scanner dependency. Chrome's current
foundation-model APIs do not support Android or iOS, require substantial desktop
hardware/storage, and the web Prompt API remains availability-gated. They also
do not replace a barcode decoder or grounded OCR. The implementation instead
uses the local `BarcodeDetector` when present and pinned ZXing fallback; feature
detection remains mandatory because `BarcodeDetector` is experimental and not
Baseline, although it is available in Web Workers. See Chrome's
[built-in AI requirements](https://developer.chrome.com/docs/ai/prompt-api) and
MDN's [BarcodeDetector status](https://developer.mozilla.org/en-US/docs/Web/API/BarcodeDetector).

The target decoder runs in a Web Worker so camera rendering remains responsive.
It receives downscaled luminance frames, is throttled according to device load
and stops after a stable result. The UI sends only the decoded value, symbology,
scan-generation ID and optional GS1 elements for product resolution—never a
continuous video stream. A server response is applied only when its generation
ID still matches the active scan.

The implemented product-resolution contract returns local Odoo, catalogue and
cache results immediately. An external cache miss performs one bounded
synchronous broker request; the camera preview stays open, stale scan-generation
responses are ignored, and timeout/no-result states preserve manual and lot-crop
paths. If measured concurrency or latency cannot meet the budget, promote only
the external miss to an operation key completed through Odoo's existing bus
service (with bounded polling fallback). The control plane already coalesces
concurrent misses for the same provider/schema/GTIN into one request.
The SQLite cache in
the standalone POC proves TTL and schema behavior; production uses the shared
control-plane database so every worker sees the same positive and negative
entries. Cache keys are provider + normalization-schema version + GTIN-14;
positive TTL defaults to 30 days and negative TTL to 24 hours. A provider
adapter change bumps the schema version instead of trusting incompatible data.

### 5.3 Extraction service

Keep OCR and optional vision outside the Odoo request worker. The control plane
gains queue `inventory-capture`, operation kind `inventory.capture.extract`, and
module/capability gate `inventory-capture` plus provider-specific gates such as
`azure-label-extraction`, `inventory-ai-gemini`, `inventory-ai-openai` and
`inventory-ai-anthropic`. Odoo
enqueues the operation through a tenant-authenticated internal endpoint after it
has stored and sanitized the photographs.

The operation payload contains identifiers and digests, never image bytes:

```json
{
  "capture_id": "tenant-scoped-uuid",
  "assets": [
    {"asset_id": "uuid", "role": "front", "content_sha256": "..."},
    {"asset_id": "uuid", "role": "lot_detail", "content_sha256": "..."}
  ],
  "task": "inventory_label",
  "hints": {"brand": "Mayco", "languages": ["fr", "en"]}
}
```

#### Image pull and result callback contract

1. The extraction broker resolves the tenant Odoo service and uses its existing
   tenant-scoped Odoo control token to call
   `GET /mb_control/v1/inventory-captures/<capture_uuid>/assets/<asset_uuid>`.
2. The Odoo route returns the sanitized attachment bytes only when the capture
   is in `processing`, the requested asset belongs to it and the authenticated
   workshop matches `company_id`. It includes MIME type, byte length and digest
   headers. The broker verifies all three before sending anything to a provider.
3. The route accepts no arbitrary attachment ID, filesystem path or URL. Each
   response is capped at 15 MB and 12 megapixels; a capture has at most two
   source assets in the first release. Redirects are forbidden.
4. Neither the queue payload nor the control-plane database stores image bytes,
   base64, OCR bodies or provider response bodies. The broker holds bytes and
   provider envelopes in memory only for the active attempt and drops them
   afterwards.
5. The broker posts each completed attempt to
   `POST /mb_control/v1/inventory-captures/results` using the established Odoo
   control authentication. The payload carries `operation_key`, capture/attempt
   UUIDs, input digests, provider/model/version, normalized output, a bounded
   diagnostic status object such as `{"retained": false}`, usage and safe failure
   data. It never sends the source image or raw provider body back.
6. The Odoo receiver uses `mb.control.operation.receipt` exactly as invoice
   capture does: replaying an identical operation returns the stored result;
   reusing a key with a different payload digest is rejected.
7. A callback can append an immutable attempt and candidates but cannot select
   a product/lot, create either record, change a move line or validate a receipt.
8. Retrying creates a new attempt UUID linked to the prior attempt. It does not
   overwrite evidence. A cancelled capture makes asset pull return `410` and
   rejects later callbacks without resurrecting the workflow.

The normalized response contains detected codes, OCR tokens with bounding
polygons, language, raw confidence, image-quality warnings and provider/version.
Odoo—not the provider—applies product and lot business rules.

Benchmark the already-provisioned development Azure Document Intelligence
`prebuilt-read` endpoint first. It runs higher-resolution OCR and may be enough
for close crops of the small lot text, even though it is primarily optimized for
documents and uses an asynchronous operation.

If that benchmark misses materially more product-label text than the acceptance
threshold, benchmark a currently supported Azure successor such as Content
Understanding and, only when it has a material measured advantage, Azure Vision
Image Analysis 4.0 Read as a temporary deterministic OCR provider. Microsoft
lists Document Intelligence and Content Understanding among the migration
options for Image Analysis; Content Understanding processes images and can
extract OCR/barcodes into structured output. See
[Azure Content Understanding](https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/overview).
Microsoft's
synchronous Read API is designed for in-the-wild images such as product labels,
signs and user photographs. See
[Azure Vision OCR for images](https://learn.microsoft.com/en-us/azure/ai-services/computer-vision/concept-ocr)
and [Document Intelligence Read](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/prebuilt/read?view=doc-intel-4.0.0).

This choice is deliberately conditional because Microsoft has deprecated Image
Analysis 4.0 and states that calls will stop working after 25 September 2028.
If Vision wins the benchmark, record the retirement date at provisioning time,
give the adapter a provider-neutral contract and schedule a replacement decision
well before that date. See [Microsoft's Image Analysis overview and retirement
notice](https://learn.microsoft.com/en-us/azure/ai-services/computer-vision/overview-image-analysis).

This is Azure **AI** Document Intelligence, not Power BI or a generic “Azure
Business Intelligence” product. Power BI can report on capture accuracy and
inventory later; it does not extract barcodes or lot text from the photographs.
A Tesseract adapter remains useful for offline development and as the known
baseline rather than the proposed production extractor.

The six-photo pilot provides a provisional development choice, not a production
accuracy claim. Gemini 3.1 Flash-Lite was the lowest-cost useful multimodal
fallback tested: it recovered 5/5 visible UPCs and 2/5 exact lots for an
estimated $0.00444 across six photos. Gemini 3.5 Flash recovered one additional
lot but cost about ten times as much. The tested OpenAI models did not improve
the cost/accuracy frontier; GPT-4o mini at high image detail recovered only 2/5
UPCs and no exact structured lot values. Keep Gemini 3.1 Flash-Lite as the first
POC comparator and Gemini 3.5 Flash as a recorded alternative, while evaluating
Azure-hosted multimodal, OpenAI and Claude under the same contract. The locked
validation corpus—not this pilot—selects the primary and optional retry. Full method,
limitations, usage, and results are in the
[six-image pilot](PRODUCT-PHOTO-INVENTORY-CAPTURE-SAMPLE-TEST.md).

A follow-up region-isolation POC validates the intended staged shape. ZXing-C++
decodes all 5/5 visible barcodes after trying right-angle orientations and
checksum validation. Tesseract proposes candidate text regions; the worker then
adds a barcode-adjacent context crop, selects a likely text orientation, and
creates grayscale, CLAHE, sharpened, and adaptive-threshold variants. Sending at
most two selected color evidence crops to Gemini 3.1 Flash-Lite improves exact
lot recovery from 2/5 on full images to 3/5 and correctly returns no lot for the
barcode-free front photo. The crop request is not automatically cheaper: in
this pilot two crops cost about $0.00569 for six photos versus $0.00444 for one
full sanitized photo each, because Gemini charges image tokens per crop. Use the
staged route for accuracy and evidence localization, then benchmark one crop
versus two before fixing production routing.

#### Infrastructure change in `../makersbrain-infra`

The sibling infrastructure repository already owns
`environments/development/azure-documents`, which provisions the France Central
`makersbrain-development-documents` Document Intelligence resource and delivers
`AZURE_DOCUMENT_KEY` out of band to
`makersbrain-runtime/dev/invoice-capture`. A human-operated benchmark may use
that resource immediately, but production inventory code must not read that
secret path directly.

The implemented control-plane boundary makes the dedicated `document-extraction`
broker the only process that receives Azure OCR/vision credentials. Invoice and
inventory operations use typed extraction contracts and receive normalized
results; neither Odoo addon receives an Azure key. Before production reuse,
migrate the existing
`AZURE_DOCUMENT_KEY` from `makersbrain-runtime/<env>/invoice-capture` to
`makersbrain-runtime/<env>/document-extraction` with an overlapping deployment:
publish at the new path, start and verify the broker, move invoice extraction to
it, then revoke access to the old path. Do not duplicate the key indefinitely.

The shared broker is not a shared business authority. Its allowlist permits
`prebuilt-invoice` only for an enabled invoice operation and `prebuilt-read`
only for an enabled inventory-label operation; it has no Odoo write endpoint
other than the typed result receivers. Usage counters remain separate
(`azure_invoice_pages` and `azure_inventory_images`).

If the benchmark proves that Azure Vision Read, rather than a supported
successor, is needed, update
`../makersbrain-infra` as an explicit dependency of this feature:

1. Add an independently state-backed root such as
   `environments/development/azure-vision`, following the existing
   `azure-documents` layout and provider pin.
2. Provision a `Microsoft.CognitiveServices` account of kind `ComputerVision`
   named `makersbrain-development-vision`, in `francecentral` when the selected
   API/model is confirmed available there, using a paid pay-as-you-go tier with
   predictable limits. France Central currently supports Image Analysis 4.0.
3. Give it a custom endpoint/subdomain, public access for the Hetzner worker,
   local key authentication until the worker has an Entra workload identity,
   and the repository's standard environment/purpose/owner tags.
4. Output only the non-secret endpoint and resource identity. Do not output a
   key or place it in an OpenTofu variable, plan log or application repository.
5. Add or generalize the existing out-of-band two-key delivery/rotation script
   so it publishes `AZURE_VISION_KEY` to
   `makersbrain-runtime/dev/document-extraction`. Keep the non-secret
   `AZURE_VISION_ENDPOINT` in reviewed deployment configuration, mapped to
   `CONTROL_AZURE_VISION_ENDPOINT`, and map the secret to
   `CONTROL_AZURE_VISION_KEY`; materialize both provider keys only for the
   document-extraction broker.
6. Keep the Vision key distinct from `AZURE_DOCUMENT_KEY`, with independent
   rotation and usage metrics. Only the broker receives both. Inventory and
   invoice business workers receive neither, so neither can expand its provider
   access by invoking an unapproved model.
7. Add quota, request-rate and cost alerts plus an application-side monthly
   image limit. The development subscription's spending limit is not a durable
   production control.
8. Validate with one of the supplied sample crops, then test wrong-key denial,
   rotation with overlap, retry after `429`, and that no image/key/body reaches
   Terraform output, shell history or logs.
9. Document the 25 September 2028 retirement, replacement owner and teardown
   criterion. If Document Intelligence or its successor reaches the agreed
   accuracy first, do not provision Vision—or remove the development resource
   after preserving only the non-sensitive benchmark results.

The first infrastructure preflight is subscription viability. The current
development subscription is a Free Trial created on 8 August 2026 and documented
as expiring roughly 30 days later. Before Increment 0 depends on it, verify the
subscription/resource, upgrade to Pay-As-You-Go or replace it, configure a
budget, and prove that the endpoint and published key still authenticate. A dead
trial credential in Infisical is not a benchmark environment.

This plan authorizes future infrastructure changes; it does not require an
immediate apply. Creating an Azure resource, moving/publishing a key or changing
the sibling repository occurs only when implementing the benchmark result and
must follow `makersbrain-infra`'s normal plan/apply review.

When Gemini, OpenAI or Claude is approved, update `../makersbrain-infra` and the
control-plane release contract to deliver only that provider's endpoint/project
metadata and secret credential to the extraction broker. Use separate secret
names, rotation, quotas and usage metrics for every provider; do not reuse a key
between environments or inject any provider credential into Odoo. These providers
do not imply provisioning an Azure resource. Infrastructure changes remain
conditional on the benchmark and normal plan/apply review.

Add a separate `inventory_label_vision` adapter for the multimodal AI fallback.
It receives the images, decoded symbols, OCR tokens and optional known receipt
vendor/product context. Require a strict schema rather than accepting prose:

```json
{
  "status": "candidates|unknown",
  "product_candidates": [{
    "brand": "Mayco",
    "manufacturer_sku": "SC-74",
    "name": "Hot Tamale",
    "pack": "473 ml",
    "visible_evidence": ["MAYCO", "SC-74", "HOT TAMALE"],
    "search_query": "Mayco SC-74 Hot Tamale 473 ml",
    "confidence": 0.93
  }],
  "lot_candidates": [{
    "raw_value": "8O1B",
    "evidence_text": "LOT 8O1B",
    "asset_id": "detail",
    "reported_region": [0.42, 0.61, 0.71, 0.69],
    "confidence": 0.78
  }],
  "warnings": ["O may be zero"]
}
```

Validate the schema, length, reported regions and confidence ranges before
storing the response. A model-reported region is a navigation hint, not evidence:
mark it grounded only when it overlaps deterministic OCR tokens/decoded symbols
that contain the proposed value, or when the user confirms a displayed crop.
Never draw a precise evidence box solely because a multimodal model returned
coordinates. Treat text printed on the package as untrusted data, not
instructions: prompts explicitly delimit it, tools are allowlisted, and the
model cannot call Odoo write APIs. The worker—not the model—performs any proposed
catalogue or online query and returns grounded records for comparison. AI text
must never confirm inventory or manufacture a source URL.

#### Multimodal provider adapters

The broker supports Azure-hosted multimodal models, Google Gemini, OpenAI and
Anthropic Claude through separate adapters behind one capability contract. A
deployment may enable none, one, or several; provider/model order is tenant
configuration backed by a benchmark, never browser input. Each adapter must:

- accept only one selected color lot crop by default and at most two bounded
  sanitized assets for product-label identification;
- return the same strict, versioned schema using `asset_id`, with no prose or
  tool calls; reject unknown fields, excessive lengths and invalid coordinates;
- expose provider, exact model identifier/version, request ID, latency and usage
  units in normalized metadata without retaining the provider envelope;
- implement provider-specific authentication, timeouts, retry/`429` handling,
  regional/retention controls and circuit breaking inside the broker;
- keep credentials out of Odoo, the browser, queue payloads and logs; and
- preserve `unknown` as a successful result and never fail over merely because a
  provider declined to guess. Failover is allowed for unavailability, quota or a
  schema-invalid response, with a new immutable attempt and a total cost cap.

Azure Document Intelligence remains a deterministic OCR adapter rather than a
multimodal reasoning model. Azure-hosted multimodal models use their own adapter.
Gemini supports image understanding and schema-constrained structured output;
OpenAI supports image inputs and Structured Outputs; Claude supports vision and
structured outputs. Pin an approved model per adapter in deployment configuration
and benchmark identical crops because provider confidence values are not
comparable. See the official [Gemini image](https://ai.google.dev/gemini-api/docs/image-understanding)
and [structured-output](https://ai.google.dev/gemini-api/docs/structured-output)
guides, [OpenAI vision](https://developers.openai.com/api/docs/guides/images-vision)
and [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
and [Claude vision](https://platform.claude.com/docs/en/build-with-claude/vision)
and [structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).

Provider selection is policy, not truth. Run Azure, Gemini, OpenAI and Claude on
the same locked crop corpus and compare exact-lot accuracy, false proposals,
`unknown` behavior, p95 latency, regional processing/retention, operational
reliability and normalized cost. Do not cascade through all providers for every
capture. The normal route uses one configured primary; a user-visible retry may
use one configured secondary when policy and the remaining cost budget allow it.

| Provider adapter | Intended role | Required contract behavior |
| --- | --- | --- |
| Azure Document Intelligence | Deterministic OCR/tokens/barcodes | Fixed `prebuilt-read` allowlist, normalized boxes, delete terminal analyze result. |
| Azure-hosted multimodal | Optional vision primary/secondary | Strict schema, approved deployment/region/model, independent credential and quota. |
| Google Gemini | Optional vision primary/secondary | Native image input and structured output mapped to the common schema. |
| OpenAI | Optional vision primary/secondary | Responses image input and Structured Outputs mapped to the common schema. |
| Anthropic Claude | Optional vision primary/secondary | Vision input and structured output mapped to the common schema. |

### 5.4 Product lookup provider chain

Providers return candidates under one normalized contract and never write Odoo
records:

```text
identifier, identifier type, brand, manufacturer SKU, name, pack quantity/unit,
optional permitted image reference, source URL, source record ID, provider,
retrieved_at, confidence
```

Run providers in this order:

1. **Local exact match:** `product.product.barcode` and stored external
   identifiers. This is authoritative.
2. **Makersbrain catalogue:** add barcode/GTIN identifiers to the catalogue
   service and its canonical-product API. Prefer curated manufacturer identity
   and pack variants over generic web titles.
3. **UPCitemDB, provisional POC winner:** its trial API returned an exact
   identifier-bound candidate for all 5/5 visible pilot UPCs. Treat its metadata
   as a proposal: only 2/5 responses contained every expected brand, SKU, and
   product-name term, and some brand/model/weight fields were misleading. Use
   the [documented lookup endpoint](https://www.upcitemdb.com/api), a normalized
   TTL cache, and manager review; do not retain raw responses, descriptions,
   offers, or third-party images.
4. **Barcode Lookup, optional:** Odoo's documented provider covers UPC/EAN/ISBN.
   Its [API](https://www.barcodelookup.com/api-documentation) returns title,
   manufacturer, brand, MPN, size, images and stores, but not the physical lot.
   Current commercial terms/cost must be approved before production.
5. **Open Facts, optional fallback:** the Open Food Facts family exposes a
   [barcode product endpoint](https://openfoodfacts.github.io/documentation/docs/Product-Opener/v3/products/get-api-v3-product-code/)
   across product types. Benchmark Open Product Facts coverage for ceramic
   materials and review attribution/database-license obligations before use.
6. **Manual web search link:** open a search for the normalized barcode in a new
   tab for human research. Do not scrape arbitrary search results in the receipt
   path; their structure, provenance and product rights are unstable.

External provider calls run in the control-plane extraction/lookup broker, where
credentials, rate limits and egress are controlled. The Odoo addon may call the
tenant's configured Makersbrain catalogue directly through its existing client,
but it must not hold credentials for UPCitemDB, Barcode Lookup, Azure, Gemini,
OpenAI, Claude or any other external provider.
Every provider result returns to Odoo as an immutable candidate; matching and
business writes remain in Odoo.

An unknown product remains a candidate until an inventory manager confirms
**Create product**. Confirmation creates one ordinary active
`product.template`/`product.product` using only reviewed fields, sets it as a
stocked good, applies the reviewed pack/UoM and category, and assigns the
verified primary barcode only if conflict checks still pass. There is no
inactive pseudo-draft product. Cancelling review creates nothing. Catalogue
import remains the preferred path when a canonical product exists.

Before choosing a paid provider, run a recorded coverage trial with at least 100
real containers: major glaze brands, clay bags, stains, oxides, tools and generic
consumables. Report exact-match rate, wrong-match rate, pack-size accuracy,
latency and cost. A zero-result is safer than an attractive wrong result.

### 5.5 Catalogue changes

The current `mb_catalogue_sync` search contract uses product name/manufacturer
SKU and contains no documented barcode identifier. Extend the independent
catalogue service first:

- introduce `canonical_product_identifiers` with canonical product/offer or pack
  identity, scheme (`gtin_8`, `gtin_12`, `gtin_13`, `gtin_14`, `ean`, `upc`,
  `manufacturer_sku`), normalized value, source and verification state;
- attach a GTIN to the pack-size variant, not merely the template, because two
  jar sizes normally have different barcodes;
- add exact `GET /v1/canonical-products?barcode=<normalized>` lookup;
- never infer a barcode from an SKU or accept a checksum-invalid GTIN;
- retain contradictory supplier claims for curation instead of arbitrarily
  selecting one; and
- let `mb_catalogue_sync` set `product.product.barcode` only for one verified,
  unambiguous identifier and only when that field is empty.

### 5.6 Lot candidate engine

Candidate extraction is deterministic and explainable:

1. Accept GS1 AI `10` as an exact encoded candidate.
2. Decode a separate Code 128/QR/Data Matrix near a printed `LOT` marker.
3. Normalize OCR text conservatively: Unicode normalization and whitespace
   cleanup, but preserve punctuation and leading zeroes.
4. Find marker/value pairs using generic multilingual markers.
5. Apply optional manufacturer profiles containing label marker, allowed
   pattern, nearby date pattern and exclusion rules—not a hard-coded lot value.
6. Reject known product codes, GTINs, weights, firing cones, prices, dates and
   expiry values unless the label explicitly identifies them as the lot.
7. Rank by source reliability, marker proximity, OCR confidence, bounding-box
   alignment and profile agreement.
8. Display the source crop around every candidate.
9. If no deterministic candidate is reliable, send the image and extracted
   evidence to the multimodal fallback. Accept only schema-valid candidates and
   show them under a distinct **AI suggestion** source.

Suggested bands:

| Result | UI behavior |
| --- | --- |
| Exact GS1 AI `10` with exact product GTIN | Preselect; still show before receipt confirmation. |
| High confidence, one marker-bound OCR candidate | Preselect and require one-tap confirmation. |
| Several plausible candidates | Show alternatives; no default if scores are close. |
| No reliable deterministic candidate | Offer **Analyze with AI**, then require confirmation or manual entry. Allow **Receive without lot** only when product tracking permits it. |

Do not silently turn `O/0`, `I/1` or `B/8` into each other. Present such OCR
alternatives visibly because a one-character correction creates a different lot.

#### Best extraction route from the pilot

The pilot-recommended target is local region detection/OCR followed by the
configured primary multimodal adapter on selected crops. Gemini 3.1 Flash-Lite is
the current six-photo POC leader, not a permanent production default. Azure
Document Intelligence remains a deterministic benchmark/compatibility adapter,
not a required future critical-path hop: on the
six full images it reached 3/5 lots and deterministic enhancement did not fix
the other two. Do not pay both Azure and Gemini for every frame unless the larger
locked benchmark proves that the combination adds unique correct results.

The production route should use the following waterfall:

1. **Encoded lot first.** Parse GS1 AI `10` locally. This is the only lot source
   that may be considered exact without OCR, although the receipt still shows it
   before confirmation.
2. **Use the barcode as a spatial and identity anchor.** Rectify its polygon and
   retain a wider color context perpendicular to the bars. The pilot found the
   PC-33, SW-166 and S-2726 lot area this way even when full-frame OCR was weak.
3. **Use manufacturer guidance.** Once barcode lookup resolves Mayco, AMACO or
   another known maker, apply only layout/marker/pattern hints—not expected lot
   values. Ask for a second detail frame when the known lot area is absent.
4. **Detect text before recognizing it.** Propose marker-bound regions and
   plausible unlabelled inkjet lines across 0°, 90°, 180° and 270°. Preserve a
   generous color margin and record the crop transform back to the evidence
   image.
5. **Rectify and enhance the crop, not the full frame.** Keep the color crop and
   derive grayscale/CLAHE, mild sharpened and adaptive-threshold variants in
   memory. Never replace the evidence with a thresholded image; the full-frame
   enhancement experiment recovered no additional lots.
6. **Run deterministic OCR as an ensemble.** Merge exact strings seen across
   orientations/variants, preserve leading zeroes and retain both AMACO-style
   lines. Exclude the known GTIN, manufacturer SKU, address/postcode, weights,
   firing cones and dates unless a marker explicitly changes their meaning.
7. **Send one crop to the configured AI primary when unresolved.** Start with the
   best color crop and the provider-neutral lot-only schema. During development,
   Gemini 3.1 Flash-Lite is the provisional first adapter to reproduce; Azure-
   hosted multimodal, OpenAI and Claude remain supported benchmark/route choices.
   Add a second independently useful crop only if the first crop lacks context or returns ambiguity; each
   crop adds image tokens. Never send ten enhancement variants to AI.
8. **Fuse without inventing confidence.** Record agreement and disagreement
   between OCR and AI, marker proximity and manufacturer-pattern compatibility.
   High provider confidence is not proof: both OCR and AI dropped a repeated
   digit from Alabaster and misread C-10 in the pilot.
9. **Confirm against visible evidence.** For every non-GS1 lot, show the color
   crop, editable transcription and alternatives. Applying the receipt requires
   a tap on the candidate or manual correction. Save the chosen value and the
   rejected machine candidates for audit.
10. **Fail usefully.** If the crop is clipped, blurred, glare-obscured or methods
    disagree by a character, ask for a close-up instead of retrying the same
    bytes. Manual entry remains available; receiving without a lot is allowed
    only when the product's tracking policy permits it.

The six-photo evidence supports this choice: local ZXing recovered 5/5 visible
UPCs; crop-level Tesseract recovered 2/5 exact lots; two selected crops with
Gemini 3.1 recovered 3/5 and correctly returned `unknown` for the front-only
photo. That is useful assistance but far below an automatic-write threshold.

### 5.7 Tracking policy

Incoming raw-material traceability needs an explicit policy in
`mb_workshop_base`. Add `product.template.mb_supplier_lot_required`, a reviewed
business declaration distinct from `mb_food_contact`: the former explains why a
raw material must retain its supplier batch, while the latter continues to
govern finished food-contact ware. An onchange proposes `tracking = 'lot'`; a
constraint prevents a declared product from remaining untracked.

- glaze and clay that may be consumed into traceable finished ware should use
  native `tracking = 'lot'`;
- stains, oxides and other formulation inputs may be configured the same way;
- tools, packaging and low-risk consumables remain quantity-tracked unless a
  workshop deliberately enables lots; and
- the capture wizard respects the product's setting. It does not create a lot
  for an untracked product merely because OCR found a string beginning `LOT`.

Category or catalogue family may propose the declaration in a review wizard but
must not set it or change `tracking` silently during import. The manager owns the
decision per product.

#### Existing-stock cutover

Changing tracking on an existing product is a stock migration, not a field
update hidden inside installation:

1. Inventory managers run a dry-run report listing candidate products, on-hand
   quantities, reservations, open moves, manufacturing consumption and whether
   Odoo 19 permits the tracking change.
2. Products with no quantity, reservation or open operation can be changed after
   explicit selection. Historical traceability is not fabricated.
3. For on-hand stock, freeze operations and perform a documented inventory
   cutover through ordinary stock moves: remove the untracked opening quantity,
   enable tracking, and restore the counted quantity under an explicit
   transitional lot `OPENING/<product-code>/<date>`. Mark that lot
   `mb_supplier_lot_origin = 'opening_balance'` and state visibly that the actual
   supplier batch is unknown. Never label it as a supplier lot.
4. If Odoo 19 refuses a tracking transition because historical moves make it
   unsafe, create a replacement lot-tracked product, transfer future purchasing
   and bills of materials deliberately, and archive the old product after its
   stock reaches zero. Never bypass an Odoo constraint with SQL.
5. Resume operations only after total quantities and valuation reconcile, and
   retain the cutover report/stock documents.

Tests cover zero-stock conversion, opening-balance lots, active reservations,
historical moves, manufacturing/BOM references, rollback before resume and
catalogue re-import not reverting the manager's tracking decision.

This extends rather than replaces `IDENTITY-SPINE-DESIGN.md`: the existing
finished-ware policy remains intact, while supplier lots on consumed raw
materials provide the upstream traceability that `mb_glaze_lot_ids` expects.

## 6. Odoo data model

### `mb.inventory.capture`

One attempted identification, retained as evidence and an audit trail.

| Field | Purpose |
| --- | --- |
| `name` | Human sequence such as `CAP/2026/00042`. |
| `company_id`, `create_uid`, timestamps | Tenant and operator boundary. |
| `state` | `draft`, `processing`, `review`, `applied`, `failed`, `cancelled`. |
| `picking_id`, `move_id`, `move_line_id` | Optional receipt context. |
| `asset_ids` | Sanitized front/detail evidence through owned asset records. |
| `attempt_ids` | Immutable deterministic/OCR/AI attempts and retries. |
| `product_id`, `lot_id` | Human-confirmed result only. |
| `proposed_quantity`, `proposed_expiry` | Encoded/extracted proposals, never silently applied. |
| `applied_by`, `applied_at` | Audit of the business decision. |
| `failure_code`, `failure_detail` | Actionable retry/support information. |

### `mb.inventory.capture.asset`

One input image or user-confirmed crop. Fields include capture/company, stable
UUID, role (`front`, `lot_detail`, `crop`), owned `ir.attachment`, MIME type,
pixel dimensions, byte length, received-byte SHA-256, sanitized-byte SHA-256,
sanitizer/version, parent asset and normalized crop rectangle. The attachment
must have `res_model = 'mb.inventory.capture.asset'` and `res_id = asset.id`;
constraints reject a detached or cross-company attachment. The first release
accepts at most two source assets, while generated crops do not count toward
that limit.

The received-byte digest is provenance, not a global idempotency key: the same
photograph may legitimately appear on two receipts. Idempotency is scoped to
capture + asset role + sanitized digest and to the control operation key.

### `mb.inventory.capture.attempt`

One immutable terminal processing attempt. Queue and lease transitions live in
the control plane rather than mutating this audit row. Fields include
capture/company, stable UUID, parent attempt, operation key, kind (`barcode`,
`ocr`, `multimodal`, `lookup`), provider/model/version, input asset IDs and
digests, request ID, state, start/end timestamps, bounded diagnostic status,
normalized response, safe failure code, usage/units and estimated cost. A retry
appends a child; an Odoo attempt is never updated. Raw provider bodies are not
persisted. The manager-only `raw_response` compatibility field contains only a
bounded redacted diagnostic object and should be renamed in a future schema
migration.

The built-in worker already sends only `{"retained": false}`. Before enabling
third-party callbacks, tighten the Odoo receiver to reject every other
`raw_response` shape; its current generic bounded-JSON validation is a compatibility
gap, not permission to persist a provider envelope.

### `mb.inventory.capture.candidate`

Store each product/lot/date/quantity candidate with `attempt_id`, raw value,
normalized value, kind, provider/source, numeric confidence, explanation,
evidence asset/token references, reported region, grounding state and whether
the user accepted/rejected/edited it. Preserve the original proposal when a user
corrects it. An AI region without matching deterministic tokens is explicitly
`unverified`, not evidence.

### `mb.product.identifier`

Use this only when Odoo's one primary barcode is insufficient. It links a
`product.product` to a scheme/value/provider/source record, pack identity and
verification state. Normalize every UPC/EAN/GTIN to a canonical GTIN-14
comparison key while preserving the printed value/scheme for display. A valid
GS1 identifier is global and must have `company_id = False`; enforce one owner
with a unique index on `(comparison_scheme, normalized_value)`. For non-GS1 or
private identifiers, use one partial unique index on `(comparison_scheme,
normalized_value)` where `company_id IS NULL` and another on `(company_id,
comparison_scheme, normalized_value)` where `company_id IS NOT NULL`. Mirror
every primary `product.product.barcode` into this registry so primary and
alternate identifiers cannot conflict across two products. Deactivating a
product does not release an identifier: reassignment changes its owner only
through an explicit manager action that records old/new owners and reason.
Resolution fails visibly unless exactly one product remains.

### Native records

- `product.product` remains the product/pack identity.
- `product.product.barcode` remains the primary ordinary EAN/UPC/GTIN.
- `stock.lot` remains the supplier lot.
- `stock.move.line` remains the receipt's product, lot, quantity and locations.
- With `product_expiry`, `stock.lot.expiration_date`, `use_date`, `removal_date`
  and `alert_date` remain the native lifecycle dates. The first release may
  apply only a user-confirmed `expiration_date`; it never derives the other
  dates unless the product has reviewed shelf-life configuration.
- The sanitized evidence image may be linked to the confirmed lot through the capture, but
  do not duplicate the binary on both models.

Create/reuse a lot by `(company, product, exact supplier lot value)` under the
native Odoo constraints. Never merge the same printed value across different
products. Preserve leading zeroes and original case unless the manufacturer has
a documented normalization rule.

## 7. Security, privacy and lifecycle

- Camera permission is requested only after the user taps the capture button.
- Show what will leave the device and which provider processes it.
- Store API credentials in deployment secrets/control plane, never in capture
  JSON, Odoo attachments, logs or browser assets.
- Treat the browser upload as transient input. Hash the received bytes, validate
  the file signature and MIME type, decode it server-side, cap pixels/bytes,
  apply EXIF orientation to the pixels, then strip all EXIF/XMP/IPTC metadata,
  including GPS. Persist only the sanitized evidence rendition and delete the
  transient upload after the same transaction commits; on failure, persist
  neither. UI and documentation call this sanitized evidence, not an original.
- A provider adapter may expose a remote product image only when its terms permit
  display and caching. Proxy permitted images for review with strict
  size/content/time limits; never persist UPCitemDB images and never let the Odoo
  server fetch an arbitrary URL supplied by a client.
- Apply Odoo company record rules to captures, assets, attempts, candidates and
  identifiers.
- Inventory users can capture/review their company's records; only inventory
  managers can create a new product from a provider candidate or override an
  identifier conflict.
- Define retention separately for sanitized evidence images and structured
  audit data. A reasonable starting point is to retain applied lot evidence for
  the lot's traceability lifetime, while automatically purging
  cancelled/unapplied images after 30 days. Make the period configurable and
  document backup impact.
- Log hashes, provider IDs and decisions, not full OCR/photo content.

## 8. Failure and concurrency rules

- Loss of network after capture leaves a retryable draft; it creates no stock.
- Provider timeout degrades to local match/manual entry.
- A repeated callback with the same operation key and payload digest is
  idempotent; reusing the key with a different digest is rejected.
- Applying a capture takes a row lock and rechecks the move line and product
  tracking. Lot creation runs inside a savepoint, relies on the native/database
  unique constraint, catches a unique violation and re-queries the winning lot;
  a row lock alone cannot protect a row that does not yet exist.
- Two operators confirming the same product/lot converge on one native lot.
  Identifier assignment uses the same constraint/savepoint/re-query pattern and
  never relies only on a prior search.
- A barcode already assigned to another product blocks confirmation and
  creates a manager review activity.
- A product candidate whose pack size conflicts with the receipt line must be
  explicitly reconciled; quantity conversion is never inferred from an image
  title alone.
- Cancelling a receipt does not delete the product, lot or applied capture
  evidence. It leaves the normal Odoo audit trail and marks the capture's linked
  operation cancelled.

## 9. Delivery increments

### Increment 0 — evidence and provider benchmark (POC partial; release gate open)

- Use at least 100 real workshop packages under realistic lighting as the
  discovery set; record ground-truth barcode, manufacturer, SKU, pack size and
  lot, and catalogue actual manufacturer lot markers and patterns. Seed this
  work with the documented [six-image pilot](PRODUCT-PHOTO-INVENTORY-CAPTURE-SAMPLE-TEST.md),
  which proves feasibility but not accuracy.
- Build a separate locked validation set. Before allowing automatic
  preselection, the policy must produce at least 600 independently sampled,
  qualifying preselection decisions across brands, substrates, languages,
  lighting and devices; do not tune prompts, rules or thresholds on this set.
- Measure catalogue, Barcode Lookup and Open Facts coverage without importing.
- Reproduce the UPCitemDB POC on the discovery corpus. Record exact-identifier
  coverage separately from complete brand/SKU/name/pack metadata, cache positive
  results for 30 days and negative results for 24 hours, and confirm production
  storage/reuse terms before enabling it for tenants.
- First verify that the current Azure subscription/resource is live, funded,
  budgeted and authenticates with the broker-delivered key. A dead Free Trial
  blocks the cloud benchmark, not local corpus work.
- Run the supplied images, their label crops and then the discovery corpus
  against the existing development Document Intelligence endpoint.
- If it misses the agreed OCR threshold, compare a supported Azure successor,
  a suitable multimodal OCR model and—only as a time-bounded option—deprecated
  Azure Vision Image Analysis 4.0 Read. Compare accuracy, latency, EU
  processing, retention, lifecycle and cost rather than forcing a binary Azure
  choice.
- Update `../makersbrain-infra` with the isolated development endpoint, broker
  secret delivery, limits and smoke tests specified in section 5.3 only for the
  provider justified by those results.

Exit: a versioned, redacted discovery corpus, a locked validation manifest and
a provider report choosing **Document Intelligence**, a **supported successor**,
a **temporary Vision endpoint**, another approved provider, or **manual-only**.
No cloud provider is required if none passes the gate. Do not buy an annual API
plan or provision a second production service before this result.

### Increment 1 — camera, barcode and local product match (still-image baseline implemented)

- Scaffold `mb_inventory_capture` for Odoo 19 Community.
- Add the receipt-line and standalone capture actions.
- Implement camera/upload UX, image checks and barcode decoder.
- Normalize/check EAN/UPC/GTIN and parse GS1 AIs.
- Match existing products and show evidence.
- Apply exact product + GS1 lot to a draft receipt after confirmation.

Exit: a phone photo of a supported barcode identifies an existing variant; a
GS1 lot fills a draft receipt; no internet/OCR is necessary.

### Increment 2 — catalogue and online product candidates (implemented; approval gate open)

- Add identifiers/barcode endpoint to the ceramics catalogue.
- Implement provider contract, caching, timeouts and provenance.
- Add Barcode Lookup or the provider chosen by Increment 0.
- Build match/map/import/create review choices.
- Prevent provider fields from overwriting curated product data silently.

Exit: an unknown real glaze barcode yields a reviewable product candidate, or a
clear no-result, and confirmation creates/imports at most one correct variant.

### Increment 3 — OCR, AI fallback and printed lot review (code implemented; benchmark gate open)

- Add the `inventory-capture` control-plane queue, typed operation, module gates,
  broker allowlists, authorized asset-pull route and signed/idempotent result
  receiver described in section 5.3.
- Add asynchronous provider adapters and append-only attempt/retry handling.
- Store token boxes/confidence and render evidence crops.
- Implement generic lot markers and the first manufacturer profiles.
- Add ambiguous-character, date and product-code exclusion handling.
- Add the schema-constrained multimodal fallback for unresolved cases.
- Implement and benchmark capability-compatible Azure-hosted multimodal, Gemini,
  OpenAI and Claude adapters. Enable only approved primary/secondary routes per
  tenant; no deployment is required to configure every provider.
- Ground AI product proposals through the catalogue/provider chain and visually
  distinguish grounded matches from unverified visual suggestions.
- Add prompt-injection resistance, provider timeout/quota controls and a
  per-company switch disabling AI analysis.
- Apply confirmed lot to the native receipt move line.

Exit: the benchmark corpus meets agreed precision; every non-GS1 OCR lot needs a
visible user confirmation, including candidates recovered by AI after ordinary
OCR fails.

### Increment 4 — near-live UX, hardening and operations (core loop implemented; field validation open)

- Add concurrency, retry, retention, security and multi-company tests.
- Add the Web Worker frame loop, stable two-frame decode, scan-generation IDs,
  explicit cache/lookup states and continuous lot-framing guidance.
- Move only external cache misses to bus/poll completion if field measurements
  show that the bounded synchronous request misses the latency/concurrency SLO.
- Add provider quota/latency/error metrics without photo content.
- Complete the French catalogue for the English source UI and the accessibility pass.
- Test iOS Safari, Android Chrome, desktop upload and hardware scanner input.
- Write operator and administrator documentation and a rollback/disable switch.

Exit: staged receipt trials can be audited from sanitized evidence image to
`stock.move.line` and native traceability report.

Planning estimate, including the cross-repository work omitted by a simple addon
estimate:

| Workstream | Engineering days |
| --- | ---: |
| Evidence collection, ground truth and provider evaluation | 5–8 |
| Odoo models, receipt workflow and Owl camera/review UI | 10–15 |
| Control-plane queue, broker, asset/result contracts and observability | 8–12 |
| Catalogue identifiers, exact lookup API and Odoo glue | 5–8 |
| Infrastructure, secret migration, budgets and provider smoke tests | 3–5 |
| OCR/AI normalization, grounding and manufacturer rules | 6–10 |
| Security, concurrency, browser validation, operations and documentation | 6–10 |
| **Total effort** | **43–68** |

These are effort days, not elapsed calendar days; independent workstreams can
overlap. Provider procurement and a statistically adequate validation corpus can
extend elapsed time. Increment 1 remains independently useful and should be
demonstrated before committing to cloud OCR.

## 10. Test strategy

### Server tests

- EAN/UPC/GTIN normalization, check digits and leading zeroes.
- Official Odoo GS1 examples plus AI `01`, `10`, `17`, `30`, FNC1 and
  variable-length edge cases.
- Local exact match, no match and duplicate-identifier refusal.
- Provider response normalization, cache expiry, 404, 429 and timeout for each
  enabled product-lookup and multimodal adapter.
- Positive and negative cache entries, provider/schema/GTIN key isolation,
  schema-version invalidation, tenant policy isolation and concurrent-miss
  single-flight behavior.
- Asset-pull authorization, capture/asset ownership, digest/length/MIME mismatch,
  cancelled-capture `410`, size limits and rejection of arbitrary URLs or
  attachment IDs.
- Result-receiver signature, operation-key replay, conflicting payload digest,
  late callback and retry-parent behavior.
- The control-plane queue/database and logs contain no image bytes, base64,
  credentials or provider response bodies.
- Schema-invalid, contradictory and `unknown` multimodal responses.
- An image containing instruction-like label text cannot trigger tools or
  bypass review.
- Catalogue pack-size variant matching.
- Lot reuse scoped to product/company; same lot text on two products stays two
  lots.
- Idempotent extraction callbacks and confirmation.
- No unreviewed capture creates product, lot, move line or quantity.
- Access and record rules across two companies.
- Receipt changed/cancelled while OCR is running.

### Browser tests

- Permission denied, no camera and upload fallback.
- Rear camera selection, retake and two-photo flow.
- Exact scan, multiple codes in frame and checksum-invalid code.
- Candidate crop/highlight and keyboard/screen-reader review.
- AI fallback opt-in, processing state, grounded/unverified badges and manual
  recovery after provider failure.
- Near-live two-frame consensus, check-digit rejection, scan-generation rollover,
  stale-response rejection, uninterrupted preview and non-blocking worker decode.
- Progressive local/cache/online states and a concurrent lot-capture path while
  an external product lookup remains pending.
- Offline/network interruption and safe retry.
- Confirmation changes only the intended draft move line.

### Extraction evaluation

Keep a ground-truth manifest separate from test images. Report precision and
recall by source:

- barcode product identification;
- exact GS1 lot extraction;
- OCR lot candidate present in top 1/top 3;
- AI recovery rate when deterministic barcode/OCR lookup fails;
- grounded versus unverified AI product suggestions;
- false lot proposal rate; and
- full correct product + pack + lot result.

Measure near-live latency on named low/mid/high reference phones and supported
browsers with fixed frame sizes and warm/cold cache plus Wi-Fi/mobile network
profiles. Instrument timestamps for frame submission, stable decode, local
resolution, cache response, external completion, crop acceptance and lot proposal;
“code framed” is approximated by the first frame in the two-frame accepted pair.
Report p50/p95 and sample count rather than a provider-only duration.

Production gate: zero silent false confirmations by design. Any OCR lot class
that is preselected must achieve at least 99.5% precision on the locked set and
publish its sample count and one-sided 95% confidence bound. As an initial
simple gate, zero false preselected values in at least 600 qualifying independent
cases gives an approximate upper error bound of 0.5% by the rule of three; use
an exact binomial interval in the report. Stratify results by brand, substrate,
language, device and lighting so one easy class cannot hide a weak class. If the
locked set is smaller or any stratum lacks support, show candidates without a
default until more evidence exists. Coverage may be lower—manual review is an
acceptable fallback; false traceability is not.

## 11. Acceptance scenarios

1. Photograph a Mayco/AMACO jar already in Odoo. Its barcode resolves the exact
   pack variant, OCR highlights the printed lot, and confirmation fills a draft
   receipt without validating it.
2. Scan a GS1 Data Matrix containing GTIN and AI `10`. The result needs no OCR
   and records the exact encoded lot.
3. Photograph a clay bag whose barcode is not local but exists in the ceramics
   catalogue. The user imports/maps the candidate, confirms the bag's printed
   lot and receives it as a lot-tracked material.
4. Photograph a generic consumable with an online match but no lot tracking.
   The product is proposed; OCR text does not create a meaningless `stock.lot`.
5. Photograph two similar glaze labels or an image containing two barcodes. The
   system asks which item is intended and writes nothing before selection.
6. OCR reads `LOT 8O1B` with ambiguous `O/0`. Both the crop and alternatives are
   visible; the user correction is preserved alongside the original candidate.
7. No provider recognizes the barcode. Manual product/lot entry remains
   available; **Analyze with AI** extracts visible brand/SKU/lot candidates and
   grounds the product through a new catalogue search. If that also fails, the
   failed attempts remain auditable without blocking manual receipt.
8. Submit the same image/callback twice. Only one applied capture/lot assignment
   results.
9. A user from another company cannot read the photograph, OCR or candidates.
10. Disable every external provider. Local barcode/GS1 capture and ordinary
    manual inventory continue to work.

## 12. Decisions to settle after Increment 0

- Which actual glaze/clay families require supplier-lot tracking, beyond the
  minimum needed for food-contact traceability?
- Does the 100-container discovery benchmark justify paid Barcode Lookup, a
  different provider, or catalogue-only lookup? It does not establish the
  99.5% preselection gate.
- Is cloud OCR acceptable for product-label photographs, and in which region?
- Which multimodal vision model/provider meets the corpus accuracy, regional
  processing, retention, contractual and per-image cost requirements? Benchmark
  Azure-hosted multimodal, Gemini, OpenAI and Claude through the common adapter
  contract; the answer may be different for primary and explicit retry.
- What is the legal/operational retention period for sanitized lot evidence?
- Should confirmed GTINs learned during review write back only to tenant Odoo,
  or enter a separate catalogue curation queue? They must never write directly
  into the shared canonical catalogue.
- Is direct standalone inventory adjustment needed in the first release, or is
  receipt-first sufficient?

The recommended target is receipt-first and catalogue-first, with local crop OCR
before a single configured multimodal primary, an optional explicit secondary
retry, human confirmation of every non-GS1 lot and no automatic write-back to the
shared catalogue. The present implementation uses Azure Document Intelligence
OCR followed conditionally by the configured native Azure-hosted, Gemini, OpenAI
or Claude primary and, for eligible transport/contract failures only, one
explicit secondary. The reviewed local crop route is implemented; provider and
device release gates remain open.

For an Azure deployment, update `../makersbrain-infra` and create only the
Document Intelligence, supported successor, temporary Vision and Azure-hosted
multimodal resources individually justified by the benchmark, in the approved EU
region. Gemini, OpenAI and Claude credentials/endpoints follow the same broker-only
secret-delivery pattern without requiring Azure infrastructure. Retrieve results
immediately and call a provider deletion API when that provider exposes one and
policy requires it, including the Document Intelligence Delete Analyze Result API.
Microsoft states that Document Intelligence processes and temporarily stores the
input/results in the resource's region, retains an analyze result for 24 hours by
default, and supports earlier deletion. See [Microsoft's Document Intelligence
privacy and retention documentation](https://learn.microsoft.com/en-us/azure/foundry/responsible-ai/document-intelligence/data-privacy-security?view=form-recog-3.0.0).

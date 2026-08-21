# Product photo inventory capture

Odoo 19 receipt workflow for identifying a product and preserving the supplier
lot from one or two package photographs. No stock record changes until a user
reviews the candidates and presses **Apply to receipt**.

The addon uses the shared `mb_ai_bridge` for typed, idempotent, descriptor-only
job submission and callback metadata validation. Inventory-specific evidence,
candidates, review and stock writes remain here; provider HTTP clients and keys
remain in the control-plane extraction broker.

## Current development baseline

- Browser decoding uses the native Barcode Detection API where available and
  Odoo 19's pinned ZXing 0.21.3 fallback (Apache-2.0) elsewhere.
- Chrome's built-in foundation-model APIs are not used for scanning: they do not
  currently support Android/iOS and do not replace deterministic barcode/OCR
  evidence. Browser capability detection keeps this workflow portable.
- The camera samples downscaled frames in a Web Worker, reports simple
  light/glare/sharpness guidance, and accepts a checksum-valid barcode after two
  matching recent reads. A generation ID rejects stale lookup responses; the
  camera remains open for lot framing. Still-image upload and ZXing remain the
  fallback.
- Uploads accept genuine JPEG/PNG files up to 15 MB and a 50 MP safe decode
  bound. Odoo applies EXIF orientation, downsizes to at most 12 MP, strips all
  metadata by re-encoding, and persists only that sanitized rendition.
- A user can select and rotate a lot-text crop and optionally create a linked
  grayscale/autocontrast/threshold PNG. Both follow evidence retention; only the
  derivative is added to deterministic OCR, while paid multimodal analysis keeps
  the reviewed color crop and current front-label context. Retaking one role
  supersedes its current image and derived crops without deleting audit evidence.
- Local primary/alternate GTIN and GS1 AI 01/10/17/30 resolution runs first.
- The optional `mb_inventory_capture_catalogue` glue addon performs read-only
  exact GTIN or text lookup in the MakersBrain ceramics catalogue.
- An unknown checksum-valid GTIN can progress to the broker's UPCitemDB adapter.
  The shared PostgreSQL cache is keyed by provider/schema/GTIN-14, coalesces
  concurrent misses, and retains only normalized review candidates (30-day
  positive and 24-hour negative defaults).
- The control plane queues OCR using UUID/digest descriptors only. Its
  document-extraction broker pulls the sanitized bytes, verifies SHA-256,
  length, and MIME type, and fixes Azure models to `prebuilt-read` or
  `prebuilt-invoice`. After retrieving a successful result, the broker calls
  Azure's Delete Analyze Result endpoint before returning normalized data.
- Identical enqueue retries return the original operation ID. Normalized OCR and
  multimodal callback commands are durably checkpointed before delivery, so an
  uncertain callback is replayed with the identical operation key, attempt ID
  and payload instead of re-running a completed provider stage.
- If the tenant enables `inventory-ai-fallback`, a separately configured
  multimodal endpoint may return strict candidate JSON. Its product suggestions
  remain unverified until grounded by a provider lookup. A lot is machine-grounded
  only when deterministic OCR/decoded evidence contains the proposed value; an
  otherwise unverified lot can become user-verified only through explicit
  confirmation against the displayed sanitized evidence.
- Azure OCR and multimodal fallback usage are reserved independently. Defaults
  are 500 Azure inventory images and 100 multimodal images per workshop/month;
  deployment may lower them with `CONTROL_AZURE_MONTHLY_IMAGE_LIMIT` and
  `CONTROL_INVENTORY_AI_MONTHLY_IMAGE_LIMIT`.

Azure Power BI is suitable for later accuracy/cost reporting, but it is not an
image extraction service. The current deterministic backend uses Azure AI
Document Intelligence. Azure Vision is not provisioned unless a controlled
benchmark shows a material advantage over the existing development Document
Intelligence resource.

The product-lookup chain is local Odoo, MakersBrain catalogue, shared cache, then
the optional UPCitemDB adapter. Positive entries default to 30
days, negative entries to 24 hours, and concurrent misses for the same
provider/schema/GTIN are coalesced. UPCitemDB data is review-only; raw responses,
offers, descriptions and third-party images are not retained.

## Multimodal providers

The broker contract supports Azure-hosted multimodal models, Google
Gemini, OpenAI and Anthropic Claude through separate capability-compatible
adapters. Azure Document Intelligence remains a deterministic OCR adapter. A
tenant may configure zero or more AI adapters, with one benchmark-approved primary
and at most one explicit secondary retry; the system does not call every provider
for every capture.

Every adapter receives the same bounded sanitized crop/assets and deterministic
evidence, and must return the same strict versioned schema using `asset_id`.
Provider/model/version, request ID, latency and usage are normalized. Raw provider
bodies are held only for the active request and are not stored in the queue,
control-plane database or Odoo; Odoo's diagnostic `raw_response` field contains
only a bounded redacted status such as `{"retained": false}`. A valid `unknown`
response is not a reason to cascade to another paid model.

Provider credentials, model pins, region/retention policy and quotas belong only
to the extraction broker. A company may choose the names of one configured
primary and one distinct fallback; the broker validates that route and remains
the only component holding credentials. Consult the official
[Gemini image](https://ai.google.dev/gemini-api/docs/image-understanding),
[Gemini structured-output](https://ai.google.dev/gemini-api/docs/structured-output),
[OpenAI vision](https://developers.openai.com/api/docs/guides/images-vision),
[OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[Claude vision](https://platform.claude.com/docs/en/build-with-claude/vision), and
[Claude structured-output](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
documentation when implementing adapters.

## Configuration

The tenant Odoo process receives:

- `MB_CONTROL_BRIDGE_TOKEN`: tenant-scoped service credential, injected as an
  environment secret and never stored in an Odoo model;
- `MB_CONTROL_API_URL`: internal control API base URL.

Each company must also explicitly enable **Allow AI fallback for inventory
photos** and choose an available primary/optional fallback before the broker may
call a multimodal provider. Local barcode/GS1, OCR, crop, lookup and manual review
continue to work when it is disabled.

The extraction broker alone receives provider credentials. Its deployment
release contract defines the provider-specific Azure-hosted multimodal, Gemini,
OpenAI and Claude settings. Provision only the approved provider's secrets and
endpoints; create an Azure Vision endpoint only if a controlled benchmark shows
it is needed.

Unapplied sanitized images are deleted after 30 days by default. Override with
the system parameter `mb_inventory_capture.unapplied_image_retention_days`
(1–3650). Applied evidence follows the native lot traceability/backup lifetime;
structured attempts, digests, and decisions are retained when unapplied image
binaries are purged.

## Private sample evaluation

The supplied originals remain outside Git. Validate them without extracting
them to disk:

```sh
uv run --with pillow python tools/evaluate_inventory_capture.py \
  "/home/rick/Downloads/Photos-1-001 (2).zip"
```

Pass `--results normalized-results.json` to score exact barcode, lot, and
product fields against `fixtures/inventory_capture_expected.json`.

For an operator-authorized live development benchmark, load the protected
deployment environment and run:

```sh
set -a
. control-plane/deploy/.env
set +a
uv run --no-project --with pillow python \
  tools/benchmark_azure_inventory_capture.py \
  "/home/rick/Downloads/Photos-1-001 (2).zip" \
  --output /tmp/azure-inventory-capture-report.json
```

This benchmark-only path submits sanitized renditions directly because it is
used to qualify the provider before deployment. Production requests must still
go through the document-extraction broker. The tool deletes each terminal Azure
result and stores neither provider response bodies nor image bytes.

Use `tools/benchmark_azure_inventory_preprocessing.py` for controlled
grayscale, high-contrast, and black-and-white comparisons on explicitly named
samples. Benchmark derivatives are in-memory. The application can persist one
explicitly requested crop derivative as traceable OCR evidence, but it never
replaces the sanitized color crop or enters the paid multimodal request. The
six-image pilot found no lot-recall improvement from blind full-frame
enhancement, so production does not enable it by default.

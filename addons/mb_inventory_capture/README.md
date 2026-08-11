# Product photo inventory capture

Odoo 19 receipt workflow for identifying a product and preserving the supplier
lot from one or two package photographs. No stock record changes until a user
reviews the candidates and presses **Apply to receipt**.

## Current development baseline

- Browser decoding uses the native Barcode Detection API where available and
  Odoo 19's pinned ZXing 0.21.3 fallback (Apache-2.0) elsewhere.
- The current camera action takes a still image (or accepts an uploaded file),
  uploads its sanitized rendition, and then decodes that accepted file. It does
  not yet scan live frames or perform progressive online product lookup.
- Uploads accept genuine JPEG/PNG files up to 15 MB and a 50 MP safe decode
  bound. Odoo applies EXIF orientation, downsizes to at most 12 MP, strips all
  metadata by re-encoding, and persists only that sanitized rendition.
- Local primary/alternate GTIN and GS1 AI 01/10/17/30 resolution runs first.
- The optional `mb_inventory_capture_catalogue` glue addon performs read-only
  exact GTIN or text lookup in the Makersbrain ceramics catalogue.
- The control plane queues OCR using UUID/digest descriptors only. Its
  document-extraction broker pulls the sanitized bytes, verifies SHA-256,
  length, and MIME type, and fixes Azure models to `prebuilt-read` or
  `prebuilt-invoice`. After retrieving a successful result, the broker calls
  Azure's Delete Analyze Result endpoint before returning normalized data.
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

## Target v19 processing

The following behavior is planned and must not be treated as present in the
current Owl action:

- sample downscaled luminance frames in a Web Worker while keeping the preview
  responsive;
- accept a checksum-valid barcode only after matching reads in two recent frames;
- show local digits and product resolution first, then catalogue/cache/online
  states, with a scan-generation ID that discards stale responses;
- keep the camera open so product lookup and lot framing can proceed concurrently;
- rotate/rectify barcode-context and text regions, run bounded in-memory
  grayscale/CLAHE/sharpened/threshold variants through deterministic OCR, and ask
  for a closer detail photo when quality is insufficient; and
- send only one selected color lot crop by default, or at most two independently
  useful sanitized assets, to an enabled multimodal provider. Live video frames
  are never continuously uploaded.

The product-lookup target is local Odoo, Makersbrain catalogue, shared cache, then
an approved external adapter such as UPCitemDB. Positive entries default to 30
days, negative entries to 24 hours, and concurrent misses for the same
provider/schema/GTIN are coalesced. UPCitemDB data is review-only; raw responses,
offers, descriptions and third-party images are not retained.

## Multimodal providers

The target broker contract supports Azure-hosted multimodal models, Google
Gemini, OpenAI and Anthropic Claude through separate capability-compatible
adapters. Azure Document Intelligence remains a deterministic OCR adapter. A
tenant may configure zero or more AI adapters, with one benchmark-approved primary
and at most one explicit secondary retry; the system does not call every provider
for every capture.

Every adapter receives the same bounded sanitized crop/assets and deterministic
evidence, and must return the same strict versioned schema using `asset_id`.
Provider/model/version, request ID, latency and usage are normalized. Raw provider
bodies are held only for the active request and are not stored in the queue,
control-plane database or Odoo; Odoo's compatibility `raw_response` field contains
only a bounded redacted status such as `{"retained": false}`. A valid `unknown`
response is not a reason to cascade to another paid model.

Provider credentials, model pins, region/retention policy, quotas and primary/
secondary order belong only to the extraction broker. Consult the official
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

The extraction broker alone receives provider credentials. See
`control-plane/deploy/release-contract.json` for the currently implemented
environment contract. Provider-specific Azure-hosted multimodal, Gemini, OpenAI
and Claude configuration must be added there and in `../makersbrain-infra` only
when its adapter and benchmark route are approved.

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
samples. These are OCR-only in-memory derivatives; they never replace the
sanitized color evidence. The six-image pilot found no lot-recall improvement
from blind full-frame enhancement, so production must not enable it by default.

# Product photo capture: six-image pilot

- Date: 10–11 August 2026
- Source: six JPEG photographs supplied in `Photos-1-001 (2).zip`
- Source ZIP: read only and unchanged
- Evaluation method: ZIP members decoded and sanitized entirely in memory
- Scope: feasibility evidence, not an accuracy benchmark

## Result

These photographs are sufficient to prove the proposed layered workflow:

1. the printed UPC identifies the exact product and pack online;
2. the physical supplier lot is separately visible on the same label;
3. generic full-frame Tesseract OCR is not reliable on these curved, rotated,
   cluttered labels; and
4. visual AI can recover label structure and lot candidates that generic OCR
   misses, but ambiguous unlabelled inkjet lines still need user confirmation.

On 11 August, all six sanitized images were submitted to the live France Central
development Azure Document Intelligence endpoint using `prebuilt-read` and API
version `2024-11-30`. The credential authenticated successfully. Every analyze
result was deleted through Azure's result-deletion API after retrieval; source
images and provider bodies stayed in memory, and only aggregate match decisions
were retained below.

## Observations

| Image | Product evidence | Product result | Lot evidence | Confidence/action |
| --- | --- | --- | --- | --- |
| `PXL_20260810_150006272.jpg` | UPC `097539118054` | Mayco Stoneware Matte `SW-106 Alabaster`, 16 oz / 473 ml | Label explicitly prints `Lot#24111042` | Exact product and exact lot; strong deterministic case. |
| `PXL_20260810_150008818.MP.jpg` | Front text `AMACO`, `Blue Midnight`, `PC-12`, `16 fl oz (472 ml)` | AMACO Potter's Choice `PC-12 Blue Midnight`, pint | No lot or foreground barcode visible | AI/OCR can identify product, but the UI must request a second lot/detail photo. |
| `PXL_20260810_150011411.jpg` | UPC `039672394025`, reorder `39402B` | AMACO Celadon `C-10 Snow`, 16 oz / 473 ml | Inkjet lines `1213724` and `0196`, with no visible `LOT` marker | Propose `1213724` as likely lot and retain `0196` as an alternative/auxiliary code; confirmation required. |
| `PXL_20260810_150016223.MP.jpg` | UPC `039672354340`, reorder `35434V` | AMACO Potter's Choice `PC-33 Iron Lustre`, 16 oz / 473 ml | Inkjet lines `0507625` and `0704`, with no visible `LOT` marker | Propose `0507625` as likely lot and retain `0704` as an alternative/auxiliary code; confirmation required. |
| `PXL_20260810_150018482.jpg` | UPC `097539108055` | Mayco Stoneware Classic `SW-166 Norse Blue`, pint / 473 ml | Label explicitly prints `Lot#2515022` | Exact product and exact lot; strong deterministic case. |
| `PXL_20260810_150035576.MP.jpg` | UPC `097539397145` | Mayco Jungle Gems/Crystalites `S-2726 Cheetah`, 4 oz / 118 ml | Label explicitly prints `Lot#2216038` | Exact product and exact lot; blur/rotation makes this a useful camera-decoder test. |

The exact UPC lookups were corroborated by current supplier pages:

- [Mayco SW-106 Alabaster](https://www.dickblick.com/items/mayco-stoneware-matte-glaze-alabaster-16-oz/)
- [AMACO C-10 Snow](https://www.dickblick.com/items/amaco-celadon-glazes-snow-pint/)
- [AMACO PC-33 Iron Lustre](https://www.dickblick.com/items/amaco-potters-choice-glaze-pint-iron-lustre/)
- [Mayco SW-166 Norse Blue](https://www.dickblick.com/items/mayco-stoneware-classic-glaze-norse-blue-pint/)
- [Mayco S-2726 Cheetah](https://maycopaintstore.com/mayco-s2726-4-cheetah-4-oz)

Online lookup therefore grounded all five barcodes with expected ground truth:
`097539118054` → SW-106 Alabaster, `039672394025` → C-10 Snow,
`039672354340` → PC-33 Iron Lustre, `097539108055` → SW-166 Norse Blue, and
`097539397145` → S-2726 Cheetah. The barcode-free Blue Midnight photograph was
also corroborated by product text; its pint UPC is `039672354296`, but that value
must not be attributed to the photograph unless decoded from another image or
selected from a grounded catalogue/provider result.

## Baseline OCR test

Tesseract English, page-segmentation mode 11, was run against each unmodified
full image. It recovered fragments of manufacturer/legal text and occasional
barcode digits, but it did not reliably return any of the four explicit Mayco
lot strings and did not recover the two AMACO inkjet groups as usable structured
values. This is expected from:

- vertical and rotated text;
- cylindrical perspective and label curvature;
- small dot-matrix printing;
- glaze drips, worn labels and background containers;
- more than one product in frame; and
- the barcode, product reference and lot occupying different orientations.

Cropping, rotation, contrast and manufacturer-specific rules should improve the
deterministic baseline, but this sample demonstrates why conventional OCR cannot
be the final fallback.

## Live Azure Document Intelligence result

The exact expected value was searched in normalized Azure OCR text. Product
matching required every expected brand, manufacturer-code, and name term; it
did not award credit for brand recognition alone.

| Field | Exact matches | Interpretation |
| --- | ---: | --- |
| UPC/barcode | 1 / 5 | Document OCR is not a replacement for the browser barcode decoder. |
| Supplier lot | 3 / 5 | It recovered PC-33 `0507625`, SW-166 `2515022`, and S-2726 `2216038`; it missed SW-106 `24111042` and C-10 `1213724`. |
| Complete product term set | 1 / 6 | It recovered AMACO PC-12 Blue Midnight completely; other photos need barcode grounding or multimodal recovery. |

Azure also recovered both secondary AMACO inkjet strings, `0196` and `0704`.
Per-image completion took 2.7–7.3 seconds (about 3.5 seconds average), and all
six deletion checks passed. This small pilot rejects Document Intelligence as a
standalone product-label solution, while retaining it as a useful deterministic
lot/OCR stage before the schema-constrained AI fallback.

### Grayscale and high-contrast experiment

The two photos whose expected lots were missed were re-tested with three
deterministic, metadata-free derivatives: grayscale plus autocontrast/unsharp
mask, stronger grayscale contrast, and Otsu-thresholded black-and-white. None of
the six additional analyses recovered SW-106 lot `24111042` or C-10 lot
`1213724`. Both grayscale variants retained the C-10 barcode and secondary
`0196` code, while hard black-and-white retained the barcode but lost `0196`
and reduced recognized words.

Therefore the application must not apply black-and-white/high contrast blindly.
Keep the sanitized color image as evidence. A derivative may be generated in
memory for an explicitly bounded OCR attempt, but the next benchmark should
prioritize a rotated close crop of the lot area or the guided second-photo flow.
If those fail, use the schema-constrained multimodal fallback and show the
original crop for human confirmation. All six derivative analyze results were
deleted after retrieval.

## Live multimodal model comparison

On 11 August 2026, the same six sanitized images were sent one at a time to
OpenAI and Gemini with the same ground-truth-blind prompt and strict response
schema. OpenAI requests used `store: false`; the local reports contain only
sanitized-image hashes, normalized candidates, usage, timings, and match
decisions. They do not contain image bytes, API keys, or complete provider
envelopes. Provider-side abuse-monitoring and retention terms still apply.

Matches below are exact after case/punctuation normalization. A combined value,
nearby digit, or plausible product name did not receive credit. Costs are
estimates from returned token usage and the providers' standard list prices on
the test date; they exclude tax, free-tier allowances, batch discounts, and
network costs.

| Model | UPC | Lot | Complete product | Mean latency | Estimated six-photo cost |
| --- | ---: | ---: | ---: | ---: | ---: |
| Gemini 3.1 Flash-Lite | **5 / 5** | 2 / 5 | 1 / 6 | 3.40 s | **$0.00444** |
| Gemini 3.5 Flash-Lite | **5 / 5** | 2 / 5 | 1 / 6 | 3.42 s | $0.00465 |
| Gemini 3.5 Flash | **5 / 5** | **3 / 5** | 1 / 6 | 5.06 s | $0.04497 |
| OpenAI GPT-5.6 Luna | 2 / 5 | 1 / 5 | 1 / 6 | 6.41 s | $0.01769 |
| OpenAI GPT-4o mini, high detail | 2 / 5 | 0 / 5 | 1 / 6 | **2.73 s** | $0.02353 |
| OpenAI GPT-5.6 Terra | 3 / 5 | **3 / 5** | 1 / 6 | 8.10 s | $0.18332 |
| OpenAI GPT-5.6 Sol | 4 / 5 | **3 / 5** | 1 / 6 | 10.77 s | $0.44994 |

GPT-4o mini did visibly read the SW-166 lot digits but returned `Lo# 2515022`
inside `raw_value`, so the strict structured-value scorer rejected it. Even if
that field-label formatting were normalized, its lot score would be only 1/5.
Its low per-token price also did not make the high-detail run cheapest: the six
images consumed 154,734 input tokens. Gemini 3.1 Flash-Lite used 7,260 input,
1,087 candidate-output, and 660 thinking tokens.

For the first implementation, use Gemini 3.1 Flash-Lite as the inexpensive
multimodal fallback, behind deterministic barcode decoding and OCR. Escalate an
unresolved capture to Gemini 3.5 Flash only when the user requests another
attempt. Never auto-confirm a supplier lot from either model: both Flash-Lite
versions confidently returned wrong or combined lot strings on some photos.
The product identity should continue to come from a checksum-valid barcode plus
a grounded catalogue lookup; the visual model is not a replacement for that
lookup.

### Region-isolation POC

The follow-up POC implements the proposed decomposition rather than enhancing a
complete frame indiscriminately:

1. read and sanitize each ZIP member in memory;
2. try right-angle orientations and decode UPC/EAN/GTIN with ZXing-C++;
3. reject any decoded value with an invalid GS1 check digit;
4. use rotated full-frame Tesseract layout only to propose possible lot regions;
5. add a wider region perpendicular to each barcode, because supplier lots are
   often printed directly above or beside it;
6. choose a likely text orientation and produce original, grayscale, CLAHE,
   sharpened, and adaptive-threshold evidence crops; and
7. send at most two selected color crops to Gemini 3.1 Flash-Lite with a
   lot-only schema and an explicit `unknown` result.

| POC stage | Exact result | Observation |
| --- | ---: | --- |
| Deterministic ZXing-C++ barcode | **5 / 5** | All visible UPCs decoded and passed their check digit. |
| Crop-level Tesseract lot candidate | 2 / 5 | Exact on SW-166 and S-2726; useful for localization, not confirmation. |
| Two-crop Gemini 3.1 Flash-Lite lot | **3 / 5** | Exact on PC-33, SW-166, and S-2726; correctly returned no lot for Blue Midnight. |

The crop model separated PC-33's `0507625` and `0704` inkjet lines and warned
that their meaning is ambiguous. It still misread Alabaster `24111042` as
`2411042` and C-10 `1213724` as `121972`, demonstrating that a high-confidence
model response is not sufficient for automatic inventory mutation.

The two-crop run averaged 1.88 seconds at the provider and used 13,890 input,
533 candidate-output, and 943 thinking tokens. At the test-date standard price,
that is approximately $0.00569 for six photos, or $0.00095 per photo. It is about
28% more expensive than the one-full-image Gemini 3.1 run, but recovered one
additional exact lot and produced a much better evidence crop for review. A
one-crop route should be included in the larger discovery benchmark.

Run the local stage without sending anything to a provider:

```sh
UV_CACHE_DIR=/tmp/mb-region-poc-uv-cache uv run --script \
  tools/poc_inventory_label_regions.py \
  "/path/to/private-photos.zip" \
  --output-directory /tmp/mb-inventory-region-poc/crops \
  --report /tmp/mb-inventory-region-poc/report.json
```

For a ground-truth-blind Gemini run, export `GEMINI_API_KEY` from an approved
secret source and run:

```sh
python tools/benchmark_multimodal_region_poc.py \
  /tmp/mb-inventory-region-poc/report.json \
  --output /tmp/mb-inventory-region-poc/gemini-report.json
```

`--expected fixtures/inventory_capture_expected.json` enables local scoring for
this private pilot; expected values are never included in provider prompts.

### UPCitemDB product-lookup POC

The decoded UPCs were also submitted to UPCitemDB's public trial lookup API in
three batches of at most two identifiers, spaced by ten seconds. Expected
product names were not sent to the provider and were used only for local
post-response scoring.

| Metric | Result | Interpretation |
| --- | ---: | --- |
| Exact returned GTIN/UPC | **5 / 5** | Every visible barcode returned a candidate bound to the requested identifier. |
| Complete expected brand + SKU + name terms | 2 / 5 | SW-166 and S-2726 were complete; other records were useful but incomplete or oddly normalized. |
| Cold-cache provider requests | 3 | Trial batches contain no more than two identifiers. |
| Immediate warm-cache provider requests | **0** | All five candidates came from the local cache. |

This establishes strong pilot coverage, not authoritative product metadata.
For example, the Alabaster record uses `Coloramics` as its brand and `Mayco` as
its model, PC-33 returns a reseller model instead of the manufacturer SKU, and
C-10 omits its manufacturer code. The exact barcode remains strong identity
evidence, but a manager must confirm the curated product variant before import.

`tools/benchmark_upcitemdb_lookup.py` implements a persistent SQLite cache keyed
by provider, schema version, and zero-padded GTIN-14 comparison value. It uses
WAL mode, a five-second busy timeout, atomic upserts, a 30-day positive TTL, a
24-hour negative TTL, and `--refresh` for explicit revalidation. It caches only
the normalized identifier, brand, manufacturer SKU, name, pack, category,
provider record ID, and retrieval time. Raw responses, descriptions, offers,
prices, and third-party images are deliberately discarded.

Run the POC with an explicit cache outside Git:

```sh
python tools/benchmark_upcitemdb_lookup.py \
  fixtures/inventory_capture_expected.json \
  --cache /tmp/mb-upcitemdb-poc-cache.sqlite3 \
  --output /tmp/mb-upcitemdb-poc-report.json
```

Re-running the same command uses the cache and makes no network requests until a
record expires or `--refresh` is supplied.

## Further Azure evaluation

Infrastructure ownership is `../makersbrain-infra`. First use its existing
development Document Intelligence endpoint after verifying that its subscription
is live, funded and authenticates through the extraction broker. If it misses
the threshold, compare a supported Azure successor such as Content Understanding
and the selected multimodal provider. Provision deprecated Azure Vision Image
Analysis 4.0 Read only if it shows a material advantage and its time-bounded
retirement plan is accepted, as described in section 5.3 of the main plan.

For every original and relevant crop, record the same outputs from:

1. Azure Document Intelligence `prebuilt-read` with high-resolution OCR where
   appropriate;
2. a supported Azure image/content extraction option such as Content
   Understanding;
3. the selected approved multimodal vision model, using the strict schema in
   the main plan; and
4. Azure Vision Image Analysis 4.0 Read only as an explicitly temporary
   comparison candidate.

Score exact product barcode, brand, manufacturer SKU, name, pack size, raw lot
candidate, lot-marker association, bounding polygon, latency and cost. Do not
score a product as correct merely because the model recognizes the brand.

Expected behavior for this set:

- three Mayco photos should yield an explicit marker-bound lot;
- two AMACO photos should yield two inkjet strings and an ambiguity warning;
- the Blue Midnight front photo should yield the product but `lot = unknown`;
- product lookup should ground five UPC-based identities online;
- no method should invent a lot for Blue Midnight; and
- no non-GS1 result should update Odoo before review.

## Capture UX changes justified by the sample

- Detect multiple containers and draw a selectable subject box.
- Prompt for a second photograph when the chosen product view lacks a lot area.
- Auto-rotate/crop each barcode and lot region independently.
- Show the decoded digits below the barcode before lookup.
- For AMACO-style two-line inkjet stamps, show both lines together and ask which
  value is the supplier lot until manufacturer semantics are verified.
- Prefer a close-up taken square to the label; the small Cheetah jar demonstrates
  that an otherwise readable barcode can become difficult through motion blur and
  rotation.

This pilot should be added to Increment 0, but the received originals should not
be committed to Git. If the owner approves retention, apply orientation, remove
all EXIF/XMP/IPTC/GPS metadata and commit only bounded sanitized evidence
renditions under the corpus access policy.

## Reproducible sanitizer check

`tools/evaluate_inventory_capture.py` now reads the supplied ZIP without
extracting originals to disk, applies orientation, downsizes, strips metadata
by re-encoding, and reports only dimensions, sizes, and hashes. On all six
files it reported no missing or unexpected samples. Each 12.2 MP phone image
became a 3005×3992 (under 12 MP) JPEG of approximately 1.57–1.76 MB. This run
exposed and fixed the initial implementation's rejection of ordinary 12.2 MP
phone images: the server now uses a 50 MP safe decode bound and persists only
the at-most-12 MP sanitized evidence rendition.

Expected product/barcode/lot values live in
`fixtures/inventory_capture_expected.json`; provider-normalized output can be
scored with the evaluator's `--results` option. The private image bytes remain
outside Git.

The live provider check is reproducible with
`tools/benchmark_azure_inventory_capture.py`. It reads credentials from the
environment, rejects non-Azure/cross-origin endpoints, sends only sanitized
renditions, bounds provider responses, deletes terminal results, and emits no
OCR body or credential. The aggregate report from the run above was written
under `/tmp`, not committed.

`tools/benchmark_azure_inventory_preprocessing.py` reproduces the deterministic
grayscale/high-contrast comparison. It stores only derivative hashes, sizes,
aggregate match decisions and timings; derivative bytes and OCR bodies remain
in memory.

`tools/benchmark_multimodal_inventory_capture.py` reproduces the OpenAI/Gemini
comparison. It sanitizes ZIP members in memory, uses schema-constrained output,
bounds responses, disables OpenAI response storage, and writes only the limited
normalized report described above. Reports from this private pilot remain under
`/tmp` and are not committed.

`tools/poc_inventory_label_regions.py` and
`tools/benchmark_multimodal_region_poc.py` reproduce the staged region POC. The
first writes private evidence crops only to an explicit output directory. The
second accepts only bounded PNGs beneath that declared directory, sends at most
two crops per photo, bounds the provider response, and stores hashes and
normalized candidates rather than image bytes or provider envelopes.

`tools/benchmark_upcitemdb_lookup.py` reproduces the product-lookup POC and its
cache behavior. Its report contains only normalized candidates, match decisions,
rate-limit metadata, timings, and cache hit/miss counts.

# Product Photo Inventory Capture: Remaining Release Plan

Status: implementation complete; release evidence open

The implemented behavior is specified in `SPEC.md` and documented operationally
in `addons/mb_inventory_capture/README.md`. This file contains only work that is
not complete.

## Release gates

1. Build and freeze the redacted discovery corpus and statistically useful
   validation set. Record separate barcode, lot-text, full-product, ambiguity,
   latency, and cost measures.
2. Run the supported phone/browser matrix on real receiving sessions. Verify
   continuous preview, worker decoding, rotated crop review, retakes,
   accessibility, poor-light guidance, memory bounds, and interruption recovery.
3. Complete automatic sharp-frame and crop selection without allowing an
   automatic choice to bypass user review or exact receipt-line validation.
4. Benchmark the currently supported extraction providers against the locked
   set, approve the production primary and optional secondary, and document the
   cost/privacy/retention decision. Keep unapproved provider routes disabled.
5. Exercise concurrency, stale-result rejection, provider outage, quota, cache
   invalidation, and retention jobs under production-like multiworker load.
6. Run controlled field acceptance on real clay, glaze, packaging, curved
   labels, damaged barcodes, handwritten lots, and unknown products. Record the
   manual fallback rate and every unsafe false-positive candidate.

## Acceptance

Release is allowed only when the signed evidence names the exact code release,
device/browser matrix, dataset version, provider policy, thresholds, observed
failure rates, cost envelope, and unresolved exceptions. No benchmark result may
write products, lots, quantities, receipts, or inventory without the existing
Odoo review and authorization boundary.

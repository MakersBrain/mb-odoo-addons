# Shop catalogue import

This addon imports catalogue artifacts emitted by the `catalogue-ceramics`
scraper. It does **not** parse an official SumUp merchant export. Supported
inputs are `ceramics.catalogue_item.v2` NDJSON (plain or gzip-compressed) and
the scraper's flattened CSV.

## Operator workflow

1. In **Inventory → Shop catalogue imports → Scraped shop sources**, create one
   stable source for the shop. Set its scraper source key, an uppercase SKU
   prefix, service category names, and allowed image hosts.
2. Create an import batch, upload the scraper artifact, select the workshop's
   finished-goods stock location and product category, and choose the price/tax
   interpretation.
3. Click **Parse file**. Parsing only creates staging lines; it never creates a
   product, changes stock, downloads an image, or creates a category/tag.
4. Review the normalized lines, then click **Validate**. Use **Filter review
   lines** for errors, warnings, matches, price/stock changes, services, and
   missing images. Validation records the current stock/reservation baseline.
5. Select the accepted valid lines. Explicitly acknowledge warnings, if any,
   and have a Shop Import Manager click **Import selected**.
6. If enabled, images are fetched after the atomic product/stock transaction.
   Failed images can be retried without repeating the product import.

Import failure rolls back every product, binding, and inventory mutation from
the batch while retaining a bounded failure result for review. A manager can
purge the original file and per-line raw JSON after the batch is closed; the
checksum, normalized results, affected products, and import summary remain.

## Product and depot policy

Every imported physical product is saleable, storable, not purchasable, and
invoiced on delivered quantities. Explicit MTO/Buy routes are removed. This is
the policy required by `mb_depot`: there is no separate product-level "depot"
flag. A physical product appears in a depot placement catalogue because it is
storable; after placement, the depot warehouse and its available quant control
whether it can be sold there.

Service-category rows become saleable, non-storable, non-purchasable services
invoiced on ordered quantities. Their source stock is ignored.

Only the selected target location is adjusted, to the reviewed exact quantity.
Null/untracked stock remains distinct from zero and is never adjusted. The
importer does not modify depot or other workshop locations and refuses to
overwrite stock that changed after validation.

`mb_shop_import_ceramics` automatically uses the canonical
`mb_ceramics_base.categ_finished_ceramics` category. `mb_shop_import_depot`
adds a runtime guard and integration coverage for the depot invariants. Both
are auto-installed only when their corresponding domain addon is present.

## Access and capability lifecycle

Reviewers may upload, parse, edit staging lines, and validate. Only managers
may ingest, fetch images, manage sources, or purge evidence. Company record
rules isolate sources, bindings, batches, and lines.

The control-plane capability key is `shop_catalogue_import`, mapped only to
`mb_shop_import`. The bridge's standard read-preserving restriction rules block
create/write/delete on the addon's owned models while keeping historical
batches and bindings readable. Re-enabling removes those rules; it does not
rewrite historical data.

## Limits and image safety

- Upload: 20 MB; decompressed artifact: 100 MB; records: 10,000.
- Retained raw JSON: 65,536 characters per record.
- Image: HTTPS only, source hostname allowlist, public IP resolution, pinned
  destination with TLS verification for the original hostname, at most three
  redirects, 15 MB and 50 megapixels.
- Images are decoded and normalized as a single-frame raster before storage.

The legacy `scripts/import_shop_catalogue.py` remains for transitional command
line use. The Odoo review workflow is the supported ingestion path.

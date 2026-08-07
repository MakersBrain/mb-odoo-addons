# Makersbrain label QR in Odoo 19 POS

`mb_label_pos` is an upgrade-safe companion to `mb_label`. It extends Odoo 19
through supported addon seams and does not replace or edit Point of Sale core:

- `pos.session._load_pos_data_models()` adds the bounded
  `mb.label.qr.alias` projection;
- `pos.load.mixin` supplies its fields, relations and IndexedDB/offline data;
- `ProductScreen` is patched with Odoo's `patch()` utility;
- `useBarcodeReader()` handles label URLs that a nomenclature returns as an
  error, while `_barcodeProductAction()` handles the usual catch-all product
  rule;
- `super._barcodeProductAction()` remains the final path for native EAN, UPC,
  GS1, weighted, priced and other ordinary Odoo barcodes.

## QR format

Set **QR URL prefix** in Label Studio, for example:

```text
https://instagram.com/username
```

Saving creates a new immutable version. The renderer then encodes and records:

```text
https://instagram.com/username#SKU
https://instagram.com/username#SKU/LOT-OR-SERIAL
```

SKU and lot segments use URL percent encoding, so slashes and spaces inside an
identifier cannot change the path structure. The full URL is the durable alias.

## Resolution order and safety

1. Exact normalized alias from the POS projection.
2. Authoritative online lookup, including aliases minted after the session
   opened and URL compatibility parsing.
3. Native Odoo barcode behavior when the value is not one of the configured
   label prefixes.

Retired and cross-company aliases, malformed paths, duplicate SKUs, unknown
lots, empty source-location stock and duplicate draft serials are rejected
before an order line is added. Product-only QR values deliberately provide no
lot code, so Odoo keeps its normal lot/serial selection dialog. Lot and serial
URLs use Odoo's standard tracked-product order-line path; serial quantity is
forced to one.

Exact aliases already loaded into IndexedDB continue working offline. A legacy
or newly minted alias that is not cached requires one online scan for
authoritative validation. Retirements and reactivations are checked online on
every scan; when offline, the last successfully loaded projection applies.
Restarting or reloading the POS refreshes the complete projection.

## Performance envelope

The browser builds a normalized `Map` index for constant-time exact lookup.
The server projection is restricted to the POS company and products allowed by
the POS product domain. The retained 1,000-alias regression fixture records
payload size and full POS bootstrap time in `tests/test_pos_qr.py`.

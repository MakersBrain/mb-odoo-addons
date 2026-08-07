# Makersbrain Label Studio

`mb_label` adds a versioned thermal-label editor and product/lot printing to
Odoo 19. It deliberately separates the document, renderer and printer
transport:

```text
immutable JSON document + product/lot bindings
    -> deterministic monochrome PNG and exact-size PDF
    -> system print, Phomemo BLE, or NIIMBOT BLE adapter
```

## Template bindings

The expression language is an allowlist, not Python or arbitrary ORM access:

- `{{product.name}}`
- `{{product.default_code}}`
- `{{product.barcode}}`
- `{{product.price}}`
- `{{product.price.raw}}`, for numeric formatting filters
- `{{lot.name}}`
- `{{company.name}}`
- `{{company.currency}}`
- `{{qr}}`
- `{{qr.path}}`, the URL-encoded `SKU` or `SKU/LOT` fragment path
- `{{manual.<name>}}`, for a value entered in the print wizard

Safe print-time expressions from the old editor are also supported:
`[[date]]`, `[[time]]`, `[[datetime]]`, `[[iso]]`, `[[month]]`,
`[[monthyear]]`, and formatted values such as `[[date|DD.MM.YY]]`.

Bindings accept safe, chainable format filters. For example,
`{{product.price|money_trim}}` prints `45 €` instead of `45,00 €` while retaining
real cents, `{{product.price.raw|money}}` uses the company currency,
`{{product.price.raw|fixed:1}}` fixes decimal precision, and `|number`, `|trim`,
`|upper`, `|lower`, `|title`, or `|default:Text` handle common label formatting.

Text, QR and barcode elements also have a **Required value** switch. Disable it
for optional bindings such as `{{lot.name}}`; when the binding is empty, the
entire element—including its background—is omitted. Required elements continue
to fail visibly instead of producing an incomplete label.

QR elements are kept square and expose a **Quiet zone** setting. `0` fills the
entire defined square, matching the old editor. Margins of 2–4 modules improve
scanning when the QR touches dark artwork; 4 modules is the QR standard.

## Editor and old JSON compatibility

Label Studio provides the old editor's practical design features in physical
millimetres: multi-selection and grouping, keyboard nudging, undo/redo,
rotation, z-order, rectangles, ellipses, triangles and lines, three bundled
font families, horizontal/vertical text alignment, bold/italic/underline,
background knockout, inverted ink, thermal tint patterns, image paste/upload,
four image dithering modes, round/continuous media, printer target and real
product/lot preview values.

The printer selector applies a matching resolution and recommended stock:
System/PDF uses 300 dpi, while the supported Phomemo M110/M120 and NIIMBOT
D110 families use 203 dpi. Selecting a printer applies its default stock size;
the dependent **Label stock** selector offers die-cut, round and continuous
presets while **Custom / manual** keeps arbitrary dimensions available.

**Import JSON** accepts the old Ateliera/phomymo version-3 format. Old element
coordinates are printer dots and are converted using `dotsPerMm` (8 when the
old file omitted it); the stored Odoo document remains in millimetres. Old
`name`, `price`, `ref`, `batch`, `qr`, manual and composed fields are converted
to the allowlisted bindings. Unsupported external brand-asset references are
reported as warnings rather than silently discarded. The import creates a new
template and immutable version 1. **Export JSON** writes a version-3 file with
resolution and media metadata so its physical geometry round-trips.

The canonical `qr` value is `<configured URL>#SKU` for a product-only label and
`<configured URL>#SKU/LOT` for a lot or serial. The URL prefix is configured per
template and snapshotted in each immutable version. Every rendered value is materialized in
`mb.label.qr.alias`; changing a template does not invalidate a physical label.

## Printing

- **System/PDF:** supported in normal desktop and mobile browsers. The PDF page
  is exactly the template size. Browser print requests the same size with zero
  margin; the driver still needs scale 100% and matching media.
- **Phomemo:** Web Bluetooth adapter for the M110/M120 203 dpi lineage.
- **NIIMBOT:** Web Bluetooth adapter for the common D110 protocol family.

Web Bluetooth requires Chrome/Edge on desktop or Android and is unavailable in
iOS Safari. PDF/system printing remains the fallback. The BLE protocols are
reverse-engineered and isolated in `static/src/printer/`; adding or correcting a
device does not change stored templates or the renderer.

The device-print client action opens as a modal and remains open after a
successful send. It remembers the last destination and the identifier of the
Chrome-authorized BLE device for the current Odoo origin, reconnecting without
the chooser when `Bluetooth.getDevices()` still exposes that grant. **Choose
another printer and print** deliberately opens the chooser again. Browser or
site-data permission resets simply fall back to the normal chooser.

Install the companion `mb_label_pos` addon to resolve these durable product and
lot/serial URLs in Odoo 19 Point of Sale, including offline exact-alias scans and
native barcode fallthrough.

## Roles

Inventory users inherit **Label Printer** and can preview/render/print.
Inventory administrators inherit **Label Designer** and can edit templates,
save immutable versions, and retire/reactivate QR aliases.

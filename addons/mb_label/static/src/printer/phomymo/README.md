# phomymo, vendored

Upstream: <https://github.com/transcriptionstream/phomymo>
Commit: `1f58d3f0e7f941b9143277cda828380149e56855` (2026-05-17)
Licence: ISC (`package.json`; upstream ships no LICENSE file)

Browser printing enters this vendored transport through
`../phomemo_adapter.js`. That adapter supplies Odoo's settings, raster and
print-job shell; this directory owns the Web Bluetooth transport and device
protocol commands. No other addon code imports these files directly.

## Files

| file            | source                                    |
| --------------- | ----------------------------------------- |
| `constants.js`  | `src/web/constants.js`, verbatim          |
| `ble.js`        | `src/web/ble.js`, verbatim                |
| `printer.js`    | `src/web/printer.js`, one deviation below |
| `printers.json` | `src/web/printers.json`, verbatim         |
| `raster.js`     | `src/web/canvas.js` lines 1885-2248       |

## Deviations

Every one is marked `mb:` in the source. There are two.

1. `printer.js` imports `printers.json` instead of `fetch`ing it. Upstream
   serves the file next to the page; this app has to print with no network,
   and the bundler inlines it.
2. `raster.js` is the pixel-to-raster path lifted out of `canvas.js`, which is
   otherwise a DOM-bound editor class we have no use for. The methods are
   standalone functions and `this._x(` reads `_x(`; the bodies are unchanged.

Each file also carries `// @ts-nocheck` so JavaScript-aware type checkers do not
rewrite or reject upstream's untyped implementation.

## Re-vendoring

Do not fix bugs here - fix them upstream and re-vendor, or the next re-vendor
silently undoes the fix. `../../../tests/printer_protocols.test.js` pins the
transport, raster and M110 command behavior this addon depends on; run the
`mb_label` web unit tests after any re-vendor.

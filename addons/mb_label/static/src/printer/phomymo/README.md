# phomymo, vendored

Upstream: <https://github.com/transcriptionstream/phomymo>
Commit: `1f58d3f0e7f941b9143277cda828380149e56855` (2026-05-17)
Licence: ISC (`package.json`; upstream ships no LICENSE file)

Printing in the browser goes through this code rather than through
`phomemo-protocol.ts`. The app's own encoder produces, for the M110, the same
bytes as `bridge/print_label.py` - which prints - and still would not print
from the browser, so the whole job was handed to upstream instead of bisecting
a stream that already matched a working one. `../phomymo-print.ts` is the only
thing that imports from here.

Native builds do not use this: `ble.js` is `navigator.bluetooth` throughout,
which a Capacitor build has no access to. Native keeps `phomemo.ts`.

## Files

| file            | source                                    |
| --------------- | ----------------------------------------- |
| `constants.js`  | `src/web/constants.js`, verbatim          |
| `ble.js`        | `src/web/ble.js`, verbatim                |
| `printer.js`    | `src/web/printer.js`, one deviation below |
| `printers.json` | `src/web/printers.json`, verbatim         |
| `raster.js`     | `src/web/canvas.js` lines 1885-2248       |

## Deviations

Every one is marked `ateliera:` in the source. There are two.

1. `printer.js` imports `printers.json` instead of `fetch`ing it. Upstream
   serves the file next to the page; this app has to print with no network,
   and the bundler inlines it.
2. `raster.js` is the pixel-to-raster path lifted out of `canvas.js`, which is
   otherwise a DOM-bound editor class we have no use for. The methods are
   standalone functions and `this._x(` reads `_x(`; the bodies are unchanged.

Each file also carries `// @ts-nocheck`, because the project sets `checkJs`.

## Re-vendoring

Do not fix bugs here - fix them upstream and re-vendor, or the next re-vendor
silently undoes the fix. `phomymo-print.test.ts` pins the behaviour this app
depends on; run it after any re-vendor.

# Frontend and asset qualification

The local frontend gates are the same entry points used by GitHub Actions:

```console
DISPOSABLE_DB=mb_scratch make assets-test
DISPOSABLE_DB=mb_scratch make browser-test
DISPOSABLE_DB=mb_scratch make frontend-test
```

All three targets destroy and recreate only an allowlisted disposable database.
The standalone `assets-test` and `browser-test` commands each install every
repository addon before their focused gate. `frontend-test`, which CI uses, installs
the addons once and runs both checks against that exact database and checkout.
`assets-test` deletes
generated `/web/assets/` attachments, clears Odoo's asset cache, verifies that
`mb_tokens.scss` precedes `primary_variables.scss`, and compiles backend, frontend,
POS, and unit-test consumers. `browser-test` runs the repository Hoot suites in the
digest-pinned Playwright Chromium image. It requires the exact expected test count,
zero failed tests, and zero browser console errors or uncaught exceptions.

On browser failure, `result.json`, `browser-console.json`, `chromium.log`, and a
page screenshot are written to `HOOT_ARTIFACTS` (default:
`/tmp/mb-odoo-hoot-artifacts`). CI uploads those files and the target's complete
console log for 14 days. The combined target keeps separate `assets.log` and
`browser.log` files under `FRONTEND_ARTIFACTS` (default:
`/tmp/mb-odoo-frontend-artifacts`); CI uploads them only on failure.

## Physical-device release check

CI mocks browser APIs and validates packet/raster construction; it does not claim
that real Bluetooth, camera, printer, media, or firmware combinations work. Before
a release that changes scanner, camera, raster, transport, or printer code, perform
and record this manual qualification:

1. Scan one supported QR label with the target camera/scanner and confirm selection,
   cancellation, repeated open/close, and permission-denied recovery.
2. Print representative text, barcode, QR, solid, and blank labels on a Phomemo M110
   and a NIIMBOT D110, including reconnect, cancellation, retry, and a second print
   without reloading Odoo.
3. Confirm dimensions, orientation, density, feed/cut behavior, and that no content
   is cropped on each supported media size.
4. Attach the Odoo version, addon version, browser/OS, device model, firmware, media,
   result, and operator to the release record.

A green automated browser lane is required in addition to this check; neither one
substitutes for the other.

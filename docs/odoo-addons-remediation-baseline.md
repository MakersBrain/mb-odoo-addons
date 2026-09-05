# Odoo add-ons remediation baseline

Captured on 2026-09-05 for the remediation defined in
`docs/odoo-addons-remediation-plan.md`.

## Pinned predecessor environment

- Source commit: `632e043e166d15ceceb8846fea120e3d6e928023`
- Odoo image: `odoo:19`, image ID
  `sha256:b035658c87344395df999c4ad196dd81e25be7a2e3c94cad4b87b87588afc939`
- PostgreSQL image: `postgres:17-alpine`, image ID
  `sha256:93aa428db0aeeb71d24dcad1491bef6e1396a4255697e4bfc4c725bfeb981b74`
- PostgreSQL runtime: `17.10`
- Locked extension Python packages: none. The hash-checked lock and inventory
  agree on an empty extension payload; runtime packages come from the pinned
  Odoo image.
- Platform: `linux/amd64`

The predecessor asset run failed while compiling a consumer of
`web._assets_primary_variables`: Sass resolved the relative `mb_tokens` import
from the concatenated web-core location and reported the import as missing.
That failure is the detection fixture for ASSET-01/CI-01; the candidate must
compile backend, frontend, login, and unit-test consumers without accepting a
warning as success.

## Discovered repository add-ons (41)

```text
l10n_fr_micro_enterprise
l10n_fr_micro_urssaf
mb_account_payment_sumup
mb_ai_bridge
mb_brand
mb_catalogue_sync
mb_ceramics_base
mb_ceramics_compliance
mb_ceramics_firing
mb_ceramics_workflow
mb_commercial_operations
mb_commercial_operations_depot
mb_commercial_operations_expense
mb_commercial_operations_fleet
mb_commercial_operations_mrp
mb_commercial_operations_pos
mb_commercial_operations_purchase
mb_commercial_operations_sale
mb_commercial_operations_stock
mb_commercial_operations_urssaf
mb_control_bridge
mb_dbfilter_gateway
mb_depot
mb_email_bridge
mb_inventory_capture
mb_inventory_capture_catalogue
mb_invoice_capture
mb_kiln_bridge
mb_label
mb_label_pos
mb_payment_sumup
mb_pos_sumup
mb_shop_import
mb_shop_import_ceramics
mb_shop_import_depot
mb_webshop
mb_webshop_carrier_base
mb_webshop_carrier_boxtal
mb_webshop_carrier_sendcloud
mb_workshop_base
mb_workshop_pos
```

## Candidate evidence collected during implementation

- RPC-private bridge/capture packages: 94 tests, zero failures/errors.
- Transaction atomicity packages: 98 tests, zero failures/errors.
- Commercial-depot and webshop multi-company packages: 44 tests, zero
  failures/errors.
- Label upgrade-safety package: 23 tests, zero failures/errors.
- Commercial stock allocation uniqueness: 7 tests, zero failures/errors,
  including genuine two-session contention.
- URSSAF invariant serialization: four concurrency tests plus the full module
  suite, zero failures/errors.
- Firing/workflow/depot/kiln/label/shop-import combined gate: 243 tests, zero
  failures/errors.
- Label Hoot gate: 18 tests in two suites, zero failures.

These focused results do not replace the final fresh-install, upgrade,
uninstall, concurrency, asset, browser, and full-suite gates in REL-01.

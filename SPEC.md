# MakersBrain Odoo addon specification

- Status: living specification of the current implementation
- Target: Odoo 19 Community, one PostgreSQL database per artisan
- Licence: LGPL-3
- Installation baseline: fresh installation of the current manifests

This repository contains the Odoo side of the MakersBrain workshop platform.
The source, manifests, tests, and addon READMEs are authoritative. This document
summarizes the supported module boundaries and invariants; it does not describe
past schemas, retired formats, or upgrade paths.

## Addon families

| Family | Addons | Current responsibility |
| --- | --- | --- |
| Workshop foundation | `mb_workshop_base`, `mb_workshop_pos`, `mb_brand` | Shared workshop navigation, continuous calendar, supplier-lot policy, priced selectors, default POS counter, and branding |
| Ceramics | `mb_ceramics_base`, `mb_ceramics_compliance`, `mb_ceramics_firing`, `mb_ceramics_workflow`, `mb_kiln_bridge` | Ceramics taxonomy, food-contact compliance, kiln loads/programmes, throwing, bisque, glazing and board workflows, inspection, genealogy, and ROHDE myKiln import |
| Labels and identity | `mb_label`, `mb_label_pos` | Current-schema label documents, immutable template versions, durable exact QR aliases, rendering, printing, and POS resolution |
| Catalogue and capture | `mb_catalogue_sync`, `mb_inventory_capture`, `mb_inventory_capture_catalogue` | Master-material import and reviewed product/package photo identification |
| Shop import | `mb_shop_import`, `mb_shop_import_ceramics`, `mb_shop_import_depot` | Reviewed ingestion of scraper artifacts with ceramics and consignment policy integrations |
| Consignment | `mb_depot` | Depot warehouses, placement, sale, ageing, statements, commission, and stock ownership |
| Commercial operations | `mb_commercial_operations` and its `stock`, `depot`, `mrp`, `purchase`, `sale`, `pos`, `fleet`, `expense`, and `urssaf` integrations | Markets and site obligations, scenario-owned cost/revenue planning, travel, stock preparation, evidence, and profitability |
| Payments | `mb_payment_sumup`, `mb_pos_sumup`, `mb_account_payment_sumup` | SumUp hosted checkout, mobile POS handoff, invoice links, and QR payments |
| French micro-enterprise | `l10n_fr_micro_enterprise`, `l10n_fr_micro_urssaf` | Franchise-en-base tax configuration, Factur-X exemption treatment, cash-basis turnover declarations, receipt book, and threshold monitoring |
| Webshop and shipping | `mb_webshop`, `mb_webshop_carrier_base`, `mb_webshop_carrier_boxtal`, `mb_webshop_carrier_sendcloud` | Switchable native Odoo webshop, customer returns, and durable provider-neutral carrier operations through Boxtal or Sendcloud |
| Platform bridges | `mb_control_bridge`, `mb_dbfilter_gateway`, `mb_email_bridge`, `mb_ai_bridge`, `mb_invoice_capture` | Tenant identity and entitlement reconciliation, trusted database routing, transactional email, AI jobs, and reviewed supplier-bill extraction |

## Current addon versions

| Addon | Version | Addon | Version |
| --- | --- | --- | --- |
| `l10n_fr_micro_enterprise` | 19.0.4.0.2 | `l10n_fr_micro_urssaf` | 19.0.2.0.1 |
| `mb_account_payment_sumup` | 19.0.1.1.2 | `mb_ai_bridge` | 19.0.1.0.1 |
| `mb_brand` | 19.0.1.0.1 | `mb_catalogue_sync` | 19.0.1.5.1 |
| `mb_ceramics_base` | 19.0.1.0.0 | `mb_ceramics_compliance` | 19.0.1.0.1 |
| `mb_ceramics_firing` | 19.0.3.0.1 | `mb_ceramics_workflow` | 19.0.3.0.2 |
| `mb_commercial_operations` | 19.0.2.3.0 | `mb_commercial_operations_depot` | 19.0.2.1.0 |
| `mb_commercial_operations_expense` | 19.0.2.0.1 | `mb_commercial_operations_fleet` | 19.0.2.0.1 |
| `mb_commercial_operations_mrp` | 19.0.2.0.1 | `mb_commercial_operations_pos` | 19.0.2.0.1 |
| `mb_commercial_operations_purchase` | 19.0.2.0.1 | `mb_commercial_operations_sale` | 19.0.2.0.1 |
| `mb_commercial_operations_stock` | 19.0.2.0.1 | `mb_commercial_operations_urssaf` | 19.0.2.2.0 |
| `mb_control_bridge` | 19.0.2.0.0 | `mb_dbfilter_gateway` | 19.0.1.0.2 |
| `mb_depot` | 19.0.4.0.9 | `mb_email_bridge` | 19.0.1.1.1 |
| `mb_inventory_capture` | 19.0.1.1.1 | `mb_inventory_capture_catalogue` | 19.0.1.0.3 |
| `mb_invoice_capture` | 19.0.1.5.3 | `mb_kiln_bridge` | 19.0.1.3.1 |
| `mb_label` | 19.0.1.2.2 | `mb_label_pos` | 19.0.1.1.2 |
| `mb_payment_sumup` | 19.0.1.1.1 | `mb_pos_sumup` | 19.0.1.1.2 |
| `mb_shop_import` | 19.0.1.0.1 | `mb_shop_import_ceramics` | 19.0.1.0.0 |
| `mb_shop_import_depot` | 19.0.1.0.0 | `mb_webshop` | 19.0.1.5.2 |
| `mb_webshop_carrier_base` | 19.0.1.1.3 | `mb_webshop_carrier_boxtal` | 19.0.1.1.1 |
| `mb_webshop_carrier_sendcloud` | 19.0.1.0.1 | `mb_workshop_base` | 19.0.2.0.0 |
| `mb_workshop_pos` | 19.0.1.0.0 |  |  |

## Supported invariants

### Data and identity

- `product.product` and `stock.lot` remain the inventory identities; addons do
  not create a parallel piece identity.
- Product barcodes remain native Odoo barcodes. Printed custom QR values are
  exact `mb.label.qr.alias` values and resolve authoritatively to their bound
  product and optional lot.
- Label import/export accepts only the current schema-1 template file containing
  schema-1 document data. Template versions and printed aliases are immutable.
- Food-contact ware is serial/lot tracked, and consumed glaze lots require a
  passing laboratory migration test before manufacturing completion.
- Depot stock remains company-owned internal stock in a dedicated warehouse
  until the depositary reports a sale.

### Planning and operations

- Commercial profitability scenarios use scenario sales lines and
  scenario-owned cost lines. There is no scalar-field or operation-cost fallback.
- Fixed cost, labour time, travel time, and travel distance are expressed by
  categorized cost lines. Accepted travel estimates may provide route distance
  and duration.
- Operational completion, stock reconciliation, document completeness,
  financial close, accounting reconciliation, and legal recognition are
  separate states.

### External boundaries

- Provider callbacks are claims: settlement or shipping state is confirmed
  against the provider API before authoritative records change.
- Carrier providers declare safety per operation. The runtime does not infer it
  from provider-wide capability flags.
- `/mb_control/v1` is the current private control-plane API surface. Its route
  contract is generated in `contracts/mb_control_v1.json` and checked with
  `python3 tools/bridge_contract.py --check`.
- Credentials stored in Odoo are group-restricted and must never be logged.
- Core Odoo files are not modified; integration uses supported inheritance,
  service, registry, and patch seams.

### Installation and language

- Only a fresh installation of the current Odoo 19 manifests is supported.
- The repository contains no historical addon migration hooks or runtime shims
  for retired fields, routes, contexts, records, or payload formats.
- English source terms and committed French catalogues must remain complete and
  free of obsolete gettext entries.

## Repository interfaces

| Path | Purpose |
| --- | --- |
| `addons/` | Installable Odoo addons and their tests |
| `contracts/` | Generated bridge surface contract |
| `deploy/` | Published Odoo image definition and deployment assets |
| `scripts/` | Current repeatable development and operational utilities |
| `tools/` | Static checks, translation tooling, release metadata, and contract generation |
| `Makefile` | Local stack, install, check, translation, and test entry points |

The supported local validation gates are:

```text
make check
make test
git diff --check
```

Frontend unit tests and the French integration run are invoked by their
dedicated repository tooling when those surfaces change. Open release or
qualification work is kept only in the focused plan files at the repository
root.

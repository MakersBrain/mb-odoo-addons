# Dépôt-vente Standalone App Navigation Plan

## Decision

Move **Dépôt-vente** out of the Inventory menu and make it a standalone Odoo
application.

Do not split the workflow into unrelated Inventory and Sales entry points. The
standalone app is the operational workspace for a depot sale, while Sales
Orders, stock transfers, invoices, payments, and accounting entries remain
standard Odoo documents and continue to appear in their native applications.

This is a navigation and discoverability change. It must not introduce parallel
sale, stock, or accounting models, and it must not alter the transaction,
backdating, reservation, invoicing, or URSSAF rules already implemented.

## Objectives

- Give users one obvious app tile named **Dépôt-vente**.
- Organise the complete workflow by user intent instead of by Odoo's underlying
  technical models.
- Keep **Record a Sale** as the primary operational entry point.
- Provide filtered shortcuts to the standard documents created by the depot
  workflow.
- Preserve access controls: a visible menu must never grant access to its model.
- Follow Odoo 19's root-menu, application, and `res.groups.privilege`
  conventions.
- Keep existing bookmarks, external IDs, report links, and generated-document
  relationships working after the move.

## Proposed navigation

```text
Dépôt-vente
├── Operations
│   ├── Sale Reports
│   ├── Record a Sale
│   └── Place Products
├── Documents
│   ├── Sales Orders
│   ├── Deliveries
│   └── Invoices
├── Stock
│   ├── Stock in depots
│   └── Transfers
├── Reporting
│   └── Depot statement
└── Configuration
    ├── Depots
    └── New depot
```

The root application menu has no action, following the native Odoo 19 pattern
used by applications whose users have different accessible children. Odoo
opens the first accessible child for the current user. For a Depot Sales
Manager that child is **Sale Reports**; an Inventory-only or Accounting-only
user never lands on a model they cannot read.

Keep the existing list/form action as **Sale Reports** and add a separate,
stable form-only `ir.actions.act_window` for **Record a Sale**. The latter opens
a new persistent `mb.depot.sale.report` in the current window. This requires no
custom client code.

### Operations

**Record a Sale** is available only to **Depot Sales: Manager**. It creates a
persistent `mb.depot.sale.report`; it is not a transient convenience wizard.

**Sale Reports** opens the existing report list/form action, including Draft,
Processed, Reversal required, and Reversed records. This is the application's
home and audit trail.

**Place Products** opens a dedicated action on the standard `stock.picking`
model, filtered with `is_depot_placement = True`. Its **New** button opens the
standard picking form; the operator selects the normal internal operation and
the depot destination location, then adds products and validates through the
native Inventory workflow. The existing depot catalog extension becomes
available once the selected locations identify the picking as a placement.

The first release does not add a placement wizard, auto-validate a transfer, or
create a parallel stock-entry model. If a one-step depot-placement assistant is
later required, specify and review it as a separate workflow change.

### Documents

These entries are filtered views of standard Odoo models:

- **Sales Orders**: `sale.order` records with a depot sale report.
- **Deliveries**: `stock.picking` records with a depot sale report.
- **Invoices**: `account.move` customer invoices linked through
  `mb_depot_sale_report_ids`.

Use inherited or dedicated list/search views only where depot evidence needs to
be visible. Reuse the standard form views. Opening a record must lead to the
normal Sales, Inventory, or Accounting document, not a copy inside `mb_depot`.

The actions must retain normal allowed-company record rules and expose useful
search fields such as depot, report reference, effective/delivery dates, state,
and customer. Creation defaults are added only where the current context has an
unambiguous value; an action must not guess a depot or company. They must not
use `sudo()` or broader domains to work around missing permissions.

### Stock

**Stock in depots** reuses `action_depot_quant` and remains a filtered
`stock.quant` view. It must continue to show actual on-hand and reserved
quantities, commercial depot values, and ageing without changing valuation
costs.

**Transfers** opens standard `stock.picking` records with
`depot_warehouse_id != False`. This stored relationship already covers both
placements and outbound depot deliveries without relying on names, operation
types, or fragile location traversal. **Place Products** uses the narrower
stored `is_depot_placement = True` domain.

### Reporting

**Depot statement** reuses the existing statement wizard and report. Its dates,
opening/closing balance, Sold on evidence, and reconciliation rules remain
unchanged.

### Configuration

**Depots** reuses the filtered `stock.warehouse` action. **New depot** reuses the
existing creation wizard so that warehouse, locations, operation types,
depositary, legal structure, commission, and pricelist remain consistent.

Configuration entries are restricted to Inventory Administrators. Ordinary
operators must not be able to create or reconfigure warehouses through the new
app.

## Odoo 19 implementation design

### Root application menu

Keep the external ID `mb_depot.menu_depot_root`, remove its
`stock.menu_stock_root` parent, and make it a root application menu. Preserving
the external ID allows upgrades to move the existing menu record instead of
leaving a stale duplicate under Inventory.

Set:

- English source `name="Depot Sales"`, translated to **Dépôt-vente** in
  `fr_FR`;
- a stable application sequence near Sales and Inventory;
- a `web_icon` from an `mb_depot/static/description` asset;
- no root action; and
- no group restriction on the root itself.

Clear the current Inventory-user group and parent values explicitly when
updating the record. Root visibility is derived from accessible leaf menus, as
in native Odoo 19 applications. This avoids sending Inventory-only users to a
Depot Sales model and also lets an Accounting-only user reach the invoice
shortcut without granting stock or report access.

Create section menus with new stable external IDs. Re-parent the existing leaf
menu records instead of replacing them whenever possible:

- `menu_depot_record_sale`, renamed to **Sale Reports** while retaining its
  existing list/form action;
- `menu_depot_quant`;
- `menu_depot_statement`;
- `menu_depot_locations`; and
- `menu_depot_create`.

Create `menu_depot_record_sale_new` for the new form-only **Record a Sale**
action. Keeping the old menu external ID attached to the existing action
preserves bookmarks and upgrade identity.

This follows Odoo's standard root-menu mechanism; no JavaScript app shell or
custom router is required.

### Application icon

Add a simple module-owned icon suitable for both light and dark app-switcher
backgrounds. Odoo 19 accepts SVG app-menu assets, so keep a repository-native
SVG unless a PNG is deliberately chosen for consistency with the other custom
applications. Do not reuse an Inventory icon that would make the two
applications indistinguishable.

### Filtered document actions

Add dedicated `ir.actions.act_window` records for depot Sales Orders,
deliveries, invoices, and transfers. Their domains must be based on the stored
depot/report relationships already present in the models, not on display names,
references, or chatter text.

Use these existing relationships for stock actions:

- **Place Products**: `stock.picking.is_depot_placement = True`;
- **Transfers**: `stock.picking.depot_warehouse_id != False`; and
- **Stock in Depots**: retain the existing depot-location quant action.

Where a standard search view lacks depot fields, inherit the search view or add
a dedicated search view with filters such as:

- Depot;
- report reference;
- effective sale/delivery period;
- document state;
- depositary/customer; and
- invoicing/payment state where the user has Accounting access.

Do not fork standard form views. The existing depot evidence fields and smart
buttons remain small extensions of the native forms.

## Permissions and visibility

Use the deployed Odoo 19 privilege:

**Supply Chain → Depot Sales → Manager**

The root has neither an action nor groups. A user sees the app tile only when at
least one accessible leaf exists. Apply groups to leaf menus as follows:

| Area | Required access |
| --- | --- |
| App tile | Derived from at least one accessible leaf menu |
| Record a Sale / Sale Reports | Depot Sales Manager |
| Depot Sales Orders | Depot Sales Manager plus normal Sales access implied by the role |
| Place Products / Deliveries / Stock / Transfers / Statement | Inventory User |
| Invoices | normal Accounting/Invoicing access |
| Depots / New depot | Inventory Administrator |

Because Odoo menu `groups` are additive/OR rather than an AND-policy engine,
model ACLs and record rules remain authoritative. Do not attempt to encode
compound security solely by listing several groups on a menu.

Apply `account.group_account_invoice` (or its verified Odoo 19 replacement if
the dependency changes) to the invoice and credit-note smart buttons on depot
reports. A user without Accounting/Invoicing access must not see those buttons
or gain invoice-read access through their actions. Counts may still be computed
without exposing records. Stock-document buttons remain governed by Inventory
access, and all direct actions remain protected by model ACLs and record rules.

## Standard application integration

Keep native visibility intact:

- generated quotations/orders remain in **Sales**;
- placements and deliveries remain in **Inventory**;
- invoices and payments remain in **Accounting**;
- URSSAF declarations remain in the URSSAF/accounting area.

The standalone app adds filtered shortcuts only. It must not remove native menus
or hide standard documents from their original applications.

The existing `scripts/configure_app_visibility.py` allowlist must explicitly
include `mb_depot.menu_depot_root`, otherwise bootstrap or UI reconfiguration
could hide the new application tile even though the module is correctly
installed.

## Language and labels

Choose one coherent UI language per installed translation. The current mixture
of **Record a sale**, **Stock en dépôt**, **Relevé de dépôt**, and **Dépôts**
should be normalised in source strings and translated through Odoo's normal
translation mechanism.

Recommended English source labels:

- Depot Sales
- Operations
- Record a Sale
- Sale Reports
- Place Products
- Documents
- Sales Orders
- Deliveries
- Invoices
- Stock
- Stock in Depots
- Transfers
- Reporting
- Depot Statement
- Configuration
- Depots
- New Depot

The French translation should consistently use **Dépôt-vente** and established
French Odoo document terms.

Add or update `addons/mb_depot/i18n/fr.po` in the same change. Verify a `fr_FR`
user sees the French app, section, menu, action, and search-filter labels after
the module upgrade; changing English XML source strings without updating the PO
file is incomplete.

## Migration and upgrade

1. Bump the `mb_depot` module version.
2. Update `menu_depot_root` in place: explicitly set `parent_id` and `action` to
   false, clear its existing groups, and add its icon.
3. Create the section menus, the distinct Sale Reports and Record a Sale
   actions, and the filtered standard-document actions with stable XML IDs.
4. Re-parent existing leaf menus in place.
5. Update `scripts/configure_app_visibility.py`.
6. Update the README path from **Inventory → Dépôt-vente** to the standalone
   application.
7. Perform a two-stage upgrade test in a disposable database: install the
   currently released module first, update the addon code, then run the module
   upgrade. Verify that the original `menu_depot_root` XML ID still resolves to
   the same database record, only one root exists, `parent_id` and `action` are
   empty, and the old Inventory child is gone.
8. Upgrade `odoo_test`, restart Odoo, and refresh the web client assets/menu
   cache.

No business-data migration should be necessary. Existing reports, orders,
pickings, invoices, warehouses, references, and links must remain untouched.

## Tests

Add regression coverage for:

- `menu_depot_root` is an active root application menu with no action, no group
  restriction, and an icon.
- No second Dépôt-vente menu remains under Inventory after upgrade.
- Existing menu external IDs are preserved and point to the new sections.
- Depot Sales Managers see Record a Sale and Sale Reports, and the two entries
  use distinct form-only and list/form actions.
- Inventory users without the manager role cannot process a depot sale.
- Inventory users can open Place Products and Transfers without being sent to
  the sale-report action; placement and transfer domains use the stored fields.
- Inventory Administrators see depot configuration actions.
- Accounting-only users see the app through Invoices, can open that filtered
  action, and receive no broader depot-report or Inventory permissions.
- Filtered Sales Order, delivery, invoice, stock, and transfer actions exclude
  unrelated documents.
- Multi-company record rules still restrict every action to allowed companies.
- Standard Sales, Inventory, and Accounting actions still expose the same depot
  documents.
- `configure_app_visibility.py` keeps the standalone app active.
- Existing report smart buttons still open authorised generated documents;
  invoice and credit-note buttons are hidden for users without Accounting.
- Direct invocation of invoice and credit-note actions remains rejected without
  the underlying Accounting ACL even if a menu or URL is known.
- A two-stage old-version-to-new-version module upgrade moves the old Inventory
  child menu rather than producing a duplicate.
- A `fr_FR` user receives translated app and navigation labels from
  `i18n/fr.po`.

Exercise menu visibility with real users through Odoo's menu-loading/
`_visible_menu_ids` path, not only by inspecting the menu `groups_id` field.
Keep the two-stage migration scenario separate from fresh-install
`TransactionCase` coverage, because a fresh database cannot prove preservation
of an older menu record.

Run the complete `mb_depot`, `l10n_fr_micro_enterprise`, and
`l10n_fr_micro_urssaf` test suites because menu/security changes can affect the
same manager and accounting roles used by the closed-period workflow.

## Deployment verification

On `odoo_test`:

1. Confirm the **Dépôt-vente** tile appears in the app switcher after sign-in
   for each user that has at least one accessible leaf.
2. Confirm the old **Inventory → Dépôt-vente** parent menu is gone.
3. Verify the Administrator, a non-administrator Depot Sales Manager, an
   Inventory-only user, and an Accounting-only user; each must land on their
   first accessible child without an access error.
4. Verify an Inventory User without Depot Sales Manager cannot access the sale
   report action by URL/RPC.
5. Open each filtered document action and compare its records with the native
   application.
6. Open an existing depot report and follow every smart button.
7. Confirm the URSSAF permanent horizon still blocks closed dates.
8. Confirm local and external web health and inspect post-upgrade logs.

Do not create a fake live depot sale in `odoo_test` for navigation testing. Use
a disposable database for mutations, and use existing records or read-only
metadata checks in `odoo_test`.

## Definition of done

The user signs in and sees one standalone **Dépôt-vente** application. From it,
they can record and audit depot sales, inspect depot stock and standard generated
documents, produce statements, and—when authorised—configure depots.

The same Sales Orders, deliveries, invoices, payments, and accounting evidence
remain visible and editable through their standard Odoo applications. There are
no duplicated business records, no custom replacement for standard forms, no
security escalation through menus, and no change to historical dates or the
irreversible URSSAF closing horizon.

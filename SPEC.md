# MakersBrain Odoo addon specification

- Status: **living specification of what is built**, updated 13 August 2026
- Target: Odoo 19 Community, one PostgreSQL database per artisan
- Licence: LGPL-3 throughout, deliberately (see [Licence boundary](#licence-boundary))

This document specifies the addon suite in `addons/`. It is written
from the code, the manifests and the installed state of the running database,
not from intent.

It replaces the addon table in `POC-PLAN.md` section 4 and the boundary sketch
in section 10.2, both of which describe a module set that was never built.
`POC-PLAN.md` remains the strategic document — the edition decision, the
e-invoicing research, the control plane — and is not superseded here.
`IDENTITY-SPINE-DESIGN.md` remains the reference for product, lot and QR
identity, which this specification depends on and does not restate.

A module is listed here only if its code exists. Nothing below is planned work.
This is not a frozen contract: it evolves when operational experience, Odoo
best practice, or an applicable industry standard yields a better design. Such
changes require an explicit rationale, migration impact, and verification; they
are not specification violations merely because an earlier edition differed.

## Contents

- [The module set](#the-module-set)
- [Cross-cutting rules](#cross-cutting-rules)
- [Workshop foundation](#workshop-foundation) — `mb_workshop_base`, `mb_ceramics_base`,
  `mb_ceramics_compliance`, `mb_brand`, `mb_workshop_pos`
- [Labels and piece identity](#labels-and-piece-identity) — `mb_label`, `mb_label_pos`
- [Firing](#firing) — `mb_ceramics_firing`, `mb_ceramics_workflow`, `mb_kiln_bridge`
- [Materials](#materials) — `mb_catalogue_sync`
- [Consignment](#consignment) — `mb_depot`
- [Commercial operations](#commercial-operations) — depot refills, markets, travel and profitability
- [Payments](#payments) — `mb_payment_sumup`, `mb_pos_sumup`, `mb_account_payment_sumup`
- [French tax regime](#french-tax-regime) — `l10n_fr_micro_enterprise`
- [Environment](#environment)
- [Verification status](#verification-status)
- [Known gaps](#known-gaps)

## The module set

Three independent trees. Nothing spans them, and that is the design: a workshop
that sells at a market but owns no kiln installs the label branch and none of
the firing branch.

```text
stock, web
└── mb_label ─────────────── label design, versions, QR aliases, printing
    └── mb_label_pos ─────── point_of_sale

stock, resource, sale, web
└── mb_workshop_base ─────── menu spine, 24/7 calendar, supplier-lot policy
    └── mb_ceramics_base ─── material and ware taxonomy, work centres, clay body
        ├── mb_ceramics_compliance ─ 84/500/EEC, migration tests, mark-done gate
        ├── mb_ceramics_firing ─ mrp, maintenance
        │   ├── mb_ceramics_workflow ─ throwing, boards, inspection, genealogy
        │   └── mb_kiln_bridge ─ ROHDE myKiln connector
        └── mb_catalogue_sync ── product, purchase, uom

point_of_sale, account
└── mb_workshop_pos ──────── the workshop's one POS counter

stock, sale_stock
└── mb_depot ─────────────── dépôt-vente

payment
└── mb_payment_sumup ─────── SumUp as an Odoo payment provider
    ├── mb_pos_sumup ─────── point_of_sale
    └── mb_account_payment_sumup ─ account_payment

l10n_fr_account, account_edi_ubl_cii
└── l10n_fr_micro_enterprise ── franchise en base

project, account, hr_timesheet
└── mb_commercial_operations ── calendar, contracts, travel, break-even, profitability
    ├── mb_commercial_operations_stock ── event stock and reconciliation
    │   ├── mb_commercial_operations_depot ── refill forecasts, rent and depot evidence
    │   ├── mb_commercial_operations_mrp ── reviewed manufacturing supply
    │   ├── mb_commercial_operations_purchase ── reviewed purchase supply
    │   ├── mb_commercial_operations_sale ── market sales, revenue and COGS
    │   └── mb_commercial_operations_pos ── market POS sessions, revenue and COGS
    ├── mb_commercial_operations_fleet ── vehicles and route assumptions
    ├── mb_commercial_operations_expense ── operation expenses
    └── mb_commercial_operations_urssaf ── read-only legal recognition status
```

| Addon | Version | Owns | Live state |
| --- | --- | --- | --- |
| `mb_workshop_base` | 19.0.2.0.0 | Menu spine, continuous calendar, supplier-lot policy, priced product selectors | installed |
| `mb_ceramics_base` | 19.0.1.0.0 | Material and finished-ware taxonomy, seeded work centres, clay body | installed |
| `mb_ceramics_compliance` | 19.0.1.0.0 | Food-contact declaration, derived tracking, migration tests, the mark-done gate | installed |
| `mb_label` | 19.0.1.0.0 | Label templates and immutable versions, QR aliases, deterministic renderer, Owl editor, print jobs, BLE printer adapters | installed |
| `mb_label_pos` | 19.0.1.0.0 | Bounded alias projection into POS, QR resolution, fall-through to native barcodes | installed |
| `mb_ceramics_firing` | 19.0.2.0.0 | `mb.firing` as the kiln load, kiln records, controller programmes and segments, cooling hold, work-centre creation | installed |
| `mb_ceramics_workflow` | 19.0.1.0.0 | Throwing and finishing sessions, WIP boards, kiln loading, inspection, losses and firing-aware traceability | installed |
| `mb_kiln_bridge` | 19.0.1.2.0 | myKiln connection, read-only client, normalization, polling cron, programme derivation | installed |
| `mb_catalogue_sync` | 19.0.1.3.0 | On-demand import of curated manufacturer identities and supplier offers | installed |
| `mb_depot` | 19.0.1.0.0 | Depot locations, creation wizard, commission pricelist, ageing, statement, bon de dépôt | installed |
| `mb_payment_sumup` | 19.0.1.0.0 | SumUp hosted checkout provider, return and webhook routes, polling cron, refunds | **uninstalled** |
| `mb_pos_sumup` | 19.0.1.0.0 | POS payment through the SumUp app URL scheme on the same phone | **uninstalled** |
| `mb_account_payment_sumup` | 19.0.1.0.0 | Invoice-bound checkout link and printed QR code | **uninstalled** |
| `mb_workshop_pos` | 19.0.1.0.0 | The default POS counter, seeded when a company gains a chart of accounts | installed |
| `l10n_fr_micro_enterprise` | 19.0.2.1.0 | Franchise-en-base tax preparation, regime switching, Factur-X exemption codes | installed |

Live state is `ir_module_module` in the `odoo` database of the running stack.
The three uninstalled addons carry 32 test methods between them and have not
been installed against the database holding real data.

## Cross-cutting rules

These hold across every module and are the first thing to check when adding one.

**One database per artisan.** No addon may assume it is alone in a database, but
none may assume multi-tenancy either. Records carry `company_id` where Odoo's own
models do; nothing implements a tenant discriminator of its own.

**Odoo owns inventory identity.** `product.product` and `stock.lot` are the only
piece identities. `tracking = 'serial'` is a unique piece, `tracking = 'lot'` is
a batch, untracked is a product-only article. No addon invents a parallel
identity model. `mb_ceramics_compliance` derives `tracking` from the food-contact
declaration rather than leaving it as an unexplained setting.

**Odoo's `barcode` stays an ordinary barcode.** EAN, UPC and internal references
remain on `product.barcode`. Printable QR values live in `mb.label.qr.alias`, and
POS resolution tries aliases first and then falls through to Odoo's native
barcode path unchanged.

**Printed identity is durable.** A custom QR template is not generally
reversible, so every printed value is materialised as an alias at print time.
Template versions are immutable; editing a template mints a new version and
leaves every previously printed label scannable. Alias retirement is an explicit
audited action that deletes no print or POS history.

**Credentials.** Odoo has no secret store. Where a credential must live in the
database it is a field on a record, restricted by group, never logged, and the
reason is stated on the model. This currently applies to `mb.kiln.connection`
(myKiln username, password, provider token) and to the SumUp provider record
(merchant code, secret key). Both are single-workshop decisions and both reverse
if the product goes multi-tenant. Development credentials live in gitignored
`*.env` files at the repository root and nowhere else.

**Untrusted callbacks are claims, not evidence.** Every external callback route
re-reads the authoritative state from the provider API with the merchant's own
key before anything settles. This is why forging a call to
`/payment/sumup/webhook` achieves nothing beyond an early poll, and why the POS
verifies `smp-status` against the SumUp transactions endpoint.

**Supported seams only.** Core Odoo files are not edited. Extension goes through
`_inherit`, `patch()`, `_load_pos_data_models()`, `pos.load.mixin`, registries
and services. `mb_label_pos/README.md` enumerates the POS seams used.

### Licence boundary

Every addon is LGPL-3. AGPL-3 OCA modules may be
recommended but never declared as a dependency — `mb_depot` documents the one
case (`sale_order_global_stock_route`) and degrades to manual route selection
without it.

### Migration scripts start at first release, not before

Nothing here is
released and no artisan database exists, so a version bump today is free: the
development and demonstration databases are rebuilt from `make bootstrap` and
the seed scripts, not migrated. Version numbers still move, because they are how
Odoo decides to re-run an addon's data files.

The rule changes the day the first tenant database exists. From then on, one
database per artisan means an addon without a migration path is an outage
multiplied by the tenant count, and every version bump that touches stored data
needs a script.

**The exception is a record that moves between modules**, which needs a script
whether or not anything is released, because the loss is not recoverable by
reinstalling. Odoo's end-of-load cleanup deletes the `ir.model.data` rows a
module no longer accounts for, and takes the records with them. Three
cross-module transfer scripts exist for this:

| Script | Moved |
| --- | --- |
| `mb_ceramics_firing/19.0.1.2.0/pre-migrate.py` | `mb.kiln.program` out of `mb_kiln_bridge` |
| `mb_workshop_base/19.0.1.2.0/pre-migrate.py` | the eight material categories out of `mb_catalogue_sync` |
| `mb_workshop_base/19.0.2.0.0/pre-migrate.py` | the whole ceramics half of the base into `mb_ceramics_base` and `mb_ceramics_compliance`, and three menu IDs renamed in place |

Each reassigns `module` on the affected rows in a pre-migrate on the addon that
loads first, which turns a drop-and-recreate into a move. Each is one-shot: after
it runs the source rows are gone and a re-run matches nothing.

Other migrations in the repository backfill or normalize records in place and
are documented by their own module/version; they are not ownership transfers.

The split migration treats pre-existing successor IDs explicitly. Two IDs that
already point to the same record are collapsed. IDs with the same name that
point to different records abort the upgrade and name the conflict; they are not
left for end-of-load cleanup to resolve destructively. Odoo-generated field and
selection IDs are safe without an exhaustive manual list because successor
reflection gives the same metadata record another owner before stale-ID cleanup.

## Workshop foundation

### `mb_workshop_base`

Depends on `stock`, `resource`, `sale`, `web`. The craft-neutral floor, and
since 19.0.2.0.0 that is all it is.

Until then it was also the ceramics vertical, which meant `mb_label`,
`mb_inventory_capture` and `mb_catalogue_sync` — none of which has any interest
in tableware — could not be installed without a ceramic food-contact
regulation. `mb_label` used nothing in it at all. The split, its migration and
the rule it follows are in [CRAFT-PLATFORM-PLAN.md](CRAFT-PLATFORM-PLAN.md)
section 2: a module sits here only if a leatherworker would install it
unchanged.

**The menu spine and its label are neutral.** Production, Stock & Quality and
Configuration are the same three questions in any workshop, so
`menu_mb_workshop_root` and its three children are declared here under
"Workshop". Vertical addons add entries beneath it but do not overwrite shared
data; installing two verticals cannot make load order choose the app name. The
three child IDs were `menu_mb_ceramics_*` until 19.0.2.0.0 and were renamed in
place. The root keeps its ID because `scripts/configure_app_visibility.py`
names it.

**`mb_calendar_continuous`** is the 24/7 `resource.calendar` everything
unattended runs on. UTC deliberately: nothing on it keeps office hours, so a
local timezone would only put a daylight-saving discontinuity into durations
that are physical and absolute. It stayed here rather than moving with the kiln
because a dye bath, a tanning pit and a lumber drier want it for the same reason.

**`mb_supplier_lot_required`** says a purchased material must retain the
supplier's physical batch in Odoo lot traceability, and derives `tracking` from
that. Independent of food contact, and now independent in the dependency graph
too, which is what `mb_inventory_capture` needed.

**Priced product selectors.** Quotation lines pick from an autocomplete showing a
name and no price. The active pricelist's price is appended to the display name
through context keys, so nothing else changes.

12 test methods, including identical and divergent conflicts for both handovers
and menu renames.

### `mb_ceramics_base`

Depends on `mb_workshop_base`, `mrp`. The ceramics vertical's floor: what a
ceramics workshop is configured with before anything else is installed.

**No material-type field.** Material families are `product.category`, defined in
`data/mb_material_categories.xml`: ceramic materials, and under it glazes,
underglazes, engobes, clay bodies, stains, oxides and raw materials. A second
taxonomy disagrees with the first the moment anyone edits either.

They moved out of `mb_catalogue_sync` in 19.0.1.2.0, on the finding that the
families are not the catalogue's, and out of `mb_workshop_base` in 19.0.2.0.0,
on the finding that they are not craft-neutral. A workshop that never imports
anything still buys glaze and still owes a migration test on the food-contact
ware it makes with it — so leaving the taxonomy in the importer put the
`button_mark_done` gate behind an optional connector, and its docstring admitted
it silently checked less without one. `mb_catalogue_sync` maps onto the taxonomy
rather than owning it, and `mb_ceramics_compliance` reads it to enforce.

**No design model.** A piece with its own price gets its own product record.
Design-level grouping uses `product.tag`, which is native, unique by name,
filterable and already carries `visible_to_customers`.

**Work centres are seeded, not modelled.** Throwing, handbuilding, trimming,
assembly, glazing and decorating are plain `mrp.workcenter` records under
`noupdate="1"`, so the artisan owns them after install. One per contended
resource, not one per craft skill. Drying is a wait: no hourly cost, and
capacity past anything a batch reaches, or it puts phantom load on the shop
floor. It runs on `mb_workshop_base.mb_calendar_continuous`, as the kiln does.

**`mb_clay_body_id`** points at the material product itself rather than a code,
so it joins to the master catalogue — the same reasoning as the categories.

**The shared app name stays neutral.** This addon hangs ceramic entries under
the workshop spine without rewriting its root. A future vertical can coexist in
the same database without last-loaded-wins menu data.

4 test methods.

### `mb_ceramics_compliance`

Depends on `mb_ceramics_base`, `mrp`, `stock`. Directive 84/500/EEC, and nothing
else.

**Food contact is a property of the finished article.** The directive applies to
ceramic articles intended for food contact and to nothing else, so a mug carries
lead and cadmium limits and a decorative plate carries none. `mb_food_contact`
is declared on `product.template` and `tracking` is derived from it, so the
traceability setting always has a stated reason. A migration limit class is
refused on an article not intended for food, and a decorative article in a
tableware form carries a label warning saying what it is not.

**`mb.migration.test`** holds a laboratory's lead and cadmium migration result
against a *glaze lot*, not against the ware: one result covers every article made
from that lot. `passed` is recorded as the laboratory issued it and is never
derived from the figures, because the limits in force on the test date are the
lab's to apply. The migration limit class, the figures and the report attachments
are kept so the verdict stays auditable.

**The gate is at `button_mark_done`.** A food-contact order needs a lot number
before it can be closed, and every glaze lot it consumed needs a passing
migration test. Which consumed lots are glaze is answered by
`mb_ceramics_base`'s categories, which is seed data with no connector behind it,
so the gate is always enforceable.

6 test methods.

### `mb_brand`

Depends on `web`. Applies the MakersBrain visual identity, and deliberately
nothing else — it declares no model, no menu and no access rule.

**Variables, not selectors.** Odoo declares `$o-brand-primary`, `$primary`, the
grey ramp and the font families in `web._assets_primary_variables`, every one of
them `!default`. Prepending one file to that bundle sets them first, so core's
declarations no-op and the whole web client follows. Chasing Odoo's class names
with `!important` instead would break on each upgrade, and break silently: a
stylesheet that no longer matches anything still compiles.

**The public pages take their primary colour from a different place, and that
cost an afternoon to find.** `html_editor` derives Bootstrap's `$theme-colors`
from a colour *palette* rather than from `$primary`:
`$o-color-palettes['base-1']['o-color-1']` becomes
`$o-theme-color-palette['primary']` becomes `$theme-colors['primary']`, which is
what generates `.btn-primary`. Its default is `$o-enterprise-color`. Setting only
the brand colour therefore brands the backend and leaves the *login page* — the
first page anyone sees — on stock Odoo purple. Both seams are set, and both are
verified in the compiled bundle rather than by eye.

**The login page keeps the workshop's logo.** `web.login_layout` renders
`/web/binary/company_logo`, which is the artisan's own mark; replacing it with
ours would be the wrong trade, because the person signing in works at that
pottery. The company logo stays and a MakersBrain lockup sits under the card.

Two selectors exist in the whole addon, both where no variable does: the login
ground and the login card. `body_classname` is *replaced* rather than added to,
because Bootstrap's `bg-100` carries `!important` and beats any ground colour
set on the same element.

Fonts are self-hosted: Bitter and IBM Plex Sans, both SIL OFL, in
`static/src/fonts`. A webfont CDN would put a third party in the request path of
every page load.

The values mirror `brand/tokens.css`; `brand/design-chart.html` documents what
they mean. SCSS cannot read CSS custom properties at compile time, so the mirror
is maintained by hand and a change belongs upstream in the tokens first.

Deliberately not done: the app switcher, list and form views keep Odoo's layout.

No test methods: the addon ships no Python and no translatable strings, and what
it does assert — that the bundles compile with the brand values in them — is not
something an Odoo test method can see.

### `mb_workshop_pos`

Depends on `point_of_sale` and `account`. Ships one `pos.config` per company and
nothing else: no model of its own, no view, no menu.

**What it prevents.** Odoo 19 replaces the `pos.config` kanban with
`pos_config_kanban_view`, which paints "Choose your store" whenever the list is
empty — Clothes, Furniture, Bakery, Restaurant, Bar, Retail. Every provisioned
workshop has Point of Sale installed, because `mb_control_bridge` depends on it
for the cashier groups, and none shipped a config. So the app opened on a
shop-type quiz whose Restaurant and Bar cards call `install_pos_restaurant()` —
`button_immediate_install()` on `pos_restaurant` — and put table management and a
kitchen display into a ceramics studio on one click.

**Odoo's own code makes the counter.** A `pos.config` cannot be written as XML
data: it needs a sale journal, a cash journal and the Cash, Card and Customer
Account payment methods, all company-specific and none existing before a chart
of accounts. `_mb_ensure_default_counter` therefore calls
`load_onboarding_retail_scenario(with_demo_data=False)` — the Retail card without
the click — which names the config after the company.

**It waits for the chart of accounts.** A workshop is initialised by `odoo
--init` against a database whose company has no country; the French chart is
loaded afterwards, by `mb_control_bridge`'s `_mb_bootstrap_french_accounting`. So
the seam is `account.chart.template.try_loading`, which that bootstrap and the
`l10n_fr_micro_enterprise` setup wizard both go through, with `post_init_hook`
covering databases whose accounting already exists. Seeding is idempotent and
never raises: a missing counter costs a shop-type screen, while an exception
would abort loading a chart of accounts.

Databases provisioned before this addon joined the `--init` set keep their
module set and need it installed explicitly.

## Labels and piece identity

### `mb_label`

Depends on `stock`, `web`. Declared as an application; the only one. It depended
on `mb_workshop_base` until 19.0.1.2.0 and used nothing in it — no XML ID, no
field, no group — so a database that only prints labels no longer carries a
ceramic food-contact regulation.

Three layers, deliberately separate:

```text
immutable JSON document + product/lot bindings
    -> deterministic monochrome PNG and exact-size PDF
    -> system print, Phomemo BLE, or NIIMBOT BLE adapter
```

**Models.** `mb.label.template` and immutable `mb.label.template.version`;
`mb.label.qr.alias`; `mb.label.print.job`; `mb.label.render.service`;
`mb.label.print.wizard`.

**Document.** Versioned JSON with text, QR, image, rectangle and line elements.
Geometry is stored in millimetres and converted to pixels only for a selected DPI
at render time. Version 3 documents from the earlier editor import and export
with dot-to-millimetre conversion and field, style, group and media mapping.

**Expression grammar is an allowlist**, not Python and not ORM access:
`{{product.name}}`, `{{product.default_code}}`, `{{product.barcode}}`,
`{{product.price}}`, `{{product.price.raw}}`, `{{lot.name}}`,
`{{company.name}}`, `{{company.currency}}`, `{{qr}}`, `{{qr.path}}` and
`{{manual.<name>}}` for a value typed into the print wizard. Print-time
expressions `[[date]]`, `[[time]]`, `[[datetime]]`, `[[iso]]`, `[[month]]` are
carried over from the old editor. A missing required binding fails visibly
rather than rendering blank.

**Rendering is deterministic and its physical size is asserted.** A 40 × 30 mm
template at 203 dpi produces a 320 × 240 px monochrome PNG; the PDF MediaBox is
113.3858 × 85.03937 points. QR box scaling and quiet zones are computed, not
approximated.

**Editor.** An Owl client action with canvas zoom, grid, safe printable bounds,
selection, move, resize, duplicate, z-order, delete, numeric geometry controls,
keyboard-accessible editing, local undo/redo on the unsaved document, and
product/lot preview selection with visible binding errors. Saving mints a new
immutable version.

**Printing.** `printer_registry.js` selects a transport without the renderer
knowing which: `system_adapter` (browser and system print through a zero-margin
`@page` route), `phomemo_adapter` (Ateliera's 18 Phomemo definitions and seven
protocol families) or `niimbot_adapter` (D110). Both BLE adapters check browser
capability and fall back to system print. Remembered device selection is
persisted. The Phomemo path is Ateliera's complete vendored `phomymo` browser
transport and print wrapper: persistent connection, service/characteristic
selection, retries, notifications, write-without-response fallback and the
serial-named M110 model override. Its UI exposes model, roll position, media
sensing, feed, density, speed, dithering, connection diagnostics and a
renderer-independent test pattern.

**Routes.** `/mb_label/job/<id>/label.pdf`, `/preview.png`, `/print`.

**Security.** `group_mb_label_manager` designs templates;
`group_mb_label_user` prints but cannot edit.

19 server test methods, 20 Hoot tests across `mb_label` and `mb_label_pos`.

### `mb_label_pos`

Depends on `mb_label`, `point_of_sale`. Upgrade-safe companion; edits no POS
core.

**Projection.** `pos.session._load_pos_data_models()` adds a bounded
`mb.label.qr.alias` projection; `pos.load.mixin` supplies fields, relations and
the IndexedDB payload. The bound is saleable stock available to the configured
POS, plus product-only aliases. Measured: 1,001 aliases, a 202,214-byte
projection, a 0.0671-second full bootstrap query. Lookup is a `Map`, so
constant-time.

**Resolution order.** Exact alias, then compatibility parsing, then
`super._barcodeProductAction()` unchanged. Compatibility forms are `SKU`,
`SKU@LOT`, the customer URL fragment form, GS1 Digital Link and GS1 element
strings.

**QR format.** A prefix set in Label Studio, for example an Instagram profile,
plus a fragment:

```text
https://instagram.com/username#SKU
https://instagram.com/username#SKU/LOT-OR-SERIAL
```

**Selling.** An exact serial goes through Odoo's tracked-product path at quantity
one. A batch lot follows Odoo's ordinary quantity and lot rules. A product-only
QR keeps normal lot selection. Payment produces the ordinary Odoo stock move, not
a bypass.

**Rejection without mutation.** Zero stock, wrong warehouse or company, archived
alias, duplicate serial and malformed QR each leave the order untouched.

**Offline.** An already-loaded session resolves from the cached projection with
no network call; reconnection reconciles through Odoo authoritatively. Aliases
minted during an open session require a reload, and the module says so.

11 server test methods, 7 Hoot tests.

## Firing

### `mb_ceramics_firing`

Depends on `mb_workshop_base`, `mb_ceramics_base`, `mrp`, `maintenance`. Not on
`mb_ceramics_compliance`: a firing is a physical event whether or not the ware
in it is meant for food.

**A firing is not a work order, and Odoo will not let it be one.**
`mrp.workorder.production_id` is `required=True`, so a work order belongs to
exactly one manufacturing order. A kiln is filled because firing is expensive, so
one load routinely holds ware from several orders, and one order passes through
at least two firings — bisque then glaze. Firing and manufacturing order are
many-to-many, so the physical event needs its own record. `mb.firing` owns it,
and each work order points at the firing it happened in, which gives the
many-to-many without a join model.

**Boards, not pieces.** No adhesive label survives a kiln, so nothing printed can
be attached to ware before the last firing. Identity through the process is borne
by the carrier, which Odoo already models: `stock.package` with a reusable
package type is a ware board, and `parent_package_id` nests board inside shelf
inside load. `stock.quant` already joins package to lot.

**Cooling is a property of the firing.** `cooling_end` is the earliest moment a
load may be unloaded and labelled, which is not the moment the manufacturing
order is marked done.

**A kiln is one work centre, created with the kiln.** Adding an `mb.kiln` creates
its `mrp.workcenter` and its `maintenance.equipment` and keeps both named after
it. One per physical kiln — not one called "Firing", which would serialise two
kilns that fire in parallel, and not one per firing type, which would let Odoo
book the same chamber twice. The work centre sits on `mb_calendar_continuous`,
and `pieces_per_load` becomes its fallback capacity, which is what makes the kiln
a batch: at forty pieces per load, a firing of eight and a firing of forty cost
the same time.

**Duration comes from the programme, not from a routing.** `mb.kiln.program`
carries `firing_hours`; a routing operation points at a programme and takes its
duration from it. Cooling counts, on by default, or a plan books two firings into
one night. `mb.kiln.program.segment` holds the ramp rate, target and hold per
step, which is what a potter reads and what a duration can be derived from.

Declared, scheduled and measured are kept apart: `firing_hours` is what plans
rest on, `scheduled_hours` is what the segments add up to, `measured_hours` is
the **median** of firings actually recorded — median rather than mean, because
one interrupted firing would drag an average somewhere no real firing has been.
Adopting either is a button, never a drift.

**A kiln says what it is.** Manufacturer, model, series, chamber volume, maximum
temperature, connected load and zones on `mb.kiln`. Model, serial and purchase
date are mirrored onto `maintenance.equipment`, where Odoo expects an asset's
identity to be.

**Curve figures are fields, the curve is an attachment.** A twelve-hour firing
sampled every thirty seconds is about 1,400 points, never read point by point.
Peak temperature and hold time are queried and constrained, so they are fields;
the trace is evidence, so it is an attachment.

This addon carries `19.0.1.1.0/post-migrate.py` and
`19.0.1.2.0/pre-migrate.py`, the latter for the programme model moving here from
`mb_kiln_bridge`. Other addons also carry migrations for their own data changes.

39 test methods.

### `mb_kiln_bridge`

Depends on `mb_ceramics_firing`. Pulls kilns, live status and completed firings
from ROHDE myKiln into the provider-neutral records above.

**Ordinary Odoo shape, reversing an earlier decision.** `POC-PLAN.md` section
10.7 specified an external sidecar so no tenant database would hold a provider
credential. That was reversed on 6 August 2026: a single workshop does not need a
fan-out poller, and a connection record with an `ir.cron` and a Python client is
the shape an Odoo developer can read and maintain. **The cost is real and is
stated on the model** — the myKiln password and the provider token are columns in
this database, restricted to manufacturing managers and never logged. Going
multi-tenant reverses the decision again, and at that point the credential moves
out and this addon keeps only the apply surface. The persisted token also
knowingly departs from section 10.7, because myKiln issues Django REST Framework
tokens, which have no expiry, so the cron can reuse one; it is cleared whenever
the connection changes.

**Read-only toward the provider.** The client authenticates, lists kilns and
controllers, lists firings and fetches samples. There is no method that starts a
firing, sends a programme or edits provider data. A write-capable connector needs
its own safety review and explicit authorization.

**Programmes are derived, because there is no library to read.** Checked against
the live service on 7 August 2026: `/api/v1/programs/` returns one nameless,
slotless snapshot per firing ever recorded, and `/api/v1/library_programs/` — the
real library — is empty, which is why `library_program_name` is null on every
firing. What every firing does report is the controller slot it ran on and the
programme as it ran, so the programme list is built by grouping firings by slot
and taking the most recent. Newest wins; an older firing is ignored, so a
backfill walking the archive cannot overwrite current state. What a programme
*means* — bisque or glaze, how long the load must stand — stays the potter's, and
no refresh touches it.

**Connection state.** `state`, `last_sync`, `last_error`, a firing limit, a
timeout, resumable backfill (`backfill_state`, `backfill_offset`,
`backfill_total`, `backfill_page_size`, `backfill_progress`), optional programme
scanning and an optional raw-payload store for debugging.

53 test methods across normalization and sync, against sanitized fixtures in
`tests/fixtures.py`.

## Materials

### `mb_catalogue_sync`

Depends on `mb_ceramics_base`, `product`, `purchase`, `uom`, `stock`. Reads the
cross-tenant ceramics catalogue service; never writes back.

**Status: undecided.** Nothing depends on it, no product in the live database
carries a catalogue identity, and no import has ever been run. It is specified
here because it exists and installs, not because it is settled — see *Known
gaps*.

**What crosses the boundary.** The catalogue holds roughly 47,000 supplier
listings across 76 shops with price history. None of that belongs in an artisan's
database: it is cross-tenant, volatile, and the most independent asset in the
product. What crosses is the curated manufacturer identity — Mayco SC74 Hot
Tamale — plus the offers of the suppliers this workshop actually buys from.

**Nothing is imported by searching**, which is why the wizard exists. Search a
manufacturer code or product name, tick what the workshop uses, import those.
Punctuation in a code does not matter: AMACO stores `PC20` and prints `PC-20` on
the jar, and both find Blue Rutile. Results are ordered by how many suppliers
carry the product, because a code eleven shops sell is more likely the one
somebody means than a code one shop sells. A product already held is shown as
held rather than offered again.

Materials are stocked products (`is_storable`), not service lines: a ceramic
material is bought, held and consumed.

**Catalogue families map onto the taxonomy, they do not define it.** The
`product.category` records live in `mb_ceramics_base`; this addon translates a
family name onto one of them and writes `categ_id` only where it is empty. A
family it has never heard of lands on the parent category rather than nowhere,
so it is visible and correctable instead of silently uncategorised. Before
19.0.1.3.0 the categories were defined here, which put a compliance gate behind
an optional connector.

**Models.** `mb.catalogue.client`, `mb.catalogue.service`,
`mb.catalogue.supplier`, `mb.catalogue.units`, `mb.catalogue.import` and
`mb.catalogue.import.line`.

17 test methods. Runs against the read API in
`catalogue-ceramics/catalogue-service/`.

## Consignment

### `mb_depot`

Depends on `stock`, `sale_stock`. Dépôt-vente: stock held at galleries and shops,
and the statement that settles it.

**Odoo has no outbound consignment.** Its built-in Consignment setting is the
other direction — vendor-owned stock in your warehouse — and a search of every
OCA manifest turns up nothing either. The location model below is not a
workaround; it is what everyone builds.

**A depot is an internal location we own and a gallery physically holds.**
Internal matters: unsold pieces stay on our balance sheet and no revenue is
recognised until the gallery reports a sale, which is the legal situation of
dépôt-vente. Delivering to the customer location instead would derecognise the
stock with no counterpart revenue.

**Depots sit in their own root tree**, not under a warehouse. Internal keeps them
on the books; being outside `WH` keeps an ordinary delivery from reserving a
piece standing on a shelf in Nantes. Odoo 19 has no Physical Locations root any
more, so the depots get their own.

```text
Dépôts                 (view, no parent)
└── Galerie Truc       (internal, is_depot)
```

**The commission is a pricelist, not code.** Under achat-revente sur vente the
gallery buys at list minus its percentage at the moment it sells. For that
percentage to appear on the invoice as a discount rather than a quietly reduced
unit price, the pricelist item must be `compute_price='percentage'` **and** the
Discounts feature must be enabled — see `sale/models/product_pricelist_item.py`,
`_show_discount()`. The creation wizard sets both.

**What the module adds:** a depot flag on the location carrying gallery,
commission and sourcing route; a wizard creating location, route, pull rule and
commission pricelist in one action, because that set repeats per gallery; live
stock per depot with an ageing column, so a piece unsold for four months is
visible; and the depot statement — opening, placed, sold, returned, closing over
a period, per piece.

**Sold and returned are both outgoing moves** and are told apart by destination,
which is what makes the statement reconcile against the quants rather than drift
from them.

**Bon de dépôt.** Its own report, because `stock_picking_report_valued` cannot
serve: every value on it comes from `move_id.sale_line_id`, and a placement is an
internal transfer with no sale line, so it renders blank.

Selecting the depot route on a quotation needs OCA's
`sale_order_global_stock_route`. That is deliberately not a dependency — it is
AGPL-3 and this module is LGPL-3. Without it the route is created and set on the
order line by hand.

9 test methods.

## Payments

All three are currently **uninstalled** in the live database.

### `mb_payment_sumup`

Depends on `payment`. SumUp as an Odoo payment provider, which Odoo does not
ship.

SumUp is the acquirer an artisan already has: the reader costs thirty euros and
there is no monthly fee.

**Hosted checkout, not an inline form.** One POST to `/v0.1/checkouts` with
`hosted_checkout.enabled` returns a `hosted_checkout_url` that SumUp operates —
card form, 3-D Secure, wallets, receipt — and Odoo never sees a card number. Same
shape as `payment_mollie`, and deliberate: an inline form would put this database
inside the cardholder-data environment.

**Two facts about SumUp's callbacks decide the design.** `return_url` is a
backend notification, unsigned and carrying no payment evidence, so
`/payment/sumup/webhook` reads the body not at all: the reference comes from the
URL this module built, and the payment data is fetched from the API with the
merchant's key. And a checkout can be paid without anyone returning to Odoo — the
QR code on a printed invoice is exactly that case — so a cron re-reads pending
checkouts and the callback is an optimisation rather than a requirement.

`/payment/sumup/return` uses `save_session=False` for the reason every other
provider does: the session cookie is set without `SameSite`, some browsers drop
it on a cross-site POST, and the customer would otherwise get a brand new
session.

**Credentials are the workshop's own** secret key and merchant code on the
provider record. There is no deployment-wide key: money settles into the account
named on the request, and that account must be the one printed on the facture.

Refunds POST to `/v1.0/merchants/{code}/payments/{id}/refunds`, which SumUp
acknowledges with an empty 200 and settles asynchronously. Odoo marks the refund
done on acknowledgement; a refund SumUp later rejects appears in their dashboard,
not here.

14 test methods. `post_init_hook` and `uninstall_hook`.

### `mb_pos_sumup`

Depends on `point_of_sale`, `mb_payment_sumup`. Makes the artisan's phone the
terminal.

**A deep link rather than the terminal API.** SumUp's server-side terminal
endpoints drive a Solo or an Air Lane — a networked reader with its own identity.
A reader paired over Bluetooth to a phone has none, and only the SumUp app can
reach it, so the payment goes where the reader is.

```text
POS  ──window.location──▶  sumupmerchant://pay/1.0?...&foreign-tx-id=<line uuid>
SumUp app  ──callback──▶   /pos/ui/<config>/payment/<order uuid>?smp-status=...
POS boots  ──▶  restores the order from IndexedDB, finds the line, finishes it
```

**The page is left and reloaded, and that is the part to get right.** The payment
line is written to IndexedDB *before* the handover; the callback returns to the
payment screen's own route so the router lands there; the line is found again by
`foreign-tx-id`, the one parameter SumUp echoes back unchanged. A pending-line
fallback covers SumUp app versions older than 1.53.2, which do not echo it.

**`smp-status` is a claim, not evidence.** When the payment method names a SumUp
provider, the result is verified against
`GET /v2.1/merchants/{code}/transactions?foreign_transaction_id=...`, amount
included, before the line is marked paid. Without a provider the callback is
taken at face value, defensible only because it never crosses the network: the
SumUp app opens it in the same browser on the same device.

Refunds are an API call against the original transaction code, so they need the
provider configured; without it the POS says so rather than appearing to refund.

**Platform constraints, inherited.** Android or iOS, in Safari or Chrome. The
native Odoo mobile app has no URL handling and cannot come back from the SumUp
app; a desktop browser has no SumUp app to open.

10 test methods.

### `mb_account_payment_sumup`

Depends on `mb_payment_sumup`, `account_payment`. An invoice handed over at the
studio door is paid by someone holding a phone.

One button produces a link and a QR code, the QR code prints on the invoice PDF,
and the customer pays by scanning it. Two destinations, because they fail
differently:

- **SumUp hosted checkout** creates the checkout up front and encodes SumUp's own
  URL. Nothing of ours is on the path between the customer and their card, so it
  works when this Odoo is behind a VPN, asleep, or unreachable from the
  customer's phone. Settlement arrives later, through the callback or the polling
  cron in `mb_payment_sumup`. This is the default, because the common case is a
  printed invoice and a customer standing in a workshop.
- **Customer portal** encodes Odoo's `/payment/pay` link. The customer sees what
  they are paying and can choose any enabled provider — but only if they can
  reach this instance.

**The link is bound to the invoice, not regenerated per view.** Odoo's
`payment.link.wizard` recomputes its URL whenever the amount changes, which is
free for a portal link and not free for a checkout: every recompute would mint
another checkout in the merchant's reporting. So the SumUp link is created by an
explicit action, stored on the invoice, and reused while still open.

The QR code is rendered by Odoo's own barcode endpoint, so nothing is fetched
from outside when the PDF is printed.

8 test methods.

## French tax regime

### `l10n_fr_micro_enterprise`

Depends on `l10n_fr_account`, `account_edi_ubl_cii`. Idempotent franchise-en-base
setup that does not replace the economic VAT rates stored on products.

For every French fiscal company it prepares separate 0% goods and service sales
taxes; EN16931 category `E` with exemption code `VATEX-FR-FRANCHISE`; the invoice
note `TVA non applicable, article 293 B du CGI`; mappings from active or archived
standard-category (`S`) French sales VAT; and a France-only automatic fiscal
position.

**Switching is an administrator action, not a migration.** Under **Invoicing →
Settings → Taxes → Micro-enterprise VAT regime**, *Activate franchise en base*
enables the automatic domestic mapping and *Activate VAT liable* disables it so
the original product taxes apply again. The operation records its date and user
and **never rewrites products or existing accounting documents**. Foreign
transactions keep Odoo's normal fiscal-position handling, which is why every
customer needs a valid country: Odoo determines no fiscal position for a partner
without one.

**Factur-X comes from Odoo's native `account_edi_ubl_cii` exporter** and may be
downloaded or handed to any approved-platform connector. The addon does not
require Odoo's PDP service. For a franchise seller with no VAT number, the native
preflight accepts the company registration identifier Odoo already emits as
EN16931 BT-30; **no VAT identifier is ever fabricated.**

`post_init_hook`. 7 test methods across setup, regime switching and Factur-X
export.

## Commercial operations

The `mb_commercial_operations` family is an optional application layer over
Odoo 19's projects, tasks, analytic accounts, timesheets, accounting, stock,
MRP, Purchase, Sales, POS, Expenses and Fleet models. One market occurrence or
long-lived depot contract owns one project and analytic account; native source
documents remain the evidence for actual revenue and cost.

The base addon provides the planning calendar, six-month contractual occurrence
generator, labour and travel plans, TollQuote quote revisions, break-even
scenarios and a live planned-versus-actual pivot/graph/list report. TollQuote
calls are explicit, host allow-listed, time-bounded and sanitized; incomplete,
unpriced, unknown-currency or unvalidated API revisions cannot silently become
zero-cost accepted quotes.

Optional bridges keep their native boundaries:

- Stock prepares and returns exact event stock through internal pickings, with
  lot/serial reconciliation and no cost entry for the internal transfer.
- Depot forecasts refill quantities from completed sale/exposure evidence,
  creates reviewed refill work, prepares prorated draft rent bills, and carries
  consolidated invoice revenue and outbound COGS to the depot project.
- MRP and Purchase create idempotent reviewed draft supply documents; native
  confirmation alone makes supply incoming.
- Sales and POS source only free event stock and put revenue plus outbound COGS
  on the event account exactly once. POS sessions snapshot the operation and
  cannot be reconfigured while open.
- Fleet, Expenses and the URSSAF bridge add vehicle conflicts, native expense
  allocation and a read-only pending/draft-declaration/filed recognition status.

Operational completion, stock reconciliation, document completeness, financial
close, accounting reconciliation and URSSAF recognition are deliberately
separate. Financial close locks operation-owned planning and links; later native
payment, reconciliation, credit and legal-recognition events remain possible and
continue to update their computed statuses.

## Environment

**This repository now stands up on its own**, which is what POC-PLAN section
10.2 asked for. `make bootstrap` on a clean checkout copies `.env`, pulls the
images, starts Postgres and Odoo, creates the database and installs all eleven
addons. See [README.md](README.md) for the full target list.

```text
docker-compose.yml    db (postgres:17-alpine) + odoo:19 + mailpit (profile)
config/odoo.conf      addons_path, workers = 0, list_db = True, proxy_mode = False
Makefile              bootstrap, up, dev, logs, shell, psql, install, upgrade,
                      test, check, lint, oca, reset-poc
tools/                check_addons.py, vendor-oca.sh
.github/workflows/    static, install, upgrade, test
oca/                  vendored, gitignored, and optional — nothing depends on it
```

Ports default to **8169** and **5442**, not 8069/5432, so this stack and the
sibling `odoo-poc/` can run at once.

**The local config is not the published one, deliberately.** Here `list_db` is
True and `proxy_mode` is False because nothing terminates TLS in front of it and
nothing outside the host can reach it. The sibling stack publishes through
cloudflared and makes the opposite choices — `list_db = False`, a pinned
`dbfilter`, `proxy_mode = True`. Copying this config toward anything public means
revisiting all three.

The sibling remains useful reference material and is unmodified. It still holds
the databases with real data; this stack creates its own.

`reset-poc` accepts only `mb_scratch`, `mb_ci` or `mb_test` and refuses every
other name, so a mistyped variable cannot destroy a demonstration database.

`scripts/` holds nine one-off data operations, each driving `odoo shell` through
`docker exec` and a `subprocess` call rather than a network API, so nothing needs
the two Compose stacks to share a network. They cover catalogue seeding, stock
and image import, category assignment, depot and SumUp fixtures, and demo
cleanup. They are operational tools, not part of any addon, and none is covered
by a test.

`seed_from_catalogue.py` states it exists because the catalogue service "does not
exist yet" and reads `catalogue.canonical_catalogue` directly. A healthy
`catalogue-service` container is now running, and `mb_catalogue_sync/README.md`
says the addon runs against it. One of the two is stale; the script is the
likelier candidate and should be retired once that is confirmed.

## Verification status

Test methods on disk, by module:

| Module | Server | Hoot | Migrations |
| --- | ---: | ---: | --- |
| `mb_workshop_base` | 12 | — | 2 |
| `mb_ceramics_base` | 4 | — | — |
| `mb_ceramics_compliance` | 6 | — | — |
| `mb_label` | 19 | 10 | — |
| `mb_label_pos` | 11 | 7 | — |
| `mb_ceramics_firing` | 39 | — | 2 |
| `mb_kiln_bridge` | 53 | — | — |
| `mb_catalogue_sync` | 17 | — | — |
| `mb_depot` | 9 | — | — |
| `mb_payment_sumup` | 14 | — | — |
| `mb_pos_sumup` | 10 | — | — |
| `mb_account_payment_sumup` | 8 | — | — |
| `l10n_fr_micro_enterprise` | 7 | — | — |
| **Total** | **192** | **17** | **2** |

Verified beyond unit tests:

| Claim | Evidence |
| --- | --- |
| Label artifact has correct physical dimensions | 320 × 240 px at 203 dpi; PDF MediaBox 113.3858 × 85.03937 pt |
| Generated QR decodes to the exact URL | ZXing decode of the generated PNG |
| Label Studio works at desktop and phone width | Live Odoo action at 1280 × 900 and 390 × 844, real preview options, no browser exceptions |
| Fresh QR sells the exact serial | Live ProductScreen scan added `RUNTIME-CUP` qty 1, lot `PIECE 2026/01`; paid order created the standard done stock move |
| POS projection is bounded | 1,001 aliases, 202,214-byte projection, 0.0671 s bootstrap query |
| myKiln programme endpoints | Checked against the live service, 7 August 2026 |

Verified by CI, on every push:

| Lane | Result |
| --- | --- |
| Static: ruff, manifests, data paths, assets, XML, access rules, dependency graph | 11 addons clean |
| Clean install on an empty database, with an empty OCA path | 11 modules installed |
| Upgrade in place (`-u` after `-i`) | no-op rather than crash |
| Server tests, scoped to these addons | **192 tests, 0 failed, 0 errors** |

Checked once by hand, on 7 August 2026, and worth repeating whenever the
question comes up again: installing the other ten addons **without**
`mb_catalogue_sync` gives 175 tests, 0 failed, 0 errors, and the three glaze
categories the food-contact gate reads are present and owned by
`mb_ceramics_base` since 19.0.2.0.0. The importer is removable.

The category migration was tested the same day against a database built from the
pre-split commit, with a product filed under `mb_catalogue_sync.categ_glaze`:

| Check | Result |
| --- | --- |
| After upgrade, categories owned by | `mb_workshop_base`, all 8 — and `mb_ceramics_base` after the 19.0.2.0.0 script |
| Category records named `categ_*` | 8 — no duplicates |
| The product's `categ_id` | unchanged, same record, now re-owned |
| Re-running the upgrade | no-op, still 8 |
| Then uninstalling `mb_catalogue_sync` | categories survive; product keeps its category |
| **Same uninstall on the pre-split code** | **all 8 categories deleted, product's `categ_id` set to NULL** |

That last row is what the script prevents.

Not verified:

- Physical printer and scanner qualification. The synchronized Ateliera
  Phomemo browser transport/protocol path and NIIMBOT D110 packet builder are tested
  against fixtures only; no device is attached to any test run.
- The 20 Hoot tests, in CI. They need a browser and the `odoo:19` image has
  none; see README.md for the tag and the command to run them by hand.
- Migration from a previously released version, as opposed to `-u` being a
  no-op. Deliberate: nothing is released, so there is no prior version to
  migrate from. See "Migration scripts start at first release".
- The three SumUp addons against the live database. They install and their
  tests pass on a fresh one.
- Cross-company denial, which is untested throughout.

## Known gaps

Ordered by consequence, not by effort.

1. **The Hoot suite is outside CI**, and the browser image that would let it in
   does not exist yet. 20 tests covering the label editor, printer protocols,
   old-JSON conversion and POS QR parsing run only when someone runs them.
2. **Two credentials at rest in the tenant database**, both knowingly:
   `mb.kiln.connection` (myKiln password and non-expiring token) and the SumUp
   provider record. Both reverse on the move to multi-tenancy.
3. **`admin_passwd = poc-master-change-me`** in the sibling
   `odoo-poc/config/odoo.conf`, on a host published through cloudflared.
   `list_db = False` limits the blast radius; the password is still a default.
   This repository's own config uses a distinct local-only value and publishes
   nothing.
4. **Reverse-engineered printer protocols** regress silently on untested
   firmware. Keep the packet fixtures, and smoke-test each model before
   advertising support for it.
5. **Unofficial myKiln API.** No contract, no versioning. The connector is
   isolated and stops on auth or schema failure, which is the mitigation; there
   is no warning.
6. **`mb_depot` does not depend on `mb_ceramics_compliance`**, so a database can
   hold consignment stock without the food-contact identity that gives products
   their tracking rules. Unlike the catalogue case this may well be right —
   consignment is about where a piece is, not what it is made of — but it should
   be decided rather than inherited. The 19.0.2.0.0 split narrowed the question:
   what `mb_depot` would be opting into is now a named compliance addon rather
   than something called a base.
7. **`mb_catalogue_sync`'s future is undecided.** Nothing depends on it, no
   product carries a catalogue identity and no import has ever run; the
   catalogue service it reads is a separate deliverable. The 19.0.1.3.0 split
   moved the material taxonomy into `mb_workshop_base`, and 19.0.2.0.0 moved it
   on to `mb_ceramics_base`, so that dropping the importer is now a
   self-contained decision with nothing else at stake.

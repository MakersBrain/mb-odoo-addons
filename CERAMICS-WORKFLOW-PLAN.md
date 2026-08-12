# Ceramics Production Workflow Plan

## Purpose

Give the ceramicist a short, natural workflow while retaining reliable material,
batch, and firing traceability in Odoo.

The workflow must support this ordinary case:

1. Throw 10 small box blanks and 7 medium box blanks.
2. Keep them in a damp box.
3. Later take 4 small and 2 medium blanks.
4. Add sculpted decoration and dry them on a board or in the serre.
5. Put them into a bisque firing with unrelated ware.
6. Glaze them.
7. Put them into a second shared firing.
8. Inspect and place the successful pieces in finished stock.

The system must not force all blanks from one throwing session to continue
together. It must preserve the connection from a finished piece or batch back to
the clay and glaze lots actually used.

## Odoo 19 implementation baseline

This plan targets Odoo 19 only. Implementation and tests must use the models and
field shapes shipped in the `odoo:19` image used by this repository, rather than
examples copied from an older release.

In particular:

- a stocked product is configured with `is_storable=True`;
- lots and serials are `stock.lot` records distinguished by the product's
  `tracking` value (`none`, `lot`, or `serial`);
- manufacturing outputs use the Odoo 19 Many2many `lot_producing_ids`, not the
  older singular `lot_producing_id`;
- reusable carriers are `stock.package` records with a reusable package type;
- kiln operations remain `mrp.routing.workcenter` operations and resulting
  `mrp.workorder` records;
- relational updates use `fields.Command` in Python code;
- every wizard and automation is tested against Odoo 19's actual reservation,
  backorder, manufacturing completion, package, and traceability behaviour.

No compatibility layer for Odoo 16, 17, or 18 is part of this work.

## Design decision

Use two manufacturing stages:

1. **Blank production:** clay becomes lot-tracked blank stock in the damp box.
2. **Finishing:** selected blanks become sellable pieces through decorating,
   drying, bisque firing, glazing, glaze firing, and inspection.

Only raw materials, reusable blanks, sellable seconds, and finished pieces are
inventory products. Leather-hard, bone-dry, bisqued, and glaze-dry are operational
states, not separate inventory products.

```text
Clay lot
  -> Throwing session
  -> Blank lot in damp box
  -> Finishing order
  -> Decorate and dry on a board
  -> Shared bisque firing
  -> Glaze
  -> Shared glaze firing
  -> Inspection
  -> Finished lot or finished serial
```

This boundary keeps stock meaningful without creating a transfer and an
intermediate SKU for every physical change in the clay.

## Identity rules

Four different identities answer four different questions:

| Identity | Meaning | Example |
|---|---|---|
| Product reference | What kind of item is it? | `Small Flower Box` |
| Lot | Which pieces were made together? | `FIN-20260820-003` |
| Serial number | Which single physical piece is it? | `PIECE-00247` |
| Carrier | Where is the work physically grouped? | `BOARD-12` |

A serial number always identifies one piece. A lot may contain several pieces of
the same product reference.

Use lots for finished pieces that are interchangeable. Use serial numbers only
where an individual piece has its own price, photograph, description, QR code,
reservation, defect status, or return history. Because Odoo configures tracking
per product, a product reference should have one stable policy: no tracking, by
lot, or by unique serial number.

A sellable second is a separate product reference, normally named from the first-
quality product with a `- Second` suffix. This gives it an explicit catalogue and
pricing identity. A stock location alone does not make the same product sell at a
different price.

## Product setup

### Raw materials

Create storable products for materials whose origin matters:

- clay bodies;
- food-contact glazes;
- other glazes where batch traceability is useful;
- significant stains, oxides, slips, and decoration clays where required.

Recommended tracking:

| Material | Tracking |
|---|---|
| Clay | Required by lot |
| Food-contact glaze | Required by lot |
| Other glaze | By lot when useful |
| Minor uncritical material | No tracking |

A tracked raw material must have a lot on its incoming receipt and whenever it is
consumed. The lot may be filled later while a movement is still a draft, but Odoo
must refuse validation without it.

### Blank products

Create a storable, manufactured, non-saleable product for every reusable blank
shape and size, for example:

- `Small Box - Blank`;
- `Medium Box - Blank`.

Track blank products by lot. Create one blank lot per throwing session and product
reference. A session producing two sizes therefore produces two lots:

```text
THR-20260809-001-S  Small Box - Blank   quantity 10
THR-20260809-001-M  Medium Box - Blank  quantity 7
```

The intermediate blank lot is essential. Without it, native Odoo traceability
cannot cross from the finishing order back through the throwing order to the clay
lot.

### Finished products

Create one product for each sellable reference.

- Configure ordinary repeatable pieces as tracked by lot when batch genealogy is
  needed.
- Configure individually unique pieces as tracked by serial number.
- Leave tracking off only where provenance is not required.

Example for interchangeable work:

```text
Product: Small Flower Box
Lot: FIN-20260820-003
Quantity: 4
```

Example for unique work:

```text
Product: Unique Sculpted Box
Serial: PIECE-00247
Quantity: 1
```

For every product that can be sold as a second, create a paired sellable product
such as `Small Flower Box - Second`. Give it the same lot-or-serial tracking
policy as the first-quality product and its own price. The inspection workflow
uses it as an actual secondary output; it is not included as a fixed expected
quantity on the normal bill of materials.

## Locations and carriers

Use stock locations only at meaningful inventory boundaries:

```text
Workshop
|-- Raw Materials
|-- Damp Box
|-- Finished Stock
|-- Seconds
`-- Scrap
```

The damp box is a real internal stock location. Blanks can wait there for an
indefinite time and remain available for later finishing orders.

Do not initially create inventory locations for decorating, drying, waiting for
bisque, bisqued, or waiting for glaze. Represent those states through work orders,
boards, and firing records. More granular locations can be added later only if
the workshop finds a real stock question they answer.

Model ware boards, bats, and trays as reusable `stock.package` carriers. Give each
one a durable identifier such as `BOARD-12`.

### WIP on boards

A native package contains stock quants. It cannot, by itself, identify a blank
after that blank has been consumed by a finishing order and before a finished
quant exists. Add an explicit `mb.board.content` model as the operational source
of truth for work in progress on carriers.

Each content line records:

- `board_id`: a reusable `stock.package`;
- `production_id`: the finishing `mrp.production`;
- `quantity`: how much of that order is on the board;
- `current_workorder_id`: the current operation, constrained to the production;
- `date_loaded` and `date_unloaded`;
- `state`: current or removed;
- company, derived product, and display references needed for filtering.

One production may be divided over several boards, and one board may carry lines
from several productions. Current board quantities may not exceed the unfinished
quantity of their manufacturing order. Removing or transferring a line must keep
history rather than deleting it.

The existing firing relationship is one firing per work order. Consequently, all
boards carrying quantity from one firing work order must travel in the same kiln
load. If only some of that order is to fire now, the operator must first use an
explicit **Split for later firing** action. It creates an Odoo manufacturing
backorder/split order, reallocates the deferred board-content quantity to it, and
thereby gives each physical group its own firing work order. Never attach one
work order fractionally to two `mb.firing` records.

When blanks are reserved and consumed, `mb.board.content` continues to identify
the physical WIP. At final production, normal Odoo output move lines and packages
identify the resulting stock again. The board model never replaces input and
output lot move lines and never participates in inventory valuation.

## User workflow

### 1. Record throwing

Expose one workshop action named **Record Throwing**.

The ceramicist enters:

- date;
- clay product and clay lot;
- output product and quantity lines;
- damp-box destination;
- optional board or bat;
- optional notes.

Example:

```text
Clay: White Stoneware
Clay lot: CLAY-026

Outputs:
10 x Small Box - Blank
 7 x Medium Box - Blank
```

Standard Odoo manufacturing produces one primary product per manufacturing
order. The simplified action therefore creates one internal manufacturing order
per output line and groups them under one visible throwing-session reference.

On confirmation, the system must:

1. reserve the selected clay lot;
2. allocate the clay quantity to each internal order;
3. generate one output blank lot for each product line;
4. complete the throwing operation;
5. place the output lots in the damp-box location;
6. offer a carrier label when one is useful.

The resulting inventory is:

```text
Damp Box
  Small Box - Blank / THR-20260809-001-S / 10
  Medium Box - Blank / THR-20260809-001-M / 7
```

### 2. Take blanks for finishing

Expose one action named **Take Blanks for Finishing**.

The ceramicist chooses:

- an available blank product and lot;
- the quantity to take;
- the finished product reference;
- the board carrying the work;
- optional additional decoration materials.

Example:

```text
4 x Small Box - Blank from THR-20260809-001-S
    -> Small Flower Box

2 x Medium Box - Blank from THR-20260809-001-M
    -> Medium Sculpted Box

Carrier: BOARD-12
```

Create one finishing manufacturing order per finished product reference. Group
the orders under the visible board or finishing session; do not try to make a
single manufacturing order produce several unrelated output products.

Reserve and consume only the selected quantities. The damp-box balance must then
be six small and five medium blanks. Create `mb.board.content` lines for the six
selected pieces so the board remains meaningful after the blank stock moves are
consumed and before finished stock exists.

### 3. Decorate and dry

The finishing routing contains these operations:

1. sculpt/decorate;
2. dry;
3. bisque fire;
4. glaze;
5. glaze dry;
6. glaze fire;
7. inspect.

Record important decoration materials and their lots on the finishing order.

Drying is waiting, not labour:

- use the continuous calendar;
- assign no hourly cost;
- give it effectively unlimited planning capacity for the initial version;
- use an estimated duration for planning;
- let the ceramicist explicitly mark the board ready, since actual drying time
  depends on the ware and environment.

The board view reads current `mb.board.content` lines and says what is physically
on the carrier, its current operation, and its next required action. Advancing a
work order updates its board lines; moving some pieces to another board creates a
transfer in the board-content history.

### Kiln assignment rule

Odoo creates a work order against the work centre selected by its routing
operation. In this repository, each physical kiln owns exactly one work centre,
and a kiln programme belongs to that kiln. Therefore the kiln and programme are
assigned when the finishing routing/work orders are created, not chosen freely
afterwards.

For the first version:

- a firing work order may only load into the kiln whose work centre it uses;
- its routing operation's `mb_kiln_program_id` must equal the firing's
  `program_id`;
- the programme kind must equal the firing kind;
- arbitrary kiln reassignment at loading is not supported.

If the workshop later needs to move ready work to another kiln, implement an
explicit **Reroute firing operation** action. It must select a programme on the
target kiln, update and replan the work order before loading, and retain the
previous assignment in the chatter. It must not silently replace the work centre
while a firing is underway.

### 4. Load and run a bisque firing

Create one `mb.firing` record for the physical kiln load. A firing is not a
manufacturing order: it gathers bisque work orders from any number of finishing
orders.

The operator first opens or creates a firing for a kiln and programme. The loading
screen then shows only bisque work orders that are marked ready and whose assigned
work centre and routing programme match that firing. The operator selects work or
scans boards and starts the load; an incompatible work order is rejected even if
it is submitted through RPC or import.

Scanning one board loads its compatible work-order lines. If other current boards
carry quantity belonging to the same work order, loading is blocked until those
boards are included or **Split for later firing** has separated the deferred
quantity.

```text
Loading -> Firing -> Cooling -> Unloaded
```

Retain on the firing:

- kiln and programme;
- firing kind;
- start, end, and cooling deadline;
- boards loaded;
- participating work orders and manufacturing orders;
- peak temperature and hold duration;
- energy use where reported;
- controller payload and firing curve where available.

The firing form must expose `program_id`, not merely the controller's historical
`program_name`. Loading a work order writes its `mb_firing_id`. Add server-side
constraints that enforce company, kiln work centre, programme, firing kind, and
one-load-only compatibility.

Prevent normal unloading before the cooling deadline. An early opening must
require a reason and remain visible on the firing record.

After unloading, complete only the participating bisque work orders that are still
open and advance their finishing orders to glazing. Unloading must be idempotent:
repeating it may not finish a later operation or duplicate quantities.

### 5. Glaze

The ceramicist selects the glaze product and actual glaze lot. Associate glaze
BOM lines with the glazing operation so the material is presented and consumed
at the correct point in the routing.

Require the lot for tracked glazes. Record useful process notes, such as dipped
or sprayed, without making them mandatory for completion.

For a food-contact finished product, Odoo must not complete the manufacturing
order unless:

- the finished output has a lot or serial;
- every consumed food-contact glaze lot has a passing migration test;
- the product has its migration limit class where required.

The glazing screen should show migration-test status before firing, but the
existing server-side `button_mark_done` gate remains authoritative. A failed or
untested glaze lot blocks release. If the piece is deliberately downgraded to
decorative/non-food-contact stock, that must use a separately configured product
carrying the required warning; it is not a checkbox bypass on the original
food-contact product.

### 6. Load and run the glaze firing

Use another shared `mb.firing` record, this time with kind `glaze`. Show only
glaze-fire work orders marked ready and compatible with the firing's assigned
kiln and programme.

Link each glaze-firing work order to this firing just as for bisque. Preserve both
firing links through the finishing manufacturing order.

### Compatibility definition

A work order is compatible with a firing only when all of these are true:

1. both records belong to the same company;
2. the work order is open and is not already in another firing;
3. the work order's work centre is the selected kiln's work centre;
4. the routing operation's programme equals `mb.firing.program_id`;
5. programme kind and firing kind agree;
6. the programme peak temperature does not exceed the kiln's maximum temperature;
7. any configured clay-body and glaze firing-range limits contain the programme's
   peak temperature.

Items 1 through 6 are required for the initial release. Item 7 requires explicit
minimum and maximum firing-temperature fields on relevant material products and
is enabled only after those catalogue values are populated; absence of optional
range data must be displayed as unknown, not silently treated as verified.

### 7. Inspect and finish

At unloading or final inspection, balance every selected blank into exactly one
outcome:

- accepted;
- seconds;
- process loss/scrap.

Rework is outside the first release. A later rework route must create an explicit
new work order or manufacturing order and firing link rather than reopening a
completed firing.

For lot-tracked finished products, generate one finished lot for the accepted
quantity. For serial-tracked products, generate one serial per accepted piece.
Generate identifiers automatically and present them for confirmation instead of
asking the ceramicist to type them.

Model a sellable second as an actual output of its separate `- Second` product,
with its own output lot or serial and destination in the seconds location. The
inspection action creates the required Odoo 19 by-product/output move and validates
it with the manufacturing order, preserving the same input genealogy. A second
must not be represented merely by moving the first-quality product to another
location.

A piece broken while it is WIP has no stock quant that native `stock.scrap` can
truthfully remove. Record it on an immutable `mb.production.loss` line containing
the manufacturing order, quantity, operation, reason, date, user, board, and
relevant firing. Finish the manufacturing order with the actual accepted and
second output quantities and explicitly decline/cancel a backorder for the lost
balance. The consumed blank and material moves remain on the order, so cost and
material genealogy show the loss without inventing a finished scrap product.

The inspection transaction must enforce:

```text
selected blank quantity = first-quality output + second output + process loss
```

It must create output lots/serials, loss lines, output moves, and the no-backorder
decision atomically. If any step fails, none of the inspection is committed.

Move accepted work to finished stock and second outputs to the seconds location.
Close the corresponding `mb.board.content` lines while retaining their history.
Offer final QR or price-label printing only now, when a label can survive on the
finished piece or its packaging.

## Simplified interface

The normal workshop surface should expose five primary actions:

1. **Record Throwing**
2. **Take Blanks for Finishing**
3. **Work on Board**
4. **Load Kiln**
5. **Unload and Inspect**

Manufacturing orders, stock moves, lots, packages, and work orders remain native
Odoo records underneath. They should be available for diagnosis and accounting,
but routine work should not require navigating each technical document.

### Automation

Automate:

- throwing-session numbering;
- blank-lot generation;
- finished-lot and serial generation;
- suggestion of the oldest appropriate damp-box lot;
- reservation of selected blank quantities;
- creation and grouping of internal manufacturing orders;
- creation, transfer, and closure of board-content lines;
- remaining-quantity calculation;
- state advancement after unloading;
- final stock placement and label preparation.

Ask the operator for an explicit decision only when:

- multiple clay or blank lots may be consumed;
- the requested blank quantity is unavailable;
- a required material lot is missing;
- a board contains work incompatible with the selected programme;
- a kiln is opened before cooling completes;
- a food-contact glaze lot is untested or failed;
- selected, accepted, second, and process-loss quantities do not balance.

## Traceability contract

Native Odoo genealogy must connect every tracked output to its tracked inputs
through validated stock moves. Firings are operational records attached through
work orders rather than stock moves, so they do not appear in Odoo's native stock
trace automatically.

Add a ceramics traceability action on `stock.lot`. It starts with the native
input/output genealogy and augments each manufacturing step with:

- bisque and glaze work orders from the producing manufacturing order;
- each work order's `mb_firing_id`;
- kiln, programme, firing dates, peak temperature, and cooling interruption;
- associated current and historical board-content lines;
- production-loss lines;
- first-quality and second outputs from the same order.

The firing links may be exposed as computed, non-copied fields on `stock.lot`, but
the work-order relationships remain the source of truth. Do not duplicate a
firing identifier into a free-text lot field.

Expected backward trace:

```text
Finished lot or serial
|-- Glaze lot
|-- Glaze firing
|-- Bisque firing
`-- Blank lot
    `-- Clay lot
        `-- Supplier receipt
```

Expected forward trace:

```text
Clay lot
|-- Small blank lot
|   |-- Finished lot or serials
|   `-- Remaining quantity in damp box
`-- Medium blank lot
    |-- Finished lot or serials
    `-- Remaining quantity in damp box
```

Boards and locations must never be used as a substitute for input and output lot
move lines. They show physical grouping and position, not material genealogy.
The custom report must clearly distinguish native stock genealogy from the
operational firing and carrier context it adds.

## Existing-stock migration

Lot tracking cannot be enabled cleanly while anonymous on-hand quantities remain.
Before activation:

1. count clay by known supplier batch;
2. create an explicitly unknown opening lot where historic identity is lost;
3. count blanks by product, approximate throwing batch, and damp box;
4. create opening blank lots and assign all existing quantities;
5. reconcile the physical damp-box count with Odoo;
6. record migration-test status for existing food-contact glaze lots;
7. enable required tracking;
8. test that future receipts, production, consumption, and transfers cannot be
   validated without a lot.

Use honest identifiers such as `CLAY-OPENING-UNKNOWN` rather than inventing false
supplier provenance.

## Delivery phases

### Phase 1: Odoo 19 foundation and executable vertical slice

- Configure raw, blank, and finished products.
- Configure tracking policies.
- Configure blank and finishing bills of materials.
- Configure work centres and routing operations.
- Configure damp-box, finished, seconds, and scrap destinations.
- Register boards and kiln programmes.
- Add `mb.board.content` and the minimum board assignment view.
- Expose `mb_firing_id` on firing work orders or provide a minimal firing loader;
  the current read-only firing work-order list is not sufficient.
- Expose `program_id` on the firing form and enforce loading compatibility on the
  server.
- Add unloading completion that is safe to repeat.
- Add the ceramics lot trace showing both native genealogy and firing context.
- Run the entire example through this minimal vertical slice before building the
  convenience wizards.

### Phase 2: workshop actions

- Implement Record Throwing.
- Implement Take Blanks for Finishing.
- Expand the board assignment view into the workshop board overview and transfer
  workflow.
- Expand the minimum loader into ready-for-firing selection and board scanning.
- Add unloading and inspection assistance.

### Phase 3: automation and controls

- Add automatic lot and serial generation.
- Add oldest-lot suggestions and reservations.
- Add material-lot and quantity-balance validation.
- Add firing readiness and programme compatibility checks.
- Add second-output and production-loss handling.
- Surface the existing food-contact migration-test gate before release.
- Add final label preparation.

### Phase 4: reporting

- Damp-box availability by product and lot.
- Boards and their current operations.
- Work waiting for bisque or glaze firing.
- Finished-product backward genealogy augmented with boards and firings.
- Clay and glaze lot forward traceability augmented with loss and second outputs.
- Breakage, process loss, and seconds. Rework reporting is added only with a
  separately designed rework route.
- Kiln utilisation and firing history.

## Acceptance scenario

The first complete implementation must pass this end-to-end scenario:

1. Receive clay lot `CLAY-026`.
2. Record one throwing session with 10 small and 7 medium blanks.
3. Verify that two generated blank lots appear in the damp box.
4. Take four small and two medium blanks for finishing.
5. Verify that six small and five medium blanks remain available.
6. Put the selected work on `BOARD-12`.
7. Verify that current board-content lines account for all six pieces even though
   their blank quants have been consumed.
8. Complete decoration and mark drying ready.
9. Load the board into a matching bisque firing containing unrelated work and
   verify that another kiln or programme is rejected.
10. Complete cooling and unload the bisque firing twice; the second call must make
    no additional change.
11. Record a tested glaze product and glaze lot.
12. Load the work into a matching shared glaze firing.
13. Complete cooling, unload, and inspect.
14. Split the result into first-quality, second, and process-loss quantities and
    verify that the three outcomes equal six.
15. Generate a finished lot or one serial per unique accepted and second piece.
16. Verify that no backorder remains for process loss and that immutable loss
    lines retain its reason, operation, board, and firing.
17. Trace every accepted and second output through the custom ceramics report to
    its blank lot, clay lot, glaze lot, board history, bisque firing, and glaze
    firing.
18. Trace `CLAY-026` forward to first-quality outputs, seconds, losses, and the
    remaining damp-box blanks.
19. Repeat completion with an untested food-contact glaze lot and verify that the
    manufacturing order is blocked; add a passing migration test and verify that
    it can then complete.

## Completion criteria

The workflow is complete when:

- the acceptance scenario passes without manual correction of stock moves;
- the ceramicist can perform normal work through the five workshop actions;
- no adhesive piece label is required before final firing;
- partial blank withdrawals retain correct damp-box balances;
- board-content quantities identify all WIP between blank consumption and final
  output;
- shared firings accept work from several manufacturing orders;
- incompatible kiln, programme, kind, and company combinations are rejected;
- missing tracked lots prevent validation;
- untested or failed food-contact glaze lots prevent release;
- lot and serial creation is automatic in the routine path;
- first-quality, second, and process-loss quantities balance without an accidental
  backorder;
- backward and forward traceability reports contain no unexplained gaps and show
  both native stock genealogy and firing context.

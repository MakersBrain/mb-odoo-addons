# Bisque Stock Workflow Plan for Odoo 19

Status: complete implementation-ready plan

Target addon: `mb_ceramics_workflow`

Related addons: `mb_workshop_base`, `mb_ceramics_firing`, `mb_label`

Target platform: Odoo 19 Community

Initial validation database: `odoo_test`

## 1. Objective

Add bisque ware as a real, lot-tracked intermediate inventory stage while
preserving the existing throwing, ware-board, shared-kiln, loss, glaze-lot, and
finished-piece traceability.

The supported stock genealogy must become:

```text
Clay product / clay lot
  -> Green blank product / throwing lot
  -> Bisque product / bisque lot
  -> Finished product / serial or finished lot
```

For glazed products, the final genealogy must also identify every glaze lot
consumed by the glazing manufacturing order.

This plan extends `CERAMICS-WORKFLOW-PLAN.md`. Where the older plan treats
bisque as work in progress inside one long finishing order, this plan introduces
a stock boundary after bisque firing because the workshop wants to count, store,
select, and consume bisque ware independently.

## 2. Why the Addon Must Change

The current addon implements two manufacturing stages:

1. throwing produces lot-tracked green blanks;
2. one finishing MO consumes the blank and carries it through decoration,
   drying, bisque firing, glazing, glaze firing, and final inspection.

That second MO cannot honestly expose bisque stock. In standard Odoo, the
primary manufactured product enters stock when its MO is completed. Creating a
bisque quant halfway through a still-open finished-product MO would bypass the
normal stock-move genealogy, valuation, reservation, and backorder mechanisms.

The correct Odoo model is therefore three MOs separated by two genuine stock
boundaries:

```text
Throwing MO
  clay lot -> green blank lot in Damp Stock

Bisque MO
  green blank lot -> decorate/dry/bisque -> bisque lot in Bisque Stock

Glazing MO
  bisque lot + glaze lot(s) -> glaze firing -> finished identities in Finished Stock
```

Ware on a board remains WIP with no stock quant while its MO is in progress.
Stock reappears only after an inspection has established the accepted output.

## 3. Scope

### Included

- product-stage classification for green blanks, bisque ware, and finished ware;
- lot-tracked bisque products;
- a bisque-production session that consumes selected damp-box lots;
- a bisque result/inspection step that creates accepted bisque stock;
- a glazing session that consumes selected bisque lots and glaze lots;
- integration with shared bisque and glaze firings;
- board-content tracking across both in-progress stages;
- process-loss recording at the bisque boundary;
- printable 30 × 20 mm lot labels kept with green and bisque ware or boxes;
- end-to-end lot genealogy;
- views, menus, access rights, migration handling, and Odoo 19 tests.

### Excluded from the First Increment

- automatic generation of workshop-specific product records;
- hardcoded `Small Box` or `Medium Box` products in addon XML;
- automatic selection of glaze recipes based only on colour names;
- accounting policy changes, custom journal entries, or new costing methods;
- barcode-label report design beyond exposing stable lot identifiers;
- rewriting completed historical manufacturing orders.

Products and BoMs are tenant data. The addon supplies the reusable workflow and
validation, not a fixed ceramics catalogue.

## 4. Product and BoM Design

### 4.1 Product Stages

Add `mb_ceramics_stage` to `product.template` with these values:

- `green`: unfired reusable blank;
- `bisque`: bisque-fired intermediate ware;
- `finished`: saleable or otherwise completed ceramic ware;
- unset: clay, glaze, other consumed materials, products outside this workflow,
  or products not yet classified.

The stage is operational metadata, not a replacement for `categ_id`. Existing
categories continue to answer whether a product is clay, glaze, a ceramic piece,
or another product family.

Rules:

- green and bisque products must be storable;
- green and bisque products must use lot tracking;
- finished products may use lot or serial tracking, with serial tracking
  recommended when pieces are individually sold or inspected;
- changing a stage must not rewrite historical stock moves.

### 4.2 Bisque BoM

One normal manufacturing BoM produces one bisque product and consumes its green
blank product at one unit per unit unless the workshop explicitly configures a
different ratio.

Example tenant configuration:

```text
BISQUE-BOX-S  Small Box - Bisque
  1 x BLANK-BOX-S

BISQUE-BOX-M  Medium Box - Bisque
  1 x BLANK-BOX-M
```

The bisque BoM owns the pre-bisque operations:

1. decorate or sculpt, when applicable;
2. dry;
3. bisque firing.

The bisque firing operation must carry a compatible `mb.kiln.program` of kind
`bisque`.

### 4.3 Glazing BoM

One normal manufacturing BoM produces the finished product and consumes:

- one bisque intermediate;
- the configured glaze product quantities;
- any other material whose lot must be traceable.

Its operations are:

1. glaze;
2. glaze firing;
3. final inspection.

The glaze firing operation must carry a compatible programme of kind `glaze`.

### 4.4 Product Mapping

Do not add a single hardcoded next-product field that assumes every green blank
has exactly one possible decoration or final article. The selected BoM is the
authoritative mapping between input and output products.

The UI may suggest eligible BoMs by stage and component product, but it must
require an unambiguous user choice when several outputs are possible.

### 4.5 Cost and Valuation

This change adds stock boundaries but does not introduce a new accounting
policy. Standard Odoo MRP valuation remains authoritative. The implementation
must verify that configured costing and valuation carry the existing input cost
from clay to green, green to bisque, and bisque to finished ware, including
glaze and other consumed components at the glazing step.

Accepted output receives only the value produced by the normal MO stock moves.
Losses must not create output quants, ghost value, duplicate valuation layers,
or custom accounting entries. Deployment must compare quantities and inventory
value before and after the upgrade and run one controlled cost-rollup scenario.

## 5. Stock and Board Lifecycle

### 5.1 Green Stock

The existing throwing session remains responsible for:

- consuming a selected clay lot;
- producing one green lot per throwing output line;
- placing green stock in a configured damp location.

No change is required to the fundamental throwing genealogy.

### 5.2 Starting Bisque Production

Starting a bisque session must:

1. select a green product, green lot, and available quantity;
2. select the bisque output product and its BoM;
3. create one bisque MO per output product reference;
4. reserve and consume only the chosen green lot quantity;
5. create current `mb.board.content` for the physical ware;
6. leave no quant for those selected pieces while they are on boards;
7. retain the remaining green quantity in damp stock.

Example after selecting four small and two medium blanks:

```text
AT-WIP/DAMP-01
  BLANK-BOX-S / BLK... / 6
  BLANK-BOX-M / BLK... / 5

Ware board WIP
  Bisque MO small / 4
  Bisque MO medium / 2
```

### 5.3 Shared Bisque Firing

The existing `mb.firing` loader continues to load compatible work orders from
multiple MOs and boards into one physical kiln firing.

It must continue to enforce:

- programme kind and operation compatibility;
- kiln and company compatibility;
- complete inclusion or explicit split of board content;
- no unloading before cooling without an interruption reason.

Unloading a bisque firing completes its loaded firing work orders, but it does
not create accepted bisque stock automatically. Physical inspection determines
the quantity that survived.

`AT-WIP/BISQUE-01` is exclusively the pre-firing queue or staging location. It
must not be shown as available fired bisque stock. Accepted post-fire ware is
placed in the dedicated internal location `AT/Stock/Bisque`, which is the source
used by the Start Glazing workflow.

### 5.4 Bisque Inspection and Stock Creation

Add a `mb.bisque.inspection` transient model opened from an eligible bisque MO
after its bisque firing has been unloaded.

It records:

- selected quantity;
- accepted bisque quantity;
- loss quantity;
- loss reason and responsible operation;
- board and firing context;
- bisque destination location.

For the first increment:

```text
accepted quantity + loss quantity = selected quantity
```

On confirmation it must:

1. validate that every bisque firing work order is linked to an unloaded firing;
2. require a reason for nonzero loss;
3. prepare exact raw-material consumption;
4. when accepted quantity is positive, generate one output lot using
   `mb.bisque.lot` and assign it through Odoo 19 `lot_producing_ids`;
5. set the exact accepted `qty_producing`, including zero for a total loss;
6. complete the MO without an unintended backorder;
7. create a production-loss record when necessary;
8. close current board-content lines;
9. place accepted stock in the selected bisque location when accepted quantity
   is positive.

For a total loss, the selected green input remains consumed, the MO closes with
zero produced quantity, and the action creates a loss record but no output lot,
output quant, or label job.

One lot per MO is the default because one MO represents one output product and
one controlled batch. Do not create one serial per bisque piece unless a product
is deliberately configured for serial tracking.

### 5.5 Starting Glazing

Add a glazing session that:

1. selects a bisque product, lot, and quantity from bisque stock;
2. selects a finished product and compatible glazing BoM;
3. selects or reserves exact glaze lots required by the BoM;
4. creates one glazing MO per finished product reference;
5. consumes the selected bisque quantity into WIP;
6. assigns the WIP to one or more ware boards;
7. starts at the glazing operation rather than repeating decoration and bisque.

The current final inspection logic remains the final stock-producing action,
but its input is now a bisque lot rather than a green blank lot.

## 6. Model Changes

### 6.1 `product.template`

Add:

```text
mb_ceramics_stage: Selection
```

Add constraints for storable/tracking requirements. Domains in session views
must use this stage to prevent a finished article from appearing as a bisque
input.

### 6.2 `mrp.production`

Extend `mb_workflow_kind` to:

- `throwing`;
- `bisque`;
- `glazing`;
- `finishing` retained as a legacy value for existing records.

Add links:

```text
mb_bisque_session_id
mb_glazing_session_id
mb_bisque_inspected
```

Keep the existing `mb_finishing_session_id` and `mb_inspected` fields for
backward compatibility. Do not change the workflow kind of completed MOs.

Update the Odoo 19 `_post_inventory` genealogy preservation so already-consumed
green or bisque input move lines remain attached to the output move lines for
new bisque and glazing orders as well as legacy finishing orders.

### 6.3 Bisque Session Models

Add:

```text
mb.bisque.session
mb.bisque.session.line
```

Session fields:

- sequence-generated name;
- date;
- board;
- green source location;
- bisque destination location;
- lines;
- generated MOs;
- state and company.

Line fields:

- green product and lot;
- selected quantity;
- bisque product;
- bisque BoM;
- generated MO.

Constraints must verify product stages, lot ownership, positive quantities,
BoM output, BoM input, tracking, and company consistency.

### 6.4 Glazing Session Models

Add:

```text
mb.glazing.session
mb.glazing.session.line
```

The structure parallels the bisque session but selects a bisque lot and a
finished output.

Add `mb.glazing.material.allocation` as child rows of each glazing session line.
Each row records:

- glazing session line;
- tracked BoM component product;
- selected component lot;
- quantity and UoM;
- company;
- generated raw stock move, read-only after MO creation.

The glazing session has separate internal source locations for bisque ware and
for glaze/other materials. Non-bisque raw moves use the material location;
the selected bisque move uses the dedicated accepted-bisque location.

Allow several allocation rows for one component so a requirement can be split
across lots. Before creating or reserving anything, validate product, lot,
company, source location, UoM conversion, positive quantity, and availability.
For every tracked BoM component other than the already selected bisque input,
the allocation sum must equal the scaled BoM requirement using Odoo UoM
rounding. Missing and excess allocations are errors. The bisque product/lot is
reserved from the session line itself and must not be duplicated as a material
allocation.

Starting glazing must be one atomic transaction: create and confirm the MO,
write the selected lots and quantities to the native raw stock move lines, and
reserve those exact lots. If any selected lot is unavailable, roll back the
whole action and never substitute another lot. Untracked components may use
normal Odoo assignment. Allocation rows provide the operator input and audit
link; native stock moves and move lines remain the stock source of truth.

### 6.5 `mb.board.content`

Update the production domain and constraints to allow:

- new bisque MOs;
- new glazing MOs;
- legacy finishing MOs.

Keep board-content history immutable through remove/replace records. Splitting
for a later firing continues to use Odoo 19 `_split_productions` and must retain
the correct workflow-session links.

### 6.6 `mb.production.loss`

Allow bisque and glazing MOs in addition to legacy finishing MOs. The loss must
remain linked to the exact operation, board, and firing at which it occurred.

### 6.7 Sequences

Add `noupdate="1"` sequences:

```text
mb.bisque.session   -> BIS/%(year)s/0001
mb.bisque.lot       -> BSQ/%(year)s/00001
mb.glazing.session  -> GLZ/%(year)s/0001
```

The existing throwing, blank-lot, finishing-session, and finished-identity
sequences remain unchanged.

## 7. Odoo 19 Implementation Rules

The implementation must follow the APIs already verified by this repository:

- manufactured outputs use the Many2many `mrp.production.lot_producing_ids`;
- tracked raw material selection uses stock moves and move lines, never a custom
  copied lot field as the source of truth;
- quantities use the Odoo 19 move `quantity` and `picked` behavior;
- genealogy is preserved through output move-line `consume_line_ids`;
- MO splitting uses `_split_productions` with explicit amounts;
- completion uses `button_mark_done()` with reviewed contexts for backorders,
  consumption, and action redirection;
- available lot quantities use `_get_available_quantity(..., strict=True)`;
- business workflow code must not create or edit `stock.quant` directly;
- XML view modifiers use Odoo 19 expressions such as
  `invisible="state != 'draft'"`, not removed `attrs` syntax;
- XML action domains and contexts that need external IDs must resolve `ref()`
  server-side with `<field ... eval="..."/>`; browser Python expressions must
  never contain `ref()`.

Use `fields.Command` for relational updates and `models.Constraint` for new SQL
constraints, matching the existing v19 code style.

## 8. Green and Bisque WIP Labels

Use the shared `mb_label` addon rather than introducing a second report or
printer stack. The reusable template is `WIP lot label 30 × 20 mm` and must be
available for both green blank lots and bisque lots.

The printed label contains:

- workflow stage, prefilled as `GREEN` or `BISQUE`;
- product name;
- internal product reference;
- lot number;
- a printed quantity snapshot for that box or carrier;
- the existing durable product/lot QR identity.

The QR identifies the Odoo product and lot. Quantity is deliberately not encoded
into the durable QR because a lot can be split between boxes without changing
its identity. In the first increment the label is informational and is not an
authoritative package or container inventory record.

Add a **Print WIP label** action to:

- each recorded throwing output line;
- each accepted bisque inspection output;
- green and bisque lot forms;
- the relevant board or box workflow when it represents one product/lot line.

The workflow action opens `mb.label.print.wizard` with:

```text
default_product_id
default_lot_id
default_template_id = mb_label.template_wip_lot_30x20
default_manual_values_json = {stage, quantity}
```

Printing remains optional. A throwing or bisque transaction must not fail merely
because no printer is connected. The operator may download the exact-size PDF,
use browser print, or send it through a supported device adapter.

If a lot is split across several physical boxes, print one label per box with
that box's quantity. Split, merge, or quantity-change operations require a
reprint for each affected physical box. Reprinting creates an audited label job
but preserves the same durable QR alias for the same product and lot. If the
workshop later needs persistent box identity and authoritative contents, add
native `stock.package` tracking in a separate increment rather than treating
the printed quantity as live stock data.

Tests must verify exact 30 × 20 mm PDF geometry, the 203-DPI 240 × 160 pixel
artifact, GREEN/BISQUE prefill, product/lot QR stability, and safe reprinting.

`mb_ceramics_workflow` must depend on `mb_label` when these workflow print
actions are implemented. The label template itself lives in `mb_label` because
it is a reusable stock-lot label and not a ceramics-specific renderer.

## 9. User Interface

Add workshop menu actions in this order:

1. Record Throwing;
2. Prepare Bisque;
3. Bisque Stock;
4. Start Glazing;
5. Ware Boards;
6. Production Losses.

### Prepare Bisque Form

The form must show:

- green source and bisque destination;
- board;
- green product, lot, available quantity, selected quantity;
- bisque product and BoM;
- generated MOs and session state.

The oldest available compatible green lot may be suggested but never silently
substituted after the user selects a lot.

### Bisque Stock View

Use standard stock quants or lot views filtered to products whose stage is
`bisque` and internal bisque locations. Show:

- product;
- lot;
- available quantity;
- location;
- originating MO and firing through traceability links.

Do not build a second inventory table.

### Start Glazing Form

Show:

- bisque source, glaze/material source, and finished destination;
- board;
- bisque product, lot, available quantity, and selected quantity;
- finished product and glazing BoM;
- generated MO;
- required glaze moves and reserved lots.

### Manufacturing and Lot Views

Extend existing pages to display:

- workflow stage and session;
- source green or bisque lots;
- output bisque or finished lots;
- related board history;
- related bisque/glaze firings;
- production losses;
- clay and glaze ancestry.

## 10. Security

Add model access for the new persistent and transient models to the same
workshop/manufacturing groups currently allowed to use throwing and finishing.

Record rules and server validations must keep company data isolated. A board,
location, lot, MO, firing, and session used together must belong to the same
company or be explicitly company-neutral where Odoo permits it.

Do not rely on UI domains as security or data-integrity enforcement; repeat the
important checks in Python constraints and actions.

## 11. Migration and Backward Compatibility

### 11.1 Addon Version

Bump `mb_ceramics_workflow` from `19.0.1.0.0` to `19.0.2.0.0` because the
workflow and data model gain a new stock boundary while remaining on Odoo 19.

### 11.2 Existing Records

- completed throwing and finishing MOs remain unchanged;
- existing `mb_workflow_kind="finishing"` orders stay on the legacy path;
- in-progress legacy finishing sessions must remain operable with the current
  final inspection wizard;
- only newly created sessions use `bisque` and `glazing` kinds;
- no migration rewrites historical stock moves, lots, firings, or genealogy.

The old `Finish Blanks` menu should be renamed or limited to legacy records only
after all active legacy sessions have completed. The underlying model must not
be deleted in the first release.

### 11.3 Tenant Configuration

After upgrading `odoo_test`:

1. classify the existing blank, bisque, and finished products;
2. retain the manually created `BISQUE-BOX-S` and `BISQUE-BOX-M` products;
3. validate their BoMs instead of recreating them;
4. configure bisque and glazing operation routings;
5. configure workflow locations as follows: `AT-WIP/DAMP-01` for damp green stock,
   `AT-WIP/BISQUE-01` for the pre-firing bisque queue, and a dedicated
   `AT/Stock/Bisque` internal location for accepted post-fire bisque stock, plus
   the existing finished-goods location for accepted final ware;
6. register or validate compatible kiln programmes;
7. keep the existing simulated MOs as historical demonstration data.

This database-specific configuration belongs in a repeatable deployment script,
not in generic addon XML or a generic addon migration. The script must be
idempotent and classify only records resolved by validated unique internal
references or external IDs; it must never guess from display names.

For `odoo_test`, the explicit mappings are:

```text
BLANK-BOX-S, BLANK-BOX-M   -> green
BISQUE-BOX-S, BISQUE-BOX-M -> bisque
```

Clay and glaze products keep `mb_ceramics_stage` unset and remain identified by
their categories. Finished mappings are added explicitly only when the target
products exist. The script must fail before writing if a required reference is
missing, duplicated, belongs to the wrong company, or conflicts with its
configured BoM; partial classification is not allowed.

## 12. Test Plan

### 12.1 Model and Constraint Tests

- green and bisque products reject tracking `none`;
- session lot must belong to the selected product;
- a bisque BoM must consume the selected green product;
- a glazing BoM must consume the selected bisque product;
- output product must match the selected BoM;
- quantities must be positive and cannot exceed available lot stock;
- tracked glazing components other than the selected bisque input require
  allocations whose UoM-normalized totals exactly match the scaled BoM
  requirements;
- glaze allocation lots must match their component product and company;
- cross-company locations, boards, lots, and firings are rejected.

### 12.2 Bisque Integration Test

1. stock one clay lot;
2. throw 10 small and 7 medium blanks;
3. verify separate green lots in damp stock;
4. select 4 small and 2 medium for bisque preparation;
5. verify damp balances of 6 small and 5 medium;
6. assign the six pieces to boards;
7. load their work orders with unrelated compatible work into one bisque firing;
8. finish, cool, and unload the firing;
9. inspect with all six accepted;
10. verify 4 small and 2 medium bisque pieces in bisque stock;
11. verify each bisque lot traces through its green lot to the clay lot.

### 12.3 Bisque Loss Test

- select five pieces;
- record four accepted and one cracked during bisque firing;
- verify four enter stock, one loss is recorded, and no fifth quant exists;
- verify the loss links to the exact MO, firing, operation, and board.
- repeat with zero accepted and all five lost; verify the MO closes, selected
  green input remains consumed, and no output lot, quant, or label job exists.

### 12.4 Glazing Integration Test

- consume a selected bisque lot and an exact glaze lot;
- run a shared glaze firing;
- perform final inspection;
- verify finished serials or lots in finished stock;
- trace backward through bisque lot, green lot, clay lot, and glaze lot;
- trace forward from the clay and glaze lots to finished identities.
- split one tracked glaze requirement across two explicitly selected lots and
  verify both native raw move lines and genealogy links.

### 12.5 Split, Reservation, and Concurrency Tests

- split one board for a later firing and preserve quantities/session links;
- prevent two sessions from consuming the same available lot quantity;
- handle partial reservation without silently switching lots;
- reject missing, insufficient, or excess glaze allocations atomically;
- race two transactions for the same glaze lot and allow only the valid
  reservation to commit;
- rerunning an action after success must not create duplicate MOs or output lots;
- a failed action must roll back the entire session transaction.

### 12.6 Cost and Valuation Tests

- verify standard MO valuation rolls clay cost into green, green into accepted
  bisque, and bisque plus glaze into finished output;
- verify partial and total bisque loss create no output quant or ghost valuation;
- verify inspection does not duplicate valuation layers or post custom entries;
- compare product quantities and inventory values before and after module
  upgrade with no business transactions between snapshots.

### 12.7 Odoo 19 Regression Tests

- `lot_producing_ids` produces correct tracked output move lines;
- exact raw move quantities and lots survive `button_mark_done`;
- `consume_line_ids` retains genealogy for inputs consumed at session start;
- no unwanted backorder or redirection action remains after inspection;
- list/form views load without client expression errors;
- module installs on a fresh database and upgrades an existing v19 database.

## 13. Implementation Sequence

### Phase 1: Data Model

1. add product stages and constraints;
2. extend MO workflow kinds and session links;
3. add bisque/glazing session models and sequences;
4. update board-content and loss domains/constraints;
5. add security access.

### Phase 2: Bisque Workflow

1. implement green-lot selection and exact consumption;
2. create bisque MOs and board content;
3. integrate bisque work orders with shared firings;
4. implement bisque inspection, losses, output lots, and stock placement;
5. add bisque views and menus;
6. complete bisque-specific tests.

### Phase 3: Glazing Workflow

1. implement bisque-lot selection;
2. create glazing MOs and exact glaze-lot reservation;
3. add allocation rows and validate exact scaled component totals;
4. adapt final inspection and genealogy;
5. add glazing views and menus;
6. complete end-to-end tests, including multi-lot and concurrent reservation.

### Phase 4: Compatibility and Deployment

1. keep and test the legacy finishing path;
2. add database-specific classification/configuration script;
3. run fresh-install and upgrade tests;
4. deploy to `odoo_test` from a verified backup;
5. repeat the complete physical workflow acceptance test.

## 14. Deployment Procedure for `odoo_test`

1. create and verify a PostgreSQL custom-format backup;
2. run addon unit and integration tests in an isolated test database;
3. upgrade with `-u mb_ceramics_workflow` under Odoo 19;
4. restart the web process so its registry loads the new models and views;
5. confirm `/web/health` passes;
6. run the explicit configuration script and validate the two bisque BoMs;
7. verify `AT-WIP/BISQUE-01` is pre-firing only and accepted stock resolves to
   `AT/Stock/Bisque`;
8. verify current green and bisque quants and inventory values are unchanged;
9. execute a new throwing-to-bisque-to-glazing simulation;
10. inspect traceability from a finished identity back to clay and glaze lots;
11. retain the backup until acceptance is complete.

## 15. Acceptance Criteria

The change is complete when all of the following are true:

- bisque ware appears as standard Odoo stock by product, lot, quantity, and
  internal location;
- bisque stock is created only after an unloaded bisque firing and recorded
  inspection;
- losses do not enter bisque stock and retain their operational context;
- glazing consumes a specifically selected bisque lot and glaze lot quantities;
- tracked glaze allocations exactly match scaled BoM demand and never silently
  substitute a different lot;
- damp, bisque, and finished balances reconcile after partial selections;
- standard Odoo valuation reconciles through all three manufacturing stages;
- shared kiln loads continue to support work from several MOs and boards;
- native Odoo traceability links finished output to bisque, green, clay, and
  glaze lots;
- green and bisque output lots can print an exact 30 × 20 mm WIP label with
  stage, quantity snapshot, product, lot, and durable QR identity;
- legacy in-progress finishing orders can still be completed;
- the addon installs and upgrades cleanly on Odoo 19;
- no workflow action modifies `stock.quant` directly;
- the full automated test suite and the `odoo_test` acceptance scenario pass.

## 16. Recommended First Deliverable

Implement Phase 1 and Phase 2 first. That delivers the requested bisque stock
boundary without destabilizing final glazing. Keep the current legacy finishing
path available during this increment. After bisque stock and genealogy are
accepted in `odoo_test`, implement the glazing session and retire the ambiguous
legacy `Finish Blanks` entry in a later compatible release.

## 17. Exact Addon File Change Map

The implementation should use this file layout so ownership stays clear and the
existing models do not become monolithic.

### `mb_ceramics_workflow`

Modify:

```text
addons/mb_ceramics_workflow/__manifest__.py
addons/mb_ceramics_workflow/models/__init__.py
addons/mb_ceramics_workflow/models/mrp_production.py
addons/mb_ceramics_workflow/models/mb_board_content.py
addons/mb_ceramics_workflow/models/mb_production_loss.py
addons/mb_ceramics_workflow/wizards/__init__.py
addons/mb_ceramics_workflow/views/mb_ceramics_workflow_menus.xml
addons/mb_ceramics_workflow/views/mrp_production_views.xml
addons/mb_ceramics_workflow/views/stock_lot_views.xml
addons/mb_ceramics_workflow/security/ir.model.access.csv
addons/mb_ceramics_workflow/data/mb_ceramics_workflow_data.xml
addons/mb_ceramics_workflow/tests/test_ceramics_workflow.py
```

Add:

```text
addons/mb_ceramics_workflow/models/product_template.py
addons/mb_ceramics_workflow/models/mb_bisque_session.py
addons/mb_ceramics_workflow/models/mb_glazing_session.py
addons/mb_ceramics_workflow/models/mb_glazing_material_allocation.py
addons/mb_ceramics_workflow/wizards/mb_bisque_inspection.py
addons/mb_ceramics_workflow/wizards/mb_bisque_inspection_views.xml
addons/mb_ceramics_workflow/views/mb_bisque_session_views.xml
addons/mb_ceramics_workflow/views/mb_glazing_session_views.xml
scripts/configure_bisque_workflow.py
```

Manifest changes:

- bump version to `19.0.2.0.0`;
- add `mb_label` to dependencies;
- load the new security, data, wizard, and view files in dependency order;
- keep `mb_workshop_base`, `mb_ceramics_firing`, `mrp`, and `stock`.

### `mb_label`

The label prerequisite is already implemented in version `19.0.1.1.0`:

```text
mb_label.template_wip_lot_30x20
```

It provides the shared 30 × 20 mm template for both green and bisque lots. The
ceramics addon should call it and prefill its manual `stage` and `quantity`
bindings; it should not duplicate the template or renderer.

## 18. Action Contracts and Transaction Boundaries

Every user action must be atomic. If one output line fails, the action must not
leave completed MOs, consumed stock, lots, or board content for earlier lines in
the same uncommitted request.

### Start Bisque

Input contract:

```text
green product + green lot + quantity
bisque output product + compatible BoM
source location + bisque destination
board + company
```

Successful result:

```text
one confirmed bisque MO per output line
selected green quantity consumed into WIP
current board-content line
session state = progress
```

Idempotency rule: calling the action again on a non-draft session returns without
creating another MO. Each line stores its generated `production_id` and rejects
a second different production.

### Confirm Bisque Inspection

Input contract:

```text
eligible bisque MO
accepted quantity + loss quantity = selected quantity
unloaded bisque firing
destination location
loss reason when required
```

Successful result:

```text
positive accepted output assigned to one bisque lot
MO completed
accepted quant in AT/Stock/Bisque when accepted quantity is positive
loss record when applicable
board content closed
print-label action available only when an output lot exists
```

For zero accepted quantity, completing the MO consumes the selected input and
records the total loss but creates no output lot, quant, or label job.

Idempotency rule: `mb_bisque_inspected` prevents a second inspection. The
generated lot is stored on the MO through native output moves and
`lot_producing_ids`.

### Start Glazing

Input contract:

```text
bisque product + bisque lot + quantity
finished product + compatible BoM
exact glaze lot reservations
source and finished locations
board + company
```

Successful result:

```text
one glazing MO per output line
selected bisque quantity consumed into WIP
exact glaze moves reserved by lot
current board-content line
session state = progress
```

Before MO creation, each tracked component other than the selected bisque input
must have allocation rows equal to its scaled BoM requirement. The bisque lot
comes from the session line. On success all exact product/lot/quantity
selections are represented by native raw move lines. Missing stock, a changed
reservation, or concurrent consumption rolls back the whole action; automatic
lot substitution is forbidden.

The final inspection remains responsible for first-quality, seconds, loss, and
finished identities.

## 19. Label Workflow Details

Labels are attached to the damp box, storage box, board paperwork, or bisque
container. They are never expected to pass through the kiln.

### Green Blank Label

After a throwing line completes, show **Print WIP label** beside its generated
blank lot. Prefill:

```json
{"stage": "GREEN", "quantity": "10"}
```

The label subject is the green product and generated blank lot. If the batch is
split into two physical boxes, the operator prints two labels with the quantity
in each box while retaining the same product/lot QR identity. Those quantities
are print-time snapshots; split, merge, or quantity changes require reprinting.

### Bisque Label

After bisque inspection, show **Print WIP label** for the accepted output lot.
Prefill:

```json
{"stage": "BISQUE", "quantity": "4"}
```

Do not offer a label for loss quantity. If accepted quantity is zero, no output
lot and no label job are created.

### Label Action Helper

Implement one reusable helper on `stock.lot` or an abstract workflow mixin that
returns the existing `mb.label.print.wizard` action with:

```python
{
    "default_product_id": lot.product_id.id,
    "default_lot_id": lot.id,
    "default_template_id": env.ref(
        "mb_label.template_wip_lot_30x20"
    ).id,
    "default_manual_values_json": {
        "stage": stage,
        "quantity": formatted_quantity,
    },
}
```

Use the product UoM rounding when formatting quantity. Do not use locale-formatted
text as a database identity or QR component.

## 20. Upgrade, Rollback, and Operational Safety

### Before Upgrade

- stop creating new legacy finishing sessions during the maintenance window;
- record all currently active sessions and MOs;
- create a verified custom-format PostgreSQL backup;
- record current stock totals by product, lot, and internal location;
- run `git diff --check` and the addon tests against the exact deployment tree.

### Upgrade

1. upgrade `mb_label` first and verify the WIP template external ID;
2. upgrade `mb_ceramics_workflow`;
3. restart Odoo to refresh the web registry;
4. run `scripts/configure_bisque_workflow.py` with the reviewed database-specific
   mapping and require its validation phase to pass before it writes;
5. compare stock totals with the pre-upgrade snapshot;
6. complete one controlled acceptance batch.

### Rollback

Code rollback alone is unsafe after new bisque/glazing transactions exist because
the older registry does not understand their workflow values and session links.

If acceptance fails before new workflow transactions are entered:

1. restore the previous addon tree;
2. restore the verified pre-upgrade database backup;
3. restart Odoo;
4. confirm stock totals and health.

If real transactions have already been entered, do not delete them or downgrade
in place. Freeze new activity, preserve the database, diagnose forward, and use
the backup only through an explicit reconciliation decision.

## 21. Delivery Checklist

### Design and Models

- [ ] Product stages exist with server-side constraints.
- [ ] Bisque and glazing workflow kinds coexist with legacy finishing.
- [ ] New session models and sequences are installed.
- [ ] Boards and losses accept the correct new MO types.
- [ ] No tenant product is hardcoded in generic addon data.
- [ ] Tenant classification is explicit, idempotent, and fails on missing or
      duplicate internal references.
- [ ] Clay and glaze products keep workflow stage unset.
- [ ] Standard Odoo valuation reconciles across green, bisque, and finished MOs.

### Bisque Workflow

- [ ] Green lots can be partially selected from damp stock.
- [ ] Selected quantities become board WIP with no duplicate quant.
- [ ] Shared bisque firings work across MOs and boards.
- [ ] Inspection creates only accepted bisque stock.
- [ ] The pre-firing queue and accepted bisque stock use different locations.
- [ ] A total-loss inspection creates no output lot, quant, or label.
- [ ] Bisque lots trace to green and clay lots.

### Glazing Workflow

- [ ] Glazing consumes a selected bisque lot.
- [ ] Exact glaze lots are reserved and consumed.
- [ ] Multi-lot allocations exactly match scaled tracked-component requirements.
- [ ] Reservation failure rolls back without substituting another glaze lot.
- [ ] Shared glaze firings still work.
- [ ] Final inspection creates finished identities, seconds, and losses correctly.
- [ ] Finished output traces to bisque, green, clay, and glaze lots.

### Labels

- [ ] Green output lines open the 30 × 20 mm WIP label with GREEN and quantity.
- [ ] Bisque inspection opens the same template with BISQUE and accepted quantity.
- [ ] Labels can print by PDF, browser, or supported thermal device.
- [ ] Reprints retain the durable product/lot QR alias.
- [ ] Split boxes can print different quantities without changing lot identity.
- [ ] Label quantities are treated as snapshots and affected boxes are reprinted
      after split, merge, or quantity changes.

### Odoo 19 Quality Gates

- [ ] Fresh install succeeds.
- [ ] Upgrade from `19.0.1.0.0` succeeds.
- [ ] Python, XML, access, and test files load without warnings introduced by the change.
- [ ] Automated model, integration, firing, label, and genealogy tests pass.
- [ ] Web actions open without client expression errors.
- [ ] `/web/health` passes after restart.
- [ ] No business action writes directly to `stock.quant`.

### `odoo_test` Acceptance Batch

- [ ] Start with the existing PRAI clay lot.
- [ ] Throw 10 small and 7 medium green blanks.
- [ ] Print both green lot labels.
- [ ] Take 4 small and 2 medium into bisque WIP.
- [ ] Confirm damp balances are 6 small and 5 medium.
- [ ] Run and unload a shared bisque firing.
- [ ] Inspect and create 4 small and 2 medium bisque stock.
- [ ] Print both bisque lot labels.
- [ ] Glaze selected bisque pieces using a recorded AMACO glaze lot.
- [ ] Run and unload the glaze firing.
- [ ] Inspect final pieces and verify complete backward genealogy.

The plan is complete when this checklist can be implemented without requiring a
new architectural decision. Any later product naming, label artwork, or default
location choice is tenant configuration and does not change the workflow model.

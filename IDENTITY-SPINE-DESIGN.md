# Identity spine: lots only where they earn their place

- Status: implemented as `addons/mb_workshop_base` and
  `addons/mb_ceramics_firing`; both install clean on Odoo 19 Community with
  11 passing tests
- Date: 6 August 2026
- Scope: Increment 1 of [POC-PLAN.md](POC-PLAN.md), plus the label and POS
  surfaces that depend on it
- Supersedes the plan to port OCA `mrp_restrict_lot` and
  `mrp_lot_number_propagation`

## 1. The constraint that shapes this

Food-contact ware needs lot traceability. Everything else does not.

That single sentence removes most of the work previously scoped here. It is
also, as it happens, already Odoo's native switch:

```python
# stock/models/product.py:844  (Odoo 19 Community)
tracking = fields.Selection([
    ('serial', 'By Unique Serial Number'),
    ('lot',    'By Lots'),
    ('none',   'By Quantity')], default='none', ...)
```

So the tracking mechanism is not ours to build. What is ours is the *reason*
for the setting, the compliance payload that hangs off a tracked lot, and the
gate that refuses to finish a food-contact firing without it.

**Assumption, stated rather than asked:** the relevant regime is EU — framework
Regulation 1935/2004 (Article 17 traceability, declaration of compliance) and
Directive 84/500/EEC on ceramic articles, which sets lead and cadmium migration
limits. This follows from the French localisation already committed to in
POC-PLAN. The migration limits themselves vary by article geometry (non-fillable,
fillable, cookware and large containers), so section 4 keeps them as data rather
than constants. Which of those apply to this catalogue is settled in section 11.1.

**A note on the word "category."** The Directive calls its three geometry classes
"categories", but that word is already spoken for twice over in this system, so
the field is named `mb_migration_limit_class` instead. Three distinct things:

| Concept | Where it lives | Example |
| --- | --- | --- |
| Product category — merchandising and accounting | Odoo `categ_id`, `product.category` | `ceramics_material`, `Sculpture` |
| Range | the existing export's `Range` column | `raw_material` |
| Migration limit class — 84/500/EEC geometry | `mb_migration_limit_class` | `cat2` |

The first is the one a user means by "category" in the interface. The third is a
regulatory property that happens to share the word and nothing else, and naming
it `mb_article_category` — as an earlier draft did — invited exactly the
confusion this table exists to prevent.

## 2. Tracking is driven by food contact, and nothing else

The earlier plan treated every piece as needing a unique identity. It does not.

| Class | `tracking` | QR resolves to |
| --- | --- | --- |
| Food contact | `lot` | `stock.lot` |
| Everything else | `none` | `product.product` |

An intermediate draft added a `serial` column for uniquely priced pieces. That is
withdrawn. **A piece with its own price gets its own SKU** (decided 6 August 2026,
section 11.3), so uniqueness is expressed in the product catalogue rather than in
the tracking layer, and per-piece identity for commercial reasons disappears as a
requirement.

The second row is the important one. A decorative piece gets a QR that resolves
to the *product*, not to a lot — there is no lot to resolve to, and inventing one
to satisfy a uniform model would mean carrying regulatory machinery for ware that
is not regulated. Since a uniquely priced piece is already its own product, that
QR is as specific as a serial would have been.

This makes the Increment 1 gate — "old/new QR aliases resolve uniquely" — a
statement about a resolver that returns one of two record types, not one.

Lots exist only for food-contact ware, and are pre-assigned at kiln loading
(section 5) rather than created at forming, because the maker does not mark the
clay.

## 3. Why propagation is no longer needed

`mrp_lot_number_propagation` (578 production LOC, a rewrite rather than a port
under Odoo 19) exists to make a finished product reuse a component's serial
number. Its value here was continuity: a piece labelled at throwing keeps its
number after firing.

Under the constraint above that value largely evaporates:

- Food-contact ware is tracked **by lot**, and a lot is naturally a kiln load or
  a glaze batch — formed before the pieces are finished. There is nothing to
  propagate; the lot is assigned once and stays.
- "Which glaze went into this piece" is not propagation. Odoo already records it
  in `mrp.production.move_raw_ids.move_line_ids.lot_id` and exposes it through
  native traceability. Section 4 derives it rather than storing it again.
- Decorative ware is untracked, so there is no number to carry.

What survives is *pre-assignment*: knowing the lot from kiln loading rather than
from MO completion, so the lot is already available when the load comes out of
cooling and labels are printed (section 9.6). That was `mrp_restrict_lot`'s job,
and against Odoo 19's Many2many it is about ten lines (section 5).

## 4. Models

Written against Odoo 19 Community. No Enterprise dependency, no OCA dependency,
therefore no AGPL question (see section 7).

### 4.1 Product: declare intent, derive the setting

```python
class ProductTemplate(models.Model):
    _inherit = "product.template"

    mb_food_contact = fields.Boolean(
        string="Food contact",
        help="Article intended to come into contact with foodstuffs. "
             "Forces lot or serial tracking and requires a declaration "
             "of compliance before sale.",
    )
    # No material-type field. mb_catalogue_sync already maps the catalogue's
    # families onto product.category, and states the reason: a second taxonomy
    # disagrees with the first the moment anyone edits either. A glaze is
    # identified by its category.
    mb_migration_limit_class = fields.Selection(
        [("cat1", "Non-fillable, or fillable with internal depth <= 25 mm"),
         ("cat2", "Other fillable articles"),
         ("cat3", "Cooking ware; storage vessels over 3 litres")],
        help="Determines which migration limits apply (84/500/EEC). "
             "Only meaningful for food-contact articles; 84/500/EEC does "
             "not reach decorative ware.",
    )
    mb_tableware_form = fields.Boolean(
        string="Tableware form",
        help="Shaped like an article for food use. Decorative ware in "
             "tableware form needs the distinction to reach the label.",
    )

    @api.constrains("mb_food_contact", "mb_migration_limit_class")
    def _check_migration_limit_class_scope(self):
        for tmpl in self:
            if tmpl.mb_migration_limit_class and not tmpl.mb_food_contact:
                raise ValidationError(_(
                    "%s is not a food-contact article, so it has no "
                    "84/500/EEC category.", tmpl.display_name))

    @api.onchange("mb_food_contact")
    def _onchange_mb_food_contact(self):
        if self.mb_food_contact and self.tracking == "none":
            self.tracking = "lot"

    @api.constrains("mb_food_contact", "tracking")
    def _check_food_contact_tracking(self):
        for tmpl in self:
            if tmpl.mb_food_contact and tmpl.tracking == "none":
                raise ValidationError(_(
                    "%s is marked as food contact and must be tracked by "
                    "lot or serial number.", tmpl.display_name))
```

The onchange sets a sensible default; the constraint is what actually holds,
including for imports and API writes that bypass onchange.

### 4.2 Lot: compliance payload, glaze link derived

```python
class StockLot(models.Model):
    _inherit = "stock.lot"

    mb_food_contact = fields.Boolean(
        related="product_id.mb_food_contact", store=True)
    mb_firing_id = fields.Many2one("mb.firing", string="Firing")
    mb_glaze_lot_ids = fields.Many2many(
        "stock.lot", compute="_compute_mb_glaze_lot_ids",
        string="Glaze lots consumed")
    mb_migration_passed = fields.Boolean(
        compute="_compute_mb_migration_passed", store=True)

    def _compute_mb_glaze_lot_ids(self):
        """Derive from native traceability rather than propagating numbers."""
        productions = self.env["mrp.production"].search(
            [("lot_producing_ids", "in", self.ids)])
        by_lot = defaultdict(lambda: self.env["stock.lot"])
        for prod in productions:
            glazes = prod._mb_consumed_glaze_lots()
            for lot in prod.lot_producing_ids:
                by_lot[lot.id] |= glazes
        for lot in self:
            lot.mb_glaze_lot_ids = by_lot.get(lot.id, self.env["stock.lot"])
```

`mb_glaze_lot_ids` is deliberately **not** stored. It is a view onto the move
lines Odoo already maintains; storing it would create a second source of truth
for the one fact regulators care about.

### 4.3 Migration test, held against the glaze lot

The test belongs to the glaze, not to every piece glazed with it. One test
result covers every article made from that glaze lot.

```python
class MbMigrationTest(models.Model):
    _name = "mb.migration.test"
    _description = "Lead and cadmium migration test (84/500/EEC)"

    lot_id = fields.Many2one(
        "stock.lot", required=True, ondelete="restrict",
        # Glaze lots, identified by mb_catalogue_sync's categories.
        )
    test_date = fields.Date(required=True)
    laboratory = fields.Char()
    migration_limit_class = fields.Selection(
        [("non_fillable", "Non-fillable"), ("fillable", "Fillable"),
         ("cookware", "Cookware / large container")], required=True)
    lead_result = fields.Float("Lead migration")
    cadmium_result = fields.Float("Cadmium migration")
    passed = fields.Boolean(required=True)
    report_ids = fields.Many2many("ir.attachment", string="Laboratory report")
```

`passed` is recorded, not computed. The laboratory issues the verdict against
the limits in force at test date; deriving it from a limits table we maintain
would put us in the position of overruling a lab report when the table drifts.
The `migration_limit_class` and result figures are kept so the verdict is auditable.

## 5. Pre-assignment: the whole of `mrp_restrict_lot`, adapted

Odoo 19 changed `mrp.production.lot_producing_id` (Many2one) to
`lot_producing_ids` (Many2many, `mrp_production.py:120`). That is what made the
OCA module a rewrite. Against the Many2many it is short:

```python
class MrpProduction(models.Model):
    _inherit = "mrp.production"

    def mb_assign_lot(self, lot):
        """Pin the lot at kiln loading, so it exists before cooling ends."""
        self.ensure_one()
        if lot.product_id != self.product_id:
            raise UserError(_("Lot %s does not belong to %s.",
                              lot.name, self.product_id.display_name))
        if lot not in self.lot_producing_ids:
            self.lot_producing_ids = [Command.link(lot.id)]
        return lot
```

## 6. The gate

```python
    def _mb_check_food_contact(self):
        for prod in self:
            if not prod.product_id.mb_food_contact:
                continue
            if not prod.lot_producing_ids:
                raise UserError(_(
                    "%s is food contact and needs a lot number before "
                    "it can be marked done.", prod.name))
            glazes = prod._mb_consumed_glaze_lots()
            untested = glazes.filtered(lambda l: not l.mb_migration_passed)
            if untested:
                raise UserError(_(
                    "Glaze lots without a passing migration test: %s",
                    ", ".join(untested.mapped("name"))))

    def button_mark_done(self):
        self._mb_check_food_contact()
        return super().button_mark_done()
```

`button_mark_done` is confirmed present at `mrp_production.py:2214` in Odoo 19.
Note that the OCA modules also override `_action_done`; no such method was found
on `mrp.production` in 19, so it is not hooked here.

## 7. What this removes from the plan

| Previously scoped | Now |
| --- | --- |
| Port `mrp_lot_number_propagation` (578 LOC, rewrite) | Dropped. Native traceability answers the question. |
| Port `mrp_restrict_lot` (~30 LOC, rewrite) | Absorbed into section 5, ~10 lines. |
| Port `mrp_lot_production_date` | Already dropped; dependency last existed on 17.0. |
| Per-piece identity for all ware | Only food contact and one-off artwork. |

It also removes the AGPL-3 question from Increment 1 entirely. Every OCA module
on this path was AGPL-3; nothing above depends on any of them, so `mb_workshop_base`
stays free of the network-copyleft decision. That decision still has to be made
for `mrp_bom_version` and `mrp_workorder_blocking_time`, which remain genuine
gaps — but it no longer gates the identity spine.

## 8. Open

1. ~~Which article categories do you actually produce?~~ Answered from the
   6 August 2026 stock export: categories 1 and 2 only, nothing in category 3.
   See section 11.1. The enum keeps all three because it mirrors the Directive,
   not our catalogue.
2. ~~Is a piece ever labelled before the kiln load is formed?~~ Settled in
   section 9. One decision is handed back to you there: the bisqueware fork
   in 9.4.
3. ~~Does `mb.firing` own the kiln load, or does `mrp.production`?~~ Settled in
   section 10: `mb.firing` owns it, because `mrp.workorder.production_id` is
   required and a load routinely spans several manufacturing orders.

Nothing in this document is now open. What remains before scaffolding are two
decisions rather than questions — the per-piece pricing proposal in section 11.4,
and the prefix split for `BRM` and `BTV` in section 11.6.

## 9. Greenware: identity before the first firing

### 9.1 The question is settled by physics, not preference

No adhesive label survives a kiln. Bisque runs around 1000 °C and glaze around
1250 °C; paper, adhesive and plastic are gone long before either. A barcode or
QR code applied to greenware cannot reach the finished piece.

So section 8's open question does not have a yes/no answer about workflow
preference. It has a physical answer: **identity before firing is borne either
by a mark in the clay or by a carrier, never by a printed label on the piece.**

### 9.2 Three mechanisms, and where each belongs

| Mechanism | Survives firing | Use for |
| --- | --- | --- |
| Mark in the clay — stamp, incised number, underglaze pencil | Yes | One-off artwork the maker already signs and numbers |
| Carrier — ware board, batt, kiln shelf | N/A, carrier is not fired away | Batch production ware |
| Positional — kiln map, shelf position | N/A | Falls out of carrier nesting; no extra model |

The middle row is how batch work actually moves through a workshop. Operators
scan the board, not the pieces.

### 9.3 Carrier identity is already native in Odoo 19

Odoo 19 renamed the model to `stock.package` (`stock/models/stock_package.py:18`)
and carries exactly the semantics a ware board needs:

- `stock.package.type.package_use` is `disposable` or `reusable`. The help text
  for `reusable` reads: totes, emptied afterwards to be reused, and scanning one
  in the barcode application adds the products it contains. That is a ware board.
- `parent_package_id` / `child_package_ids` give nesting, so **board → shelf →
  kiln load** is the native hierarchy rather than three models of ours.

The gap is that packages flow through pickings, not manufacturing:
`mrp.production` has no package field in Odoo 19. The bridge is small.

```python
class MrpProduction(models.Model):
    _inherit = "mrp.production"

    mb_carrier_ids = fields.Many2many(
        "stock.package", string="Ware boards",
        domain="[('package_type_id.package_use', '=', 'reusable')]",
        help="Boards and shelves carrying this load. Scanned instead of "
             "the pieces, which cannot hold a label before firing.",
    )
```

Nothing else is needed. The carrier is not the product and is not tracked
inventory — it is how an operator finds the pieces between operations.

### 9.4 Both firing topologies, supported by not encoding the choice

Both shapes must work:

- **Single** — one manufacturing order, bisque and glaze as two routing
  operations. Bisqueware never enters stock.
- **Staged** — two manufacturing orders, bisqueware a stocked intermediate.
  Supports bisquing a full load for fuel efficiency and glazing from it in
  smaller batches over the following weeks.

There is no setting for this, and there should not be one. The difference is
already expressed by the bill of materials: a multi-level BOM with a bisqueware
product *is* staged; a single BOM with two operations *is* single. Odoo supports
both natively. Adding `mb_firing_topology` would create a second, desynchronisable
statement of a fact the BOM graph already carries.

What matters is that nothing downstream branches on it, and nothing does:

| | Single | Staged |
| --- | --- | --- |
| Carrier through the process | `mb_carrier_ids` per MO | `mb_carrier_ids` per MO |
| Intermediate lot | none | bisqueware lot |
| Label trigger | cooling hold of final operation | cooling hold of final operation |
| Label subject | finished lot or product | finished lot or product |

Only the middle row differs, and it is a consequence of the BOM rather than a
branch in our code. Where the finished ware is food contact, bisqueware should
also be lot-tracked so the clay body batch stays traceable; the glaze — the
material that actually carries the migration risk — is consumed in the final
manufacturing order either way, so section 4.2 and section 6 are unaffected.

### 9.5 No incised numbers: identity is minted at labelling

The maker does not mark the clay. That removes the last reason to carry a number
through the process, and with it the last remnant of propagation:

- There is no maker-assigned serial at forming, so there is nothing to reuse
  across greenware, bisqueware and finished lots.
- A one-off artwork therefore does **not** get its serial at forming. It gets it
  when the finished piece is labelled, after the final firing.
- Sections 3 and 9.5 of earlier drafts proposed reusing a lot name across three
  products. That design is withdrawn. `mrp_lot_number_propagation` is now dead
  outright rather than dead-for-most-cases.

Through the process, identity is borne entirely by the carrier. A piece has no
individual identity until it is labelled, and that is correct: before then, no
identity could survive.

**The carrier-to-lot join is native.** `stock.quant` carries `product_id`,
`lot_id`, `package_id`, `quantity` and `location_id` together
(`stock/models/stock_quant.py:45-78`), and `stock.package.contained_quant_ids`
recurses through board → shelf → load nesting. So "what is on this board, and
which lot is it" needs no model of ours. Output is placed on a board through
`stock.move.line.result_package_id`, which already exists.

The one action we own is labelling:

```python
    def mb_label_carrier(self, carrier):
        """Scan a board after the cooling hold; mint identity and print.

        Returns the records the labels name: a lot per piece for serial
        products, one lot for lot-tracked products, the product itself
        for untracked ware.
        """
        self.ensure_one()
        subjects = self.env["stock.lot"].browse()
        for quant in carrier.contained_quant_ids:
            product = quant.product_id
            if product.tracking == "none":
                continue                      # label names the product
            if product.tracking == "lot":
                subjects |= quant.lot_id      # already assigned, section 5
            else:                             # serial: mint one per piece
                subjects |= self.env["stock.lot"].create([
                    {"product_id": product.id, "company_id": self.company_id.id}
                    for _ in range(int(quant.quantity))
                ])
        return subjects
```

`stock.lot.name` is computed with a sequence fallback in Odoo 19
(`stock_lot.py:42`), so serials created without a name self-number.

Note the asymmetry this produces, and that it is deliberate: a lot-tracked board
yields one label subject shared by every piece on it, while a serial-tracked
board yields one per piece. That is the difference between a batch of mugs and a
shelf of individual sculptures.

### 9.6 When the label actually prints

The first moment a durable label can be applied is after the final firing, once
the ware is cool enough to handle. That is not the same moment as the MO being
marked done.

It is, however, precisely what `mrp_workorder_blocking_time` models — the module
from the port review that turned out to be the most domain-relevant of the eight.
Its `blocking_stage_end` on the work order is the cooling hold. Label printing
should key off that, not off `button_mark_done`.

This makes the case for that module concrete rather than speculative: it is the
only thing on the shortlist that gives Increment 2 a defensible trigger point.
Its AGPL-3 licence is therefore a decision that has to be made after all, even
though section 7 cleared it out of the identity spine.

## 10. The kiln load belongs to `mb.firing`, not to `mrp.production`

### 10.1 Odoo's cardinality settles it

A kiln is filled because firing is expensive, so a load routinely holds ware from
several manufacturing orders — mugs from one, bowls from another, a sculpture
from a third. In the other direction a single order passes through at least two
firings, and under the staged topology of section 9.4 always does.

Firing and manufacturing order are therefore many-to-many. Odoo forbids modelling
that as a work order:

```python
# mrp/models/mrp_workorder.py:44
production_id = fields.Many2one(
    'mrp.production', 'Manufacturing Order', required=True, ...)
```

`required=True` — a work order belongs to exactly one order. A shared load cannot
be one. So the physical event needs its own record, and `mb.firing` owns it.

### 10.2 Shape

The kiln itself stays an `mrp.workcenter`, as the brewery reference established
for process stages. It gains only provider identity:

```python
class MrpWorkcenter(models.Model):
    _inherit = "mrp.workcenter"

    mb_is_kiln = fields.Boolean("Kiln")
    mb_kiln_provider = fields.Selection([("rohde_mykiln", "ROHDE myKiln")])
    mb_kiln_external_id = fields.Char(copy=False)

    _mb_kiln_external_uniq = models.Constraint(
        'unique (mb_kiln_provider, mb_kiln_external_id, company_id)',
        'A kiln may only be bound once to a given provider device.',
    )
```

Note the Odoo 19 syntax: `_sql_constraints` is gone from core entirely, replaced
by `models.Constraint` declarations (`stock/models/stock_location.py:93`). Any
port of an 18.0 module has to make this change.

```python
class MbFiring(models.Model):
    _name = "mb.firing"
    _description = "Kiln firing"
    _inherit = ["mail.thread"]

    name = fields.Char(required=True, copy=False, default="New")
    workcenter_id = fields.Many2one(
        "mrp.workcenter", string="Kiln", required=True,
        domain="[('mb_is_kiln', '=', True)]")
    kind = fields.Selection(
        [("bisque", "Bisque"), ("glaze", "Glaze"), ("other", "Other")],
        required=True)
    workorder_ids = fields.One2many("mrp.workorder", "mb_firing_id")
    mb_carrier_ids = fields.Many2many(
        "stock.package", string="Boards loaded",
        domain="[('package_type_id.package_use', '=', 'reusable')]")

    date_start = fields.Datetime()
    date_end = fields.Datetime()
    cooling_end = fields.Datetime(
        help="Earliest moment the load may be unloaded and labelled.")
    cooling_interrupted = fields.Boolean()
    interruption_reason = fields.Text()

    peak_temperature = fields.Float()
    hold_minutes = fields.Float()
    curve_attachment_id = fields.Many2one("ir.attachment", copy=False)

    provider = fields.Selection(
        [("rohde_mykiln", "ROHDE myKiln"), ("manual", "Entered manually")],
        default="manual", required=True)
    external_id = fields.Char(copy=False)

    _mb_firing_external_uniq = models.Constraint(
        'unique (provider, external_id, company_id)',
        'A provider firing may only be imported once.',
    )
```

The work order side is a single field, `mb_firing_id`, a Many2one. Each work
order — "bisque firing of MO #12" — happens in exactly one physical firing, while
one firing gathers work orders from many orders. That is the many-to-many,
expressed without a join model.

### 10.3 Carriers move here from section 9.3

Boards are loaded into a kiln, not into a manufacturing order. `mb_carrier_ids`
belongs on `mb.firing`, and the earlier placement on `mrp.production` in section
9.3 is withdrawn.

Nothing is lost by moving it. The route from a board back to an order is already
complete: board → `contained_quant_ids` → `lot_id` → the order whose
`lot_producing_ids` contains that lot. Keeping a direct link on `mrp.production`
as well would be the second source of truth that section 4.2 avoids.

### 10.4 Curve: scalars are fields, the curve is evidence

A twelve-hour firing sampled every thirty seconds is roughly 1,400 points. Stored
as rows that is a table which grows by a million rows per hundred firings and is
never queried point-by-point.

Split by use:

- **Queried and constrained** — `peak_temperature`, `hold_minutes`,
  `date_start`, `date_end`, `cooling_end`. Real fields. These are what a
  compliance question or a schedule actually asks about.
- **Evidence** — the full curve, as an `ir.attachment`. Retrieved when someone
  disputes a firing, never aggregated.

This is not only a storage argument. Peak temperature is compliance-relevant: an
under-fired glaze is a less mature glaze, and lead release rises when a glaze has
not reached maturity. Keeping peak temperature as a queryable scalar lets the
section 6 gate eventually assert against it, which an attachment could not
support.

### 10.5 Replay-safe import

Increment 4 requires the myKiln synchronisation to be replay-safe and to make no
provider writes. Both fall out of the shape above:

- **Idempotence** is the `(provider, external_id, company_id)` constraint. Import
  upserts on that key, so re-running a sync over the same window converges
  instead of duplicating.
- **No provider writes** is a property of the connector, not the model: nothing
  in `mb.firing` holds a provider mutation. `provider = 'manual'` remains valid
  for kilns with no telemetry at all, which is most kilns in most workshops.

Manual entry and imported firings are the same record type deliberately. A
workshop with one connected ROHDE and two older kilns should not have two
different firing histories.

### 10.6 This removes the last AGPL dependency

Section 9.6 argued that `mrp_workorder_blocking_time` was load-bearing, because
its `blocking_stage_end` gave Increment 2 its label trigger, and that its AGPL-3
licence therefore had to be decided after all.

Owning `mb.firing` removes that. Cooling is a property of the physical firing,
not of a work order, and `cooling_end` above is its natural home — with
`cooling_interrupted` and `interruption_reason` reproducing the only other thing
that module offered. The label trigger becomes a check on our own record:

```python
    def mb_unload(self):
        self.ensure_one()
        if self.cooling_end and self.cooling_end > fields.Datetime.now():
            raise UserError(_(
                "%s is still cooling until %s.", self.name, self.cooling_end))
        return self.mb_carrier_ids
```

So the position across the whole review is now: **no OCA module is required for
Increments 1, 2 or 4.** `mrp_bom_version` and `mrp_workorder_blocking_time`
remain genuine gaps in Odoo Community, but neither is on the critical path, and
the AGPL-3 decision can be deferred until something actually needs them.

## 11. What the live catalogue says

Read from the stock export of 6 August 2026: 50 references, 48 finished articles
and 2 raw materials.

### 11.1 Article categories: 1 and 2, none in 3

Classifying the finished articles by name against 84/500/EEC:

| Category | Present as | Count |
| --- | --- | --- |
| 1 — non-fillable, or fillable ≤ 25 mm deep | Repose Cuillère, Gratte Ail ×2 (both flat) | 3 |
| 2 — other fillable | Mug ×4, Tasse ×6, Grand Saladier | 11 |
| 3 — cooking ware, storage over 3 L | nothing | 0 |

Nothing in the catalogue is cooking ware, and no piece is a storage vessel over
three litres — a *grand saladier* is a serving bowl, which is category 2. So only
two of the three limit sets are ever needed today. The enum in section 4.1 still
carries all three, because it is the Directive's taxonomy rather than a
description of this catalogue, and truncating it would silently mis-file the
first casserole.

The food-contact subset is about 15 of 48 references. That confirms the premise
of section 1 from live data rather than assumption: **lot tracking applies to
roughly a third of the catalogue.**

Note also that the maker already draws the line explicitly — six references are
named *Plat décoratif*. Decorative ware falls outside the food-contact regime,
which is exactly why the distinction has to reach the printed label in Increment 2:
a decorative plate is shaped like tableware, and the label is the only thing that
says it is not.

### 11.2 The materials already match

The two raw materials carry `Range=raw_material`, `Category=ceramics_material`:

- `MAT-MAY-CEL-PINT` — Mayco Celadon, a commercial glaze, stock 0
- `MAT-CLAY-GRES-PRAI` — PRAI, a stoneware clay body, stock 11

Glaze and clay body — the two families the compliance gate and the clay-body
field actually need. Both already carry `Category=ceramics_material`, which is
why this design identifies materials by `categ_id` and declares no material-type
field of its own: `mb_catalogue_sync` owns that taxonomy and states plainly why a
second one would rot. The `MAT-` prefix convention carries forward unchanged.

### 11.3 Price is per piece, and the SKU carries it

The reference scheme is already doing a serial number's job. `BB-GP-0001`,
`BB-GP-0002` and `BB-GP-0003` are three *Boite Baleine*, one unit each. Eight
design groups hold more than one reference, and **in all eight the prices
differ**:

| Group | Prices |
| --- | --- |
| `SP-GP` Sculpture Poulpe | 50, 70, **1150** |
| `BB-GP` Boite Baleine | 50, 65, 80 |
| `BRM-GP` | 45, 80 |
| `BRM-GL` | 35, 45, 50 |
| `PDP-GP` Plat décoratif Poulpe | 105, 135 |
| `PDB-GP` Plat décoratif Baleine | 110, 120 |
| `BTV-GL` Boite Tortue Verte | 35, 45 |
| `TP-GP` Tasse Poulpe | 45, 50 |

Uniqueness tracks price almost perfectly. Above 70 € nothing is ever stocked in
multiples; below it genuine multiples exist — 14 anti-stress stones at 8 €, five
spoon rests at 18 €.

| Price band | References | With qty > 1 | Max qty |
| --- | ---: | ---: | ---: |
| ≤ 30 € | 6 | 5 | 14 |
| 31–70 € | 27 | 4 | 4 |
| 71–150 € | 11 | **0** | 1 |
| > 150 € | 4 | **0** | 1 |

Odoo prices per *product*: `list_price` lives on `product.template` and
`stock.lot` has no price field. An earlier draft proposed adding
`stock.lot.mb_unit_price` and teaching sale orders and the POS to prefer it.

**That proposal is withdrawn.** Decided 6 August 2026: a piece with its own price
gets its own SKU. The consequences, stated plainly because they are the cost of
the decision:

- The catalogue grows by one product record per uniquely priced piece. Today that
  is 48 records for roughly 30 designs, and it will keep growing.
- Nothing custom touches pricing. `list_price` works as Odoo intends, the POS
  needs no JavaScript, and Increment 3 reduces to scanning a product barcode.
- Per-design reporting is the thing lost, and section 11.4 restores it.

### 11.4 Per-design reporting, if it is ever wanted

One SKU per piece makes "how many Boite Baleine did I sell" unanswerable except
by parsing reference strings, which the collisions in section 11.6 show is
unsafe.

An earlier draft answered this with an `mb.design` model. **That is withdrawn,
6 August 2026.** The requirement was inferred from the SKU decision rather than
asked for, and Odoo answers it already: `product.tag` is on every template as
`product_tag_ids`, is unique by name, groups and filters natively, and carries a
`visible_to_customers` flag that puts the design on the shop front for free.
A model of ours reached the same place via a form, a menu and two access rules.

Tagging is data, so adopting it later costs nothing. A design model would only
earn its place if something began *generating* references from the design code,
and nothing does.

What does stay on the product is the clay body, because it is a material and not
a label:

```python
    mb_clay_body_id = fields.Many2one(
        comodel_name="product.product", string="Clay body")
```

A Many2one to the clay product itself rather than a code, so it joins to the
material master already present as `MAT-CLAY-GRES-PRAI`.

### 11.5 The reference scheme already encodes the whole model

The second segment is the **clay body**: `GP` is Grès PRAI, `GL` is Grès Luna.
`MAT-CLAY-GRES-PRAI` in the materials list is the same PRAI. Confirmed
6 August 2026.

Every one of the 48 finished references parses as `DESIGN-BODY-NNNN`, with no
exceptions, and the piece number restarts at 1 for each (design, body) pair with
no gaps anywhere. That is not an accident of naming — it is a three-level model
that has been maintained by hand:

| Segment | Example | Where it goes |
| --- | --- | --- |
| Design | `BA` — Boite Anémones | a `product.tag`, if wanted (11.4) |
| Clay body | `GP` — Grès PRAI | `mb_clay_body_id` → the clay product |
| Piece | `0001` | part of `default_code`; the SKU itself |

Under the SKU-per-piece decision the third segment is not a serial — it is part
of the product reference. The first two segments become the fields of section
11.4, which is what makes the reference decomposable without parsing it at query
time.

Three designs are made in both bodies — `BA`, `BRM` and `BTV`. Usage is `GP` 41,
`GL` 7. Clay body is not a price driver: *Boite Anémones* is 45 € in PRAI and
35 € in Luna, but `BTV-GL-0001` is 45 € and `BTV-GL-0002` is 35 € in the same
body. Per-piece variation dominates, which is exactly why price sits on the SKU.

### 11.6 Three data problems to fix before import

The scheme is sound; the data has drifted. Importing on product name would create
duplicates, and importing on design prefix would merge distinct designs.

**One hard collision.** `BRM` is used for two different designs:

- `BRM-GP-0001`, `BRM-GL-0001..0003` — *Boite Raie Menta*
- `BRM-GP-0002` — *Boite Requin Marteau*

Raie Menta and Requin Marteau are different animals and different designs sharing
one code. One of them needs a new prefix, and `BRM-GP-0002` is the single
reference to move.

**A second hard collision, not the typo it looked like.** `BTV` also carries two
designs, distinguished by the singular and the plural: one turtle, or several.

- `BTV-GL-0001`, `BTV-GL-0002` — *Boite Tortue Verte*, one turtle
- `BTV-GP-0001` — *Boite Tortues Verte*, more than one

Confirmed 6 August 2026. The plural in `BTL-GL-0001` *Boite Tortues Luth* is
deliberate for the same reason. So a one-letter difference in a product name is
load-bearing across this catalogue, and any import that normalises or
case-folds names will silently merge two designs. Both `BRM` and `BTV` need a
prefix split before import; three references move in total.

This also disqualifies product name as an import key. The design must be keyed on
a corrected prefix, assigned deliberately, not derived from the label text.

**Two case drifts, harmless but worth normalising.** *Boite Raie Menta* /
*Boite Raie menta*, and *Plat Décoratif Poulpe* / *Plat décoratif Poulpe*. Same
design each time; they would produce duplicate templates on a name-keyed import.

### 11.7 Decorative ware has no limit class, and that is the point

84/500/EEC applies to ceramic articles *intended to come into contact with
foodstuffs*. A *Plat décoratif* is not one, so it has no category, no migration
limits and no declaration of compliance. `mb_migration_limit_class` is left empty, and
section 4.1 now enforces that: setting a category on a non-food-contact article
raises.

The concrete assignment for the 6 August catalogue:

Settled 6 August 2026: *Coupelle* and *Boite* are trinket ware, not tableware.

| Product | Refs | Food contact | Category |
| --- | ---: | --- | --- |
| Mug ×4, Tasse ×6, Grand Saladier | 11 | yes | `cat2` |
| Repose Cuillère, Gratte Ail ×2 | 3 | yes | `cat1` |
| Boite ×17, Coupelle Oursin | 18 | **no** | *(empty)* |
| Plat décoratif ×6 | 6 | **no** | *(empty)* |
| Sculpture ×3, Lampe, Serre Livre, Vase, Porte Clé, Pierre anti-stress, Poulpe Rocking Chair, Oursin Porte Encens | 10 | no | *(empty)* |

So the food-contact set is **14 of 48 references** — under a third, and smaller
than the first estimate, which wrongly counted the *Coupelle*. Lot tracking for
regulatory reasons therefore reaches fewer articles than section 1 assumed, and
its premise holds more strongly rather than less.

`Gratte Ail` is flat, confirmed 6 August 2026, so it is `cat1` on the
non-fillable limb rather than the depth limb — no measurement needed. Every
assignment in the table above is now settled.

**Tableware form now covers more than the plates.** A *Coupelle* is a small dish
and a *Boite* is a lidded vessel; both read as food ware to a customer even
though neither is sold as such. On that reading **24 references** — plates,
coupelle and boites — carry a negative marking, against 14 carrying a positive
one. That inverts the intuition that the food-contact subset drives the label
work: more of this catalogue needs to say what it is not than what it is.

**And the boites settle the pricing question.** They are the largest group in the
catalogue, and now that they are decorative they need no traceability whatsoever
— yet 17 of the 18 are stocked one-at-a-time, and four design groups carry
differing prices for the same design:

| Group | Prices |
| --- | --- |
| `BB-GP` Boite Baleine | 50, 65, 80 |
| `BRM-GL` Boite Raie Menta | 35, 45, 50 |
| `BRM-GP` | 45, 80 |
| `BTV-GL` Boite Tortue Verte | 35, 45 |

Only one boite reference is a genuine multiple. So the largest group in the
catalogue lands in the bottom-right cell of section 2's matrix: serial-tracked
for commercial reasons, with no regulatory driver at all. Any design that ties
per-piece identity to food contact would fail on exactly the articles that
matter most here.

**Why decorative ware still reaches the label.** Commission Directive 2005/31/EC
amended 84/500/EEC to require a written declaration of compliance at marketing
stages prior to retail, and its stated rationale is the need to distinguish
ceramic articles intended for food contact from decorative articles. The
mechanism is positive: food-contact ware carries the declaration and, where its
purpose is not self-evident from its characteristics, the "for food contact"
indication or symbol under Article 15 of Regulation 1935/2004. Decorative ware
carries neither, and the absence is the distinction.

For a plate-shaped decorative article that reads as tableware, an explicit
negative marking is prudent — a customer will otherwise eat off it. That is a
recommendation rather than something confirmed as mandated; the regulation
approaches the problem from the positive side. `mb_tableware_form` in section 4.1
exists to drive it, and the label rule is:

```python
    mb_label_food_warning = fields.Boolean(
        compute="_compute_mb_label_food_warning")

    @api.depends("mb_food_contact", "mb_tableware_form")
    def _compute_mb_label_food_warning(self):
        for tmpl in self:
            tmpl.mb_label_food_warning = (
                tmpl.mb_tableware_form and not tmpl.mb_food_contact)
```

Six references — the *Plat décoratif* set — would carry it today. Confirm the
negative-marking expectation with your own compliance advice before the label
template is fixed; it is a labelling decision, not a modelling one, and the field
above holds either answer.

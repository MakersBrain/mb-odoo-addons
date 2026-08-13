# Craft platform plan

- Status: section 2 implemented; sections 3, 4 and 5 are planned work
- Related: [SPEC.md](SPEC.md), [CERAMICS-WORKFLOW-PLAN.md](CERAMICS-WORKFLOW-PLAN.md),
  [IDENTITY-SPINE-DESIGN.md](IDENTITY-SPINE-DESIGN.md)

This document covers four decisions that share one question: what in this suite
is ceramics, and what is craft. It was written after reading OCA's
`field-service` — currently 32 `fieldservice*` addons on 19.0 — against what is
in `addons/`. That count is a dated inventory, not an architectural premise.

The conclusion of that reading is short. The `mb_commercial_operations` family
already is the field-service shape: a core owning the domain nouns, one bridge
per Odoo application, optional dimensions as their own modules. Nothing there
needs changing. One module broke the shape, and it was the one called base.

`field-service` is AGPL-3 throughout, so it is a structure to read and never a
dependency. See [SPEC.md](SPEC.md#licence-boundary).

## Contents

- [1. What the reading found](#1-what-the-reading-found)
- [2. The `mb_workshop_base` split](#2-the-mb_workshop_base-split)
- [3. `mb.firing` as a batch process](#3-mbfiring-as-a-batch-process)
- [4. Planned firings](#4-planned-firings)
- [5. Four OCA modules worth reimplementing](#5-four-oca-modules-worth-reimplementing)
- [6. Sequence, and what is deliberately not done](#6-sequence-and-what-is-deliberately-not-done)

## 1. What the reading found

`fieldservice` declares its domain nouns in a core without pulling in sale,
stock, or accounting. Odoo applications arrive through bridge addons such as
`fieldservice_sale`, `fieldservice_stock`, `fieldservice_account`, and
`fieldservice_repair`. A bridge may also depend on another bridge when its
behavior crosses both seams — for example, the current 19.0 sale bridge depends
on `fieldservice_account`. The lesson is dependency direction and explicit
seams, not a rule that every bridge has exactly two dependencies.

Measured against that, the pre-split `mb_workshop_base` was 1,181 lines of
Python, XML, and CSV including tests, manifest, migrations, and localization.
More important than the count, it held four unrelated responsibilities, only
two of which were craft-neutral:

| what was in it | craft-neutral |
| --- | --- |
| Workshop menu root, `mb_calendar_continuous`, sale-selector price display | yes |
| `mb_supplier_lot_required` and its tracking constraint | yes |
| 84/500/EEC food contact, migration tests, limit class, label warning | no — ceramic tableware |
| material and finished-ware categories, `mb_clay_body_id` | no — ceramics |
| seeded work centres: throwing, handbuilding, trimming, glazing, drying | no — ceramics |

Five addons depended on it directly and three more transitively. The direct
consumers actually used:

- `mb_label` — nothing. Zero XML ID and zero Python references; its menu parents
  to `stock.menu_stock_root` and its groups are its own. A nominal dependency.
- `mb_inventory_capture` — one menu, and `mb_supplier_lot_required`.
- `mb_catalogue_sync` — the eight material category XML IDs, nothing else.
- `mb_ceramics_firing` — `mb_calendar_continuous` and the work centre seeds.

So three modules that are craft-neutral in mechanism — labels and QR, photo
inventory capture, supplier catalogue import — were chained to a ceramic
tableware compliance module. That is the coupling field-service's structure
exists to prevent, and it was the only place in the suite where it happened.

## 2. The `mb_workshop_base` split

Three modules where there was one. The boundary is dependency, not vocabulary:
a module goes below the craft line only if a leatherworker or a joiner would
install it unchanged.

```
mb_workshop_base ──────── menu spine, 24/7 calendar, supplier-lot policy,
   │                      sale-selector price. Craft-neutral.
   ├── mb_ceramics_base ── material and ware taxonomy, work centre seeds,
   │      │                clay body. The ceramics vertical's floor.
   │      └── mb_ceramics_compliance ── 84/500/EEC: migration tests, food
   │                                    contact, the mark-done gate.
   ├── mb_label            (dependency dropped entirely)
   └── mb_inventory_capture
```

### What moved

| record or field | from | to |
| --- | --- | --- |
| `mb.migration.test` and its views, access rules, record rule, menu | `mb_workshop_base` | `mb_ceramics_compliance` |
| `product.template.mb_food_contact`, `mb_migration_limit_class`, `mb_tableware_form`, `mb_label_food_warning` | `mb_workshop_base` | `mb_ceramics_compliance` |
| `stock.lot.mb_food_contact`, `mb_migration_passed`, `mb_migration_test_ids`, `mb_glaze_lot_ids` | `mb_workshop_base` | `mb_ceramics_compliance` |
| `mrp.production._mb_check_food_contact` and the `button_mark_done` gate | `mb_workshop_base` | `mb_ceramics_compliance` |
| the 8 material categories and 8 finished-ware categories | `mb_workshop_base` | `mb_ceramics_base` |
| the 7 work centres, 4 tags and 2 capacity lines | `mb_workshop_base` | `mb_ceramics_base` |
| `product.template.mb_clay_body_id` | `mb_workshop_base` | `mb_ceramics_base` |

### What stayed, and why

`mb_calendar_continuous` stays in the base. Anything unattended runs on it — a
kiln overnight, a dye bath, a lumber drier — and it is a `resource.calendar`
with no ceramic content at all.

`mb_supplier_lot_required` stays in the base. Its own help text already said it
is independent of food contact: it is a workshop declaring that a purchased
material must retain its supplier batch, which is as true of a hide or a board
as of a bag of glaze. `mb_inventory_capture` sets it, and now reaches it without
pulling in a tableware regulation.

The sale-selector price display stays. It is a product autocomplete extension.

### Menu XML IDs renamed

The three sub-menus were `menu_mb_ceramics_*` inside a module that no longer
holds anything ceramic. They are now `menu_mb_workshop_production`,
`menu_mb_workshop_stock_quality` and `menu_mb_workshop_configuration`.
`menu_mb_workshop_root` was already neutral and keeps its ID, which matters
because `scripts/configure_app_visibility.py` names it.

The root menu and its label stay craft-neutral: `mb_workshop_base` declares
"Workshop" and the shared production/stock/configuration spine. A vertical adds
its records below that spine without overwriting shared data. This lets ceramics
and a future wood vertical coexist; install order cannot rename the common app.

### Migration

One pre-migrate script performs four ordered transfers on `mb_workshop_base` at
19.0.2.0.0, following the precedent already in the tree at `19.0.1.2.0` — which
moved the material categories in from `mb_catalogue_sync` and is the reason the
same SQL shape is reused rather than invented.

1. Rename the three menu `ir_model_data` rows inside `mb_workshop_base`.
2. Hand the 16 category rows and the 13 work centre rows to `mb_ceramics_base`.
3. Hand the `mb.migration.test` model, view, action, access and rule rows to
   `mb_ceramics_compliance`.
4. Hand the `ir.model.fields` rows for every moved field to its new module.

Point 4 is the one that is not cosmetic. An `ir.model.data` row for a field
still naming `mb_workshop_base` after the Python moved would let Odoo's module
cleanup drop the column on upgrade, taking the stored `mb_migration_passed` and
`mb_label_food_warning` values with it. The transfer must happen pre-migrate,
before the loader reconciles the module's field list.

The script force-installs both successors before it moves anything. If a target
XML ID already exists and points to the same record, the redundant source ID is
removed. If it points to a different record, the migration aborts with the names
to reconcile; warning and continuing would allow end-of-load cleanup to delete
one side. Odoo-generated IDs for fields and selection values do not need manual
handover: successor reflection attaches a new ID to the same metadata record,
and cleanup then removes only the stale source ID.

A rehearsal against a copy of the development database found the hole: handing
rows to a module nobody installs orphans the same data by a longer route. A database that
had the old module had all of it, and the artisan did not opt out of
food-contact compliance — it was split away from them. So both new modules are
flipped to `to install` and Odoo's loader picks them up in the same run. A
database installing `mb_workshop_base` for the first time never runs the script
and still chooses freely.

### Verified

- 460 tests, 0 failed, 0 errors, across a fresh install of all 32 addons plus
  the four migration-conflict cases. Identical duplicate IDs collapse and
  divergent records abort, for both handovers and menu renames.
- The upgrade rehearsed on a copy of the development database: both successors
  installed themselves. Of the transfer lists, 22 of 30 base records and 16 of
  17 compliance records existed in that historical database; all existing rows
  moved. The eight later-added finished categories and the absent company rule
  were created by their successor data files. A seeded food-contact product
  kept its flag and derived `tracking`, one `categ_glaze` row and no duplicate,
  the three menus present under their new IDs, and the root menu reading
  "Workshop". Re-running
  the same upgrade is a no-op.

Per [SPEC.md](SPEC.md#migration-scripts-start-at-first-release-not-before) a
version bump is free today because no tenant database exists, but a record that
moves between modules needs a script regardless. This is that case, four times.

### Cost of doing it later

Every stored field above multiplies by tenant count once the first artisan
database exists. This is the cheapest this refactor will ever be, and it is the
whole argument for doing it now rather than when a second craft actually turns up.

## 3. `mb.firing` as a batch process

Not now. When a second craft is real.

The reusable asset in this suite is not the base — it is `mb.firing`, and it is
the model buried deepest in ceramic vocabulary. Strip the words and what is
there is: **a batch resource holding work from several manufacturing orders,
running a named programme of ramp and hold segments, with a post-process gate
that must elapse before the contents may be unloaded and labelled.**

That description is also lumber kiln-drying (a load, a schedule, a moisture
gate), vegetable tanning (a pit, a liquor schedule, a duration), a dye bath, and
flask burnout in casting. All four share the property that forced `mb.firing`
into existence: `mrp.workorder.production_id` is `required=True`, so a batch
holding ware from several orders cannot be a work order, and Odoo's work centre
capacity is per product while a real load is mixed. Nothing in OCA solves this.

### Target shape

A `mb_batch_process` module below `mb_ceramics_firing`, carrying:

| generic | today's ceramics name |
| --- | --- |
| `mb.batch.process` — load, state, `date_start`, `date_end`, `hold_end`, contents, energy, duration | `mb.firing` |
| `mb.batch.program` — declared / scheduled / measured hours, adopt buttons | `mb.kiln.program` |
| `mb.batch.program.segment` — ramp rate, target, hold | `mb.kiln.program.segment` |
| `mb.batch.resource` — the chamber, its work centre, its `maintenance.equipment`, its per-load capacity | `mb.kiln` |
| `mrp.workorder.mb_batch_id` and the load-compatibility constraint | `mb_firing_id` |

The inheritance strategy is deliberately not selected before the second craft
exists, but it must be selected before implementation or estimation. Classical
inheritance preserves one row/table and the existing API but leaves generic and
ceramic fields on the same records. Delegation (`_inherits`) creates parent rows,
foreign keys and access boundaries and therefore requires a backfill for every
existing firing, kiln, programme and segment. It also requires explicit handling
for attachments, chatter/resources, constraints, record rules, XML IDs, and
every foreign key currently targeting the ceramic models. The implementation
design must choose one schema and rehearse that migration; this is not the
section 2 XML-ID transfer repeated.

`mb_ceramics_firing` retains the ceramic facts: bisque versus glaze as a `kind`,
peak temperature, cone equivalence, and board/shelf/load package nesting.

### What must not generalise

Peak temperature is not a generic figure. It is physical firing evidence and
stays in `mb_ceramics_firing`, which remains installable without food-contact
compliance. If compliance later interprets temperature alongside a migration
test, a small optional bridge may depend on both modules; the physical evidence
does not move into the regulatory addon.

`mb.ceramics.session.mixin` generalises the same way — a work session over a set
of pieces on carriers is throwing, and equally planing, cutting or stitching —
but it has the same rule: extract on the second real case, not the first.

### Trigger

Do this when a non-ceramic craft is being built, and extract from the two
concrete cases together. Generalising from one case produces an abstraction that
fits nothing. Before coding, write the schema decision and a release-to-release
migration rehearsal with representative rows and attachments; only that evidence
can bound the extraction cost.

## 4. Planned firings

This is the real gap, and no OCA module addresses it.

`mb_ceramics_firing/models/mrp_workorder.py` refuses any work order that is not
already `ready`:

```python
if workorder.state != "ready":
    raise ValidationError(_("%(workorder)s is not ready for firing yet.", ...))
```

And `date_start` / `date_end` are stamped from `now()` by `action_start` and
`action_finish` — never set forward. Together those mean a firing can be
recorded and run but never planned. The artisan cannot say "glaze firing
Thursday night, these six orders should aim for it" and let the manufacturing
orders schedule backwards toward the slot. Everything the kiln does is
retrospective.

### Design

Split what is currently one `draft` state into intent and contents.

1. Add a `planned` state before the existing `draft` value. Relabel `draft` as
   Loading rather than changing its stored key, so existing rows and domains need
   no value migration. The normal sequence is
   `planned → loading (draft) → firing → cooling → done`; `cancel` remains the
   exceptional terminal transition from planned or loading. A planned firing has
   a kiln, a programme, a kind and a `date_planned_start`; it has no contents.
2. Derive `date_planned_end` from `program_id.firing_hours`, and the earliest
   unload from that plus the cooling hold — the same arithmetic
   `_mb_sync_group_duration` already does, run forward instead of backward.
3. Allow a work order in any pre-`ready` state to be *earmarked* for a planned
   firing, through a new `mb_firing_planned_id` distinct from `mb_firing_id`.
   Earmarking is a target, loading is a fact; keeping them as two fields means
   the existing `_mb_validate_firing` constraint stays exactly as strict about
   what physically entered the chamber. A lighter earmark constraint immediately
   checks company, kiln work centre, programme and firing kind; readiness remains
   a load-time condition.
4. Introduce `action_load` as the new `planned → draft` transition. Earmarked
   work orders that have reached `ready` move from
   `mb_firing_planned_id` to `mb_firing_id`. Ones that have not are listed and
   have their earmark cleared atomically, with a missed-load reason and message
   on both firing and manufacturing order. They may then be explicitly assigned
   to a successor firing; no terminal firing retains stale planned links.
5. Replan manufacturing toward the slot explicitly. Set the earmarked firing
   work order's planned start to `date_planned_start`, invoke Odoo's native work
   order replanning so predecessors schedule backward, and repeat whenever the
   kiln, programme or planned date changes. Conflicts are surfaced to the user;
   the plan must never silently write predecessor dates without native capacity
   checks.
6. Use the lead firing work order's native `leave_id` as the single capacity
   reservation for the shared physical load. Create or move that reservation to
   the planned window and remove fellow work-order reservations, as
   `_mb_sync_group_duration` already consolidates them after planning. Do not add
   an unrelated `resource.calendar.leaves` record: that would block the target
   work orders themselves. Changing or cancelling the firing updates or removes
   the lead reservation and replans affected orders.
7. Constrain overlap per kiln across the planned window plus cooling. This is
   the one piece of real algorithm, and OCA's `resource_booking` has the shape
   to copy from: `_check_scheduling` and `_availability_is_fitting` merge
   intervals against a `resource.calendar` in about fifty lines. Read it —
   `resource_booking` is AGPL-3 and Tecnativa's, so the idea travels and the
   code does not.

### What this is not

Not `resource.booking`. That model's unit is an appointment a partner picks from
a calendar, with portal tokens and a modification deadline. A firing is a load
with contents, a programme and a cooling tail, and it is already the right
model. The booking machinery is worth reading for its interval arithmetic and
nothing else.

## 5. Four OCA modules worth reimplementing

All four are AGPL-3, so all four are read-and-rewrite, never a dependency.
Ranked by what they would actually add here.

1. **`mrp_bom_line_formula_quantity`** (18.0). The only genuinely new idea. A
   glaze is percentages of a batch weight; an Odoo BoM line is a fixed quantity,
   so scaling a recipe today means editing every line. The module is roughly one
   field plus one compute. Reimplement in `mb_ceramics_workflow` against the
   glaze recipe specifically, where the denominator is the dry batch weight and
   water is expressed against it rather than in it.
2. **`mrp_bom_version`** (18.0). A glaze recipe is a compliance artifact: a
   migration-test verdict is meaningful only for the immutable recipe revision
   that produced the tested lot. Reimplement the full lifecycle, not just an
   approval flag: approved revisions are ORM-immutable; change creates a linked
   successor revision; predecessors become historical/withdrawn without losing
   visibility; and each manufacturing order and produced glaze lot retains the
   exact revision used. The mark-done gate validates that immutable link.
3. **`mrp_production_back_to_draft`** (currently present on 19.0). The undo an artisan
   reaches for. Small enough to rewrite locally; the care needed is
   what it does to a manufacturing order whose work orders are already in a
   firing, which is a question the OCA module never has to ask.
4. **`mrp_attachment_mgmt`** (19.0). Surfaces bill-of-materials attachments at
   every level on the work order. Partly overlapping what `mb.firing` already
   does with curve and raw attachments, but in the other direction: a firing
   sheet or a test tile photograph travelling from the recipe down to the bench.

`mrp_restrict_lot` is deliberately absent from this list.
`mb_ceramics_firing/models/mrp_production.py` already reimplements it, adapted
to Odoo 19 where `lot_producing_id` became `lot_producing_ids`, and says so.

## 6. Sequence, and what is deliberately not done

1. Section 2 — done.
2. Section 5 items 1 and 2, together. They are one subject: a recipe that scales
   and a recipe that can be approved.
3. Section 4. The largest of these and the one that changes what the workshop
   can do rather than how it is filed.
4. Section 3, only when a second craft exists.

**Not doing: field-service's granularity.** Its current 32 `fieldservice*`
addons are a cost OCA pays because field service serves many industries. This
suite has 32 addons,
a `.pot` and an `fr.po` per addon, per-addon migrations, and an active
[EN/FR translation plan](ODOO-I18N-EN-FR-TRANSLATION-PLAN.md). Every split
multiplies that surface. Field-service's dependency discipline is worth copying;
its module count is not, and section 2 adds two modules rather than eight for
that reason.

**Not doing: a design model, a material-type field, or a second taxonomy.**
Those were settled in `mb_workshop_base`'s original manifest and the reasoning
survives the split unchanged — it now lives in `mb_ceramics_base`.

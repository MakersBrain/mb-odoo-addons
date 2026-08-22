# Conventions

The Odoo 19 coding guidelines apply:
<https://www.odoo.com/documentation/19.0/contributing/development/coding_guidelines.html>

This file records only the places where a choice had to be made — because the
guideline is silent, because it conflicts with what the repository already does,
or because following it retroactively would cost more than it is worth. Anything
not listed here follows the guideline.

## Enforced by tooling, not by review

Do not argue these in review; run `make check`.

| Concern | Gate |
| --- | --- |
| Formatting | `ruff format` — the style authority |
| Import order | `ruff check --select I`, in three blocks: external, `odoo`, `odoo.addons` |
| Tab indentation, correctness lint | `ruff check` (`E4 E7 E9 F B C4 PIE W191 I`) |
| Types in `tools/` | `mypy tools` — blocking |
| Types in `addons/` | `mypy addons` — advisory only; see the mypy block in `pyproject.toml` |
| Manifests, data paths, ACLs, dependency graph, `SPEC.md` versions | `tools/check_addons.py` |

Ruff and mypy are **pinned** in both the `Makefile` and `.github/workflows/ci.yml`.
`ruff format --check` blocks CI, so an unpinned version that reflows one
expression differently would fail a branch that is green locally. Bump both
together.

## Directory names: singular

`wizard/`, `report/`, `models/`, `views/`, `data/`, `security/`, `controllers/`,
`tests/`, `static/`.

The repository used to be split — five addons had `wizards/` against one
`wizard/`, and one had `reports/` against four `report/`. Odoo 19 core settles
it: **107 `wizard/` to 13, and 75 `report/` to 1.** All six now match.

Wizards (`TransientModel`) belong in `wizard/`, report parsers (`report.*`
abstract models) in `report/` — not in `models/`, where several still sit.

## XML ids: model first for anything new

The guideline puts the model first:

```
mb_depot_sale_report_view_list      not   view_mb_depot_sale_report_list
mb_depot_sale_report_action         not   action_mb_depot_sale_report
mb_label_template_rule_company      not   rule_mb_label_template_company
```

**Use this for every new record. Do not rename existing ones.**

Most ids here still use the older prefix form — roughly 150 views, 57 actions,
42 rules. Renaming them breaks every `ref()` and any external data pointing at
them, and is only worth doing bundled with an `ir.model.data` migration. Odoo
core is itself mixed for the same reason, so there is no purity to restore.

The result is a repository with two id styles. That is the cheaper of the two
bad options, and it is deliberate.

## `__init__.py` import order is load-bearing

An addon's `__init__.py` imports submodules for the side effect of registering
models, and a model that references another at class-definition time has to be
imported after it. `I001` and `F401` are both off for these files
(`pyproject.toml`), and isort would also collapse the one-per-line form Odoo
core uses everywhere.

**Add new imports in dependency order, at the end. Do not alphabetize.**

## Odoo idioms worth stating

- Constraints are declarative: `models.Constraint(...)`, not `_sql_constraints`.
  Every one of the 41 addons is already migrated; keep it that way.
- Every new model that users access needs a row in `security/ir.model.access.csv`.
  `tools/check_addons.py` validates the header and row width of access files that
  exist; it does not discover models or prove that every model has an ACL row,
  so coverage still has to be checked in review.
- No search inside a per-record loop. Batch it into one query keyed by record.
  When batching changes a subtlety — self-exclusion, or claims made within the
  batch — say so in a comment; that is where the behaviour gets lost.
- `@api.depends` must name what the compute actually reads. Where an inverse
  relation makes that impossible, add the relation rather than working around
  it with `invalidate_recordset()` — a test that has to flush the cache by hand
  is reporting a bug, not passing.
- Translations use the lazy form: `_("… %s", value)`, never an f-string.

## Patching core

Two modules replace a function they do not own, both for security reasons:
`mb_dbfilter_gateway` (`odoo.http.db_filter`) and `mb_email_bridge`
(`socket.create_connection`, process-wide). Each carries a module docstring
explaining why no ordinary seam reaches the call sites, and what bounds the
blast radius.

**A third needs a better reason than the first two.** If you add one, document
it the same way and test the inert path — the bug in the dbfilter guard was
exactly there, in the branch nothing exercised.

## Running things

```
make check     # everything CI runs that needs no container
make format    # apply the formatter and import order in place
make test      # full suite on a fresh disposable database
make test TAGS=/mb_label          # one addon
make test TAGS=/mb_label:TestLabel.test_qr_collision
```

`make test` reinstalls onto a freshly dropped database on purpose: `-i` against
a database that already has the modules is a no-op, and the `at_install` tests
then silently do not run.

# Odoo XML relational-command inventory

Recorded for FMT-01 on 2026-09-05 with:

```sh
rg -n '\[\([0-6],\s*' addons --glob '*.xml'
```

The repository contains 51 matching XML `eval` expressions in 12 files. They are
intentional Odoo loader tuple commands and remain unchanged. `Command` is the
preferred Python API, but it is not part of the documented XML evaluation context;
mechanically rewriting these expressions would make data loading dependent on an
unproven evaluation namespace.

| File | Matches | Purpose | Decision |
| --- | ---: | --- | --- |
| `mb_ceramics_base/data/mb_workcenter_data.xml` | 7 | Add seeded work-centre tags | Keep `(4, ref(...))`; additive and upgrade-safe |
| `mb_ceramics_workflow/views/mb_board_views.xml` | 1 | Replace an action's view sequence before rebuilding it | Keep `(5, 0, 0)` plus following tuples; replacement is deliberate |
| `mb_commercial_operations/report/commercial_operation_report.xml` | 3 | Add the report access group | Keep `(4, ref(...))`; additive |
| `mb_commercial_operations/security/mb_commercial_operations_security.xml` | 18 | Add implied users/groups and rule groups | Keep `(4, ref(...))`; additive |
| `mb_commercial_operations_depot/security/mb_commercial_operations_depot_security.xml` | 4 | Configure rule groups, including one intentional global rule | Keep additive `(4, ...)` and deliberate `(5, 0, 0)` |
| `mb_commercial_operations_pos/security/mb_commercial_operations_pos_security.xml` | 1 | Add the POS group to a rule | Keep `(4, ref(...))`; additive |
| `mb_commercial_operations_stock/security/mb_commercial_operations_stock_security.xml` | 1 | Add the commercial group to a rule | Keep `(4, ref(...))`; additive |
| `mb_depot/security/mb_depot_security.xml` | 4 | Add implied users/groups and rule groups | Keep `(4, ref(...))`; additive |
| `mb_depot/views/mb_depot_menus.xml` | 1 | Make the intended menu global | Keep `(5, 0, 0)`; clearing is deliberate |
| `mb_label/security/mb_label_security.xml` | 5 | Add implied groups and initial administrative users | Keep `(4, ref(...))`; additive |
| `mb_shop_import/security/mb_shop_import_security.xml` | 3 | Add implied groups and initial administrative users | Keep `(4, ref(...))`; additive |
| `mb_webshop/security/return_security.xml` | 3 | Add sales/stock groups to return rules | Keep `(4, ref(...))`; additive |

The two clear commands were reviewed separately because they can remove existing
relations. Both encode required semantics: the workflow action rebuilds its complete
ordered view list in the same expression, and the depot menu/rule records are made
global intentionally. Repeated-upgrade and security tests cover those outcomes.

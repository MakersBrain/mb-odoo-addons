# The workshop counter

`mb_workshop_pos` ships one thing: the `pos.config` every workshop should have
had from the start.

## What it prevents

Odoo 19 registers `pos_config_kanban_view` for `pos.config`
(`point_of_sale/static/src/backend/pos_kanban_view/pos_kanban_view.js`). When
the kanban list is empty the renderer sets `show_predefined_scenarios` and paints
"Choose your store":

| card | server call | side effect |
| --- | --- | --- |
| Clothes / Furniture / Bakery | `load_onboarding_<x>_scenario` | POS categories, and demo products on a demo database |
| Restaurant / Bar | `install_pos_restaurant` first | installs `pos_restaurant` permanently |
| Retail | `load_onboarding_retail_scenario` | a plain counter, no demo data |

Every provisioned workshop has Point of Sale installed - `mb_control_bridge`
depends on it for `point_of_sale.group_pos_user` and `group_pos_manager` - and
none of them shipped a `pos.config`. So the app opened on a shop-type quiz, two
of whose answers install table management into a ceramics studio.

## How the counter is made

Not in XML data. A `pos.config` needs a sale journal, a cash journal and the
Cash, Card and Customer Account payment methods, all company-specific, none of
which exist before a chart of accounts does; `_create_journal_and_payment_methods`
raises `UserError` without a bank journal. `pos.config._mb_ensure_default_counter`
therefore delegates to Odoo's own `load_onboarding_retail_scenario(with_demo_data=False)`
- the Retail card, minus the click - which names the config after the company
and registers it under the `point_of_sale.pos_config_retail` external id.

## When it is made

A provisioned workshop is created by `odoo --init` against a database whose
company has no country yet. The French chart arrives later, when the control
plane calls `mb_control_bridge`'s `res.company._mb_bootstrap_french_accounting`.
A `post_init_hook` alone would run too early and seed nothing.

So the seam is `account.chart.template.try_loading`, which both that bootstrap
and the `l10n_fr_micro_enterprise` setup wizard go through:

```
control plane ──▶ _mb_bootstrap_french_accounting ──▶ try_loading('fr')
setup wizard  ──▶ _prepare_french_chart          ──▶ try_loading('fr')
                                                        │
                                                        ▼
                                          _mb_ensure_default_counter(company)
```

`post_init_hook` covers the other direction: a database that already has its
accounting and installs this addon afterwards.

The seed is idempotent - a company with any `pos.config` is left alone - and it
never raises. Failing to create a counter costs an artisan a shop-type screen;
aborting `try_loading` would cost them their chart of accounts.

## Existing databases

Installing the addon seeds the counter. Databases provisioned before it was
added to the `--init` set need it installed explicitly; nothing reaches back to
them on its own.

{
    "name": "MakersBrain Workshop Counter",
    "summary": "Give every workshop one Point of Sale counter, so nobody is asked what kind of shop they run.",
    "description": """
A workshop that sells its own work has a counter. It does not have a shop type.

Odoo 19 disagrees. `point_of_sale` replaces the `pos.config` kanban with
`pos_config_kanban_view`, and when that list is empty the renderer paints
"Choose your store": Clothes, Furniture, Bakery, Restaurant, Bar, Retail. Every
provisioned workshop installs Point of Sale - `mb_control_bridge` depends on it
to grant the cashier groups - and none of them ships a `pos.config`, so the
first thing an artisan sees in the POS app is a shop-type quiz. Two of those
cards call `install_pos_restaurant()`, which is `button_immediate_install()` on
`pos_restaurant`: one wrong click puts table management and a kitchen display
into a ceramics studio permanently.

The fix is one record. `get_pos_kanban_view_state` reports `has_pos_config` and
the renderer sets `show_predefined_scenarios` from `list.count === 0`, so a
single counter retires the whole screen and the app opens on the ordinary POS
list.

**The counter is created by the same code the Retail card runs.** A `pos.config`
is not a record that can be written in XML data: it needs a sale journal, a cash
journal, and the Cash, Card and Customer Account payment methods, all of them
company-specific and none of them existing before a chart of accounts does.
`load_onboarding_retail_scenario(with_demo_data=False)` builds exactly that set
and names the config after the company. Calling it is both less code and less
drift than reimplementing it.

**It is seeded when the chart of accounts arrives, not at install.** A
provisioned workshop is initialised by `--init` against a database whose company
has no country and no chart yet; the French chart is loaded afterwards, when the
control plane calls into `mb_control_bridge` and it runs `try_loading('fr')`.
A `post_init_hook` alone would therefore find no bank journal and seed nothing.
So `try_loading` is extended instead - the one seam both the control plane and
the `l10n_fr_micro_enterprise` setup wizard go through - and the install hook
covers the databases that already have their accounting.

Seeding never raises. A counter that could not be created leaves the artisan
looking at the shop-type screen, which is a cosmetic defect; an exception here
would abort loading a chart of accounts, which is not.

This is craft-neutral: a leatherworker and a joiner both sell over a counter,
and neither is a restaurant.
""",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "category": "Sales/Point of Sale",
    "author": "MakersBrain",
    "depends": [
        # pos.config, and the onboarding scenario that knows how to build one.
        "point_of_sale",
        # account.chart.template.try_loading is the seam the counter hangs on,
        # and account.journal is what it waits for. Declared rather than taken
        # through point_of_sale, because this addon calls both directly.
        "account",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
    "auto_install": False,
}

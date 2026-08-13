{
    "name": "Makersbrain Workshop Base",
    "summary": "The craft-neutral floor: menu spine, continuous calendar, supplier-lot policy, priced product selectors.",
    "description": """
What is true of a workshop before anyone says which craft it practises.

Until 19.0.2.0.0 this addon was also the ceramics vertical: food-contact
compliance, the material and ware taxonomy, `mb_clay_body_id` and the seeded
throwing and glazing work centres all lived here. They now live in
`mb_ceramics_base` and `mb_ceramics_compliance`. The reason for the split was
`mb_label`, `mb_inventory_capture` and `mb_catalogue_sync` - three addons that
are craft-neutral in mechanism and could not be installed without pulling in a
ceramic tableware regulation. `mb_label` no longer depends on this addon at all,
because it never used anything in it.

The test a module has to pass to sit here is that a leatherworker or a joiner
would install it unchanged. See CRAFT-PLATFORM-PLAN.md section 2.

**The menu spine and its label are neutral.** Production, Stock & Quality and
Configuration are the same three questions in any workshop, so they are declared
here under "Workshop". Vertical addons add entries beneath the spine without
overwriting shared data, which keeps their coexistence independent of install
order.

**The continuous calendar belongs to physics, not to ceramics.** A kiln fires
overnight, a board dries over a weekend, a dye bath holds temperature for hours
and a lumber drier runs for days. On the workshop's own nine-to-five calendar
Odoo fragments a fourteen-hour process across three days, so anything unattended
runs on `mb_calendar_continuous`. UTC deliberately: nothing on this calendar
keeps office hours, and a local timezone would only introduce a daylight-saving
discontinuity into durations that are physical and absolute.

**A supplier batch is a workshop policy, not a food policy.**
`mb_supplier_lot_required` says a purchased material must retain the supplier's
physical batch in Odoo lot traceability, which is as true of a hide or a board
as of a bag of glaze. Its own help text always said it was independent of food
contact; after the split it is independent in the dependency graph too, which is
what `mb_inventory_capture` needed.

**Prices in product selectors.** Quotation lines pick products from an
autocomplete that shows a name and no price, which is the wrong end of the
conversation for someone quoting from a bench. The active pricelist's price is
appended to the display name, through context keys so nothing else changes.
""",
    "version": "19.0.2.0.0",
    "license": "LGPL-3",
    "category": "Inventory/Inventory",
    "author": "Makersbrain",
    "depends": [
        # tracking and stock.lot, which mb_supplier_lot_required constrains.
        "stock",
        # resource.calendar, for the continuous calendar. Declared rather than
        # taken from mrp, which this addon no longer needs: the work centres
        # that used to be here are in mb_ceramics_base now.
        "resource",
        # Quotations show their active pricelist price in product selectors.
        "sale",
        # The generic product autocomplete is extended for every backend form.
        "web",
    ],
    "data": [
        "data/mb_workshop_calendar.xml",
        "views/product_template_views.xml",
        "views/sale_order_views.xml",
        "views/mb_workshop_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "mb_workshop_base/static/src/product_selector_price.js",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}

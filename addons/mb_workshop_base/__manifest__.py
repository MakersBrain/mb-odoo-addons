{
    "name": "Makersbrain Workshop Base",
    "summary": "Design identity, and the food-contact compliance an artisan ceramics catalogue needs.",
    "description": """
Two things Odoo has no opinion about, and one it has the wrong opinion about.

**Food contact is a property of the finished article.** Directive 84/500/EEC
applies to ceramic articles intended to come into contact with foodstuffs and to
nothing else, so a mug carries lead and cadmium limits and a decorative plate
carries none. Odoo's `tracking` field is the right mechanism for the traceability
that follows - see IDENTITY-SPINE-DESIGN.md section 1 - but nothing in Odoo says
*why* an article is tracked, and without the reason the setting drifts. So
`mb_food_contact` is declared and `tracking` is derived from it.

Note the boundary with `mb_ceramics_material`: that addon owns whether a *glaze*
is food-safe, which is a property of a material. This one owns whether an
*article* is intended for food, which is a property of a product for sale. A
food-safe glaze on a decorative vase is both true and irrelevant.

**No design model.** A piece with its own price gets its own product record,
which is the artisan's existing practice and keeps pricing entirely native. That
does cost the design-level question - forty-eight products cover about thirty
designs - but Odoo answers it already: `product.tag` is on every template, is
unique by name, groups and filters natively, and even carries a
`visible_to_customers` flag for the shop. A model of ours would have added a
form, a menu and two access rules to reach the same place.

**Material families are categories, not a field of ours.** `mb_catalogue_sync`
already maps the catalogue's families onto `product.category`, for the reason
stated there: a second taxonomy disagrees with the first the moment anyone edits
either. So this addon identifies a glaze by its category and declares no
material-type field.

**Work centres are seeded, not modelled.** Throwing, handbuilding, trimming,
assembly, glazing and decorating are plain `mrp.workcenter` records in
`data/mb_workcenter_data.xml`, under `noupdate="1"` so the artisan owns them
after install. A work centre is a resource you queue for, so the granularity
rule is one per contended resource and not one per craft skill.

Two consequences worth stating, because both are easy to get wrong and expensive
to unpick later. Drying is a *wait*: no resource is consumed, so it carries no
hourly cost and a capacity past anything a batch reaches, or it would put
phantom load on the shop floor and drag OEE down with hours nobody worked. And
`mb_calendar_continuous`, the 24/7 calendar defined here, is what anything
unattended runs on - a kiln fires overnight, and on the workshop's own calendar
Odoo would fragment a fourteen-hour firing across three days. `mb.kiln` in
`mb_ceramics_firing` puts every kiln work centre on it.
""",
    "version": "19.0.1.1.0",
    "license": "LGPL-3",
    "category": "Inventory/Inventory",
    "author": "Makersbrain",
    "depends": [
        # tracking, stock.lot and the quant/package joins the label surface reads.
        "stock",
        # The compliance gate runs when a manufacturing order is marked done, and
        # the glaze whose migration test is checked is a consumed component.
        "mrp",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/mb_workcenter_data.xml",
        "views/mb_migration_test_views.xml",
        "views/product_template_views.xml",
        "views/stock_lot_views.xml",
        "views/mb_workshop_menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}

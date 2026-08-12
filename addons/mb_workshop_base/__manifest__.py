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

**Material families are categories, not a field of ours.** A second taxonomy
disagrees with the first the moment anyone edits either, and Odoo already
filters, groups and reports on `categ_id` everywhere. So a glaze is identified
by its category and there is no material-type field.

The categories live here, in `data/mb_material_categories.xml`, and moved here
from `mb_catalogue_sync` in 19.0.1.2.0. They were in the importer on the
reasoning that the families came from the catalogue; they do not. A workshop
that never imports anything still buys glaze and still owes a lead-and-cadmium
migration test on the food-contact ware it makes with it. Leaving the taxonomy
in the importer made the `button_mark_done` gate below depend on having
installed a connector to a catalogue service, and its own docstring admitted it
silently checked less without one. A compliance check does not belong behind an
optional connector, so `mb_catalogue_sync` now depends on this addon and maps
onto the taxonomy rather than owning it.

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
    "version": "19.0.1.5.1",
    "license": "LGPL-3",
    "category": "Inventory/Inventory",
    "author": "Makersbrain",
    "depends": [
        # tracking, stock.lot and the quant/package joins the label surface reads.
        "stock",
        # The compliance gate runs when a manufacturing order is marked done, and
        # the glaze whose migration test is checked is a consumed component.
        "mrp",
        # Quotations show their active pricelist price in product selectors.
        "sale",
        # The generic product autocomplete is extended for every backend form.
        "web",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/mb_workshop_security.xml",
        "data/mb_material_categories.xml",
        "data/mb_finished_product_categories.xml",
        "data/mb_workcenter_data.xml",
        "views/mb_migration_test_views.xml",
        "views/product_template_views.xml",
        "views/sale_order_views.xml",
        "views/stock_lot_views.xml",
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

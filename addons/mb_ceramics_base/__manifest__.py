{
    "name": "Makersbrain Ceramics Base",
    "summary": "The ceramics vertical's floor: material taxonomy, ware taxonomy, seeded work centres.",
    "description": """
What a ceramics workshop is configured with before anything else is installed.

This addon and `mb_workshop_base` were one module until 19.0.2.0.0. The split is
by dependency rather than by vocabulary: what a leatherworker or a joiner would
install unchanged stayed below, and what is ceramic came here. The reason was
`mb_label`, `mb_inventory_capture` and `mb_catalogue_sync` — three addons that
are craft-neutral in mechanism and were nonetheless chained to a ceramic
tableware regulation. See CRAFT-PLATFORM-PLAN.md section 2.

**Material families are categories, not a field of ours.** A second taxonomy
disagrees with the first the moment anyone edits either, and Odoo already
filters, groups and reports on `categ_id` everywhere. So a glaze is identified
by its category and there is no material-type field.

The categories reached this addon by way of `mb_workshop_base`, and
`mb_catalogue_sync` before that. They were in the importer on the reasoning that
the families came from the catalogue; they do not. A workshop that never imports
anything still buys glaze and still owes a lead-and-cadmium migration test on
the food-contact ware it makes with it, so `mb_ceramics_compliance` reads this
taxonomy to know which consumed lots need a passing test. A compliance check
does not belong behind an optional connector, and it no longer is: the importer
maps onto this taxonomy rather than owning it, and the compliance addon depends
on this one.

**No design model.** A piece with its own price gets its own product record,
which is the artisan's existing practice and keeps pricing entirely native. That
does cost the design-level question — forty-eight products cover about thirty
designs — but Odoo answers it already: `product.tag` is on every template, is
unique by name, groups and filters natively, and even carries a
`visible_to_customers` flag for the shop. A model of ours would have added a
form, a menu and two access rules to reach the same place.

**Work centres are seeded, not modelled.** Throwing, handbuilding, trimming,
assembly, glazing and decorating are plain `mrp.workcenter` records in
`data/mb_workcenter_data.xml`, under `noupdate="1"` so the artisan owns them
after install. A work centre is a resource you queue for, so the granularity
rule is one per contended resource and not one per craft skill.

Two consequences worth stating, because both are easy to get wrong and expensive
to unpick later. Drying is a *wait*: no resource is consumed, so it carries no
hourly cost and a capacity past anything a batch reaches, or it would put
phantom load on the shop floor and drag OEE down with hours nobody worked. And
anything unattended runs on `mb_workshop_base.mb_calendar_continuous` — a kiln
fires overnight, and on the workshop's own calendar Odoo would fragment a
fourteen-hour firing across three days. That calendar stayed in the base
deliberately: a dye bath and a lumber drier need it just as much, and there is
nothing ceramic about a 24/7 `resource.calendar`.

**The root menu stays neutral.** `mb_workshop_base` calls the shared spine
"Workshop". A vertical adds its own entries beneath that spine but does not
overwrite shared data: two verticals can therefore coexist without install
order deciding the app name.

**A clay body is a product, not a code.** `mb_clay_body_id` points at the
material product itself so it joins to the master catalogue, which is the same
reasoning as the categories: one taxonomy, and it is Odoo's.
""",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "category": "Inventory/Inventory",
    "author": "Makersbrain",
    "depends": [
        # The menu spine this addon renames, and the continuous calendar the
        # drying work centre runs on.
        "mb_workshop_base",
        # mrp.workcenter, its tags and its capacity lines.
        "mrp",
    ],
    "data": [
        "data/mb_material_categories.xml",
        "data/mb_finished_product_categories.xml",
        "data/mb_workcenter_data.xml",
        "views/product_template_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}

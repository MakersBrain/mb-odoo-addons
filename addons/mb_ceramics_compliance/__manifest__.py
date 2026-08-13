{
    "name": "Makersbrain Ceramics Compliance",
    "summary": "84/500/EEC food contact: the declaration, the derived tracking and the migration test.",
    "description": """
The one regulation a ceramics workshop cannot file away.

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

**This addon exists because compliance is not a base.** All of it lived in
`mb_workshop_base` until 19.0.2.0.0, which meant `mb_label`,
`mb_inventory_capture` and `mb_catalogue_sync` - none of which has any interest
in tableware - could not be installed without it. The rule the split follows is
in CRAFT-PLATFORM-PLAN.md section 2: a module sits below the craft line only if
a leatherworker would install it unchanged. Nothing here passes that test, and
nothing here should.

**The gate is at mark-done, and it reads the taxonomy.** A food-contact order
needs a lot number before it can be closed, and every glaze lot it consumed
needs a passing migration test. Which consumed lots are glaze is answered by
`mb_ceramics_base`'s product categories rather than by a material-type field of
our own, because a second taxonomy disagrees with the first the moment anyone
edits either.

That dependency runs the safe way round. The taxonomy is seed data in a module
with no connector and no service behind it, so the gate is always enforceable.
It used to run the other way - the categories were in `mb_catalogue_sync` and
the gate silently checked less when the importer was absent - and moving them
out was the fix.

**The verdict is recorded, not computed.** `mb.migration.test.passed` is what
the laboratory issued against the limits in force on the test date. Deriving it
from a limits table of ours would put this addon in the position of overruling a
lab report the first time that table drifted. The class and the figures are kept
so the verdict stays auditable.

**A test is held against the glaze lot, not the ware.** One result covers every
article made from that lot. Recording it per piece would mean copying the same
figures onto every mug in a firing and having no single place to correct them.
""",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "category": "Inventory/Inventory",
    "author": "Makersbrain",
    "depends": [
        # The glaze, underglaze and engobe categories the mark-done gate reads,
        # and the Configuration menu the migration test list hangs under.
        "mb_ceramics_base",
        # The gate runs when a manufacturing order is marked done, and the glaze
        # whose migration test is checked is a consumed component.
        "mrp",
        # stock.lot is where a migration test and a food-contact flag land.
        "stock",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/mb_ceramics_compliance_security.xml",
        "views/mb_migration_test_views.xml",
        "views/product_template_views.xml",
        "views/stock_lot_views.xml",
        "views/mb_ceramics_compliance_menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}

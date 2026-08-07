{
    "name": "Makersbrain Catalogue Sync",
    "summary": "Read-only import of master catalogue materials into product.template.",
    "description": """
Pulls curated manufacturer identities from the cross-tenant ceramics catalogue
service into this tenant's product catalogue, on demand and never in bulk.

The catalogue holds roughly 47,000 supplier listings across 76 shops. None of
that belongs in an artisan's database. What crosses the boundary is the curated
manufacturer identity - Mayco SC74 Hot Tamale - plus the offers of the suppliers
this workshop actually buys from.
""",
    "version": "19.0.1.3.0",
    "license": "LGPL-3",
    "category": "Inventory/Inventory",
    "author": "Makersbrain",
    "depends": [
        # The material taxonomy this addon maps catalogue families onto. It is
        # not defined here on purpose: a workshop that never imports anything
        # still buys glaze and still owes a migration test on the food-contact
        # ware it makes with it, so a compliance gate must not sit behind a
        # connector. See mb_workshop_base/data/mb_material_categories.xml.
        "mb_workshop_base",
        "product",
        "purchase",
        "uom",
        # For is_storable: a ceramic material is bought, held and consumed, so it
        # is a stocked product and not a service line on an invoice.
        "stock",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/mb_catalogue_data.xml",
        "views/mb_catalogue_views.xml",
        "wizard/mb_catalogue_import_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}

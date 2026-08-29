{
    "name": "MakersBrain Catalogue Sync",
    "summary": "Read-only import of master catalogue materials into product.template.",
    "description": """
Pulls curated manufacturer identities from the cross-tenant ceramics catalogue
service into this tenant's product catalogue, on demand and never in bulk.

Supplier listings and price history stay in the shared catalogue. What crosses
the boundary is the selected curated manufacturer identity - Mayco SC74 Hot
Tamale - plus current offers from suppliers this workshop has mapped.
""",
    "version": "19.0.1.5.1",
    "license": "AGPL-3",
    "category": "Inventory/Inventory",
    "author": "MakersBrain",
    "depends": [
        # The material taxonomy this addon maps catalogue families onto. It is
        # not defined here on purpose: a workshop that never imports anything
        # still buys glaze and still needs compliance data for the food-contact
        # ware it makes with it, so a compliance gate must not sit behind a
        # connector. See mb_ceramics_base/data/mb_material_categories.xml.
        #
        "mb_ceramics_base",
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

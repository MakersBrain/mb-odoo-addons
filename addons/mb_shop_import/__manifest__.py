{
    "name": "Makersbrain Shop Catalogue Import",
    "summary": "Review scraper catalogue artifacts before creating products and stock.",
    "description": """
Upload catalogue-ceramics scraper artifacts, normalize them into persistent
review lines, and explicitly approve product and inventory changes. Source
files never mutate business data during parsing; exact variant bindings make
re-import idempotent and stock baselines prevent stale snapshots from
overwriting newer Odoo activity.
""",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "category": "Inventory/Inventory",
    "author": "Makersbrain",
    "depends": ["mail", "stock", "sale_stock", "account"],
    "data": [
        "security/mb_shop_import_security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence.xml",
        "views/shop_import_views.xml",
    ],
    "installable": True,
    "application": False,
}

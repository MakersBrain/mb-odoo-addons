{
    "name": "Makersbrain Product Photo Inventory Capture",
    "summary": "Identify products and supplier lots from reviewed package photographs.",
    "description": """
Capture one or two sanitized package photographs, decode and look up product
identifiers, retain append-only extraction evidence, and apply only a human
confirmed product and supplier lot to a draft incoming receipt. External OCR
and multimodal providers remain behind the Makersbrain control plane.
""",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "category": "Inventory/Inventory",
    "author": "Makersbrain",
    "depends": [
        "mail",
        "mb_control_bridge",
        "mb_workshop_base",
        "product_expiry",
        "purchase_stock",
        "web",
    ],
    "data": [
        "security/mb_inventory_capture_security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence.xml",
        "data/ir_cron.xml",
        "views/inventory_capture_views.xml",
        "views/product_views.xml",
        "views/stock_picking_views.xml",
        "views/stock_migration_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "mb_inventory_capture/static/src/**/*",
        ],
        "web.qunit_suite_tests": [
            "mb_inventory_capture/static/tests/**/*",
        ],
    },
    "installable": True,
    "application": False,
    "post_init_hook": "post_init_hook",
}

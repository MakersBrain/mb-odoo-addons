{
    "name": "MakersBrain Ceramics Workflow",
    "summary": "Throwing batches, ware boards, kiln loading and final inspection.",
    "description": """
The ceramicist-facing production layer above Odoo MRP and mb_ceramics_firing.

It keeps reusable wet blanks as lot-tracked stock, represents physical ware on
reusable boards while no stock quant exists, loads compatible work orders into
shared kiln firings, records yield loss and seconds, and exposes firing-aware lot
genealogy without replacing Odoo's stock identity.
""",
    "version": "19.0.3.0.2",
    "license": "LGPL-3",
    "category": "Manufacturing/Manufacturing",
    "author": "MakersBrain",
    "depends": [
        # The menu spine and the continuous calendar.
        "mb_workshop_base",
        # mb_clay_body_id, the material taxonomy and the seeded work centres the
        # sessions are named after.
        "mb_ceramics_base",
        # The food-contact gate a finished session eventually has to pass.
        "mb_ceramics_compliance",
        "mb_ceramics_firing",
        "mb_label",
        "mrp",
        "stock",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/mb_ceramics_workflow_security.xml",
        "data/mb_ceramics_workflow_data.xml",
        "views/mb_throwing_session_views.xml",
        "views/mb_bisque_session_views.xml",
        "views/mb_glazing_session_views.xml",
        "views/mb_board_views.xml",
        "views/mb_production_loss_views.xml",
        "views/product_template_views.xml",
        "views/mrp_bom_views.xml",
        "views/mrp_production_views.xml",
        "views/mrp_workorder_views.xml",
        "views/stock_lot_views.xml",
        "wizard/mb_firing_load_views.xml",
        "wizard/mb_inspection_views.xml",
        "wizard/mb_bisque_inspection_views.xml",
        "views/mb_ceramics_workflow_menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}

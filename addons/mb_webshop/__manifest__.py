{
    "name": "MakersBrain Webshop Pack",
    "summary": "A switchable artisan webshop with native Odoo theme presets.",
    "description": """
Adds the MakersBrain webshop as one product capability. Odoo 19's Website
Builder remains the editor: this addon contributes three craft-oriented design
presets and reusable artisan snippets, while Odoo supplies the page builder,
catalogue, checkout, stock validation, delivery and click-and-collect flows.

The control plane can restrict and re-enable the complete storefront without
uninstalling modules or deleting historical orders.
""",
    "version": "19.0.1.6.0",
    "license": "AGPL-3",
    "category": "Website/eCommerce",
    "author": "MakersBrain",
    "depends": [
        "mb_brand",
        "mb_control_bridge",
        "website_sale_stock",
        "website_sale_collect",
        "delivery",
        "stock",
        "website_sale",
    ],
    "data": [
        "security/return_security.xml",
        "security/ir.model.access.csv",
        "data/return_sequence.xml",
        "data/return_mail_templates.xml",
        "data/stock_hold_data.xml",
        "views/res_config_settings_views.xml",
        "views/payment_exception_views.xml",
        "views/return_views.xml",
        "views/return_portal_templates.xml",
        "views/accessibility_templates.xml",
        "views/snippets.xml",
    ],
    "assets": {
        "web._assets_primary_variables": [
            "mb_webshop/static/src/scss/primary_variables.scss",
        ],
        "web.assets_frontend": [
            "mb_webshop/static/src/scss/snippets.scss",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
    "post_init_hook": "post_init_hook",
}

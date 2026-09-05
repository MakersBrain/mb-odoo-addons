{
    "name": "MakersBrain Webshop Carrier Runtime",
    "summary": "Provider-neutral, durable shipping for the MakersBrain webshop.",
    "description": """
Provides the shared shipping journal, secure provider transport, label storage,
pickup-point checkout flow and asynchronous webhook inbox used by MakersBrain
carrier integrations. Stock pickings remain authoritative for fulfilment.
""",
    "version": "19.0.1.1.4",
    "license": "AGPL-3",
    "category": "Website/eCommerce",
    "author": "MakersBrain",
    "depends": [
        # Owns delivery.view_delivery_carrier_form, inherited directly below.
        "delivery",
        "mb_webshop",
        "stock_delivery",
        "stock",
        "web",
        "website_sale",
    ],
    "data": [
        "security/carrier_security.xml",
        "security/ir.model.access.csv",
        "data/carrier_cron.xml",
        "views/res_partner_views.xml",
        "views/delivery_carrier_views.xml",
        "views/shipment_views.xml",
        "views/manifest_views.xml",
        "report/local_handover_report.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}

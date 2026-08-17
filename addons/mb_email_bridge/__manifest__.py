{
    "name": "MakersBrain Transactional Email Bridge",
    "summary": "Durably submits webshop transaction mail through the MakersBrain mail boundary.",
    "description": """
Routes approved webshop order, invoice, shipment and return messages through a
tenant-authenticated control-plane outbox. Provider credentials and delivery
operations remain outside Odoo; unrelated Odoo mail keeps its native behavior.
""",
    "version": "19.0.1.1.0",
    "license": "LGPL-3",
    "category": "Website/eCommerce",
    "author": "Makersbrain",
    "depends": ["mail", "mb_control_bridge", "mb_webshop"],
    "data": [],
    "installable": True,
    "application": False,
}

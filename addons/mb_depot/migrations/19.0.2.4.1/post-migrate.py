from odoo import SUPERUSER_ID, api, fields


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    routes = env["stock.route"].with_context(active_test=False).search([
        ("name", "ilike", "Dépôt-vente:"),
    ])
    if not routes:
        return

    lines = env["sale.order.line"].search([("route_ids", "in", routes.ids)])
    commands = [fields.Command.unlink(route.id) for route in routes]
    lines.write({"route_ids": commands})
    routes.active = False

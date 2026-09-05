"""Create predecessor-version data that every candidate migration must preserve."""

from datetime import timedelta
from typing import Any

from odoo import fields

env: Any = globals()["env"]

parameters = env["ir.config_parameter"].sudo()
parameters.set_param("mb_remediation.predecessor_fixture", "1")

second_company = env["res.company"].create({"name": "MIG-01 Existing second company"})
parameters.set_param("mb_remediation.second_company_id", second_company.id)

template = env.ref("mb_label.template_wip_lot_30x20")
prototype = env.ref("mb_label.template_wip_lot_30x20_v1")
values = prototype.copy_data(
    default={
        "template_id": template.id,
        "number": 99,
    }
)[0]
selected = env["mb.label.template.version"].create(values)
template.current_version_id = selected
parameters.set_param("mb_remediation.selected_label_version_id", selected.id)

partner = env["res.partner"].create(
    {
        "name": "MIG-01  Normalized   Supplier",
        "vat": "fr 40-303.265.045",
        "company_registry": "303 265 045 00017",
    }
)
parameters.set_param("mb_remediation.partner_id", partner.id)

product = env["product.product"].create({"name": "MIG-01 held product", "is_storable": True})
order = env["sale.order"].create({"partner_id": env.company.partner_id.id})
hold = env["mb.webshop.stock.hold"].create(
    {
        "order_id": order.id,
        "product_id": product.id,
        "quantity": 1,
        "expires_at": fields.Datetime.now() + timedelta(days=1),
    }
)
parameters.set_param("mb_remediation.hold_id", hold.id)

env.cr.commit()
print("OK  predecessor migration fixture created")

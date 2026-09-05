"""Assert observable migration effects and repeated-upgrade idempotency."""

import json
import os
from typing import Any

env: Any = globals()["env"]

parameters = env["ir.config_parameter"].sudo()
assert parameters.get_param("mb_remediation.predecessor_fixture") == "1"

second_company_id = int(parameters.get_param("mb_remediation.second_company_id"))
selected_version_id = int(parameters.get_param("mb_remediation.selected_label_version_id"))
partner_id = int(parameters.get_param("mb_remediation.partner_id"))
hold_id = int(parameters.get_param("mb_remediation.hold_id"))

template = env.ref("mb_label.template_wip_lot_30x20")
assert template.current_version_id.id == selected_version_id
assert template.current_version_id.number == 99

companies = env["res.company"].browse([env.company.id, second_company_id]).exists()
seed_fingerprint = {}
for company in companies:
    seeds = (
        env["mb.label.template"]
        .with_context(active_test=False)
        .search([("company_id", "=", company.id), ("seed_key", "!=", False)], order="seed_key")
    )
    assert seeds.mapped("seed_key") == ["product_40x30", "wip_lot_30x20"]
    assert all(seeds.mapped("current_version_id"))
    seed_fingerprint[str(company.id)] = [
        [seed.seed_key, seed.id, seed.current_version_id.id] for seed in seeds
    ]

partner = env["res.partner"].browse(partner_id).exists()
assert partner.mb_invoice_vat_key == "FR40303265045"
assert partner.mb_invoice_registry_key == "30326504500017"
assert partner.mb_invoice_siren_key == "303265045"
assert partner.mb_invoice_name_key == "mig-01 normalized supplier"

hold = env["mb.webshop.stock.hold"].browse(hold_id).exists()
assert hold.company_id == hold.order_id.company_id

env.cr.execute("SELECT name FROM l10n_fr_micro_urssaf_invariant_lock ORDER BY name")
assert [row[0] for row in env.cr.fetchall()] == ["acre", "rate", "threshold"]

required_relations = {
    "mb_label_template_active_default_unique",
    "mb_label_template_company_seed_unique",
    "mb_market_stock_allocation_unique_operation_lot",
}
env.cr.execute(
    """
        SELECT conname FROM pg_constraint WHERE conname = ANY(%s)
        UNION
        SELECT indexname FROM pg_indexes WHERE indexname = ANY(%s)
    """,
    [list(required_relations), list(required_relations)],
)
assert required_relations <= {row[0] for row in env.cr.fetchall()}

fingerprint = json.dumps(
    {
        "seeds": seed_fingerprint,
        "selected_version": selected_version_id,
        "hold_company": hold.company_id.id,
        "partner_keys": [
            partner.mb_invoice_vat_key,
            partner.mb_invoice_registry_key,
            partner.mb_invoice_siren_key,
            partner.mb_invoice_name_key,
        ],
    },
    sort_keys=True,
)
mode = os.environ.get("MB_UPGRADE_ASSERT_MODE", "record")
if mode == "record":
    parameters.set_param("mb_remediation.first_upgrade_fingerprint", fingerprint)
elif mode == "verify":
    assert parameters.get_param("mb_remediation.first_upgrade_fingerprint") == fingerprint
else:
    raise AssertionError(f"unsupported MB_UPGRADE_ASSERT_MODE: {mode}")

env.cr.commit()
print(f"OK  candidate migration assertions ({mode})")

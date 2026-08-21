"""Point a database at a SumUp account, reading the credential from sumup.env.

Run from this repository, with a local ignored credential file exported into
the shell first:

    set -a && . sumup.env && set +a
    docker compose exec -T \
        -e SUMUP_API_KEY -e SUMUP_MERCHANT_CODE \
        odoo odoo shell -d mb_odoo --no-http --log-level=warn \
        < scripts/setup_sumup.py

The key never appears in this file, in a fixture, or in the log. Keep the
development credential in one ignored environment file; this script carries it
from there into the two records that need it and fails when it is absent.

The affiliate key is a separate credential - it comes from Developer settings in
the SumUp dashboard, is tied to an application identifier, and is only needed
for the POS deep link. Set SUMUP_AFFILIATE_KEY and SUMUP_APP_ID as well to have
the POS payment method configured too.
"""

import os

api_key = os.environ.get("SUMUP_API_KEY")
merchant_code = os.environ.get("SUMUP_MERCHANT_CODE")
if not api_key or not merchant_code:
    raise SystemExit(
        "Set SUMUP_API_KEY and SUMUP_MERCHANT_CODE in the environment "
        "(source sumup.env) before running this."
    )

# One provider record exists per company. Configure the one belonging to the
# company this shell is running as, because that is the company whose name will
# be on the invoice the customer pays.
provider = env["payment.provider"].search([
    ("code", "=", "sumup"),
    ("company_id", "=", env.company.id),
], limit=1)
if not provider:
    raise SystemExit(
        f"No SumUp provider for {env.company.display_name}. Install mb_payment_sumup first."
    )

provider.write({
    "sumup_api_key": api_key,
    "sumup_merchant_code": merchant_code,
    # 'test' rather than 'enabled': the account behind a development credential
    # is a sandbox merchant, and a provider marked enabled is one the portal
    # offers to real customers.
    "state": "test",
    "is_published": True,
})
print(f"payment.provider {provider.id}: SumUp -> merchant {merchant_code}, state {provider.state}")

# Confirm the credential actually acts for that merchant before anyone tries to
# take money with it. One read, no side effects.
memberships = provider._send_api_request("GET", "/v0.1/memberships")
codes = [
    m.get("resource", {}).get("id")
    for m in (memberships.get("items") or [])
    if m.get("resource", {}).get("type") == "merchant"
]
if codes and merchant_code not in codes:
    print(f"  WARNING: this key acts for {codes}, not for {merchant_code}")
elif len(codes) > 1:
    print(f"  note: this key can also act for {[c for c in codes if c != merchant_code]}")

affiliate_key = os.environ.get("SUMUP_AFFILIATE_KEY")
if affiliate_key:
    method = env["pos.payment.method"].search([
        ("use_payment_terminal", "=", "sumup_mobile"),
    ], limit=1)
    if not method:
        journal = env["account.journal"].search([("type", "=", "bank")], limit=1)
        method = env["pos.payment.method"].create({
            "name": "SumUp",
            "journal_id": journal.id,
            "payment_method_type": "terminal",
            "use_payment_terminal": "sumup_mobile",
        })
    method.write({
        "sumup_affiliate_key": affiliate_key,
        "sumup_app_id": os.environ.get("SUMUP_APP_ID") or False,
        "sumup_payment_provider_id": provider.id,
    })
    print(f"pos.payment.method {method.id}: {method.name} -> SumUp app handover")
    print("  add it to the POS configuration's payment methods to use it")
else:
    print("no SUMUP_AFFILIATE_KEY in the environment: POS payment method left alone")

env.cr.commit()

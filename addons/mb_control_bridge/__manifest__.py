{
    "name": "MakersBrain Control Plane Bridge",
    "summary": "Narrow tenant-side identity and entitlement reconciliation API.",
    "description": """
Receives idempotent, authenticated commands from the MakersBrain Rust control
plane. It links provisioned Odoo users to stable Rauthy subjects, applies one
allowlisted workshop role and records signed entitlement state. It is not a
general remote-administration API and stores no Rauthy administration secret.
""",
    "version": "19.0.1.5.1",
    "license": "LGPL-3",
    "category": "Administration",
    "author": "Makersbrain",
    "depends": [
        "account",
        "l10n_fr_account",
        "mrp",
        "point_of_sale",
        "purchase",
        "sale_stock",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/res_company_views.xml",
        "views/res_users_views.xml",
    ],
    "installable": True,
    "application": False,
}

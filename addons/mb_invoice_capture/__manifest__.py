{
    "name": "MakersBrain Invoice Capture",
    "summary": "Create reviewable draft supplier bills from normalized document extraction.",
    "description": """
Tenant-side receiver for Paperless and structured/Azure invoice extraction.
It retains immutable source revisions and confidence provenance, matches only
existing accounting master data, reconciles totals and creates draft supplier
bills. It never stores Paperless or Azure credentials and never posts or pays.
""",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "category": "Accounting/Accounting",
    "author": "Makersbrain",
    "depends": ["account", "mail", "mb_control_bridge", "purchase"],
    "data": [
        "security/mb_invoice_capture_security.xml",
        "security/ir.model.access.csv",
        "views/invoice_capture_views.xml",
    ],
    "installable": True,
    "application": False,
}

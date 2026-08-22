{
    "name": "MakersBrain AI Bridge",
    "summary": "Provider-neutral, tenant-scoped AI job submission for MakersBrain addons.",
    "description": """
Shared Odoo boundary for typed AI and document-extraction jobs. Domain addons
register fixed task contracts and retain their own reviewed business results;
this addon validates descriptor-only payloads, submits idempotent operations to
the MakersBrain control plane, and rejects raw provider bodies. Provider keys,
SDKs, routing, quotas, and retries remain outside Odoo in the extraction broker.
""",
    "version": "19.0.1.0.1",
    "license": "LGPL-3",
    "category": "Technical/Technical",
    "author": "MakersBrain",
    "depends": ["mb_control_bridge"],
    "data": [],
    "installable": True,
    "application": False,
}

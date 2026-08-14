"""Seed the tenant verifier before the first per-workshop token rotation.

Older bridge releases authenticated every workshop with the shared bootstrap
credential. The release driver supplies that value only to the isolated upgrade
job. Seeding its verifier keeps candidate health checks available; the next
idempotent tenant reconciliation replaces both the file and verifier with a
distinct random workshop credential.
"""

import hashlib
import os


def migrate(cr, version):
    cr.execute(
        """
        SELECT EXISTS(
            SELECT 1 FROM res_company
             WHERE mb_control_workshop_id IS NOT NULL
               AND mb_control_bridge_token_hash IS NULL
        )
        """
    )
    if not cr.fetchone()[0]:
        return
    token = os.environ.get("MB_CONTROL_BRIDGE_TOKEN", "")
    if not 48 <= len(token) <= 128 or not token.isalnum():
        raise RuntimeError(
            "a valid bootstrap credential is required to migrate tenant verifiers"
        )
    cr.execute(
        """
        UPDATE res_company
           SET mb_control_bridge_token_hash = %s
         WHERE mb_control_workshop_id IS NOT NULL
           AND mb_control_bridge_token_hash IS NULL
        """,
        (hashlib.sha256(token.encode()).hexdigest(),),
    )

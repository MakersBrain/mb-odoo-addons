from odoo import SUPERUSER_ID, api

KEY_FIELDS = [
    "mb_invoice_vat_key",
    "mb_invoice_registry_key",
    "mb_invoice_siren_key",
    "mb_invoice_name_key",
]
BATCH_SIZE = 10_000


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    partners = env["res.partner"].with_context(active_test=False)
    last_id = 0
    while True:
        cr.execute(
            """
                SELECT id
                  FROM res_partner
                 WHERE id > %s
                 ORDER BY id
                 LIMIT %s
            """,
            [last_id, BATCH_SIZE],
        )
        partner_ids = [row[0] for row in cr.fetchall()]
        if not partner_ids:
            break
        batch = partners.browse(partner_ids)
        for field_name in KEY_FIELDS:
            env.add_to_compute(partners._fields[field_name], batch)
        batch._recompute_recordset(KEY_FIELDS)
        last_id = partner_ids[-1]

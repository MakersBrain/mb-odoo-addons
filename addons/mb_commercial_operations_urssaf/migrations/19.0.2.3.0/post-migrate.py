def migrate(cr, version):
    """Backfill the legal-evidence snapshot, refusing ambiguous legacy rows."""
    cr.execute(
        """
        SELECT source.id, pos_operation.id, invoice_operation.id
          FROM l10n_fr_micro_urssaf_declaration_source AS source
          JOIN pos_order AS pos_order ON pos_order.id = source.pos_order_id
          JOIN account_move AS invoice ON invoice.id = source.origin_move_id
          JOIN mb_commercial_operation AS pos_operation
            ON pos_operation.id = pos_order.mb_commercial_operation_id
          JOIN mb_commercial_operation AS invoice_operation
            ON invoice_operation.id = invoice.mb_commercial_operation_id
         WHERE pos_operation.id <> invoice_operation.id
         ORDER BY source.id
        """
    )
    conflicts = cr.fetchall()
    if conflicts:
        details = ", ".join(
            f"source {source_id}: POS operation {pos_id}, invoice operation {invoice_id}"
            for source_id, pos_id, invoice_id in conflicts[:50]
        )
        if len(conflicts) > 50:
            details += f", and {len(conflicts) - 50} more"
        raise RuntimeError(
            "Cannot migrate mb_commercial_operations_urssaf: conflicting legacy "
            f"commercial-operation attribution ({details}). Correct the POS/invoice "
            "links so each receipt has one operation, then retry the upgrade."
        )

    cr.execute(
        """
        WITH attribution AS (
            SELECT source.id AS source_id,
                   declaration.company_id AS declaration_company_id,
                   operation.id AS operation_id,
                   operation.company_id AS operation_company_id
              FROM l10n_fr_micro_urssaf_declaration_source AS source
              JOIN l10n_fr_micro_urssaf_declaration AS declaration
                ON declaration.id = source.declaration_id
              LEFT JOIN pos_order AS pos_order ON pos_order.id = source.pos_order_id
              LEFT JOIN account_move AS invoice ON invoice.id = source.origin_move_id
              LEFT JOIN mb_commercial_operation AS operation
                ON operation.id = COALESCE(
                     pos_order.mb_commercial_operation_id,
                     invoice.mb_commercial_operation_id
                   )
        )
        UPDATE l10n_fr_micro_urssaf_declaration_source AS source
           SET mb_commercial_operation_id = CASE
                 WHEN attribution.operation_company_id = attribution.declaration_company_id
                 THEN attribution.operation_id
                 ELSE NULL
               END
          FROM attribution
         WHERE attribution.source_id = source.id
        """
    )

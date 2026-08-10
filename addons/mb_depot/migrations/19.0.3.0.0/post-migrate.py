def migrate(cr, version):
    """Preserve invoice links created by pre-M2M development revisions."""
    cr.execute("""
        INSERT INTO mb_depot_sale_report_account_move_rel (report_id, move_id)
        SELECT mb_depot_sale_report_id, id
          FROM account_move
         WHERE mb_depot_sale_report_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)

def migrate(cr, version):
    cr.execute("""
        UPDATE stock_warehouse
           SET mb_depot_legal_structure = 'resale'
         WHERE is_depot
           AND mb_depot_legal_structure IS NULL
    """)

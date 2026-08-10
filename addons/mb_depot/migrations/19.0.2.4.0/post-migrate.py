def migrate(cr, version):
    cr.execute("""
        UPDATE product_template
           SET invoice_policy = 'delivery'
         WHERE is_storable
           AND sale_ok
           AND invoice_policy != 'delivery'
    """)

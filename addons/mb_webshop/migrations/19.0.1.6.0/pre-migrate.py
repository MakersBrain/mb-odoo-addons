def migrate(cr, version):
    """Backfill company ownership before the ORM enforces the required field."""
    cr.execute(
        """
        ALTER TABLE mb_webshop_stock_hold
        ADD COLUMN IF NOT EXISTS company_id integer
        """
    )
    cr.execute(
        """
        UPDATE mb_webshop_stock_hold AS hold
           SET company_id = sale.company_id
          FROM sale_order AS sale
         WHERE sale.id = hold.order_id
           AND hold.company_id IS DISTINCT FROM sale.company_id
        """
    )
    cr.execute(
        """
        SELECT hold.id
          FROM mb_webshop_stock_hold AS hold
          LEFT JOIN sale_order AS sale ON sale.id = hold.order_id
         WHERE hold.company_id IS NULL
            OR hold.company_id IS DISTINCT FROM sale.company_id
         ORDER BY hold.id
         LIMIT 50
        """
    )
    invalid_ids = [row[0] for row in cr.fetchall()]
    if invalid_ids:
        raise RuntimeError(
            "Cannot migrate mb_webshop: cart holds have no valid order company "
            f"(hold ids: {invalid_ids}). Repair or remove those orphaned holds, then retry."
        )

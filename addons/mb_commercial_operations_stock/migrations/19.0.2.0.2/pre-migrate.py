def migrate(cr, version):
    """Report duplicate tracked-lot allocations before adding the unique key."""
    cr.execute(
        """
        SELECT operation_id, lot_id, array_agg(id ORDER BY id), count(*)
          FROM mb_market_stock_allocation
         WHERE lot_id IS NOT NULL
         GROUP BY operation_id, lot_id
        HAVING count(*) > 1
         ORDER BY operation_id, lot_id
         LIMIT 51
        """
    )
    rows = cr.fetchall()
    if not rows:
        return
    visible = rows[:50]
    details = ", ".join(
        f"operation={operation_id}, lot={lot_id}, allocation_ids={allocation_ids}"
        for operation_id, lot_id, allocation_ids, _count in visible
    )
    if len(rows) > len(visible):
        details += ", and more"
    raise RuntimeError(
        "Cannot migrate mb_commercial_operations_stock: duplicate lot allocation "
        "groups exist. Repair the listed groups and retry the upgrade; no rows were "
        f"deleted. {details}"
    )

def migrate(cr, version):
    """Report active depot-contract overlaps without choosing or deleting a winner."""
    cr.execute(
        """
        SELECT first.id, second.id, first.company_id, first.depot_warehouse_id,
               first.date_start, first.date_end, second.date_start, second.date_end
          FROM mb_commercial_contract AS first
          JOIN mb_commercial_contract AS second
            ON second.id > first.id
           AND second.active
           AND second.company_id = first.company_id
           AND second.depot_warehouse_id = first.depot_warehouse_id
           AND second.date_start <= COALESCE(first.date_end, DATE '9999-12-31')
           AND first.date_start <= COALESCE(second.date_end, DATE '9999-12-31')
         WHERE first.active
           AND first.depot_warehouse_id IS NOT NULL
         ORDER BY first.company_id, first.depot_warehouse_id, first.id, second.id
         LIMIT 51
        """
    )
    rows = cr.fetchall()
    if not rows:
        return
    visible = rows[:50]
    details = ", ".join(
        "contracts=%s/%s, company=%s, depot=%s [%s..%s] vs [%s..%s]" % row for row in visible
    )
    if len(rows) > len(visible):
        details += ", and more"
    raise RuntimeError(
        "Cannot migrate mb_commercial_operations_depot: overlapping active depot "
        "contracts exist. Repair the listed contracts and retry the upgrade; no rows "
        "were deleted. " + details
    )

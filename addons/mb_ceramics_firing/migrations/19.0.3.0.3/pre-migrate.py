def migrate(cr, version):
    """Refuse to hide existing occupancy conflicts before locking becomes authoritative."""
    cr.execute(
        """
        SELECT planned.id, occupied.id, planned.kiln_id,
               planned.date_planned_start, planned.date_planned_unload,
               occupied.date_planned_start, occupied.date_planned_unload
          FROM mb_firing AS planned
          JOIN mb_firing AS occupied
            ON occupied.kiln_id = planned.kiln_id
           AND occupied.id != planned.id
           AND occupied.state IN ('planned', 'draft', 'firing', 'cooling')
           AND occupied.date_planned_start < planned.date_planned_unload
           AND occupied.date_planned_unload > planned.date_planned_start
         WHERE planned.state = 'planned'
           AND (occupied.state != 'planned' OR planned.id < occupied.id)
         ORDER BY planned.kiln_id, planned.id, occupied.id
         LIMIT 51
        """
    )
    rows = cr.fetchall()
    if not rows:
        return
    visible = rows[:50]
    details = ", ".join(
        "planned=%s, occupied=%s, kiln=%s [%s..%s) vs [%s..%s)" % row for row in visible
    )
    if len(rows) > len(visible):
        details += ", and more"
    raise RuntimeError(
        "Cannot migrate mb_ceramics_firing: overlapping kiln occupancy exists. "
        "Repair the listed firings and retry the upgrade; no rows were deleted. " + details
    )

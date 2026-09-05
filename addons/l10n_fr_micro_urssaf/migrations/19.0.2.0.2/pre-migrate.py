OVERLAP_CHECKS = (
    (
        "declaration",
        """
        SELECT left_row.id, right_row.id, left_row.date_from, left_row.date_to,
               right_row.date_from, right_row.date_to
          FROM l10n_fr_micro_urssaf_declaration AS left_row
          JOIN l10n_fr_micro_urssaf_declaration AS right_row
            ON right_row.id > left_row.id
           AND right_row.company_id = left_row.company_id
           AND left_row.date_from <= right_row.date_to
           AND right_row.date_from <= left_row.date_to
         ORDER BY left_row.id, right_row.id
         LIMIT 51
        """,
    ),
    (
        "rate",
        """
        SELECT left_row.id, right_row.id, left_row.date_from, left_row.date_to,
               right_row.date_from, right_row.date_to
          FROM l10n_fr_micro_urssaf_rate AS left_row
          JOIN l10n_fr_micro_urssaf_rate AS right_row
            ON right_row.id > left_row.id
           AND right_row.levy = left_row.levy
           AND right_row.category = left_row.category
           AND right_row.taxpayer_kind IS NOT DISTINCT FROM left_row.taxpayer_kind
           AND right_row.chamber_kind IS NOT DISTINCT FROM left_row.chamber_kind
           AND right_row.chamber_zone IS NOT DISTINCT FROM left_row.chamber_zone
           AND left_row.date_from <= COALESCE(right_row.date_to, 'infinity'::date)
           AND right_row.date_from <= COALESCE(left_row.date_to, 'infinity'::date)
         ORDER BY left_row.id, right_row.id
         LIMIT 51
        """,
    ),
    (
        "ACRE rule",
        """
        SELECT left_row.id, right_row.id,
               left_row.creation_date_from, left_row.creation_date_to,
               right_row.creation_date_from, right_row.creation_date_to
          FROM l10n_fr_micro_urssaf_acre_rule AS left_row
          JOIN l10n_fr_micro_urssaf_acre_rule AS right_row
            ON right_row.id > left_row.id
           AND left_row.creation_date_from <=
               COALESCE(right_row.creation_date_to, 'infinity'::date)
           AND right_row.creation_date_from <=
               COALESCE(left_row.creation_date_to, 'infinity'::date)
         ORDER BY left_row.id, right_row.id
         LIMIT 51
        """,
    ),
    (
        "threshold",
        """
        SELECT left_row.id, right_row.id, left_row.date_from, left_row.date_to,
               right_row.date_from, right_row.date_to
          FROM l10n_fr_micro_urssaf_threshold AS left_row
          JOIN l10n_fr_micro_urssaf_threshold AS right_row
            ON right_row.id > left_row.id
           AND left_row.date_from <= COALESCE(right_row.date_to, 'infinity'::date)
           AND right_row.date_from <= COALESCE(left_row.date_to, 'infinity'::date)
         ORDER BY left_row.id, right_row.id
         LIMIT 51
        """,
    ),
)


def migrate(cr, version):
    """Refuse to hide overlap damage before concurrency locks become authoritative."""
    problems = []
    for label, query in OVERLAP_CHECKS:
        cr.execute(query)
        rows = cr.fetchall()
        if not rows:
            continue
        visible = rows[:50]
        details = ", ".join("%s/%s [%s..%s] vs [%s..%s]" % row for row in visible)
        if len(rows) > len(visible):
            details += ", and more"
        problems.append(f"{label}: {details}")
    if problems:
        raise RuntimeError(
            "Cannot migrate l10n_fr_micro_urssaf: overlapping dated records exist. "
            "Repair the listed pairs and retry the upgrade. " + "; ".join(problems)
        )

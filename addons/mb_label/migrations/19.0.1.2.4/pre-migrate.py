def migrate(cr, version):
    """Abort before the active-default unique index can hide dirty data."""
    cr.execute(
        """
        SELECT company_id, array_agg(id ORDER BY id)
          FROM mb_label_template
         WHERE active IS TRUE AND is_default IS TRUE
         GROUP BY company_id
        HAVING count(*) > 1
         ORDER BY company_id
         LIMIT 51
        """
    )
    duplicates = cr.fetchall()
    if duplicates:
        details = ", ".join(
            "company %s: templates %s" % (company_id, template_ids)
            for company_id, template_ids in duplicates[:50]
        )
        if len(duplicates) > 50:
            details += ", and more"
        raise RuntimeError(
            "Cannot migrate mb_label: multiple active default templates exist. "
            "Choose one winner per company, clear is_default on the others, and retry. " + details
        )

def migrate(cr, version):
	cr.execute("""
		UPDATE res_company company
		   SET l10n_fr_micro_depot_sale_closed_through = evidence.date_to,
		       l10n_fr_micro_depot_sale_horizon_confirmed = FALSE
		  FROM (
			SELECT company_id, max(date_to) AS date_to
			  FROM l10n_fr_micro_urssaf_declaration
			 WHERE state = 'filed'
			 GROUP BY company_id
		  ) evidence
		 WHERE company.id = evidence.company_id
		   AND (
			company.l10n_fr_micro_depot_sale_closed_through IS NULL
			OR company.l10n_fr_micro_depot_sale_closed_through < evidence.date_to
		   )
	""")

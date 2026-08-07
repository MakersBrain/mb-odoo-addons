{
	"name": "France - Micro-Entreprise",
	"summary": "Safe French franchise-en-base tax setup and regime switching.",
	"description": """
Prepare and switch French micro-enterprise VAT treatment without replacing the
economic taxes stored on products. Domestic sales are mapped through a fiscal
position to Factur-X-compatible franchise exemption taxes, while historical
accounting documents remain unchanged.
""",
	"version": "19.0.2.1.0",
	"license": "LGPL-3",
	"category": "Accounting/Localizations",
	"author": "Makersbrain",
	"depends": ["l10n_fr_account", "account_edi_ubl_cii"],
	"data": [
		"security/ir.model.access.csv",
		"views/res_config_settings_views.xml",
		"views/account_move_report_views.xml",
		"wizards/l10n_fr_micro_setup_wizard_views.xml",
	],
	"post_init_hook": "post_init_hook",
	"installable": True,
	"application": False,
}

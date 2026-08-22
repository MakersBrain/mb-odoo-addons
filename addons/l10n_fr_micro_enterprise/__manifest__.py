{
    "name": "France - Micro-Entreprise",
    "summary": "Safe French franchise-en-base tax setup and regime switching.",
    "description": """
Prepare and switch French micro-enterprise VAT treatment without replacing the
economic taxes stored on products. Domestic sales are mapped through a fiscal
position to Factur-X-compatible franchise exemption taxes, while historical
accounting documents remain unchanged.
""",
    "version": "19.0.4.0.2",
    "license": "LGPL-3",
    "category": "Accounting/Localizations",
    "author": "MakersBrain",
    "depends": ["l10n_fr_account", "account_edi_ubl_cii"],
    "data": [
        "security/ir.model.access.csv",
        "wizard/l10n_fr_micro_vat_switch_wizard_views.xml",
        "views/res_config_settings_views.xml",
        "views/account_move_report_views.xml",
        "wizard/l10n_fr_micro_setup_wizard_views.xml",
    ],
    "installable": True,
    "application": False,
}

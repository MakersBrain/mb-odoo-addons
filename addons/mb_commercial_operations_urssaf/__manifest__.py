{
    "name": "MakersBrain Commercial Operations - URSSAF",
    "summary": "Read-only legal recognition status for commercial operations",
    "version": "19.0.2.3.0",
    "category": "Accounting/Localizations",
    "author": "MakersBrain",
    "license": "AGPL-3",
    # Only what the code reaches for: the URSSAF rates and declaration sources,
    # the commercial operation and its planning wizard, and the POS bridge that
    # puts `mb_commercial_operation_id` on `pos.order`. The depot and sale
    # bridges were declared but never referenced, and they forced a POS-only
    # tenant to install the consignment stack to get a recognition status.
    "depends": [
        "l10n_fr_micro_urssaf",
        "mb_commercial_operations",
        "mb_commercial_operations_pos",
    ],
    "data": ["views/commercial_operation_urssaf_views.xml"],
    "installable": True,
    "application": False,
}

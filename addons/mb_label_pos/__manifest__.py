{
    "name": "MakersBrain Label QR for Point of Sale",
    "summary": "Resolve versioned product and lot QR aliases in Odoo POS.",
    "description": "Offline-first QR alias resolution with native barcode fallback for Odoo 19 POS.",
    "version": "19.0.1.1.2",
    "license": "AGPL-3",
    "category": "Sales/Point of Sale",
    "author": "MakersBrain",
    "depends": ["mb_label", "point_of_sale"],
    "data": ["security/ir.model.access.csv"],
    "assets": {
        "point_of_sale._assets_pos": [
            "mb_label_pos/static/src/**/*.js",
            "mb_label_pos/static/src/**/*.xml",
            "mb_label_pos/static/src/**/*.scss",
        ],
        "web.assets_unit_tests": [
            "mb_label_pos/static/src/qr_parser.js",
            "mb_label_pos/static/src/scanner_enhancements.js",
            "mb_label_pos/static/tests/**/*.test.js",
        ],
    },
    "installable": True,
    "application": False,
}

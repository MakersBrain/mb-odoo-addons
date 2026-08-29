{
    "name": "MakersBrain Commercial Operations - Point of Sale",
    "summary": "Explicit market POS sessions, revenue analytics, and stock cost",
    "version": "19.0.2.0.1",
    "category": "Sales/Point of Sale",
    "author": "MakersBrain",
    "license": "AGPL-3",
    "depends": [
        "mb_commercial_operations_stock",
        "point_of_sale",
        "project_stock_account",
    ],
    "data": [
        "security/mb_commercial_operations_pos_security.xml",
        "security/ir.model.access.csv",
        "views/commercial_operation_pos_views.xml",
        "views/pos_config_views.xml",
        "views/pos_order_views.xml",
    ],
    "installable": True,
    "application": False,
}

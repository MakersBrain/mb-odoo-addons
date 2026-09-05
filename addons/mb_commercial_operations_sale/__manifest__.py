{
    "name": "MakersBrain Commercial Operations - Sales",
    "summary": "Market sales, revenue analytics, and outbound product cost",
    "version": "19.0.2.0.2",
    "category": "Sales/Sales",
    "author": "MakersBrain",
    "license": "AGPL-3",
    "depends": [
        "mb_commercial_operations",
        "mb_commercial_operations_stock",
        "account",
        "sale",
        "sale_project",
        "sale_stock",
        "project_stock_account",
    ],
    "data": [
        "views/commercial_operation_sale_views.xml",
        "views/sale_order_views.xml",
        "views/account_move_views.xml",
    ],
    "installable": True,
    "application": False,
}

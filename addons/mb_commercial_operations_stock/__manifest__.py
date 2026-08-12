{
    "name": "Makersbrain Commercial Operations - Stock",
    "summary": "Market stock planning, preparation, returns, and reconciliation",
    "version": "19.0.2.0.1",
    "category": "Inventory/Inventory",
    "author": "Makersbrain",
    "license": "LGPL-3",
    "depends": ["mb_commercial_operations", "stock"],
    "data": [
        "security/mb_commercial_operations_stock_security.xml",
        "security/ir.model.access.csv",
        "views/commercial_operation_stock_views.xml",
        "views/stock_picking_views.xml",
    ],
    "installable": True,
    "application": False,
}

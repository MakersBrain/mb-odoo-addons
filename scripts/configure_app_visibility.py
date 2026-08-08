"""Apply the streamlined artisan app-switcher layout after bootstrap.

Functional modules remain installed. This only controls their root menu tiles,
so dependencies keep working underneath the workshop features that use them.
"""


VISIBLE_APPS = (
    "sale.sale_menu_root",
    "mb_workshop_base.menu_mb_workshop_root",
    "point_of_sale.menu_point_root",
    "account.menu_finance",
    "purchase.menu_purchase_root",
    "stock.menu_stock_root",
    "mrp.menu_mrp_root",
)

HIDDEN_APPS = (
    "mail.menu_root_discuss",
    "spreadsheet_dashboard.spreadsheet_dashboard_menu_root",
    "maintenance.menu_maintenance_title",
    "utm.menu_link_tracker_root",
    "base.menu_tests",
)

ADMIN_ONLY_APPS = (
    "base.menu_management",
    "base.menu_administration",
)


def resolve(xmlids):
    records = env["ir.ui.menu"]
    missing = []
    for xmlid in xmlids:
        record = env.ref(xmlid, raise_if_not_found=False)
        if record and record._name == "ir.ui.menu":
            records |= record
        else:
            missing.append(xmlid)
    return records, missing


visible, missing_visible = resolve(VISIBLE_APPS)
hidden, missing_hidden = resolve(HIDDEN_APPS)
admin_only, missing_admin = resolve(ADMIN_ONLY_APPS)

visible.write({"active": True})
hidden.write({"active": False})
admin_only.write({
    "active": True,
    "group_ids": [(6, 0, [env.ref("base.group_system").id])],
})

env.cr.commit()

print("VISIBLE", visible.mapped("name"))
print("HIDDEN", hidden.with_context(active_test=False).mapped("name"))
print("ADMIN_ONLY", admin_only.mapped("name"))
missing = missing_visible + missing_hidden + missing_admin
if missing:
    print("NOT_INSTALLED", missing)

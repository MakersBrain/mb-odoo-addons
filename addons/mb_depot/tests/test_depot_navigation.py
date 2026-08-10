import ast

from lxml import etree

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDepotNavigation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = cls.env["res.users"].create({
            "name": "Depot navigation manager",
            "login": "depot-navigation-manager",
            "group_ids": [fields.Command.set(
                cls.env.ref("mb_depot.group_depot_sale_manager").ids
            )],
        })
        cls.inventory_user = cls.env["res.users"].create({
            "name": "Depot navigation inventory user",
            "login": "depot-navigation-inventory",
            "group_ids": [fields.Command.set(
                cls.env.ref("stock.group_stock_user").ids
            )],
        })
        cls.accounting_user = cls.env["res.users"].create({
            "name": "Depot navigation accounting user",
            "login": "depot-navigation-accounting",
            "group_ids": [fields.Command.set(
                cls.env.ref("account.group_account_invoice").ids
            )],
        })
        cls.inventory_manager = cls.env["res.users"].create({
            "name": "Depot navigation inventory manager",
            "login": "depot-navigation-inventory-manager",
            "group_ids": [fields.Command.set(
                cls.env.ref("stock.group_stock_manager").ids
            )],
        })

    def _visible_menu_ids(self, user):
        return self.env["ir.ui.menu"].with_user(user)._visible_menu_ids()

    def test_root_is_an_actionless_application_with_an_icon(self):
        root = self.env.ref("mb_depot.menu_depot_root")

        self.assertFalse(root.parent_id)
        self.assertFalse(root.action)
        self.assertFalse(root.group_ids)
        self.assertTrue(root.active)
        self.assertEqual(root.web_icon, "mb_depot,static/description/icon.svg")
        self.assertTrue(root.web_icon_data)

    def test_manager_lands_on_report_navigation(self):
        visible = self._visible_menu_ids(self.manager)

        self.assertIn(self.env.ref("mb_depot.menu_depot_root").id, visible)
        self.assertIn(self.env.ref("mb_depot.menu_depot_record_sale").id, visible)
        self.assertIn(self.env.ref("mb_depot.menu_depot_record_sale_new").id, visible)
        self.assertNotIn(self.env.ref("mb_depot.menu_depot_invoices").id, visible)

    def test_inventory_user_sees_stock_but_not_reports(self):
        visible = self._visible_menu_ids(self.inventory_user)

        self.assertIn(self.env.ref("mb_depot.menu_depot_root").id, visible)
        self.assertIn(self.env.ref("mb_depot.menu_depot_place_products").id, visible)
        self.assertIn(self.env.ref("mb_depot.menu_depot_transfers").id, visible)
        self.assertNotIn(self.env.ref("mb_depot.menu_depot_record_sale").id, visible)
        self.assertNotIn(self.env.ref("mb_depot.menu_depot_invoices").id, visible)

    def test_accounting_user_sees_only_the_document_area(self):
        visible = self._visible_menu_ids(self.accounting_user)

        self.assertIn(self.env.ref("mb_depot.menu_depot_root").id, visible)
        self.assertIn(self.env.ref("mb_depot.menu_depot_documents").id, visible)
        self.assertIn(self.env.ref("mb_depot.menu_depot_invoices").id, visible)
        self.assertNotIn(self.env.ref("mb_depot.menu_depot_record_sale").id, visible)
        self.assertNotIn(self.env.ref("mb_depot.menu_depot_place_products").id, visible)
        self.assertNotIn(self.env.ref("mb_depot.menu_depot_locations").id, visible)

    def test_inventory_manager_sees_depot_configuration(self):
        visible = self._visible_menu_ids(self.inventory_manager)

        self.assertIn(self.env.ref("mb_depot.menu_depot_root").id, visible)
        self.assertIn(self.env.ref("mb_depot.menu_depot_configuration").id, visible)
        self.assertIn(self.env.ref("mb_depot.menu_depot_locations").id, visible)
        self.assertIn(self.env.ref("mb_depot.menu_depot_create").id, visible)
        self.assertNotIn(self.env.ref("mb_depot.menu_depot_record_sale").id, visible)

    def test_existing_leaf_xmlids_are_reparented(self):
        expected_parents = {
            "mb_depot.menu_depot_record_sale": "mb_depot.menu_depot_operations",
            "mb_depot.menu_depot_quant": "mb_depot.menu_depot_stock",
            "mb_depot.menu_depot_statement": "mb_depot.menu_depot_reporting",
            "mb_depot.menu_depot_locations": "mb_depot.menu_depot_configuration",
            "mb_depot.menu_depot_create": "mb_depot.menu_depot_configuration",
        }
        for menu_xmlid, parent_xmlid in expected_parents.items():
            with self.subTest(menu=menu_xmlid):
                self.assertEqual(
                    self.env.ref(menu_xmlid).parent_id,
                    self.env.ref(parent_xmlid),
                )

    def test_report_actions_have_distinct_navigation_roles(self):
        reports = self.env.ref("mb_depot.action_mb_depot_sale_report")
        record_sale = self.env.ref("mb_depot.action_mb_depot_sale_report_new")

        self.assertEqual(reports.view_mode, "list,form")
        self.assertEqual(record_sale.view_mode, "form")
        self.assertEqual(record_sale.view_id, self.env.ref(
            "mb_depot.view_mb_depot_sale_report_form"
        ))

    def test_statement_is_a_full_page_reporting_action(self):
        statement = self.env.ref("mb_depot.action_mb_depot_statement")
        menu = self.env.ref("mb_depot.menu_depot_statement")

        self.assertEqual(statement.target, "current")
        self.assertEqual(
            menu.parent_id,
            self.env.ref("mb_depot.menu_depot_reporting"),
        )

    def test_sale_orders_have_customer_depot_and_status_search_panel(self):
        view = self.env.ref("mb_depot.view_depot_sale_order_search")
        arch = view._get_combined_arch()

        fields_by_name = {
            node.get("name"): node
            for node in arch.xpath("//searchpanel/field")
        }
        self.assertEqual(
            set(fields_by_name),
            {"partner_id", "warehouse_id", "state"},
        )
        self.assertEqual(fields_by_name["partner_id"].get("string"), "Customer")
        self.assertEqual(fields_by_name["warehouse_id"].get("string"), "Depot")
        self.assertEqual(fields_by_name["state"].get("string"), "Status")
        self.assertEqual(
            fields_by_name["warehouse_id"].get("domain"),
            "[('is_depot', '=', True)]",
        )

    def test_filtered_actions_use_stored_depot_relationships(self):
        expected_domains = {
            "mb_depot.action_depot_sale_orders": [
                ("mb_depot_sale_report_id", "!=", False),
            ],
            "mb_depot.action_depot_deliveries": [
                ("mb_depot_sale_report_id", "!=", False),
            ],
            "mb_depot.action_depot_placements": [
                ("is_depot_placement", "=", True),
            ],
            "mb_depot.action_depot_transfers": [
                ("depot_warehouse_id", "!=", False),
            ],
            "mb_depot.action_depot_invoices": [
                ("mb_depot_sale_report_ids", "!=", False),
                ("move_type", "in", ["out_invoice", "out_refund", "out_receipt"]),
            ],
        }
        for action_xmlid, expected in expected_domains.items():
            with self.subTest(action=action_xmlid):
                action = self.env.ref(action_xmlid)
                self.assertEqual(ast.literal_eval(action.domain), expected)
                self.assertTrue(action.search_view_id)
                self.assertEqual(action.search_view_id.mode, "primary")

    def test_accounting_smart_buttons_are_group_restricted(self):
        view = self.env.ref("mb_depot.view_mb_depot_sale_report_form")
        arch = etree.fromstring(view.arch_db.encode())

        for method in ("action_view_invoices", "action_view_credit_notes"):
            with self.subTest(method=method):
                buttons = arch.xpath(f"//button[@name='{method}']")
                self.assertEqual(len(buttons), 1)
                self.assertEqual(
                    buttons[0].get("groups"),
                    "account.group_account_invoice",
                )

    def test_report_product_and_lot_domains_use_depot_availability(self):
        view = self.env.ref("mb_depot.view_mb_depot_sale_report_form")
        arch = etree.fromstring(view.arch_db.encode())

        self.assertTrue(arch.xpath(
            "//field[@name='line_ids']/list/field[@name='available_product_ids']"
        ))
        self.assertTrue(arch.xpath(
            "//field[@name='line_ids']/list/field[@name='available_lot_ids']"
        ))
        product_fields = arch.xpath(
            "//field[@name='line_ids']/list/field[@name='product_id']"
        )
        self.assertEqual(len(product_fields), 1)
        self.assertIn(
            "mb_depot_warehouse_id",
            product_fields[0].get("context", ""),
        )
        line_model = self.env["mb.depot.sale.report.line"]
        self.assertIn(
            "available_product_ids",
            line_model._fields["product_id"].domain,
        )
        self.assertIn(
            "available_lot_ids",
            line_model._fields["lot_id"].domain,
        )

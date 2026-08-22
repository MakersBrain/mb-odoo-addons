from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import formatLang


@tagged("post_install", "-at_install")
class TestDepotSaleReport(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref("mb_depot.group_depot_sale_manager")
        cls.env.user.group_ids |= cls.env.ref("account.group_account_invoice")
        if "l10n_fr_micro_depot_sale_horizon_confirmed" in cls.env.company._fields:
            cls.env.company.action_l10n_fr_micro_confirm_depot_sale_horizon()
        if not cls.env["account.journal"].search_count(
            [
                ("company_id", "=", cls.env.company.id),
                ("type", "=", "sale"),
            ]
        ):
            cls.env["account.chart.template"].sudo().try_loading(
                "generic_coa",
                company=cls.env.company,
                install_demo=False,
            )
        cls.home = cls.env["stock.warehouse"].search(
            [
                ("company_id", "=", cls.env.company.id),
            ],
            limit=1,
        )
        cls.gallery = cls.env["res.partner"].create(
            {
                "name": "Depot report gallery",
                "is_company": True,
            }
        )
        cls.env["mb.depot.create"].create(
            {
                "partner_id": cls.gallery.id,
                "commission": 40.0,
                "legal_structure": "resale",
            }
        ).action_create()
        cls.depot = (
            cls.env["stock.warehouse"]
            .search(
                [
                    ("is_depot", "=", True),
                    ("depot_partner_id", "=", cls.gallery.id),
                ]
            )
            .ensure_one()
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Reported bowl",
                "type": "consu",
                "is_storable": True,
                "sale_ok": True,
                "invoice_policy": "delivery",
                "list_price": 120.0,
            }
        )

    def _place(self, product=None, quantity=1.0, lot=None, when=None):
        product = product or self.product
        move = self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_qty": quantity,
                "location_id": self.home.lot_stock_id.id,
                "location_dest_id": self.depot.lot_stock_id.id,
            }
        )
        move._action_confirm()
        move.move_line_ids = [
            fields.Command.create(
                {
                    "product_id": product.id,
                    "location_id": self.home.lot_stock_id.id,
                    "location_dest_id": self.depot.lot_stock_id.id,
                    "lot_id": lot.id if lot else False,
                    "quantity": quantity,
                    "picked": True,
                }
            )
        ]
        move.picked = True
        move._action_done()
        if when:
            move.date = when
            move.move_line_ids.date = when
        return move

    def _report(self, lines, reference="DEPOT-AUG-001", invoice=False):
        return self.env["mb.depot.sale.report"].create(
            {
                "depot_warehouse_id": self.depot.id,
                "external_reference": reference,
                "create_draft_invoice": invoice,
                "line_ids": [
                    fields.Command.create(
                        dict(
                            {
                                "product_id": self.product.id,
                                "quantity": 1.0,
                                "reported_public_unit_price": 100.0,
                                "reported_commission_percentage": 40.0,
                            },
                            **values,
                        )
                    )
                    for values in lines
                ],
            }
        )

    def test_manager_group_uses_an_odoo_19_visible_privilege(self):
        group = self.env.ref("mb_depot.group_depot_sale_manager")
        privilege = self.env.ref("mb_depot.res_groups_privilege_depot_sales")

        self.assertEqual(group.privilege_id, privilege)
        self.assertEqual(
            privilege.category_id,
            self.env.ref("base.module_category_supply_chain"),
        )
        self.assertIn(self.env.ref("base.user_admin"), group.user_ids)

    def test_process_creates_dated_order_and_completed_delivery(self):
        now = fields.Datetime.now()
        placed = now - timedelta(days=4)
        sold = now - timedelta(days=2)
        self._place(quantity=2, when=placed)
        report = self._report([{"sold_at": sold}])

        report.action_process()

        self.assertEqual(report.state, "processed")
        self.assertEqual(len(report.sale_order_ids), 1)
        order = report.sale_order_ids
        self.assertEqual(order.date_order, sold)
        self.assertEqual(order.warehouse_id, self.depot)
        self.assertEqual(order.order_line.price_unit, 100.0)
        self.assertEqual(order.order_line.discount, 40.0)
        self.assertEqual(order.mb_depot_reported_public_total, 100.0)
        self.assertEqual(order.mb_depot_reported_net_total, 60.0)
        picking = report.picking_ids
        self.assertEqual(picking.state, "done")
        self.assertEqual(picking.date_done, sold)
        self.assertEqual(picking.move_ids.date, sold)
        self.assertEqual(picking.move_line_ids.date, sold)
        self.assertEqual(picking.move_line_ids.mb_depot_sale_date, sold.date())
        self.assertEqual(order.invoice_status, "to invoice")

    def test_historical_delivery_uses_native_stock_account_period_date(self):
        now = fields.Datetime.now()
        sold = now - timedelta(days=2)
        self._place(when=now - timedelta(days=4))
        report = self._report([{"sold_at": sold}], reference="DEPOT-ACCOUNT-DATE")
        observed_period_dates = []
        picking_model = type(self.env["stock.picking"])
        original_validate = picking_model.button_validate

        def capture_period_date(pickings):
            observed_period_dates.append(pickings.env.context.get("force_period_date"))
            return original_validate(pickings)

        with patch.object(picking_model, "button_validate", capture_period_date):
            report.action_process()

        self.assertEqual(observed_period_dates, [sold.date()])

    def test_one_reference_with_two_dates_creates_two_deliveries(self):
        now = fields.Datetime.now()
        self._place(quantity=2, when=now - timedelta(days=5))
        first = now - timedelta(days=3)
        second = now - timedelta(days=2)
        report = self._report(
            [
                {"sold_at": first},
                {"sold_at": second},
            ],
            reference="DEPOT-AUG-MULTI",
        )

        report.action_process()

        self.assertEqual(len(report.sale_order_ids), 2)
        self.assertEqual(len(report.picking_ids), 2)
        self.assertEqual(set(report.sale_order_ids.mapped("date_order")), {first, second})

    def test_two_times_on_one_local_day_share_one_delivery(self):
        now = fields.Datetime.now()
        sold_day = (now - timedelta(days=2)).replace(hour=0, minute=0, second=0)
        self._place(quantity=2, when=now - timedelta(days=5))
        report = self._report(
            [
                {"sold_at": sold_day + timedelta(hours=9)},
                {"sold_at": sold_day + timedelta(hours=17)},
            ],
            reference="DEPOT-AUG-ONE-DAY",
        )

        report.action_process()

        self.assertEqual(len(report.sale_order_ids), 1)
        self.assertEqual(len(report.picking_ids), 1)
        self.assertEqual(report.sale_order_ids.date_order, sold_day + timedelta(hours=17))

    def test_optional_invoice_uses_today_and_delivery_period(self):
        now = fields.Datetime.now()
        self._place(quantity=2, when=now - timedelta(days=5))
        report = self._report(
            [
                {"sold_at": now - timedelta(days=3)},
                {"sold_at": now - timedelta(days=2)},
            ],
            reference="DEPOT-AUG-INVOICE",
            invoice=True,
        )

        report.action_process()

        self.assertEqual(len(report.invoice_ids), 1)
        invoice = report.invoice_ids
        self.assertEqual(invoice.state, "draft")
        self.assertEqual(invoice.invoice_date, fields.Date.context_today(report))
        self.assertEqual(invoice.mb_depot_delivery_date_from, (now - timedelta(days=3)).date())
        self.assertEqual(invoice.mb_depot_delivery_date_to, (now - timedelta(days=2)).date())
        html, _html_type = self.env.ref("account.account_invoices")._render_qweb_html(
            "account.report_invoice_with_payments",
            invoice.ids,
        )
        self.assertIn(b"DEPOT-AUG-INVOICE", html)
        self.assertIn(b"Delivery period", html)

    def test_later_standard_invoice_keeps_report_and_delivery_period(self):
        now = fields.Datetime.now()
        sold = now - timedelta(days=2)
        self._place(when=now - timedelta(days=4))
        report = self._report(
            [
                {"sold_at": sold},
            ],
            reference="DEPOT-AUG-LATER-INVOICE",
        )
        report.action_process()

        invoice = report.sale_order_ids._create_invoices(grouped=False)

        self.assertEqual(invoice.mb_depot_sale_report_ids, report)
        self.assertEqual(invoice.mb_depot_sale_report_id, report)
        self.assertEqual(report.invoice_ids, invoice)
        self.assertEqual(invoice.mb_depot_delivery_date_from, sold.date())
        self.assertEqual(invoice.mb_depot_delivery_date_to, sold.date())

    def test_historical_shortage_rejects_without_documents(self):
        now = fields.Datetime.now()
        self._place(quantity=1, when=now - timedelta(days=1))
        report = self._report(
            [
                {"sold_at": now - timedelta(days=2)},
            ],
            reference="DEPOT-AUG-TOO-EARLY",
        )

        with self.assertRaisesRegex(ValidationError, "not available"):
            report.action_process()

        self.assertFalse(report.sale_order_ids)
        self.assertFalse(report.picking_ids)

    def test_historical_check_aggregates_all_lines_at_the_same_date(self):
        now = fields.Datetime.now()
        self._place(quantity=1, when=now - timedelta(days=5))
        self._place(quantity=1, when=now - timedelta(days=1))
        report = self._report(
            [
                {"sold_at": now - timedelta(days=3)},
                {"sold_at": now - timedelta(days=3)},
            ],
            reference="DEPOT-AUG-HISTORICAL-TOTAL",
        )

        with self.assertRaisesRegex(ValidationError, "not available"):
            report.action_process()

    def test_reported_price_and_commission_are_historical_evidence(self):
        now = fields.Datetime.now()
        self._place(when=now - timedelta(days=3))
        report = self._report(
            [
                {"sold_at": now - timedelta(days=2)},
            ],
            reference="DEPOT-AUG-HISTORICAL-PRICE",
        )
        self.product.list_price = 999.0
        self.depot.depot_commission = 12.0
        self.depot.depot_pricelist_id.item_ids.percent_price = 12.0

        report.action_process()

        self.assertEqual(report.sale_order_ids.order_line.price_unit, 100.0)
        self.assertEqual(report.sale_order_ids.order_line.discount, 40.0)

    def test_serial_numbers_are_reserved_exactly(self):
        now = fields.Datetime.now()
        serial_product = self.env["product.product"].create(
            {
                "name": "Unique reported vase",
                "type": "consu",
                "is_storable": True,
                "sale_ok": True,
                "invoice_policy": "delivery",
                "tracking": "serial",
                "list_price": 150.0,
            }
        )
        first = self.env["stock.lot"].create(
            {
                "name": "VASE-001",
                "product_id": serial_product.id,
            }
        )
        second = self.env["stock.lot"].create(
            {
                "name": "VASE-002",
                "product_id": serial_product.id,
            }
        )
        self._place(serial_product, lot=first, when=now - timedelta(days=4))
        self._place(serial_product, lot=second, when=now - timedelta(days=4))
        report = self._report(
            [
                {
                    "sold_at": now - timedelta(days=2),
                    "product_id": serial_product.id,
                    "lot_id": second.id,
                    "reported_public_unit_price": 150.0,
                },
            ],
            reference="DEPOT-AUG-SERIAL",
        )

        report.action_process()

        self.assertEqual(report.picking_ids.move_line_ids.lot_id, second)
        self.assertEqual(report.picking_ids.move_line_ids.quantity, 1.0)

    def test_stock_in_depot_sub_location_uses_the_exact_quant_location(self):
        now = fields.Datetime.now()
        depot_bin = self.env["stock.location"].create(
            {
                "name": "Display shelf",
                "location_id": self.depot.lot_stock_id.id,
                "usage": "internal",
                "company_id": self.env.company.id,
            }
        )
        placement = self._place(when=now - timedelta(days=4))
        relocation = self.env["stock.move"].create(
            {
                "product_id": self.product.id,
                "product_uom_qty": 1.0,
                "location_id": self.depot.lot_stock_id.id,
                "location_dest_id": depot_bin.id,
            }
        )
        relocation._action_confirm()
        relocation.move_line_ids = [
            fields.Command.create(
                {
                    "product_id": self.product.id,
                    "location_id": self.depot.lot_stock_id.id,
                    "location_dest_id": depot_bin.id,
                    "quantity": 1.0,
                    "picked": True,
                }
            )
        ]
        relocation.picked = True
        relocation._action_done()
        relocation.date = now - timedelta(days=3)
        relocation.move_line_ids.date = now - timedelta(days=3)
        self.assertTrue(placement)
        report = self._report(
            [
                {"sold_at": now - timedelta(days=2)},
            ],
            reference="DEPOT-AUG-SUB-BIN",
        )

        report.action_process()

        self.assertEqual(report.picking_ids.move_line_ids.location_id, depot_bin)

    def test_serial_that_previously_left_the_depot_is_rejected(self):
        now = fields.Datetime.now()
        serial_product = self.env["product.product"].create(
            {
                "name": "Returned serial vase",
                "type": "consu",
                "is_storable": True,
                "sale_ok": True,
                "invoice_policy": "delivery",
                "tracking": "serial",
            }
        )
        serial = self.env["stock.lot"].create(
            {
                "name": "VASE-RETURNED",
                "product_id": serial_product.id,
            }
        )
        self._place(serial_product, lot=serial, when=now - timedelta(days=6))
        customer = self.env.ref("stock.stock_location_customers")
        outbound = self.env["stock.picking"].create(
            {
                "picking_type_id": self.depot.out_type_id.id,
                "location_id": self.depot.lot_stock_id.id,
                "location_dest_id": customer.id,
            }
        )
        self.env["stock.move"].create(
            {
                "picking_id": outbound.id,
                "product_id": serial_product.id,
                "product_uom_qty": 1.0,
                "location_id": self.depot.lot_stock_id.id,
                "location_dest_id": customer.id,
            }
        )
        outbound.action_confirm()
        outbound.action_assign()
        self.assertEqual(outbound.move_line_ids.lot_id, serial)
        outbound.move_line_ids.picked = True
        self.assertFalse(isinstance(outbound.button_validate(), dict))
        outbound.date_done = now - timedelta(days=5)

        wizard = (
            self.env["stock.return.picking"]
            .with_context(
                active_model="stock.picking",
                active_id=outbound.id,
                active_ids=outbound.ids,
            )
            .create({"picking_id": outbound.id})
        )
        action = wizard.action_create_returns_all()
        returned = self.env["stock.picking"].browse(action["res_id"])
        returned.move_line_ids.picked = True
        self.assertFalse(isinstance(returned.button_validate(), dict))
        returned.date_done = now - timedelta(days=4)
        report = self._report(
            [
                {
                    "sold_at": now - timedelta(days=2),
                    "product_id": serial_product.id,
                    "lot_id": serial.id,
                }
            ],
            reference="DEPOT-AUG-SERIAL-RETURNED",
        )

        with self.assertRaisesRegex(ValidationError, "left.*before"):
            report.action_process()

    def test_reserved_stock_is_rejected(self):
        now = fields.Datetime.now()
        self._place(when=now - timedelta(days=3))
        reservation = self.env["stock.move"].create(
            {
                "product_id": self.product.id,
                "product_uom_qty": 1.0,
                "location_id": self.depot.lot_stock_id.id,
                "location_dest_id": self.env.ref("stock.stock_location_customers").id,
            }
        )
        reservation._action_confirm()
        reservation._action_assign()
        report = self._report(
            [
                {"sold_at": now - timedelta(days=2)},
            ],
            reference="DEPOT-AUG-RESERVED",
        )

        with self.assertRaisesRegex(ValidationError, "currently unreserved"):
            report.action_process()

    def test_product_picker_offers_only_unreserved_stock_at_the_depot(self):
        now = fields.Datetime.now()
        self._place(when=now - timedelta(days=1))
        elsewhere = self.env["product.product"].create(
            {
                "name": "Bowl outside the selected depot",
                "type": "consu",
                "is_storable": True,
                "sale_ok": True,
                "invoice_policy": "delivery",
            }
        )
        report = self.env["mb.depot.sale.report"].create(
            {
                "depot_warehouse_id": self.depot.id,
                "external_reference": "DEPOT-PICKER-AVAILABLE",
            }
        )

        self.assertIn(self.product, report.available_product_ids)
        self.assertNotIn(elsewhere, report.available_product_ids)

        reservation = self.env["stock.move"].create(
            {
                "product_id": self.product.id,
                "product_uom_qty": 1.0,
                "location_id": self.depot.lot_stock_id.id,
                "location_dest_id": self.env.ref("stock.stock_location_customers").id,
            }
        )
        reservation._action_confirm()
        reservation._action_assign()
        report.invalidate_recordset(["available_product_ids"])

        self.assertNotIn(self.product, report.available_product_ids)

    def test_product_picker_label_shows_available_quantity_at_the_depot(self):
        self._place(quantity=3.0)
        reservation = self.env["stock.move"].create(
            {
                "product_id": self.product.id,
                "product_uom_qty": 1.0,
                "location_id": self.depot.lot_stock_id.id,
                "location_dest_id": self.env.ref("stock.stock_location_customers").id,
            }
        )
        reservation._action_confirm()
        reservation._action_assign()

        ordinary_label = self.product.display_name
        depot_product = self.product.with_context(
            mb_depot_warehouse_id=self.depot.id,
        )
        expected_quantity = formatLang(self.env, 2.0, dp="Product Unit")

        self.assertIn(expected_quantity, depot_product.display_name)
        self.assertIn(self.product.uom_id.display_name, depot_product.display_name)
        self.assertIn(self.depot.display_name, depot_product.display_name)
        self.assertEqual(ordinary_label, self.product.display_name)

    def test_product_selection_populates_public_price_and_depot_commission(self):
        report = self.env["mb.depot.sale.report"].create(
            {
                "depot_warehouse_id": self.depot.id,
                "external_reference": "DEPOT-PICKER-PRICE",
            }
        )
        line = self.env["mb.depot.sale.report.line"].new(
            {
                "report_id": report.id,
                "product_id": self.product.id,
            }
        )

        line._onchange_product_id_commercial_values()

        self.assertEqual(line.reported_public_unit_price, self.product.list_price)
        self.assertEqual(
            line.reported_commission_percentage,
            self.depot.depot_commission,
        )

    def test_api_line_creation_defaults_missing_commercial_values(self):
        report = self.env["mb.depot.sale.report"].create(
            {
                "depot_warehouse_id": self.depot.id,
                "external_reference": "DEPOT-API-PRICE",
            }
        )

        line = self.env["mb.depot.sale.report.line"].create(
            {
                "report_id": report.id,
                "sold_at": fields.Datetime.now(),
                "product_id": self.product.id,
                "quantity": 1.0,
            }
        )

        self.assertEqual(line.reported_public_unit_price, self.product.list_price)
        self.assertEqual(
            line.reported_commission_percentage,
            self.depot.depot_commission,
        )

    def test_explicit_reported_commercial_values_are_preserved(self):
        report = self.env["mb.depot.sale.report"].create(
            {
                "depot_warehouse_id": self.depot.id,
                "external_reference": "DEPOT-EXPLICIT-PRICE",
            }
        )

        line = self.env["mb.depot.sale.report.line"].create(
            {
                "report_id": report.id,
                "sold_at": fields.Datetime.now(),
                "product_id": self.product.id,
                "quantity": 1.0,
                "reported_public_unit_price": 90.0,
                "reported_commission_percentage": 25.0,
            }
        )

        self.assertEqual(line.reported_public_unit_price, 90.0)
        self.assertEqual(line.reported_commission_percentage, 25.0)

    def test_lot_picker_offers_only_available_serials_at_the_depot(self):
        product = self.env["product.product"].create(
            {
                "name": "Serialised depot bowl",
                "type": "consu",
                "is_storable": True,
                "sale_ok": True,
                "invoice_policy": "delivery",
                "tracking": "serial",
            }
        )
        available_lot = self.env["stock.lot"].create(
            {
                "name": "DEPOT-SERIAL-AVAILABLE",
                "product_id": product.id,
            }
        )
        elsewhere_lot = self.env["stock.lot"].create(
            {
                "name": "DEPOT-SERIAL-ELSEWHERE",
                "product_id": product.id,
            }
        )
        self._place(product=product, lot=available_lot)
        report = self._report(
            [
                {
                    "sold_at": fields.Datetime.now() - timedelta(hours=1),
                    "product_id": product.id,
                    "lot_id": available_lot.id,
                }
            ],
            reference="DEPOT-PICKER-SERIAL",
        )

        self.assertIn(available_lot, report.line_ids.available_lot_ids)
        self.assertNotIn(elsewhere_lot, report.line_ids.available_lot_ids)

    def test_accounting_and_inventory_closings_block_dates(self):
        now = fields.Datetime.now()
        sold = now - timedelta(days=2)
        report = self._report([{"sold_at": sold}], reference="DEPOT-AUG-CLOSED")
        self.env.company.mb_depot_stock_closed_through = sold.date()
        with self.assertRaisesRegex(ValidationError, "permanently closed"):
            report._validate_dates()

    def test_sales_accounting_lock_blocks_dates(self):
        sold = fields.Datetime.now() - timedelta(days=2)
        report = self._report([{"sold_at": sold}], reference="DEPOT-AUG-SALES-LOCK")
        self.env.company.sale_lock_date = sold.date()
        with self.assertRaisesRegex(ValidationError, "permanently closed"):
            report._validate_dates()

    def test_future_date_is_rejected(self):
        report = self._report(
            [
                {
                    "sold_at": fields.Datetime.now() + timedelta(days=1),
                }
            ],
            reference="DEPOT-AUG-FUTURE",
        )
        with self.assertRaisesRegex(ValidationError, "future"):
            report._validate_dates()

    def test_mandate_depot_is_rejected_before_document_creation(self):
        gallery = self.env["res.partner"].create(
            {
                "name": "Mandate report gallery",
                "is_company": True,
            }
        )
        self.env["mb.depot.create"].create(
            {
                "partner_id": gallery.id,
                "commission": 40.0,
                "legal_structure": "mandate",
            }
        ).action_create()
        mandate = (
            self.env["stock.warehouse"]
            .search(
                [
                    ("is_depot", "=", True),
                    ("depot_partner_id", "=", gallery.id),
                ]
            )
            .ensure_one()
        )
        report = self.env["mb.depot.sale.report"].create(
            {
                "depot_warehouse_id": mandate.id,
                "external_reference": "MANDATE-REPORT",
                "line_ids": [
                    fields.Command.create(
                        {
                            "sold_at": fields.Datetime.now() - timedelta(days=1),
                            "product_id": self.product.id,
                            "quantity": 1.0,
                            "reported_public_unit_price": 100.0,
                            "reported_commission_percentage": 40.0,
                        }
                    )
                ],
            }
        )
        with self.assertRaisesRegex(ValidationError, "Purchase-resale"):
            report._validate_configuration()

    def test_company_timezone_decides_the_closed_local_date(self):
        self.env.company.partner_id.tz = "Europe/Paris"
        self.env.company.mb_depot_stock_closed_through = fields.Date.to_date("2026-08-01")
        report = self._report(
            [
                {
                    "sold_at": fields.Datetime.to_datetime("2026-07-31 22:30:00"),
                }
            ],
            reference="DEPOT-AUG-TIMEZONE",
        )
        with self.assertRaisesRegex(ValidationError, "permanently closed"):
            report._validate_dates()

    def test_downstream_failure_rolls_back_generated_documents(self):
        now = fields.Datetime.now()
        self._place(when=now - timedelta(days=3))
        report = self._report(
            [
                {"sold_at": now - timedelta(days=2)},
            ],
            reference="DEPOT-AUG-ROLLBACK",
        )

        with (
            self.assertRaisesRegex(UserError, "forced validation failure"),
            self.env.cr.savepoint(),
            patch.object(
                type(self.env["stock.picking"]),
                "button_validate",
                side_effect=UserError("forced validation failure"),
            ),
        ):
            report.action_process()

        report.invalidate_recordset()
        self.assertEqual(report.state, "draft")
        self.assertFalse(
            self.env["sale.order"].search(
                [
                    ("mb_depot_sale_report_id", "=", report.id),
                ]
            )
        )
        self.assertFalse(
            self.env["stock.picking"].search(
                [
                    ("mb_depot_sale_report_id", "=", report.id),
                ]
            )
        )

    def test_depot_sale_manager_can_process_without_accounting_access(self):
        now = fields.Datetime.now()
        self._place(when=now - timedelta(days=3))
        manager = self.env["res.users"].create(
            {
                "name": "Depot workflow manager",
                "login": "depot-workflow-manager",
                "group_ids": [
                    fields.Command.set(self.env.ref("mb_depot.group_depot_sale_manager").ids)
                ],
            }
        )
        report = self._report(
            [
                {"sold_at": now - timedelta(days=2)},
            ],
            reference="DEPOT-AUG-PERMISSION",
        )

        report.with_user(manager).action_process()

        self.assertEqual(report.state, "processed")

    def test_non_manager_and_non_accountant_are_rejected_server_side(self):
        ordinary = self.env["res.users"].create(
            {
                "name": "Ordinary depot observer",
                "login": "ordinary-depot-observer",
                "group_ids": [fields.Command.set(self.env.ref("stock.group_stock_user").ids)],
            }
        )
        manager = self.env["res.users"].create(
            {
                "name": "Depot manager without invoices",
                "login": "depot-no-invoice",
                "group_ids": [
                    fields.Command.set(self.env.ref("mb_depot.group_depot_sale_manager").ids)
                ],
            }
        )
        report = self._report(
            [
                {
                    "sold_at": fields.Datetime.now() - timedelta(days=1),
                }
            ],
            reference="DEPOT-AUG-DENIED",
        )

        with self.assertRaises(AccessError):
            report.with_user(ordinary).action_process()
        with self.assertRaises(AccessError):
            report.with_user(manager).write({"create_draft_invoice": True})
        with self.assertRaises(AccessError):
            report.with_user(manager).action_view_invoices()
        with self.assertRaises(AccessError):
            report.with_user(manager).action_view_credit_notes()

    def test_report_record_rule_respects_allowed_companies(self):
        other_company = self.env["res.company"].create({"name": "Other depot company"})
        report = self.env["mb.depot.sale.report"].create(
            {
                "company_id": other_company.id,
                "depot_warehouse_id": self.depot.id,
                "external_reference": "OTHER-COMPANY-REPORT",
            }
        )
        manager = self.env["res.users"].create(
            {
                "name": "Single-company depot manager",
                "login": "single-company-depot-manager",
                "company_id": self.env.company.id,
                "company_ids": [fields.Command.set(self.env.company.ids)],
                "group_ids": [
                    fields.Command.set(self.env.ref("mb_depot.group_depot_sale_manager").ids)
                ],
            }
        )

        with self.assertRaises(AccessError):
            report.with_user(manager).read(["name"])

    def test_processed_report_and_lines_are_immutable(self):
        now = fields.Datetime.now()
        self._place(when=now - timedelta(days=3))
        report = self._report(
            [
                {"sold_at": now - timedelta(days=2)},
            ],
            reference="DEPOT-AUG-LOCK",
        )
        report.action_process()

        with self.assertRaisesRegex(UserError, "immutable"):
            report.write({"note": "changed"})
        with self.assertRaisesRegex(UserError, "immutable"):
            report.line_ids.write({"reported_public_unit_price": 1})
        with self.assertRaisesRegex(UserError, "cannot be deleted"):
            report.line_ids.unlink()
        with self.assertRaisesRegex(UserError, "workflow buttons"):
            report.state = "reversed"
        with self.assertRaisesRegex(UserError, "workflow buttons"):
            report.with_context(mb_depot_processing=True).state = "reversed"
        with self.assertRaisesRegex(UserError, "reason"):
            report.action_start_reversal()
        report.reversal_reason = "Depositary corrected its statement"
        report.action_start_reversal()
        self.assertEqual(report.state, "reversal_required")

    def test_completed_standard_return_marks_report_reversed(self):
        now = fields.Datetime.now()
        self._place(when=now - timedelta(days=3))
        report = self._report(
            [
                {"sold_at": now - timedelta(days=2)},
            ],
            reference="DEPOT-AUG-RETURN",
        )
        report.action_process()
        original_picking = report.picking_ids
        report.reversal_reason = "Depositary cancelled the reported sale"
        report.action_start_reversal()

        wizard = (
            self.env["stock.return.picking"]
            .with_context(
                active_model="stock.picking",
                active_id=original_picking.id,
                active_ids=original_picking.ids,
            )
            .create({"picking_id": original_picking.id})
        )
        action = wizard.action_create_returns_all()
        return_picking = self.env["stock.picking"].browse(action["res_id"])
        return_picking.move_line_ids.quantity = 1.0
        return_picking.move_line_ids.picked = True
        return_picking.move_ids.picked = True
        result = return_picking.with_context(
            skip_backorder=True,
            cancel_backorder=True,
        ).button_validate()
        self.assertFalse(isinstance(result, dict))

        report.action_mark_reversed()

        self.assertEqual(report.state, "reversed")
        self.assertEqual(report.return_picking_ids, return_picking)
        with self.assertRaisesRegex(UserError, "immutable"):
            report.reversal_reason = "Changed after completion"

    def test_duplicate_reference_is_rejected(self):
        sold = fields.Datetime.now() - timedelta(days=1)
        self._report([{"sold_at": sold}], reference="DUPLICATE")
        with self.assertRaisesRegex(UserError, "already belongs"):
            self._report([{"sold_at": sold}], reference="DUPLICATE")

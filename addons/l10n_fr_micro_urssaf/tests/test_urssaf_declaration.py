from datetime import date

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged

from ..models.internal import internal_context


@tagged("post_install", "-at_install")
class TestUrssafDeclaration(TransactionCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = cls.env.company
		france = cls.env.ref("base.fr")
		cls.company.write({
			"country_id": france.id,
			"account_fiscal_country_id": france.id,
			"l10n_fr_micro_activity_start_date": date(2026, 3, 6),
			"l10n_fr_micro_urssaf_tracking_start_date": date(2026, 3, 6),
			"l10n_fr_micro_urssaf_periodicity": "monthly",
			"l10n_fr_micro_accounting_responsible_id": cls.env.user.id,
			"l10n_fr_micro_cfp_kind": "artisan",
			"l10n_fr_micro_chamber_kind": "cma",
			"l10n_fr_micro_chamber_zone": "general",
		})
		if cls.company.chart_template != "fr":
			cls.env["account.chart.template"].sudo().try_loading(
				"fr", company=cls.company, install_demo=False,
			)
			cls.company = cls.env["res.company"].browse(cls.company.id)
		cls.company._l10n_fr_micro_prepare_tax_setup()
		cls.partner = cls.env["res.partner"].create({"name": "URSSAF receipt customer"})
		cls.bank_journal = cls.env["account.journal"].search([
			("company_id", "=", cls.company.id), ("type", "=", "bank"),
		], limit=1)
		cls.bank_journal.l10n_fr_micro_receipt_method = "transfer"

	def _declaration(self):
		return self.env["l10n.fr.micro.urssaf.declaration"].create({
			"company_id": self.company.id,
			"date_from": date(2026, 3, 6),
			"date_to": date(2026, 6, 30),
			"periodicity": "monthly",
		})

	def _pay(self, invoice, amount, payment_date):
		return self.env["account.payment.register"].with_context(
			active_model="account.move", active_ids=invoice.ids,
		).create({
			"payment_date": payment_date,
			"journal_id": self.bank_journal.id,
			"amount": amount,
		}).action_create_payments()

	def _deliver(self, sale_line, delivered_on, quantity=1):
		warehouse = self.env["stock.warehouse"].search([
			("company_id", "=", self.company.id),
		], limit=1)
		customer = self.env.ref("stock.stock_location_customers")
		move = self.env["stock.move"].create({
			"product_id": sale_line.product_id.id,
			"product_uom_qty": quantity,
			"location_id": warehouse.lot_stock_id.id,
			"location_dest_id": customer.id,
			"sale_line_id": sale_line.id,
		})
		move._action_confirm()
		move.move_line_ids = [fields.Command.create({
			"product_id": sale_line.product_id.id,
			"location_id": warehouse.lot_stock_id.id,
			"location_dest_id": customer.id,
			"quantity": quantity,
		})]
		move.picked = True
		move._action_done()
		move.date = delivered_on
		return move

	def test_dated_rates_and_acre_rules(self):
		Rate = self.env["l10n.fr.micro.urssaf.rate"]
		self.assertEqual(Rate.rate_for("cotisation", "bic_goods", date(2026, 8, 1), self.company).rate, 12.3)
		self.assertEqual(Rate.rate_for("cotisation", "bic_service", date(2026, 8, 1), self.company).rate, 21.2)
		self.assertEqual(Rate.rate_for("cotisation", "bnc", date(2026, 8, 1), self.company).rate, 25.6)
		self.assertEqual(Rate.rate_for("cfp", "bnc", date(2026, 8, 1), self.company).rate, 0.2)
		self.company.action_l10n_fr_micro_apply_acre_rule()
		self.assertEqual(self.company.l10n_fr_micro_acre_coefficient, 0.5)
		self.assertEqual(self.company.l10n_fr_micro_acre_to, date(2026, 12, 31))
		self.company.write({
			"l10n_fr_micro_activity_start_date": date(2026, 7, 1),
			"l10n_fr_micro_urssaf_tracking_start_date": date(2026, 7, 1),
		})
		self.company.action_l10n_fr_micro_apply_acre_rule()
		self.assertEqual(self.company.l10n_fr_micro_acre_coefficient, 0.75)
		self.assertEqual(self.company.l10n_fr_micro_acre_to, date(2027, 6, 30))

	def test_first_monthly_period_is_deferred(self):
		defaults = self.env["l10n.fr.micro.urssaf.declaration"].default_get([
			"company_id", "periodicity", "date_from", "date_to",
		])
		self.assertEqual(defaults["date_from"], date(2026, 3, 6))
		self.assertEqual(defaults["date_to"], date(2026, 6, 30))

	def test_filing_permanently_closes_depot_sale_dates(self):
		declaration = self._declaration()
		declaration.action_file()
		self.assertEqual(
			self.company.l10n_fr_micro_depot_sale_closed_through,
			date(2026, 6, 30),
		)

		declaration.reset_reason = "Correct the filed declaration"
		declaration.action_reset_to_draft()
		self.assertEqual(declaration.state, "draft")
		self.assertEqual(
			self.company.l10n_fr_micro_depot_sale_closed_through,
			date(2026, 6, 30),
			"reopening the declaration must not reopen depot-sale dates",
		)
		with self.assertRaisesRegex(ValidationError, "cannot be reduced"):
			self.company.l10n_fr_micro_depot_sale_closed_through = date(2026, 5, 31)
		self.company._l10n_fr_micro_advance_depot_sale_horizon(date(2026, 5, 31))
		self.assertEqual(
			self.company.l10n_fr_micro_depot_sale_closed_through,
			date(2026, 6, 30),
			"filing an older period must leave the later permanent horizon intact",
		)

	def test_filed_horizon_blocks_depot_report_even_after_reset(self):
		declaration = self._declaration()
		declaration.action_file()
		declaration.reset_reason = "Accounting correction only"
		declaration.action_reset_to_draft()
		self.company.action_l10n_fr_micro_confirm_depot_sale_horizon()
		gallery = self.env["res.partner"].create({
			"name": "Closed-period gallery", "is_company": True,
		})
		self.env["mb.depot.create"].create({
			"partner_id": gallery.id,
			"commission": 40.0,
			"legal_structure": "resale",
		}).action_create()
		depot = self.env["stock.warehouse"].search([
			("is_depot", "=", True), ("depot_partner_id", "=", gallery.id),
		]).ensure_one()
		product = self.env["product.product"].create({
			"name": "Late reported bowl", "type": "consu", "is_storable": True,
			"invoice_policy": "delivery", "list_price": 100.0,
		})
		report = self.env["mb.depot.sale.report"].create({
			"depot_warehouse_id": depot.id,
			"external_reference": "CLOSED-URSSAF-001",
			"line_ids": [fields.Command.create({
				"sold_at": fields.Datetime.to_datetime("2026-06-15 12:00:00"),
				"product_id": product.id,
				"quantity": 1.0,
				"reported_public_unit_price": 100.0,
				"reported_commission_percentage": 40.0,
			})],
		})

		with self.assertRaisesRegex(ValidationError, "permanently closed"):
			report._validate_dates()
		self.env.user.group_ids |= self.env.ref("mb_depot.group_depot_sale_manager")
		for user in (self.env.user, self.env.ref("base.user_root")):
			with self.assertRaisesRegex(ValidationError, "permanently closed"):
				report.with_user(user).action_process()

	def test_unconfirmed_migrated_horizon_blocks_depot_processing(self):
		self.company.with_context(**internal_context()).write({
			"l10n_fr_micro_depot_sale_horizon_confirmed": False,
		})
		report = self.env["mb.depot.sale.report"].new({"company_id": self.company.id})
		with self.assertRaisesRegex(ValidationError, "must confirm"):
			report._validate_closed_period_configuration()

	def test_depot_invoice_is_urssaf_turnover_only_when_paid(self):
		self.env.user.group_ids |= self.env.ref("mb_depot.group_depot_sale_manager")
		self.company.action_l10n_fr_micro_confirm_depot_sale_horizon()
		gallery = self.env["res.partner"].create({
			"name": "Paid consolidated depot", "is_company": True,
		})
		self.env["mb.depot.create"].create({
			"partner_id": gallery.id,
			"commission": 40.0,
			"legal_structure": "resale",
		}).action_create()
		depot = self.env["stock.warehouse"].search([
			("is_depot", "=", True), ("depot_partner_id", "=", gallery.id),
		]).ensure_one()
		home = self.env["stock.warehouse"].search([
			("company_id", "=", self.company.id), ("id", "!=", depot.id),
		], limit=1)
		product = self.env["product.product"].create({
			"name": "Paid depot bowl", "type": "consu", "is_storable": True,
			"invoice_policy": "delivery", "list_price": 100.0,
			"taxes_id": [fields.Command.set(self.company.l10n_fr_micro_goods_tax_id.ids)],
		})
		placement = self.env["stock.move"].create({
			"product_id": product.id,
			"product_uom_qty": 1.0,
			"location_id": home.lot_stock_id.id,
			"location_dest_id": depot.lot_stock_id.id,
		})
		placement._action_confirm()
		placement.move_line_ids = [fields.Command.create({
			"product_id": product.id,
			"location_id": home.lot_stock_id.id,
			"location_dest_id": depot.lot_stock_id.id,
			"quantity": 1.0,
			"picked": True,
		})]
		placement.picked = True
		placement._action_done()
		placement.write({"date": fields.Datetime.to_datetime("2026-07-20 12:00:00")})
		placement.move_line_ids.date = fields.Datetime.to_datetime("2026-07-20 12:00:00")
		report = self.env["mb.depot.sale.report"].create({
			"depot_warehouse_id": depot.id,
			"external_reference": "PAYMENT-CABA-001",
			"create_draft_invoice": True,
			"line_ids": [fields.Command.create({
				"sold_at": fields.Datetime.to_datetime("2026-08-01 12:00:00"),
				"product_id": product.id,
				"quantity": 1.0,
				"reported_public_unit_price": 100.0,
				"reported_commission_percentage": 40.0,
			})],
		})
		report.action_process()
		invoice = report.invoice_ids
		invoice.action_post()
		declaration = self.env["l10n.fr.micro.urssaf.declaration"].create({
			"company_id": self.company.id,
			"date_from": date(2026, 8, 1),
			"date_to": date(2026, 8, 31),
			"periodicity": "monthly",
		})

		declaration.action_compute()
		self.assertEqual(declaration.total_declared, 0.0)
		self._pay(invoice, invoice.amount_total, date(2026, 8, 9))
		declaration.action_compute()

		goods = declaration.line_ids.filtered(lambda line: line.category == "bic_goods")
		self.assertEqual(goods.declared_turnover, 60.0)

	def test_root_menu_is_available_to_accounting_managers(self):
		menu = self.env.ref("l10n_fr_micro_urssaf.menu_urssaf_root")
		self.assertIn(self.env.ref("account.group_account_manager"), menu.group_ids)

	def test_recompute_preserves_reasoned_adjustment(self):
		declaration = self._declaration()
		declaration.action_compute()
		line = declaration.line_ids.filtered(lambda item: item.category == "bic_goods")
		line.write({"manual_adjustment": 25.0, "manual_adjustment_reason": "URSSAF written guidance"})
		declaration.action_compute()
		line = declaration.line_ids.filtered(lambda item: item.category == "bic_goods")
		self.assertEqual(line.manual_adjustment, 25.0)
		self.assertEqual(line.manual_adjustment_reason, "URSSAF written guidance")
		self.assertEqual(line.declared_turnover, 25.0)

	def test_negative_category_proposes_zero_and_blocks(self):
		declaration = self._declaration()
		declaration.action_compute()
		line = declaration.line_ids.filtered(lambda item: item.category == "bic_goods")
		line.write({
			"manual_adjustment": -10.0,
			"manual_adjustment_reason": "Refund treatment pending URSSAF confirmation",
		})
		declaration.action_compute()
		line = declaration.line_ids.filtered(lambda item: item.category == "bic_goods")
		self.assertEqual(line.declared_turnover, 0.0)
		self.assertTrue(declaration.blocking_anomaly)

	def test_filing_aid_report_renders(self):
		declaration = self._declaration()
		declaration.action_compute()
		goods_line = declaration.line_ids.filtered(lambda item: item.category == "bic_goods")
		self.env["l10n.fr.micro.urssaf.declaration.source"].create({
			"declaration_id": declaration.id,
			"declaration_line_id": goods_line.id,
			"event_key": "pos:test-report:bic_goods",
			"recognition_date": date(2026, 4, 2),
			"category": "bic_goods",
			"amount": 12.0,
			"engine": "pos",
			"receipt_method": "cash",
		})
		html, _html_type = self.env.ref(
			"l10n_fr_micro_urssaf.action_report_urssaf_declaration"
		)._render_qweb_html(
			"l10n_fr_micro_urssaf.report_urssaf_declaration", declaration.ids,
		)
		self.assertIn(b"URSSAF turnover declaration", html)
		self.assertIn(b"Livre des recettes", html)
		self.assertIn(b"Daily POS receipt summaries", html)
		self.assertEqual(declaration._pos_daily_summaries()[0]["amount"], 12.0)

	def test_invoice_is_recognised_when_paid_not_when_invoiced(self):
		invoice = self.env["account.move"].create({
			"company_id": self.company.id,
			"move_type": "out_invoice",
			"partner_id": self.partner.id,
			"invoice_date": date(2026, 11, 15),
			"invoice_line_ids": [(0, 0, {
				"name": "Ceramic cup", "quantity": 1, "price_unit": 100,
				"tax_ids": [(6, 0, self.company.l10n_fr_micro_goods_tax_id.ids)],
			})],
		})
		invoice.action_post()
		self._pay(invoice, invoice.amount_total, date(2027, 1, 5))
		Declaration = self.env["l10n.fr.micro.urssaf.declaration"]
		self.assertFalse(Declaration._recognition_events(
			self.company, date(2026, 11, 1), date(2026, 11, 30),
		))
		events = Declaration._recognition_events(
			self.company, date(2027, 1, 1), date(2027, 1, 31),
		)
		goods = [event for event in events if event["category"] == "bic_goods"]
		self.assertEqual(sum(event["amount"] for event in goods), 100.0)
		self.assertEqual({event["receipt_method"] for event in goods}, {"transfer"})

	def test_post_vat_partial_mixed_invoice_clears_rounding_residual(self):
		goods_tax = self.company.l10n_fr_micro_goods_tax_id.original_tax_ids[:1]
		service_tax = self.company.l10n_fr_micro_service_tax_id.original_tax_ids[:1]
		self.assertEqual(goods_tax.l10n_fr_micro_urssaf_category, "bic_goods")
		self.assertEqual(service_tax.l10n_fr_micro_urssaf_category, "bic_service")
		goods_product = self.env["product.product"].create({
			"name": "Mixed invoice goods", "type": "consu",
		})
		service_product = self.env["product.product"].create({
			"name": "Mixed invoice service", "type": "service",
		})
		invoice = self.env["account.move"].create({
			"company_id": self.company.id,
			"move_type": "out_invoice",
			"partner_id": self.partner.id,
			"invoice_date": date(2027, 1, 2),
			"invoice_line_ids": [
				(0, 0, {"name": "Goods", "product_id": goods_product.id, "quantity": 1, "price_unit": 60,
					"tax_ids": [(6, 0, goods_tax.ids)]}),
				(0, 0, {"name": "Service", "product_id": service_product.id, "quantity": 1, "price_unit": 40,
					"tax_ids": [(6, 0, service_tax.ids)]}),
			],
		})
		self.assertEqual(
			invoice.invoice_line_ids.filtered(lambda line: line.name == "Goods").tax_ids,
			goods_tax,
		)
		invoice.action_post()
		self.assertEqual(
			self.env["l10n.fr.micro.urssaf.declaration"]._invoice_category_totals(invoice),
			{"bic_goods": 60.0, "bic_service": 40.0},
		)
		self._pay(invoice, 33.0, date(2027, 1, 10))
		self._pay(invoice, invoice.amount_residual, date(2027, 2, 10))
		events = self.env["l10n.fr.micro.urssaf.declaration"]._recognition_events(
			self.company, date(2027, 1, 1), date(2027, 2, 28),
		)
		by_category = {
			category: sum(event["amount"] for event in events if event["category"] == category)
			for category in ("bic_goods", "bic_service")
		}
		self.assertEqual(by_category, {"bic_goods": 60.0, "bic_service": 40.0})

	def test_caba_final_payment_only_normalizes_the_cross_year_residual(self):
		invoice = self.env["account.move"].create({
			"company_id": self.company.id,
			"move_type": "out_invoice",
			"partner_id": self.partner.id,
			"invoice_date": date(2026, 12, 10),
			"invoice_line_ids": [fields.Command.create({
				"name": "Cross-year service", "quantity": 1, "price_unit": 100,
				"tax_ids": [fields.Command.set(self.company.l10n_fr_micro_service_tax_id.ids)],
			})],
		})
		invoice.action_post()
		self._pay(invoice, 40.0, date(2026, 12, 20))
		self._pay(invoice, 60.0, date(2027, 1, 10))
		events = self.env["l10n.fr.micro.urssaf.declaration"]._vat_threshold_events(
			self.company, date(2027, 1, 1), date(2027, 1, 31),
		)
		service_events = [event for event in events if event["category"] == "bic_service"]
		self.assertEqual(sum(event["amount"] for event in service_events), 60.0)
		self.assertEqual({event["date"] for event in service_events}, {date(2027, 1, 10)})

	def test_vat_goods_stream_splits_invoice_over_delivery_events(self):
		product = self.env["product.product"].create({
			"name": "Two-delivery VAT evidence", "type": "consu", "is_storable": True,
		})
		order = self.env["sale.order"].create({
			"partner_id": self.partner.id,
			"order_line": [fields.Command.create({
				"product_id": product.id, "product_uom_qty": 2, "price_unit": 100,
			})],
		})
		for delivered_on in (date(2026, 4, 2), date(2026, 5, 3)):
			self._deliver(order.order_line, delivered_on)
		invoice = self.env["account.move"].create({
			"company_id": self.company.id,
			"move_type": "out_invoice",
			"partner_id": self.partner.id,
			"invoice_date": date(2026, 5, 5),
			"invoice_line_ids": [fields.Command.create({
				"name": "Two deliveries", "product_id": product.id,
				"quantity": 2, "price_unit": 100,
				"tax_ids": [fields.Command.set(self.company.l10n_fr_micro_goods_tax_id.ids)],
				"sale_line_ids": [fields.Command.set(order.order_line.ids)],
			})],
		})
		line = invoice.invoice_line_ids
		events = self.env["l10n.fr.micro.urssaf.declaration"]._vat_goods_events_for_line(line)
		self.assertEqual([event["date"] for event in events], [date(2026, 4, 2), date(2026, 5, 3)])
		self.assertEqual([event["amount"] for event in events], [100.0, 100.0])

	def test_vat_goods_installment_invoices_keep_their_delivery_slots(self):
		product = self.env["product.product"].create({
			"name": "Installment delivery VAT evidence", "type": "consu", "is_storable": True,
		})
		order = self.env["sale.order"].create({
			"partner_id": self.partner.id,
			"order_line": [fields.Command.create({
				"product_id": product.id, "product_uom_qty": 2, "price_unit": 100,
			})],
		})
		self._deliver(order.order_line, date(2027, 1, 5))
		self._deliver(order.order_line, date(2027, 2, 6))
		invoice_lines = []
		for invoice_date in (date(2027, 1, 10), date(2027, 2, 10)):
			invoice = self.env["account.move"].create({
				"company_id": self.company.id,
				"move_type": "out_invoice",
				"partner_id": self.partner.id,
				"invoice_date": invoice_date,
				"invoice_line_ids": [fields.Command.create({
					"name": "Installment", "product_id": product.id,
					"quantity": 1, "price_unit": 100,
					"tax_ids": [fields.Command.set(self.company.l10n_fr_micro_goods_tax_id.ids)],
					"sale_line_ids": [fields.Command.set(order.order_line.ids)],
				})],
			})
			invoice.action_post()
			invoice_lines.append(invoice.invoice_line_ids)
		Declaration = self.env["l10n.fr.micro.urssaf.declaration"]
		first_events = Declaration._vat_goods_events_for_line(invoice_lines[0])
		second_events = Declaration._vat_goods_events_for_line(invoice_lines[1])
		self.assertEqual([(event["date"], event["amount"]) for event in first_events], [
			(date(2027, 1, 5), 100.0),
		])
		self.assertEqual([(event["date"], event["amount"]) for event in second_events], [
			(date(2027, 2, 6), 100.0),
		])

	def test_levies_round_once_per_rate_compatible_base(self):
		declaration = self._declaration()
		declaration.action_compute()
		goods = declaration.line_ids.filtered(lambda item: item.category == "bic_goods")
		self.env["l10n.fr.micro.urssaf.declaration.source"].create([{
			"declaration_id": declaration.id,
			"declaration_line_id": goods.id,
			"event_key": f"rounding:{index}",
			"recognition_date": date(2026, 4, 1),
			"category": "bic_goods",
			"amount": 9.99,
			"engine": "reconciliation",
			"receipt_method": "transfer",
			"cotisation_rate": 12.3,
			"acre_coefficient": 1.0,
			"cotisation_amount": 1.23,
		} for index in range(100)])
		goods._refresh_amounts()
		self.assertEqual(goods.declared_turnover, 999.0)
		self.assertEqual(goods.cotisation_amount, 122.88)

	def test_filed_snapshot_is_immutable_but_reason_can_be_entered(self):
		declaration = self._declaration()
		with self.assertRaises(AccessError):
			declaration.with_context(urssaf_reset=True).write({"state": "filed"})
		declaration.action_file()
		with self.assertRaises(UserError):
			declaration.write({"date_to": date(2026, 7, 31)})
		with self.assertRaises(UserError):
			declaration.line_ids[0].write({"manual_adjustment": 1.0})
		with self.assertRaises(UserError):
			declaration.with_context(urssaf_reset=True).write({"date_to": date(2026, 7, 31)})
		with self.assertRaises(AccessError):
			declaration.with_context(urssaf_reset=True).write({"state": "draft"})
		with self.assertRaises(UserError):
			declaration.line_ids[0].with_context(
				urssaf_reset=True, urssaf_compute=True,
			).write({"manual_adjustment": 1.0})
		with self.assertRaises(UserError):
			self.env["l10n.fr.micro.urssaf.declaration.line"].create({
				"declaration_id": declaration.id, "category": "bic_goods",
			})
		declaration.reset_reason = "Correction requested by URSSAF"
		declaration.action_reset_to_draft()
		self.assertEqual(declaration.state, "draft")

	def test_source_must_match_declaration_and_category(self):
		declaration = self._declaration()
		declaration.action_compute()
		goods = declaration.line_ids.filtered(lambda item: item.category == "bic_goods")
		with self.assertRaises(ValidationError):
			self.env["l10n.fr.micro.urssaf.declaration.source"].create({
				"declaration_id": declaration.id,
				"declaration_line_id": goods.id,
				"event_key": "test:wrong-category",
				"recognition_date": date(2026, 4, 1),
				"category": "bnc",
				"amount": 10.0,
				"engine": "reconciliation",
				"receipt_method": "transfer",
			})

	def test_threshold_activity_is_idempotent_across_declarations(self):
		first = self._declaration()
		second = self.env["l10n.fr.micro.urssaf.declaration"].create({
			"company_id": self.company.id,
			"date_from": date(2026, 7, 1),
			"date_to": date(2026, 7, 31),
			"periodicity": "monthly",
		})
		first._ensure_vat_activity(date(2026, 5, 2))
		second._ensure_vat_activity(date(2026, 5, 2))
		model_id = self.env["ir.model"]._get_id("res.company")
		activities = self.env["mail.activity"].search([
			("res_model_id", "=", model_id),
			("res_id", "=", self.company.id),
			("summary", "=", "Review VAT-franchise threshold crossing"),
		])
		self.assertEqual(len(activities), 1)

	def test_annual_vat_uses_filed_snapshot_and_computed_values_are_guarded(self):
		declaration = self.env["l10n.fr.micro.urssaf.declaration"].create({
			"company_id": self.company.id,
			"date_from": date(2026, 3, 6),
			"date_to": date(2026, 12, 31),
			"periodicity": "monthly",
		})
		declaration.action_compute()
		goods = declaration.line_ids.filtered(lambda line: line.category == "bic_goods")
		goods.write({
			"manual_adjustment": 25.0,
			"manual_adjustment_reason": "Filed annual correction",
		})
		declaration.with_context(**internal_context()).write({
			"state": "filed", "vat_ytd_global": 123.0, "vat_ytd_services": 45.0,
		})
		annual = self.env["l10n.fr.micro.urssaf.annual"].create({
			"company_id": self.company.id, "year": 2026,
		})
		annual.action_compute()
		self.assertEqual((annual.vat_global, annual.vat_services), (123.0, 45.0))
		self.assertEqual((annual.urssaf_goods, annual.urssaf_total), (25.0, 25.0))
		with self.assertRaises(ValidationError):
			annual.write({"vat_global": 999.0})
		annual.write({"source": "manual", "manual_reason": "Opening evidence", "vat_global": 999.0})
		self.assertEqual(annual.vat_global, 999.0)

	def test_setup_wizard_derives_acre_rule(self):
		wizard = self.env["l10n.fr.micro.urssaf.setup.wizard"].create({
			"company_id": self.company.id,
			"activity_start_date": date(2026, 7, 1),
			"tracking_start_date": date(2026, 7, 1),
			"periodicity": "quarterly",
			"accounting_responsible_id": self.env.user.id,
			"acre_granted": True,
		})
		wizard.action_apply()
		self.assertEqual(self.company.l10n_fr_micro_acre_coefficient, 0.75)
		self.assertEqual(self.company.l10n_fr_micro_acre_to, date(2027, 6, 30))
		self.assertEqual(self.company.l10n_fr_micro_urssaf_periodicity, "quarterly")

	def test_accounting_user_can_recompute_but_cannot_file_or_adjust(self):
		accountant = self.env["res.users"].create({
			"name": "URSSAF accountant",
			"login": "urssaf-accountant@example.test",
			"company_id": self.company.id,
			"company_ids": [fields.Command.set(self.company.ids)],
			"group_ids": [fields.Command.set(self.env.ref("account.group_account_user").ids)],
		})
		declaration = self._declaration().with_user(accountant)
		declaration.action_compute()
		self.assertEqual(len(declaration.line_ids), 3)
		with self.assertRaises(AccessError):
			declaration.action_file()
		with self.assertRaises(AccessError):
			declaration.line_ids[0].write({
				"manual_adjustment": 1.0, "manual_adjustment_reason": "Not manager",
			})

	def test_unreviewed_mandate_blocks_declaration(self):
		gallery = self.env["res.partner"].create({
			"name": "URSSAF mandate gallery", "is_company": True,
		})
		self.env["mb.depot.create"].create({
			"partner_id": gallery.id,
			"commission": 40.0,
			"legal_structure": "mandate",
		}).action_create()
		with self.assertRaises(UserError):
			self._declaration().action_compute()

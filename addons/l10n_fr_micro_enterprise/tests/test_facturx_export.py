from lxml import etree

from odoo import Command
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestFacturXExport(AccountTestInvoicingCommon):
	def test_franchise_invoice_without_product_tax_gets_exemption_and_mention(self):
		company = self.company_data["company"]
		company.write({
			"country_id": self.env.ref("base.fr").id,
			"account_fiscal_country_id": self.env.ref("base.fr").id,
		})
		company._l10n_fr_micro_switch("franchise", effective_date="2025-06-01")
		customer = self.env["res.partner"].create({
			"name": "Customer without country",
		})
		product = self.env["product.product"].create({
			"name": "Imported taxless ceramic",
			"taxes_id": [Command.clear()],
		})
		invoice = self.env["account.move"].create({
			"company_id": company.id,
			"partner_id": customer.id,
			"move_type": "out_invoice",
			"invoice_date": "2026-08-07",
			"journal_id": self.company_data["default_journal_sale"].id,
			"invoice_line_ids": [Command.create({
				"product_id": product.id,
				"quantity": 1,
				"price_unit": 100,
			})],
		})

		self.assertTrue(invoice.l10n_fr_micro_franchise_invoice)
		self.assertEqual(invoice.invoice_line_ids.tax_ids, company.l10n_fr_micro_goods_tax_id)
		self.assertIn("293 B", invoice.taxes_legal_notes)

		invoice.invoice_line_ids.tax_ids = [Command.clear()]
		html, _html_type = self.env.ref("account.account_invoices")._render_qweb_html(
			"account.report_invoice_with_payments", invoice.ids,
		)
		self.assertIn(b"TVA non applicable, article 293 B du CGI", html)

	def test_franchise_seller_can_export_with_registry_and_without_vat(self):
		company = self.company_data["company"]
		company.write({
			"country_id": self.env.ref("base.fr").id,
			"account_fiscal_country_id": self.env.ref("base.fr").id,
			"vat": False,
			"company_registry": "12345678900012",
			"email": "seller@example.fr",
			"phone": "+33102030405",
		})
		company._l10n_fr_micro_switch("franchise", effective_date="2025-06-01")
		company.partner_id.bank_ids = [Command.create({
			"acc_number": "FR7630006000011234567890189",
			"allow_out_payment": True,
		})]
		customer = self.partner_a.copy({
			"name": "French customer",
			"country_id": self.env.ref("base.fr").id,
		})
		invoice = self.env["account.move"].create({
			"company_id": company.id,
			"partner_id": customer.id,
			"move_type": "out_invoice",
			"journal_id": self.company_data["default_journal_sale"].id,
			"partner_bank_id": company.partner_id.bank_ids[:1].id,
			"invoice_line_ids": [Command.create({
				"name": "Handmade product",
				"quantity": 1,
				"price_unit": 100,
				"tax_ids": [Command.set(company.l10n_fr_micro_goods_tax_id.ids)],
			})],
		})

		cii = self.env["account.edi.xml.cii"]
		vals = cii._export_invoice_vals(invoice)
		constraints = cii._export_invoice_constraints(invoice, vals)
		self.assertFalse(constraints["seller_identifier"])

		xml_content, errors = cii._export_invoice(invoice)
		self.assertNotIn(constraints["seller_identifier"], errors)
		xml = etree.fromstring(xml_content)
		registration_ids = xml.xpath(
			"//*[local-name()='SellerTradeParty']"
			"/*[local-name()='SpecifiedLegalOrganization']"
			"/*[local-name()='ID']/text()"
		)
		self.assertIn(company.company_registry, registration_ids)

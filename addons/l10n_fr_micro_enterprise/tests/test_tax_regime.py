from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMicroEnterpriseTaxRegime(TransactionCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		france = cls.env.ref("base.fr")
		cls.company = cls.env["res.company"].create({
			"name": "French micro tax test",
			"country_id": france.id,
			"account_fiscal_country_id": france.id,
		})
		cls.tax_group = cls.env["account.tax.group"].with_company(cls.company).create({
			"name": "Test VAT", "company_id": cls.company.id, "country_id": france.id,
		})
		cls.goods_20 = cls.env["account.tax"].with_company(cls.company).create({
			"name": "TVA 20 goods", "company_id": cls.company.id,
			"tax_group_id": cls.tax_group.id,
			"type_tax_use": "sale", "tax_scope": "consu", "amount": 20,
			"ubl_cii_tax_category_code": "S",
		})
		cls.service_10 = cls.env["account.tax"].with_company(cls.company).create({
			"name": "TVA 10 services", "company_id": cls.company.id,
			"tax_group_id": cls.tax_group.id,
			"type_tax_use": "sale", "tax_scope": "service", "amount": 10,
			"ubl_cii_tax_category_code": "S",
		})
		cls.non_vat_tax = cls.env["account.tax"].with_company(cls.company).create({
			"name": "Environmental levy", "company_id": cls.company.id,
			"tax_group_id": cls.tax_group.id,
			"type_tax_use": "sale", "tax_scope": "consu", "amount": 3,
		})

	def test_setup_is_idempotent_and_maps_only_standard_vat(self):
		self.company._l10n_fr_micro_prepare_tax_setup()
		goods_tax = self.company.l10n_fr_micro_goods_tax_id
		service_tax = self.company.l10n_fr_micro_service_tax_id
		purchase_tax = self.company.l10n_fr_micro_purchase_tax_id
		position = self.company.l10n_fr_micro_fiscal_position_id
		self.assertEqual(goods_tax.amount, 0)
		self.assertEqual(goods_tax.ubl_cii_tax_category_code, "E")
		self.assertEqual(goods_tax.ubl_cii_tax_exemption_reason_code, "VATEX-FR-FRANCHISE")
		self.assertIn("293 B", goods_tax.invoice_legal_notes)
		self.assertEqual(goods_tax.original_tax_ids, self.goods_20)
		self.assertEqual(service_tax.original_tax_ids, self.service_10)
		self.assertNotIn(self.non_vat_tax, goods_tax.original_tax_ids)
		self.assertEqual(purchase_tax.type_tax_use, "purchase")
		self.assertEqual(purchase_tax.amount, 0)
		self.assertTrue(purchase_tax.l10n_fr_micro_franchise_tax)
		self.assertEqual(position.tax_ids, goods_tax | service_tax)
		self.assertFalse(position.auto_apply)

		ids_before = (goods_tax.id, service_tax.id, purchase_tax.id, position.id)
		self.company._l10n_fr_micro_prepare_tax_setup()
		self.assertEqual(ids_before, (
			self.company.l10n_fr_micro_goods_tax_id.id,
			self.company.l10n_fr_micro_service_tax_id.id,
			self.company.l10n_fr_micro_purchase_tax_id.id,
			self.company.l10n_fr_micro_fiscal_position_id.id,
		))

	def test_switch_changes_future_mapping_without_product_tax_rewrite(self):
		product = self.env["product.product"].with_company(self.company).create({
			"name": "Taxed cup", "taxes_id": [(6, 0, self.goods_20.ids)],
		})
		product_taxes_before = product.taxes_id
		self.company._l10n_fr_micro_switch("franchise")
		self.assertEqual(self.company.l10n_fr_micro_tax_regime, "franchise")
		self.assertTrue(self.company.l10n_fr_micro_fiscal_position_id.auto_apply)
		self.assertEqual(
			self.company.l10n_fr_micro_fiscal_position_id.map_tax(self.goods_20),
			self.company.l10n_fr_micro_goods_tax_id,
		)
		self.assertIn(self.goods_20, product.taxes_id)
		self.assertEqual(product.taxes_id, product_taxes_before)

		self.assertEqual(self.company.l10n_fr_micro_tax_switch_date, fields.Date.today())
		france_customer = self.env["res.partner"].create({
			"name": "French customer", "country_id": self.env.ref("base.fr").id,
		})
		foreign_customer = self.env["res.partner"].create({
			"name": "Belgian customer", "country_id": self.env.ref("base.be").id,
		})
		fiscal_position_model = self.env["account.fiscal.position"].with_company(self.company)
		self.assertEqual(
			fiscal_position_model._get_fiscal_position(france_customer),
			self.company.l10n_fr_micro_fiscal_position_id,
		)
		self.assertNotEqual(
			fiscal_position_model._get_fiscal_position(foreign_customer),
			self.company.l10n_fr_micro_fiscal_position_id,
		)

		self.company._l10n_fr_micro_switch("vat")
		self.assertEqual(self.company.l10n_fr_micro_tax_regime, "vat")
		self.assertFalse(self.company.l10n_fr_micro_fiscal_position_id.auto_apply)
		self.assertEqual(product.taxes_id, product_taxes_before)

	def test_switch_accepts_historical_effective_date(self):
		effective_date = fields.Date.to_date("2025-06-01")
		self.company._l10n_fr_micro_switch("franchise", effective_date=effective_date)
		self.assertEqual(self.company.l10n_fr_micro_tax_regime, "franchise")
		self.assertEqual(self.company.l10n_fr_micro_tax_switch_date, effective_date)

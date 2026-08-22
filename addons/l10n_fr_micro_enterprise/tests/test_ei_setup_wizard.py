from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestEiSetupWizard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        france = cls.env.ref("base.fr")
        cls.company = cls.env["res.company"].create(
            {
                "name": "EI wizard test",
                "country_id": france.id,
                "account_fiscal_country_id": france.id,
            }
        )

    def _wizard_values(self):
        return {
            "company_id": self.company.id,
            "legal_name": "MARTEAU CYRIELLE",
            "trade_name": "Atelier Cyrielle",
            "legal_form": "ei",
            "siren": "493 345 953",
            "siret": "493 345 953 00027",
            "ape_code": "32.99z",
            "activity_description": "Fabrication et vente d'objets céramique",
            "street": "13 CALADE SAINT COME",
            "zip": "83740",
            "city": "LA CADIERE-D'AZUR",
            "country_id": self.env.ref("base.fr").id,
            "email": "seller@example.fr",
            "phone": "+33600000000",
            "iban": "FR76 3000 6000 0112 3456 7890 189",
            "bic": "AGRIFRPP",
            "tax_regime": "franchise",
            "tax_effective_date": fields.Date.to_date("2025-06-01"),
            "edi_mode": "external_facturx",
        }

    def test_apply_configures_standard_company_bank_and_tax_records(self):
        wizard = self.env["l10n.fr.micro.setup.wizard"].create(self._wizard_values())
        wizard.action_apply()

        self.assertEqual(self.company.name, "MARTEAU CYRIELLE")
        self.assertEqual(self.company.company_registry, "49334595300027")
        self.assertEqual(self.company.l10n_fr_micro_siren, "493345953")
        self.assertEqual(self.company.l10n_fr_micro_siret, "49334595300027")
        self.assertEqual(self.company.l10n_fr_micro_ape_code, "32.99Z")
        self.assertFalse(self.company.vat)
        self.assertEqual(self.company.l10n_fr_micro_tax_regime, "franchise")
        self.assertEqual(self.company.chart_template, "fr")
        self.assertEqual(self.company.account_fiscal_country_id, self.env.ref("base.fr"))
        self.assertEqual(
            self.company.l10n_fr_micro_purchase_tax_id.type_tax_use,
            "purchase",
        )
        self.assertEqual(
            self.company.l10n_fr_micro_tax_switch_date,
            fields.Date.to_date("2025-06-01"),
        )
        bank_account = self.company.partner_id.bank_ids.ensure_one()
        self.assertEqual(bank_account.sanitized_acc_number, "FR7630006000011234567890189")
        self.assertEqual(bank_account.bank_bic, "AGRIFRPP")

    def test_rejects_invalid_siren_checksum(self):
        values = self._wizard_values()
        values["siren"] = "493345954"
        wizard = self.env["l10n.fr.micro.setup.wizard"].create(values)
        with self.assertRaises(ValidationError):
            wizard.action_apply()

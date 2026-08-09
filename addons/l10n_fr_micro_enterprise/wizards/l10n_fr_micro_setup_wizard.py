import re

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


def _digits(value):
	return re.sub(r"\D", "", value or "")


def _compact(value):
	return re.sub(r"\s", "", value or "").upper()


def _luhn_is_valid(value):
	total = 0
	for index, character in enumerate(reversed(value)):
		digit = int(character)
		if index % 2:
			digit *= 2
			digit = digit // 10 + digit % 10
		total += digit
	return total % 10 == 0


class L10nFrMicroSetupWizard(models.TransientModel):
	_name = "l10n.fr.micro.setup.wizard"
	_description = "French sole proprietor setup"

	company_id = fields.Many2one(
		"res.company", required=True, readonly=True,
		default=lambda self: self.env.company,
	)
	company_partner_id = fields.Many2one(
		"res.partner", related="company_id.partner_id", readonly=True,
	)
	legal_name = fields.Char(string="Legal name", required=True)
	trade_name = fields.Char(string="Trading name")
	legal_form = fields.Selection(
		selection=[("ei", "Entrepreneur individuel")], required=True,
		default="ei", readonly=True,
	)
	siren = fields.Char(string="SIREN", required=True)
	siret = fields.Char(string="SIRET (head office)", required=True)
	ape_code = fields.Char(string="APE / NAF code")
	activity_description = fields.Char(string="Main activity")
	street = fields.Char(required=True)
	street2 = fields.Char()
	zip = fields.Char(required=True)
	city = fields.Char(required=True)
	country_id = fields.Many2one(
		"res.country", required=True, default=lambda self: self.env.ref("base.fr"),
	)
	email = fields.Char(required=True)
	phone = fields.Char(required=True)
	vat = fields.Char(string="VAT number")
	bank_account_id = fields.Many2one(
		"res.partner.bank", string="Professional bank account",
		domain="[('partner_id', '=', company_partner_id)]",
	)
	iban = fields.Char(string="IBAN")
	bic = fields.Char(string="BIC / SWIFT")
	tax_regime = fields.Selection(
		selection=[
			("unchanged", "Not managed by this module"),
			("franchise", "Franchise en base de TVA"),
			("vat", "VAT liable"),
		], required=True,
	)
	tax_effective_date = fields.Date(string="Regime effective from", required=True)
	bnc_enabled = fields.Boolean(string="Enable a BNC turnover category")
	edi_mode = fields.Selection(
		selection=[("external_facturx", "Factur-X file for an external approved platform")],
		required=True, readonly=True,
	)
	facturx_ready = fields.Boolean(compute="_compute_readiness")
	readiness_html = fields.Html(compute="_compute_readiness", sanitize=False)

	@api.model
	def default_get(self, field_names):
		values = super().default_get(field_names)
		company = self.env.company
		bank_account = company.partner_id.bank_ids[:1]
		values.update({
			"company_id": company.id,
			"legal_name": company.name,
			"trade_name": company.l10n_fr_micro_trade_name,
			"legal_form": company.l10n_fr_micro_legal_form or "ei",
			"siren": company.l10n_fr_micro_siren or (company.company_registry or "")[:9],
			"siret": company.l10n_fr_micro_siret or company.company_registry,
			"ape_code": company.l10n_fr_micro_ape_code,
			"activity_description": company.l10n_fr_micro_activity_description,
			"street": company.street,
			"street2": company.street2,
			"zip": company.zip,
			"city": company.city,
			"country_id": company.country_id.id or self.env.ref("base.fr").id,
			"email": company.email,
			"phone": company.phone,
			"vat": company.vat,
			"bank_account_id": bank_account.id,
			"iban": bank_account.acc_number,
			"bic": bank_account.bank_bic,
			"tax_regime": company.l10n_fr_micro_tax_regime,
			"tax_effective_date": company.l10n_fr_micro_tax_switch_date or fields.Date.context_today(self),
			"bnc_enabled": company.l10n_fr_micro_bnc_enabled,
			"edi_mode": company.l10n_fr_micro_edi_mode,
		})
		return values

	@api.onchange("siret")
	def _onchange_siret(self):
		if len(_digits(self.siret)) == 14:
			self.siren = _digits(self.siret)[:9]

	@api.onchange("bank_account_id")
	def _onchange_bank_account_id(self):
		self.iban = self.bank_account_id.acc_number
		self.bic = self.bank_account_id.bank_bic

	@api.depends(
		"legal_name", "siren", "siret", "street", "zip", "city", "country_id",
		"email", "phone", "iban", "tax_regime",
	)
	def _compute_readiness(self):
		for wizard in self:
			missing = []
			siren = _digits(wizard.siren)
			siret = _digits(wizard.siret)
			checks = [
				(wizard.legal_name, _("legal name")),
				(len(siren) == 9 and _luhn_is_valid(siren), _("valid SIREN")),
				(
					len(siret) == 14 and _luhn_is_valid(siret) and siret.startswith(siren),
					_("valid SIRET"),
				),
				(wizard.street and wizard.zip and wizard.city and wizard.country_id, _("registered address")),
				(wizard.email, _("email")),
				(wizard.phone, _("phone")),
				(wizard.iban, _("professional IBAN")),
				(wizard.tax_regime != "unchanged", _("VAT regime")),
			]
			for complete, label in checks:
				if not complete:
					missing.append(label)
			wizard.facturx_ready = not missing
			if missing:
				items = Markup().join(Markup("<li>%s</li>") % item for item in missing)
				wizard.readiness_html = Markup("<div class='alert alert-warning mb-0'><strong>%s</strong><ul class='mb-0'>%s</ul></div>") % (
					_("Factur-X setup is incomplete:"), items,
				)
			else:
				wizard.readiness_html = Markup("<div class='alert alert-success mb-0'><strong>%s</strong></div>") % _(
					"Ready. Click Save and validate below to apply this setup to the company."
				)

	def _validate_identifiers(self):
		self.ensure_one()
		siren = _digits(self.siren)
		siret = _digits(self.siret)
		if len(siren) != 9 or not _luhn_is_valid(siren):
			raise ValidationError(_("SIREN must contain 9 digits and pass its checksum."))
		if len(siret) != 14 or not _luhn_is_valid(siret):
			raise ValidationError(_("SIRET must contain 14 digits and pass its checksum."))
		if not siret.startswith(siren):
			raise ValidationError(_("The SIRET must belong to the entered SIREN."))
		return siren, siret

	def _save_bank_account(self):
		self.ensure_one()
		iban = _compact(self.iban)
		if not iban:
			return self.env["res.partner.bank"]
		bank_account = self.bank_account_id
		bank = bank_account.bank_id
		bic = _compact(self.bic)
		if bic and (not bank or bank.bic != bic):
			bank = self.env["res.bank"].search([("bic", "=", bic)], limit=1)
			if not bank:
				bank = self.env["res.bank"].create({
					"name": bic,
					"bic": bic,
					"country": self.country_id.id,
				})
		values = {
			"acc_number": iban,
			"partner_id": self.company_id.partner_id.id,
			"bank_id": bank.id,
		}
		if bank_account:
			bank_account.write(values)
		else:
			bank_account = self.env["res.partner.bank"].create(values)
		return bank_account

	def _prepare_french_chart(self, company):
		self.ensure_one()
		if company.chart_template == "fr":
			return company
		if self.env["account.move.line"].sudo().search_count([
			("company_id", "=", company.id),
		]):
			raise ValidationError(_(
				"The French chart of accounts cannot replace an accounting localization "
				"after journal items exist. Ask an Accounting Administrator to migrate it."
			))
		self.env["account.chart.template"].sudo().try_loading(
			"fr", company=company, install_demo=False,
		)
		return self.env["res.company"].browse(company.id)

	def action_apply(self):
		self.ensure_one()
		company = self.company_id
		company._l10n_fr_micro_check_manager()
		siren, siret = self._validate_identifiers()
		if self.tax_regime == "vat" and not self.vat:
			raise ValidationError(_("A VAT number is required when VAT-liable mode is selected."))
		company.write({
			"name": self.legal_name,
			"l10n_fr_micro_legal_form": self.legal_form,
			"l10n_fr_micro_trade_name": self.trade_name,
			"l10n_fr_micro_siren": siren,
			"l10n_fr_micro_siret": siret,
			"l10n_fr_micro_ape_code": (self.ape_code or "").upper(),
			"l10n_fr_micro_activity_description": self.activity_description,
			"l10n_fr_micro_edi_mode": self.edi_mode,
			"l10n_fr_micro_bnc_enabled": self.bnc_enabled,
			"company_registry": siret,
			"street": self.street,
			"street2": self.street2,
			"zip": self.zip,
			"city": self.city,
			"country_id": self.country_id.id,
			"account_fiscal_country_id": self.country_id.id,
			"email": self.email,
			"phone": self.phone,
			"vat": _compact(self.vat) or False,
		})
		company.invalidate_recordset(["country_id", "account_fiscal_country_id"])
		company = self._prepare_french_chart(company)
		self._save_bank_account()
		if self.tax_regime in ("franchise", "vat"):
			company._l10n_fr_micro_switch(
				self.tax_regime, effective_date=self.tax_effective_date,
			)
		else:
			company._l10n_fr_micro_prepare_tax_setup()
		return {
			"type": "ir.actions.client",
			"tag": "display_notification",
			"params": {
				"title": _("French EI setup saved"),
				"message": _("The company identity, payment details, and tax setup were updated."),
				"type": "success",
				"sticky": False,
				"next": {"type": "ir.actions.client", "tag": "reload"},
			},
		}

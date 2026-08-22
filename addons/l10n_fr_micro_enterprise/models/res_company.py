from odoo import _, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.fields import Command

LEGAL_NOTE = "TVA non applicable, article 293 B du CGI"


class ResCompany(models.Model):
    _inherit = "res.company"

    l10n_fr_micro_tax_regime = fields.Selection(
        selection=[
            ("unchanged", "Not managed by this module"),
            ("franchise", "VAT exemption"),
            ("vat", "VAT liable"),
        ],
        string="Micro-enterprise VAT regime",
        required=True,
        default="unchanged",
        copy=False,
    )
    l10n_fr_micro_legal_form = fields.Selection(
        selection=[("ei", "Sole trader (entrepreneur individuel)")],
        string="Legal form",
        default="ei",
        copy=False,
    )
    l10n_fr_micro_trade_name = fields.Char(string="Trading name", copy=False)
    l10n_fr_micro_siren = fields.Char(string="SIREN number", copy=False)
    l10n_fr_micro_siret = fields.Char(string="SIRET number", copy=False)
    l10n_fr_micro_ape_code = fields.Char(string="APE / NAF code", copy=False)
    l10n_fr_micro_activity_description = fields.Char(
        string="Main activity",
        copy=False,
    )
    l10n_fr_micro_edi_mode = fields.Selection(
        selection=[("external_facturx", "Factur-X file for an external approved platform")],
        string="Electronic invoicing route",
        default="external_facturx",
        required=True,
        copy=False,
    )
    l10n_fr_micro_goods_tax_id = fields.Many2one(
        "account.tax",
        string="Franchise tax — goods",
        readonly=True,
        copy=False,
        check_company=True,
    )
    l10n_fr_micro_tax_group_id = fields.Many2one(
        "account.tax.group",
        string="Franchise tax group",
        readonly=True,
        copy=False,
        check_company=True,
    )
    l10n_fr_micro_service_tax_id = fields.Many2one(
        "account.tax",
        string="Franchise tax — services",
        readonly=True,
        copy=False,
        check_company=True,
    )
    l10n_fr_micro_bnc_enabled = fields.Boolean(
        string="Enable a BNC turnover category",
        copy=False,
    )
    l10n_fr_micro_bnc_tax_id = fields.Many2one(
        "account.tax",
        string="Franchise tax — BNC",
        readonly=True,
        copy=False,
        check_company=True,
    )
    l10n_fr_micro_bnc_economic_tax_id = fields.Many2one(
        "account.tax",
        string="Economic VAT tax — BNC",
        readonly=True,
        copy=False,
        check_company=True,
    )
    l10n_fr_micro_purchase_tax_id = fields.Many2one(
        "account.tax",
        string="Franchise tax — purchases",
        readonly=True,
        copy=False,
        check_company=True,
    )
    l10n_fr_micro_fiscal_position_id = fields.Many2one(
        "account.fiscal.position",
        string="Franchise fiscal position",
        readonly=True,
        copy=False,
        check_company=True,
    )
    l10n_fr_micro_tax_switch_date = fields.Date(
        string="Current VAT regime effective from",
        readonly=True,
        copy=False,
    )
    l10n_fr_micro_tax_switch_user_id = fields.Many2one(
        "res.users",
        string="Switched by",
        readonly=True,
        copy=False,
    )

    def _l10n_fr_micro_check_manager(self):
        if not self.env.is_superuser() and not self.env.user.has_group(
            "account.group_account_manager"
        ):
            raise AccessError(
                _("Only an Accounting Administrator can change the micro-enterprise VAT regime.")
            )

    def _l10n_fr_micro_french_country(self):
        self.ensure_one()
        country = self.account_fiscal_country_id or self.country_id
        if country.code != "FR":
            raise UserError(
                _("The micro-enterprise tax setup is only available for a French fiscal company.")
            )
        return country

    def _l10n_fr_micro_source_taxes(self, scope, category):
        self.ensure_one()
        taxes = (
            self.env["account.tax"]
            .with_context(active_test=False)
            .search(
                [
                    ("company_id", "=", self.id),
                    ("type_tax_use", "=", "sale"),
                    ("tax_scope", "=", scope),
                    ("amount", ">", 0),
                    ("ubl_cii_tax_category_code", "=", "S"),
                    ("l10n_fr_micro_franchise_tax", "=", False),
                ]
            )
        )
        matching = taxes.filtered(lambda tax: tax.l10n_fr_micro_urssaf_category == category)
        unclassified = taxes.filtered(lambda tax: not tax.l10n_fr_micro_urssaf_category)
        return matching if category == "bnc" else matching | unclassified

    def _l10n_fr_micro_prepare_bnc_economic_tax(self):
        self.ensure_one()
        tax_model = self.env["account.tax"].with_company(self).with_context(active_test=False)
        tax = tax_model.search(
            [
                ("company_id", "=", self.id),
                ("type_tax_use", "=", "sale"),
                ("tax_scope", "=", "service"),
                ("l10n_fr_micro_franchise_tax", "=", False),
                ("l10n_fr_micro_urssaf_category", "=", "bnc"),
            ],
            limit=1,
        )
        if tax:
            return tax
        source = self._l10n_fr_micro_source_taxes("service", "bic_service")[:1]
        if not source:
            raise UserError(_("Prepare an ordinary French service VAT tax before enabling BNC."))
        return source.copy(
            default={
                # "BNC" is a tax-code acronym and the rest is the source tax name:
                # there is nothing here to translate.
                "name": "%s — BNC" % source.name,
                "invoice_label": _("VAT — BNC service"),
                "l10n_fr_micro_urssaf_category": "bnc",
                "original_tax_ids": [Command.clear()],
            }
        )

    def _l10n_fr_micro_prepare_tax_group(self, country):
        self.ensure_one()
        group_model = (
            self.env["account.tax.group"].with_company(self).with_context(active_test=False)
        )
        group = group_model.search(
            [
                ("company_id", "=", self.id),
                ("l10n_fr_micro_franchise_group", "=", True),
            ],
            limit=1,
        )
        values = {
            "name": _("VAT 0% — VAT exemption"),
            "company_id": self.id,
            "country_id": country.id,
            "l10n_fr_micro_franchise_group": True,
        }
        if group:
            group.write(values)
        else:
            group = group_model.create(values)
        return group

    def _l10n_fr_micro_prepare_one_tax(self, category, scope, country, tax_group):
        self.ensure_one()
        tax_model = self.env["account.tax"].with_company(self).with_context(active_test=False)
        tax = tax_model.search(
            [
                ("company_id", "=", self.id),
                ("l10n_fr_micro_franchise_tax", "=", True),
                ("l10n_fr_micro_urssaf_category", "=", category),
            ],
            limit=1,
        )
        if not tax and category != "bnc":
            tax = tax_model.search(
                [
                    ("company_id", "=", self.id),
                    ("l10n_fr_micro_franchise_tax", "=", True),
                    ("type_tax_use", "=", "sale"),
                    ("tax_scope", "=", scope),
                    ("l10n_fr_micro_urssaf_category", "=", False),
                ],
                limit=1,
            )
        category_label = {
            "bic_goods": _("goods"),
            "bic_service": _("BIC services"),
            "bnc": _("BNC activity"),
        }[category]
        label = _(
            "VAT not applicable — VAT exemption (%(category)s)",
            category=category_label,
        )
        original_taxes = self._l10n_fr_micro_source_taxes(scope, category)
        original_taxes.filtered(lambda source: not source.l10n_fr_micro_urssaf_category).write(
            {
                "l10n_fr_micro_urssaf_category": category,
            }
        )
        values = {
            "name": label,
            "invoice_label": _("VAT not applicable — Article 293 B"),
            "description": LEGAL_NOTE,
            "invoice_legal_notes": LEGAL_NOTE,
            "company_id": self.id,
            "country_id": country.id,
            "tax_group_id": tax_group.id,
            "type_tax_use": "sale",
            "tax_scope": scope,
            "amount_type": "percent",
            "amount": 0,
            "active": True,
            "l10n_fr_micro_franchise_tax": True,
            "l10n_fr_micro_urssaf_category": category,
            "tax_exigibility": "on_payment",
            "cash_basis_transition_account_id": self.account_cash_basis_base_account_id.id,
            "ubl_cii_tax_category_code": "E",
            "ubl_cii_tax_exemption_reason_code": "VATEX-FR-FRANCHISE",
            "original_tax_ids": [Command.set(original_taxes.ids)],
        }
        if tax:
            tax.write(values)
        else:
            tax = tax_model.create(values)
        return tax

    def _l10n_fr_micro_prepare_purchase_tax(self, country, tax_group):
        self.ensure_one()
        tax_model = self.env["account.tax"].with_company(self).with_context(active_test=False)
        tax = tax_model.search(
            [
                ("company_id", "=", self.id),
                ("l10n_fr_micro_franchise_tax", "=", True),
                ("type_tax_use", "=", "purchase"),
            ],
            limit=1,
        )
        values = {
            "name": _("Non-deductible VAT — VAT exemption (purchases)"),
            "invoice_label": _("Non-deductible VAT — VAT exemption"),
            "description": _("Supplier VAT included in the expense"),
            "company_id": self.id,
            "country_id": country.id,
            "tax_group_id": tax_group.id,
            "type_tax_use": "purchase",
            "tax_scope": False,
            "amount_type": "percent",
            "amount": 0,
            "active": True,
            "l10n_fr_micro_franchise_tax": True,
        }
        if tax:
            tax.write(values)
        else:
            tax = tax_model.create(values)
        return tax

    def _l10n_fr_micro_prepare_tax_setup(self):
        self._l10n_fr_micro_check_manager()
        for company in self:
            country = company._l10n_fr_micro_french_country()
            company._l10n_fr_micro_prepare_cash_basis()
            tax_group = company._l10n_fr_micro_prepare_tax_group(country)
            goods_tax = company._l10n_fr_micro_prepare_one_tax(
                "bic_goods", "consu", country, tax_group
            )
            service_tax = company._l10n_fr_micro_prepare_one_tax(
                "bic_service", "service", country, tax_group
            )
            bnc_economic_tax = (
                company._l10n_fr_micro_prepare_bnc_economic_tax()
                if company.l10n_fr_micro_bnc_enabled
                else self.env["account.tax"]
            )
            if bnc_economic_tax:
                # Re-evaluate the BIC target after the BNC clone exists so the two
                # same-rate service taxes cannot both map to the BIC exemption.
                service_tax = company._l10n_fr_micro_prepare_one_tax(
                    "bic_service",
                    "service",
                    country,
                    tax_group,
                )
            bnc_tax = (
                company._l10n_fr_micro_prepare_one_tax("bnc", "service", country, tax_group)
                if bnc_economic_tax
                else self.env["account.tax"]
            )
            purchase_tax = company._l10n_fr_micro_prepare_purchase_tax(country, tax_group)
            position_model = (
                self.env["account.fiscal.position"]
                .with_company(company)
                .with_context(active_test=False)
            )
            position = position_model.search(
                [
                    ("company_id", "=", company.id),
                    ("l10n_fr_micro_franchise_position", "=", True),
                ],
                limit=1,
            )
            position_values = {
                "name": _("FR — VAT exemption"),
                "company_id": company.id,
                "country_id": country.id,
                "sequence": 1,
                "active": True,
                "auto_apply": company.l10n_fr_micro_tax_regime == "franchise",
                "vat_required": False,
                "note": LEGAL_NOTE,
                "l10n_fr_micro_franchise_position": True,
                "tax_ids": [Command.set((goods_tax | service_tax | bnc_tax).ids)],
            }
            if position:
                position.write(position_values)
            else:
                position = position_model.create(position_values)
            company.write(
                {
                    "l10n_fr_micro_tax_group_id": tax_group.id,
                    "l10n_fr_micro_goods_tax_id": goods_tax.id,
                    "l10n_fr_micro_service_tax_id": service_tax.id,
                    "l10n_fr_micro_bnc_tax_id": bnc_tax.id or False,
                    "l10n_fr_micro_bnc_economic_tax_id": bnc_economic_tax.id or False,
                    "l10n_fr_micro_purchase_tax_id": purchase_tax.id,
                    "l10n_fr_micro_fiscal_position_id": position.id,
                }
            )
        return True

    def _l10n_fr_micro_prepare_cash_basis(self):
        self.ensure_one()
        journal_model = (
            self.env["account.journal"].with_company(self).with_context(active_test=False)
        )
        journal = self.tax_cash_basis_journal_id or journal_model.search(
            [
                ("company_id", "=", self.id),
                ("code", "=", "CABA"),
            ],
            limit=1,
        )
        if not journal:
            journal = journal_model.create(
                {
                    "name": _("Micro-enterprise cash-basis recognition"),
                    "code": "CABA",
                    "type": "general",
                    "company_id": self.id,
                }
            )

        account = self.account_cash_basis_base_account_id
        if not account:
            account_model = (
                self.env["account.account"].with_company(self).with_context(active_test=False)
            )
            account = account_model.search(
                [
                    ("company_ids", "in", self.id),
                    ("code", "=", "467CABA"),
                ],
                limit=1,
            )
            if not account:
                account = account_model.create(
                    {
                        "name": _("Cash-basis base transition"),
                        "code": "467CABA",
                        "account_type": "asset_current",
                        "reconcile": True,
                        "company_ids": [Command.link(self.id)],
                    }
                )
        elif not account.reconcile:
            account.reconcile = True
        self.write(
            {
                "tax_exigibility": True,
                "tax_cash_basis_journal_id": journal.id,
                "account_cash_basis_base_account_id": account.id,
            }
        )

    def _l10n_fr_micro_switch(self, regime, effective_date=None):
        if regime not in ("franchise", "vat"):
            raise UserError(_("Unsupported micro-enterprise VAT regime."))
        self._l10n_fr_micro_check_manager()
        self._l10n_fr_micro_prepare_tax_setup()
        for company in self:
            switch_date = (
                fields.Date.to_date(effective_date)
                if effective_date
                else fields.Date.context_today(company)
            )
            if switch_date > fields.Date.context_today(company):
                raise UserError(_("A VAT regime cannot be activated before its effective date."))
            company.l10n_fr_micro_fiscal_position_id.write(
                {
                    "active": True,
                    "auto_apply": regime == "franchise",
                }
            )
            company.write(
                {
                    "l10n_fr_micro_tax_regime": regime,
                    "l10n_fr_micro_tax_switch_date": switch_date,
                    "l10n_fr_micro_tax_switch_user_id": self.env.user.id,
                }
            )
        return True

    def action_l10n_fr_micro_prepare_tax_setup(self):
        self._l10n_fr_micro_prepare_tax_setup()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Micro-enterprise taxes prepared"),
                "message": _(
                    "The franchise taxes and domestic fiscal position are ready. No regime was changed."
                ),
                "type": "success",
                "sticky": False,
            },
        }

    def action_l10n_fr_micro_activate_franchise(self):
        self._l10n_fr_micro_switch("franchise")
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Franchise en base activated"),
                "message": _(
                    "Future domestic sales will use the Article 293 B exemption. Existing documents were not changed."
                ),
                "type": "success",
                "sticky": True,
            },
        }

    def action_l10n_fr_micro_activate_vat(self, effective_date=None):
        self._l10n_fr_micro_switch("vat", effective_date=effective_date)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("VAT-liable mode activated"),
                "message": _(
                    "Automatic franchise mapping is disabled. Products keep their configured economic VAT taxes."
                ),
                "type": "warning",
                "sticky": True,
            },
        }

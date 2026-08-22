from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

from .internal import internal_context, is_internal

URSSAF_CATEGORIES = [
    ("bic_goods", "BIC — sales of goods"),
    ("bic_service", "BIC — commercial or craft services"),
    ("bnc", "BNC — liberal activity"),
]


class L10nFrMicroUrssafRate(models.Model):
    _name = "l10n.fr.micro.urssaf.rate"
    _description = "Dated micro-enterprise levy rate"
    _order = "date_from desc, levy, category, id"

    name = fields.Char(compute="_compute_name", store=True)
    date_from = fields.Date(required=True, index=True)
    date_to = fields.Date(index=True)
    levy = fields.Selection(
        selection=[
            ("cotisation", "Social contributions"),
            ("cfp", "Professional training contribution"),
            ("chamber", "Consular chamber tax"),
            ("liberatoire", "Flat-rate income tax payment"),
        ],
        required=True,
        index=True,
    )
    category = fields.Selection(URSSAF_CATEGORIES, required=True, index=True)
    taxpayer_kind = fields.Selection(
        selection=[
            ("artisan", "Craftsperson"),
            ("merchant", "Merchant"),
            ("liberal", "Liberal profession"),
        ],
        index=True,
    )
    chamber_kind = fields.Selection(
        selection=[
            ("cma", "Chamber of trades (CMA)"),
            ("cci", "Chamber of commerce (CCI)"),
        ],
        index=True,
    )
    chamber_zone = fields.Selection(
        selection=[
            ("general", "Metropolitan France — general"),
            ("alsace", "Alsace departments (Bas-Rhin / Haut-Rhin)"),
            ("moselle", "Moselle department"),
        ],
        index=True,
    )
    rate = fields.Float(string="Rate (%)", required=True, digits=(8, 4))

    @api.depends("levy", "category", "rate", "date_from")
    def _compute_name(self):
        levies = dict(self._fields["levy"].selection)
        categories = dict(URSSAF_CATEGORIES)
        for rule in self:
            rule.name = _(
                "%(levy)s — %(category)s — %(rate)s%% from %(date)s",
                levy=levies.get(rule.levy, ""),
                category=categories.get(rule.category, ""),
                rate=rule.rate,
                date=rule.date_from,
            )

    @api.constrains(
        "date_from",
        "date_to",
        "levy",
        "category",
        "taxpayer_kind",
        "chamber_kind",
        "chamber_zone",
        "rate",
    )
    def _check_validity(self):
        for rule in self:
            if rule.date_to and rule.date_to < rule.date_from:
                raise ValidationError(_("A rate end date cannot precede its start date."))
            if rule.rate < 0:
                raise ValidationError(_("A levy rate cannot be negative."))
            domain = [
                ("id", "!=", rule.id),
                ("levy", "=", rule.levy),
                ("category", "=", rule.category),
                ("taxpayer_kind", "=", rule.taxpayer_kind or False),
                ("chamber_kind", "=", rule.chamber_kind or False),
                ("chamber_zone", "=", rule.chamber_zone or False),
                ("date_from", "<=", rule.date_to or fields.Date.to_date("9999-12-31")),
                "|",
                ("date_to", "=", False),
                ("date_to", ">=", rule.date_from),
            ]
            if self.search_count(domain):
                raise ValidationError(
                    _("Rate validity periods overlap for the same applicability key.")
                )

    @api.model
    def rate_for(self, levy, category, date, company):
        domain = [
            ("levy", "=", levy),
            ("category", "=", category),
            ("date_from", "<=", date),
            "|",
            ("date_to", "=", False),
            ("date_to", ">=", date),
        ]
        if levy == "cfp":
            taxpayer_kind = "liberal" if category == "bnc" else company.l10n_fr_micro_cfp_kind
            domain.append(("taxpayer_kind", "=", taxpayer_kind))
        elif levy == "chamber":
            domain.append(("chamber_kind", "=", company.l10n_fr_micro_chamber_kind))
            if company.l10n_fr_micro_chamber_kind == "cma":
                domain.append(("chamber_zone", "=", company.l10n_fr_micro_chamber_zone))
        return self.search(domain, order="date_from desc, id desc", limit=1)


class L10nFrMicroUrssafAcreRule(models.Model):
    _name = "l10n.fr.micro.urssaf.acre.rule"
    _description = "Dated ACRE payable coefficient"
    _order = "creation_date_from desc"

    name = fields.Char(compute="_compute_name", store=True)
    creation_date_from = fields.Date(required=True, index=True)
    creation_date_to = fields.Date(index=True)
    payable_coefficient = fields.Float(required=True, digits=(5, 4))

    @api.depends("creation_date_from", "creation_date_to", "payable_coefficient")
    def _compute_name(self):
        for rule in self:
            rule.name = _(
                "ACRE creations from %(date)s — %(coefficient)s payable",
                date=rule.creation_date_from,
                coefficient=rule.payable_coefficient,
            )

    @api.constrains("creation_date_from", "creation_date_to", "payable_coefficient")
    def _check_validity(self):
        for rule in self:
            if rule.creation_date_to and rule.creation_date_to < rule.creation_date_from:
                raise ValidationError(_("An ACRE rule end date cannot precede its start date."))
            if not 0 < rule.payable_coefficient <= 1:
                raise ValidationError(
                    _("An ACRE payable coefficient must be above 0 and at most 1.")
                )
            if self.search_count(
                [
                    ("id", "!=", rule.id),
                    (
                        "creation_date_from",
                        "<=",
                        rule.creation_date_to or fields.Date.to_date("9999-12-31"),
                    ),
                    "|",
                    ("creation_date_to", "=", False),
                    ("creation_date_to", ">=", rule.creation_date_from),
                ]
            ):
                raise ValidationError(_("ACRE creation-date rules cannot overlap."))


class L10nFrMicroUrssafThreshold(models.Model):
    _name = "l10n.fr.micro.urssaf.threshold"
    _description = "Dated micro-enterprise thresholds"
    _order = "date_from desc"

    name = fields.Char(compute="_compute_name", store=True)
    date_from = fields.Date(required=True, index=True)
    date_to = fields.Date(index=True)
    vat_global_base = fields.Monetary(required=True)
    vat_global_major = fields.Monetary(required=True)
    vat_service_base = fields.Monetary(required=True)
    vat_service_major = fields.Monetary(required=True)
    micro_global = fields.Monetary(required=True)
    micro_service = fields.Monetary(required=True)
    currency_id = fields.Many2one(
        "res.currency",
        required=True,
        default=lambda self: self.env.ref("base.EUR"),
    )

    @api.depends("date_from", "date_to")
    def _compute_name(self):
        for rule in self:
            rule.name = _("Thresholds from %s", rule.date_from)

    @api.constrains("date_from", "date_to")
    def _check_validity(self):
        for rule in self:
            if rule.date_to and rule.date_to < rule.date_from:
                raise ValidationError(_("A threshold end date cannot precede its start date."))
            if self.search_count(
                [
                    ("id", "!=", rule.id),
                    ("date_from", "<=", rule.date_to or fields.Date.to_date("9999-12-31")),
                    "|",
                    ("date_to", "=", False),
                    ("date_to", ">=", rule.date_from),
                ]
            ):
                raise ValidationError(_("Threshold validity periods cannot overlap."))

    @api.model
    def threshold_for(self, date):
        return self.search(
            [
                ("date_from", "<=", date),
                "|",
                ("date_to", "=", False),
                ("date_to", ">=", date),
            ],
            order="date_from desc",
            limit=1,
        )


class L10nFrMicroUrssafAnnual(models.Model):
    _name = "l10n.fr.micro.urssaf.annual"
    _description = "Annual micro-enterprise reference evidence"
    _order = "year desc, company_id"

    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    year = fields.Integer(required=True, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    urssaf_goods = fields.Monetary()
    urssaf_services = fields.Monetary()
    urssaf_total = fields.Monetary()
    vat_global = fields.Monetary()
    vat_services = fields.Monetary()
    source = fields.Selection(
        string="Evidence source",
        selection=[
            ("computed", "Computed from filed evidence"),
            ("manual", "Manual opening evidence"),
        ],
        required=True,
        default="computed",
    )
    manual_reason = fields.Text()

    _company_year_unique = models.Constraint(
        "unique(company_id, year)",
        "There can be only one annual reference per company and year.",
    )

    @api.constrains("year", "source", "manual_reason")
    def _check_annual(self):
        for record in self:
            if record.year < 2000 or record.year > 9999:
                raise ValidationError(_("Enter a four-digit reference year."))
            if record.source == "manual" and not record.manual_reason:
                raise ValidationError(_("Manual annual evidence requires a reason."))

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            evidence = sum(
                abs(values.get(field, 0.0))
                for field in (
                    "urssaf_goods",
                    "urssaf_services",
                    "urssaf_total",
                    "vat_global",
                    "vat_services",
                )
            )
            if evidence and (
                values.get("source", "computed") != "manual" or not values.get("manual_reason")
            ):
                raise ValidationError(
                    _("Opening annual evidence must be marked manual and include a reason.")
                )
        return super().create(values_list)

    def write(self, values):
        if (
            not is_internal(self.env)
            and not self.env.is_superuser()
            and not self.env.user.has_group("account.group_account_manager")
        ):
            raise AccessError(_("Only an Accounting Administrator can edit annual evidence."))
        if values.get("source") == "computed" and not is_internal(self.env):
            raise ValidationError(
                _("Use Compute from filed evidence to create a computed annual snapshot.")
            )
        evidence_fields = {
            "urssaf_goods",
            "urssaf_services",
            "urssaf_total",
            "vat_global",
            "vat_services",
        }
        if evidence_fields.intersection(values) and not is_internal(self.env):
            for record in self:
                source = values.get("source", record.source)
                reason = values.get("manual_reason", record.manual_reason)
                if source != "manual" or not reason:
                    raise ValidationError(
                        _("Editable annual evidence must be marked manual and include a reason.")
                    )
        return super().write(values)

    def action_compute(self):
        for record in self:
            date_from = fields.Date.to_date(f"{record.year}-01-01")
            date_to = fields.Date.to_date(f"{record.year}-12-31")
            lines = self.env["l10n.fr.micro.urssaf.declaration.line"].search(
                [
                    ("company_id", "=", record.company_id.id),
                    ("declaration_state", "=", "filed"),
                    ("declaration_id.date_to", ">=", date_from),
                    ("declaration_id.date_to", "<=", date_to),
                ]
            )
            goods = sum(
                lines.filtered(lambda line: line.category == "bic_goods").mapped(
                    "declared_turnover"
                )
            )
            services = sum(
                lines.filtered(lambda line: line.category != "bic_goods").mapped(
                    "declared_turnover"
                )
            )
            latest_filed = self.env["l10n.fr.micro.urssaf.declaration"].search(
                [
                    ("company_id", "=", record.company_id.id),
                    ("state", "=", "filed"),
                    ("date_to", "=", date_to),
                ],
                order="date_to desc, id desc",
                limit=1,
            )
            if not latest_filed:
                raise ValidationError(
                    _("File the declaration covering 31 December before computing annual evidence.")
                )
            record.with_context(**internal_context()).write(
                {
                    "source": "computed",
                    "manual_reason": False,
                    "urssaf_goods": goods,
                    "urssaf_services": services,
                    "urssaf_total": goods + services,
                    "vat_global": latest_filed.vat_ytd_global,
                    "vat_services": latest_filed.vat_ytd_services,
                }
            )
        return True

from calendar import monthrange

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .depot_scenario import DEFAULT_TERM_MONTHS


class MbCommercialContract(models.Model):
    _inherit = "mb.commercial.contract"

    depot_warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Depot",
        check_company=True,
        domain="[('is_depot', '=', True), ('company_id', '=', company_id)]",
        tracking=True,
    )
    source_warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Default Refill Source",
        check_company=True,
        domain="[('is_depot', '=', False), ('company_id', '=', company_id)]",
    )
    refill_review_date = fields.Date(default=fields.Date.context_today)
    assortment_rule_ids = fields.One2many(
        "mb.depot.assortment.rule",
        "contract_id",
        string="Refill Policies",
    )
    forecast_ids = fields.One2many(
        "mb.depot.refill.forecast",
        "contract_id",
        string="Forecasts",
    )
    rent_period_to_prepare = fields.Date(default=fields.Date.context_today)
    rent_period_ids = fields.One2many(
        "mb.commercial.rent.period",
        "contract_id",
        string="Rent Periods",
    )
    rent_bill_ids = fields.Many2many(
        "account.move",
        compute="_compute_rent_bill_ids",
        string="Rent Bills",
    )
    depot_scenario_ids = fields.One2many(
        "mb.depot.profitability.scenario",
        "contract_id",
        string="Profitability Scenarios",
    )
    primary_depot_scenario_id = fields.Many2one(
        "mb.depot.profitability.scenario",
        check_company=True,
        copy=False,
        domain="[('contract_id', '=', id)]",
        ondelete="set null",
    )
    depot_recommendation = fields.Selection(
        related="primary_depot_scenario_id.recommendation",
        string="Profitability Verdict",
        store=True,
        index=True,
    )
    depot_recommendation_note = fields.Char(
        related="primary_depot_scenario_id.recommendation_note",
        string="Verdict Explanation",
    )
    depot_term_margin = fields.Monetary(
        related="primary_depot_scenario_id.term_margin",
        string="Margin Over Term",
        store=True,
    )
    depot_margin_per_hour = fields.Monetary(
        related="primary_depot_scenario_id.margin_per_effort_hour",
        string="Margin per Hour",
        store=True,
    )
    depot_break_even_monthly_sales = fields.Monetary(
        related="primary_depot_scenario_id.break_even_monthly_sales",
        string="Break-even Monthly Sales",
    )

    def _depot_scenario_defaults(self):
        """The contract terms a new profitability scenario starts from."""
        self.ensure_one()
        monthly = 0.0
        weighted_hours = 0.0
        for obligation in self.obligation_ids:
            # A weekly obligation is not four a month: 52 weeks over 12 months.
            per_month = obligation.required_occurrences * (
                52.0 / 12.0 if obligation.period_unit == "week" else 1.0
            )
            monthly += per_month
            weighted_hours += per_month * obligation.duration_hours
        return {
            "term_months": self._depot_scenario_term_months(),
            "permanences_per_month": monthly,
            "hours_per_permanence": weighted_hours / monthly if monthly else 0.0,
            "monthly_fixed_rent": self.monthly_fixed_rent,
            "commission_rate": self.depot_warehouse_id.depot_commission,
            "target_margin_per_hour": self.company_id.mb_market_target_margin_per_hour,
        }

    def _depot_scenario_term_months(self):
        self.ensure_one()
        if not (self.date_start and self.date_end):
            return DEFAULT_TERM_MONTHS
        delta = relativedelta(self.date_end, self.date_start)
        months = delta.years * 12 + delta.months
        # A contract running to the last day of a month owes that month too, so
        # leftover days count as a month rather than being dropped.
        return max(1, months + (1 if delta.days else 0))

    @api.depends("rent_period_ids.bill_id")
    def _compute_rent_bill_ids(self):
        for contract in self:
            contract.rent_bill_ids = contract.rent_period_ids.bill_id

    @api.constrains("depot_warehouse_id", "active", "date_start", "date_end")
    def _check_single_active_depot_contract(self):
        for contract in self.filtered(lambda item: item.active and item.depot_warehouse_id):
            others = self.search(
                [
                    ("id", "!=", contract.id),
                    ("active", "=", True),
                    ("company_id", "=", contract.company_id.id),
                    ("depot_warehouse_id", "=", contract.depot_warehouse_id.id),
                    ("date_start", "<=", contract.date_end or fields.Date.to_date("9999-12-31")),
                    "|",
                    ("date_end", "=", False),
                    ("date_end", ">=", contract.date_start),
                ],
                limit=1,
            )
            if others:
                raise ValidationError(
                    _(
                        "Depot %(depot)s already has an overlapping active commercial contract.",
                        depot=contract.depot_warehouse_id.display_name,
                    )
                )

    @api.constrains("depot_warehouse_id", "partner_id")
    def _check_depot_partner(self):
        for contract in self.filtered("depot_warehouse_id"):
            if (
                contract.depot_warehouse_id.depot_partner_id.commercial_partner_id
                != contract.partner_id.commercial_partner_id
            ):
                raise ValidationError(
                    _("The contract partner must be the selected depot's depositary.")
                )

    def action_refresh_depot_forecast(self):
        self.assortment_rule_ids._refresh_forecast()
        return self.action_view_depot_forecasts()

    def action_view_depot_forecasts(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "mb_commercial_operations_depot.action_depot_refill_forecasts"
        )
        action["domain"] = [("contract_id", "=", self.id)]
        return action

    def action_create_refill_operation(self):
        self.ensure_one()
        if not self.depot_warehouse_id or not self.source_warehouse_id:
            raise ValidationError(_("Configure the depot and its default refill source first."))
        self.assortment_rule_ids._refresh_forecast()
        forecasts = self.forecast_ids.filtered(
            lambda forecast: (
                forecast.snapshot_date == fields.Date.context_today(self)
                and forecast.suggested_quantity > 0
            )
        )
        if not forecasts:
            raise UserError(_("No refill quantity is currently suggested."))
        planned_date = self.refill_review_date or fields.Date.context_today(self)
        start = fields.Datetime.to_datetime(planned_date)
        operation = self.env["mb.commercial.operation"].create(
            {
                "name": _("Refill %(depot)s", depot=self.depot_warehouse_id.name),
                "operation_type": "depot_refill",
                "company_id": self.company_id.id,
                "contract_id": self.id,
                "project_id": self.project_id.id,
                "partner_id": self.partner_id.id,
                "planned_start": start,
                "planned_end": fields.Datetime.add(start, hours=3),
                "stock_preparation_deadline": start,
                "source_warehouse_id": self.source_warehouse_id.id,
                "depot_warehouse_id": self.depot_warehouse_id.id,
                "stock_plan_line_ids": [
                    fields.Command.create(forecast._stock_plan_values()) for forecast in forecasts
                ],
            }
        )
        return {
            "type": "ir.actions.act_window",
            "name": operation.display_name,
            "res_model": "mb.commercial.operation",
            "view_mode": "form",
            "res_id": operation.id,
        }

    def action_prepare_rent_bill(self):
        self.ensure_one()
        if self.rent_billing_method != "vendor_bill":
            raise UserError(_("This contract does not use separate rent vendor bills."))
        if not self.monthly_fixed_rent:
            raise ValidationError(_("Set a monthly rent amount first."))
        if not self.rent_product_id:
            raise ValidationError(_("Choose the rent service product first."))
        period_date = self.rent_period_to_prepare or fields.Date.context_today(self)
        period_start = period_date.replace(day=1)
        period = self.env["mb.commercial.rent.period"].search(
            [
                ("contract_id", "=", self.id),
                ("period_start", "=", period_start),
            ],
            limit=1,
        )
        if not period:
            period = self.env["mb.commercial.rent.period"].create(
                {
                    "contract_id": self.id,
                    "period_start": period_start,
                }
            )
        return period.action_prepare_bill()


class MbCommercialRentPeriod(models.Model):
    _name = "mb.commercial.rent.period"
    _description = "Commercial Contract Rent Period"
    _order = "period_start desc, id desc"
    _check_company_auto = True

    contract_id = fields.Many2one(
        "mb.commercial.contract",
        required=True,
        check_company=True,
        ondelete="restrict",
        index=True,
    )
    company_id = fields.Many2one(related="contract_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    period_start = fields.Date(required=True, index=True)
    period_end = fields.Date(compute="_compute_amount", store=True)
    active_days = fields.Integer(compute="_compute_amount", store=True)
    amount = fields.Monetary(compute="_compute_amount", store=True)
    bill_id = fields.Many2one(
        "account.move",
        check_company=True,
        copy=False,
        ondelete="restrict",
    )
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("draft_bill", "Draft Bill"),
            ("posted", "Posted"),
            ("cancelled", "Cancelled"),
        ],
        compute="_compute_state",
    )

    _period_unique = models.Constraint(
        "UNIQUE(contract_id, period_start)",
        "Rent has already been prepared for this contract period.",
    )

    @api.depends(
        "contract_id.date_start",
        "contract_id.date_end",
        "contract_id.monthly_fixed_rent",
        "period_start",
    )
    def _compute_amount(self):
        for period in self:
            if not period.period_start:
                period.period_end = False
                period.active_days = 0
                period.amount = 0
                continue
            days = monthrange(period.period_start.year, period.period_start.month)[1]
            period_end = period.period_start.replace(day=days)
            active_start = max(period.period_start, period.contract_id.date_start)
            active_end = min(period_end, period.contract_id.date_end or period_end)
            active_days = max(0, (active_end - active_start).days + 1)
            period.period_end = period_end
            period.active_days = active_days
            period.amount = period.currency_id.round(
                period.contract_id.monthly_fixed_rent * active_days / days
            )

    @api.depends("bill_id.state")
    def _compute_state(self):
        for period in self:
            if not period.bill_id:
                period.state = "pending"
            elif period.bill_id.state == "posted":
                period.state = "posted"
            elif period.bill_id.state == "cancel":
                period.state = "cancelled"
            else:
                period.state = "draft_bill"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("period_start"):
                vals["period_start"] = fields.Date.to_date(vals["period_start"]).replace(day=1)
        return super().create(vals_list)

    def action_prepare_bill(self):
        self.ensure_one()
        if self.bill_id:
            return self._bill_action()
        contract = self.contract_id
        analytic_distribution = {str(contract.analytic_account_id.id): 100.0}
        bill = (
            self.env["account.move"]
            .with_company(self.company_id)
            .create(
                {
                    "move_type": "in_invoice",
                    "partner_id": contract.partner_id.id,
                    "invoice_date": fields.Date.context_today(self),
                    "ref": _(
                        "Rent %(contract)s %(period)s",
                        contract=contract.name,
                        period=self.period_start,
                    ),
                    "invoice_line_ids": [
                        fields.Command.create(
                            {
                                "product_id": contract.rent_product_id.id,
                                "quantity": 1,
                                "price_unit": self.amount,
                                "analytic_distribution": analytic_distribution,
                            }
                        )
                    ],
                }
            )
        )
        self.bill_id = bill
        return self._bill_action()

    def _bill_action(self):
        return {
            "type": "ir.actions.act_window",
            "name": self.bill_id.display_name,
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": self.bill_id.id,
        }

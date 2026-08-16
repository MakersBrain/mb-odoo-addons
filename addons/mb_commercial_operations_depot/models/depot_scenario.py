from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import formatLang

from odoo.addons.mb_commercial_operations.models.profitability_verdict import (
    VERDICT_SELECTION,
)

# A depot with no end date is judged over the obligation planning horizon rather
# than forever: six months is what the contract machinery already plans ahead.
DEFAULT_TERM_MONTHS = 6


class MbDepotProfitabilityScenario(models.Model):
    """Is a depot contract worth its permanences?

    A market is one day; a depot is a standing arrangement: a commission on
    everything the gallery sells, a fixed monthly fee whether it sells or not,
    and a number of permanence days a month for however long the contract runs.
    The question is the same as for a market — does what comes back cover the
    cost and pay for the hours — but the arithmetic is monthly and then
    multiplied out over the term.
    """

    _name = "mb.depot.profitability.scenario"
    _description = "Depot Contract Profitability Scenario"
    _inherit = ["mail.thread", "mb.profitability.verdict.mixin"]
    _order = "contract_id, sequence, id"
    _check_company_auto = True

    sequence = fields.Integer(default=10)
    name = fields.Char(
        required=True, default=lambda self: _("Base scenario"), tracking=True,
    )
    contract_id = fields.Many2one(
        "mb.commercial.contract", required=True, ondelete="cascade",
        check_company=True, index=True,
    )
    company_id = fields.Many2one(related="contract_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    state = fields.Selection(
        [("draft", "Draft"), ("approved", "Approved"), ("superseded", "Superseded")],
        required=True, default="draft", copy=False, tracking=True,
    )

    # --- Term and permanences -------------------------------------------------
    term_months = fields.Integer(
        compute="_compute_term_months", store=True, readonly=False,
        help="Months this scenario judges. Taken from the contract dates, or the "
             "six-month planning horizon when the contract is open-ended.",
    )
    permanences_per_month = fields.Float(
        compute="_compute_permanences", store=True, readonly=False,
        help="Permanence days owed each month, summed from the contract's obligations.",
    )
    hours_per_permanence = fields.Float(
        compute="_compute_permanences", store=True, readonly=False,
        help="Hours spent on site per permanence, from the obligation duration.",
    )
    work_hourly_cost = fields.Monetary()

    # --- Travel ---------------------------------------------------------------
    travel_estimate_id = fields.Many2one(
        "mb.travel.estimate", check_company=True, ondelete="restrict",
        help="Round trip to the depot. Its cost and duration are multiplied by the "
             "number of permanences over the term.",
    )
    travel_cost_per_permanence = fields.Monetary(
        compute="_compute_travel", store=True, readonly=False,
    )
    travel_hours_per_permanence = fields.Float(
        compute="_compute_travel", store=True, readonly=False,
    )

    # --- Sales and the depot's cut -------------------------------------------
    expected_monthly_sales = fields.Monetary(
        string="Expected Monthly Sales (Public Price)",
        help="What customers are expected to pay the depot each month, before the "
             "depot takes its commission.",
    )
    vat_rate = fields.Float(digits=(16, 4), help="Percentage included in the public price.")
    commission_rate = fields.Float(
        digits=(16, 4), compute="_compute_commission_rate", store=True, readonly=False,
        help="Percentage the depot keeps, defaulted from the depot warehouse.",
    )
    commission_basis = fields.Selection(
        [("public", "Public price including VAT"), ("net_of_vat", "Price excluding VAT")],
        required=True, default="public",
        help="Which figure the contract applies the commission to.",
    )
    product_cost_ratio = fields.Float(
        digits=(16, 4),
        help="Cost of the goods sold, as a percentage of sales excluding VAT.",
    )
    other_monthly_variable_cost = fields.Monetary()

    # --- Standing costs -------------------------------------------------------
    monthly_fixed_rent = fields.Monetary(
        compute="_compute_monthly_fixed_rent", store=True, readonly=False,
        help="Fixed fee the depot charges each month, defaulted from the contract.",
    )
    other_monthly_fixed_cost = fields.Monetary()
    target_margin_per_hour = fields.Monetary(
        help="Hourly margin floor this depot is judged against. Defaults to the "
             "company policy; zero judges it on break-even headroom alone.",
    )

    # --- Results --------------------------------------------------------------
    permanence_count = fields.Float(compute="_compute_results", store=True)
    work_hours = fields.Float(compute="_compute_results", store=True)
    travel_hours = fields.Float(compute="_compute_results", store=True)
    effort_hours = fields.Float(
        compute="_compute_results", store=True, string="Work + Travel Hours",
    )
    monthly_sales_excl_vat = fields.Monetary(compute="_compute_results", store=True)
    monthly_commission = fields.Monetary(compute="_compute_results", store=True)
    monthly_receipts = fields.Monetary(
        compute="_compute_results", store=True, string="Monthly Receipts After Commission",
    )
    monthly_product_cost = fields.Monetary(compute="_compute_results", store=True)
    monthly_contribution = fields.Monetary(compute="_compute_results", store=True)
    contribution_margin_ratio = fields.Float(compute="_compute_results", store=True)
    monthly_fixed_cost = fields.Monetary(compute="_compute_results", store=True)
    monthly_margin = fields.Monetary(compute="_compute_results", store=True)
    term_sales = fields.Monetary(compute="_compute_results", store=True)
    term_commission = fields.Monetary(compute="_compute_results", store=True)
    term_fixed_cost = fields.Monetary(compute="_compute_results", store=True)
    term_margin = fields.Monetary(compute="_compute_results", store=True)
    break_even_monthly_sales = fields.Monetary(compute="_compute_results", store=True)
    break_even_headroom_ratio = fields.Float(compute="_compute_results", store=True)
    margin_per_effort_hour = fields.Monetary(
        compute="_compute_results", store=True, string="Margin per Hour (Work + Travel)",
    )
    margin_per_work_hour = fields.Monetary(compute="_compute_results", store=True)
    calculation_blocked = fields.Boolean(compute="_compute_results", store=True)
    calculation_note = fields.Char(compute="_compute_results", store=True)
    recommendation = fields.Selection(
        VERDICT_SELECTION, compute="_compute_results", store=True, string="Verdict",
    )
    recommendation_note = fields.Char(compute="_compute_results", store=True)

    _values_nonnegative = models.Constraint(
        "CHECK(term_months >= 0 AND permanences_per_month >= 0 "
        "AND hours_per_permanence >= 0 AND work_hourly_cost >= 0 "
        "AND travel_cost_per_permanence >= 0 AND travel_hours_per_permanence >= 0 "
        "AND expected_monthly_sales >= 0 AND vat_rate >= 0 "
        "AND commission_rate >= 0 AND commission_rate <= 100 "
        "AND product_cost_ratio >= 0 AND product_cost_ratio <= 100 "
        "AND other_monthly_variable_cost >= 0 AND monthly_fixed_rent >= 0 "
        "AND other_monthly_fixed_cost >= 0 AND target_margin_per_hour >= 0)",
        "Depot scenario rates must be percentages and amounts cannot be negative.",
    )

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            contract = self.env["mb.commercial.contract"].browse(values.get("contract_id"))
            if contract:
                values.setdefault(
                    "target_margin_per_hour",
                    contract.company_id.mb_market_target_margin_per_hour,
                )
        return super().create(values_list)

    @api.depends("contract_id.date_start", "contract_id.date_end")
    def _compute_term_months(self):
        for scenario in self:
            contract = scenario.contract_id
            if contract.date_start and contract.date_end:
                delta = relativedelta(contract.date_end, contract.date_start)
                scenario.term_months = max(1, delta.years * 12 + delta.months)
            else:
                scenario.term_months = DEFAULT_TERM_MONTHS

    @api.depends(
        "contract_id.obligation_ids.required_occurrences",
        "contract_id.obligation_ids.period_unit",
        "contract_id.obligation_ids.duration_hours",
        "contract_id.obligation_ids.active",
    )
    def _compute_permanences(self):
        for scenario in self:
            obligations = scenario.contract_id.obligation_ids
            monthly = 0.0
            weighted_hours = 0.0
            for obligation in obligations:
                # A weekly obligation is not four a month: 52 weeks over 12 months.
                per_month = obligation.required_occurrences * (
                    52.0 / 12.0 if obligation.period_unit == "week" else 1.0
                )
                monthly += per_month
                weighted_hours += per_month * obligation.duration_hours
            scenario.permanences_per_month = monthly
            scenario.hours_per_permanence = weighted_hours / monthly if monthly else 0.0

    @api.depends(
        "travel_estimate_id.total_operating_cost", "travel_estimate_id.duration_hours",
        "travel_estimate_id.state",
    )
    def _compute_travel(self):
        for scenario in self:
            estimate = scenario.travel_estimate_id
            scenario.travel_cost_per_permanence = estimate.total_operating_cost
            scenario.travel_hours_per_permanence = estimate.duration_hours

    @api.depends("contract_id.monthly_fixed_rent")
    def _compute_monthly_fixed_rent(self):
        for scenario in self:
            scenario.monthly_fixed_rent = scenario.contract_id.monthly_fixed_rent

    @api.depends("contract_id.depot_warehouse_id.depot_commission")
    def _compute_commission_rate(self):
        for scenario in self:
            scenario.commission_rate = scenario.contract_id.depot_warehouse_id.depot_commission

    @api.depends(
        "term_months", "permanences_per_month", "hours_per_permanence",
        "work_hourly_cost", "travel_cost_per_permanence", "travel_hours_per_permanence",
        "expected_monthly_sales", "vat_rate", "commission_rate", "commission_basis",
        "product_cost_ratio", "other_monthly_variable_cost", "monthly_fixed_rent",
        "other_monthly_fixed_cost", "target_margin_per_hour",
    )
    def _compute_results(self):
        for scenario in self:
            currency = scenario.currency_id
            months = scenario.term_months
            per_month = scenario.permanences_per_month
            permanences = per_month * months
            work_hours = permanences * scenario.hours_per_permanence
            travel_hours = permanences * scenario.travel_hours_per_permanence
            effort_hours = work_hours + travel_hours

            sales = scenario.expected_monthly_sales
            net_of_vat = sales / (1.0 + scenario.vat_rate / 100.0)
            commission_base = sales if scenario.commission_basis == "public" else net_of_vat
            commission = commission_base * scenario.commission_rate / 100.0
            receipts = net_of_vat - commission
            product_cost = net_of_vat * scenario.product_cost_ratio / 100.0
            contribution = receipts - product_cost - scenario.other_monthly_variable_cost
            # Expressed against the public price, because that is the number the
            # depot quotes and the only one the maker can compare an offer to.
            ratio = contribution / sales if sales > 0 else 0.0

            monthly_labour = per_month * scenario.hours_per_permanence * scenario.work_hourly_cost
            monthly_travel = per_month * scenario.travel_cost_per_permanence
            monthly_fixed = (
                scenario.monthly_fixed_rent + scenario.other_monthly_fixed_cost
                + monthly_labour + monthly_travel
            )
            monthly_margin = contribution - monthly_fixed

            blocked, note = scenario._blocking_reason(months, sales, ratio)
            break_even = monthly_fixed / ratio if ratio > 0 else 0.0

            scenario.permanence_count = permanences
            scenario.work_hours = work_hours
            scenario.travel_hours = travel_hours
            scenario.effort_hours = effort_hours
            scenario.monthly_sales_excl_vat = currency.round(net_of_vat)
            scenario.monthly_commission = currency.round(commission)
            scenario.monthly_receipts = currency.round(receipts)
            scenario.monthly_product_cost = currency.round(product_cost)
            scenario.monthly_contribution = currency.round(contribution)
            scenario.contribution_margin_ratio = ratio
            scenario.monthly_fixed_cost = currency.round(monthly_fixed)
            scenario.monthly_margin = currency.round(monthly_margin)
            scenario.term_sales = currency.round(sales * months)
            scenario.term_commission = currency.round(commission * months)
            scenario.term_fixed_cost = currency.round(monthly_fixed * months)
            scenario.term_margin = currency.round(monthly_margin * months)
            scenario.break_even_monthly_sales = currency.round(break_even) if not blocked else 0.0
            if blocked:
                scenario.break_even_headroom_ratio = 0.0
            elif break_even > 0:
                scenario.break_even_headroom_ratio = (sales - break_even) / break_even
            else:
                # Nothing standing to cover, so the first sale is already ahead.
                scenario.break_even_headroom_ratio = 1.0
            scenario.margin_per_effort_hour = currency.round(
                scenario.term_margin / effort_hours
            ) if effort_hours > 0 else 0.0
            scenario.margin_per_work_hour = currency.round(
                scenario.term_margin / work_hours
            ) if work_hours > 0 else 0.0
            scenario.calculation_blocked = blocked
            scenario.calculation_note = note
            scenario.recommendation, scenario.recommendation_note = (
                scenario._evaluate_recommendation(blocked, note)
            )

    def _blocking_reason(self, months, sales, ratio):
        """What stops this scenario from being an answer at all."""
        self.ensure_one()
        if months <= 0:
            return True, _("Set how many months this depot contract is judged over.")
        if sales <= 0:
            return True, _("Enter the sales you expect the depot to make each month.")
        if ratio <= 0:
            return True, _(
                "Commission and product cost leave nothing from a sale; check the "
                "commission rate and the cost ratio."
            )
        return False, False

    def _evaluate_recommendation(self, blocked, note):
        """Word the verdict in the terms a depot contract is actually negotiated in."""
        self.ensure_one()
        verdict, reason = self._verdict(
            blocked=blocked,
            judgeable=True,
            margin=self.term_margin,
            below_break_even=self.expected_monthly_sales < self.break_even_monthly_sales,
            effort_hours=self.effort_hours,
            margin_per_hour=self.margin_per_effort_hour,
            target_per_hour=self.target_margin_per_hour,
            headroom_ratio=self.break_even_headroom_ratio,
        )

        def money(amount):
            return formatLang(self.env, amount, currency_obj=self.currency_id)

        headroom_percent = self.break_even_headroom_ratio * 100.0
        if reason == "blocked":
            return verdict, note or _("Complete the scenario before judging this depot.")
        if reason == "below_break_even":
            return verdict, _(
                "%(margin)s over %(months)s months: %(sales)s of expected monthly sales "
                "against %(break_even)s needed to cover the commission, the fee and the "
                "permanences.",
                margin=money(self.term_margin),
                months=self.term_months,
                sales=money(self.expected_monthly_sales),
                break_even=money(self.break_even_monthly_sales),
            )
        if reason == "no_hours":
            return verdict, _(
                "%(margin)s over %(months)s months, but no permanence hours are planned, "
                "so the hourly return cannot be checked.",
                margin=money(self.term_margin),
                months=self.term_months,
            )
        if reason == "below_target":
            return verdict, _(
                "%(rate)s per hour over %(hours).1f hours of permanences and travel, "
                "below the %(target)s target.",
                rate=money(self.margin_per_effort_hour),
                hours=self.effort_hours,
                target=money(self.target_margin_per_hour),
            )
        if reason == "thin_headroom":
            return verdict, _(
                "Only %(headroom).0f%% above break-even (%(sales)s expected against "
                "%(break_even)s): a quiet month turns this into a loss.",
                headroom=headroom_percent,
                sales=money(self.expected_monthly_sales),
                break_even=money(self.break_even_monthly_sales),
            )
        return verdict, _(
            "%(margin)s over %(months)s months (%(monthly)s a month) for %(hours).1f hours "
            "of permanences and travel, %(rate)s per hour, %(headroom).0f%% above break-even.",
            margin=money(self.term_margin),
            months=self.term_months,
            monthly=money(self.monthly_margin),
            hours=self.effort_hours,
            rate=money(self.margin_per_effort_hour),
            headroom=headroom_percent,
        )

    def action_approve(self):
        for scenario in self:
            if scenario.state != "draft":
                raise UserError(_("Only draft scenarios can be approved."))
            if scenario.calculation_blocked:
                raise ValidationError(scenario.calculation_note)
            scenario.contract_id.depot_scenario_ids.filtered(
                lambda other, current=scenario:
                other != current and other.state == "approved"
            ).write({"state": "superseded"})
            scenario.write({"state": "approved"})
            scenario.contract_id.primary_depot_scenario_id = scenario
        return True

    def write(self, vals):
        protected = set(self._fields) - {
            "state", "message_follower_ids", "message_partner_ids",
        }
        if protected.intersection(vals) and self.filtered(
            lambda scenario: scenario.state != "draft"
        ):
            raise UserError(
                _("Approved or superseded scenarios are immutable; create a new scenario.")
            )
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        if self.filtered(lambda scenario: scenario.state != "draft"):
            raise UserError(_("Only draft depot scenarios can be deleted."))

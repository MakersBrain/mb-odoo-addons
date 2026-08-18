import math

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, formatLang

from .profitability_verdict import VERDICT_SELECTION


class MbCommercialProfitabilityScenario(models.Model):
    _name = "mb.commercial.profitability.scenario"
    _description = "Commercial Profitability Scenario"
    _inherit = ["mail.thread", "mb.profitability.verdict.mixin"]
    _order = "operation_id, sequence, id"
    _check_company_auto = True

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True, default=lambda self: _("Base scenario"), tracking=True)
    operation_id = fields.Many2one(
        "mb.commercial.operation", required=True, ondelete="cascade",
        check_company=True, index=True,
    )
    company_id = fields.Many2one(related="operation_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    state = fields.Selection(
        [("draft", "Draft"), ("approved", "Approved"), ("superseded", "Superseded")],
        required=True,
        default="draft",
        copy=False,
        tracking=True,
    )
    line_ids = fields.One2many(
        "mb.commercial.profitability.scenario.line", "scenario_id", string="Sales Mix",
    )
    cost_line_ids = fields.One2many(
        "mb.commercial.cost.line", "scenario_id", string="Fixed Costs",
    )
    calculation_mode = fields.Selection(
        [("product_mix", "Product Mix"), ("average_basket", "Average Basket")],
        required=True, default="product_mix", tracking=True,
    )
    revision = fields.Integer(related="operation_id.planning_revision", store=True)
    approved_by_id = fields.Many2one("res.users", copy=False, readonly=True)
    approved_at = fields.Datetime(copy=False, readonly=True)
    route_cost_mode = fields.Selection(
        [
            ("provider_total", "Accepted TollQuote total"),
            ("components", "Selected route components"),
            ("manual", "Manual travel total"),
        ],
        required=True,
        default="manual",
    )
    travel_estimate_id = fields.Many2one(
        "mb.travel.estimate", check_company=True, ondelete="restrict",
    )
    toll_cost = fields.Monetary()
    fuel_cost = fields.Monetary()
    planned_travel_hours = fields.Float()
    planned_travel_km = fields.Float(
        string="Planned Travel Distance (km)",
        help="Distance this market actually costs, counted the same way as the travel "
             "cost: a return trip is entered as the full return distance.",
    )
    travel_hourly_cost = fields.Monetary()
    ferry_cost = fields.Monetary()
    zone_cost = fields.Monetary()
    other_route_cost = fields.Monetary()
    manual_travel_total = fields.Monetary()
    accepted_travel_cost = fields.Monetary(compute="_compute_results", store=True)
    planned_work_hours = fields.Float()
    work_hourly_cost = fields.Monetary()
    stall_rent = fields.Monetary()
    parking_cost = fields.Monetary()
    accommodation_cost = fields.Monetary()
    other_fixed_cost = fields.Monetary()
    weighted_unit_revenue = fields.Monetary(compute="_compute_results", store=True)
    weighted_unit_contribution = fields.Monetary(compute="_compute_results", store=True)
    contribution_margin_ratio = fields.Float(compute="_compute_results", store=True)
    fixed_event_cost = fields.Monetary(compute="_compute_results", store=True)
    break_even_units = fields.Integer(compute="_compute_results", store=True)
    break_even_revenue = fields.Monetary(compute="_compute_results", store=True)
    planned_units = fields.Float(compute="_compute_results", store=True)
    sales_revenue_excl_vat = fields.Monetary(compute="_compute_results", store=True)
    customer_receipts_incl_vat = fields.Monetary(compute="_compute_results", store=True)
    total_variable_cost = fields.Monetary(compute="_compute_results", store=True)
    projected_contribution = fields.Monetary(compute="_compute_results", store=True)
    projected_margin = fields.Monetary(compute="_compute_results", store=True)
    break_even_sales_excl_vat = fields.Monetary(compute="_compute_results", store=True)
    break_even_customer_receipts_incl_vat = fields.Monetary(compute="_compute_results", store=True)
    calculation_blocked = fields.Boolean(compute="_compute_results", store=True)
    calculation_note = fields.Char(compute="_compute_results", store=True)
    target_margin_per_hour = fields.Monetary(
        string="Target Margin per Hour",
        help="Hourly margin floor this market is judged against. Defaults to the company "
             "policy; zero judges the market on break-even headroom alone.",
    )
    effort_hours = fields.Float(
        compute="_compute_results", store=True, string="Work + Travel Hours",
        help="Hours the market actually costs: stand work plus travel.",
    )
    margin_per_effort_hour = fields.Monetary(
        compute="_compute_results", store=True, string="Margin per Hour (Work + Travel)",
    )
    margin_per_work_hour = fields.Monetary(
        compute="_compute_results", store=True, string="Margin per Work Hour",
    )
    travel_distance_km = fields.Float(
        compute="_compute_results", store=True, string="Travel Distance (km)",
    )
    travel_distance_known = fields.Boolean(compute="_compute_results", store=True)
    margin_per_travel_km = fields.Monetary(
        compute="_compute_results", store=True, string="Margin per Kilometre",
    )
    break_even_headroom_ratio = fields.Float(
        compute="_compute_results", store=True, string="Break-even Headroom",
        help="How far the planned units sit above break-even, as a share of break-even.",
    )
    recommendation = fields.Selection(
        VERDICT_SELECTION, compute="_compute_results", store=True, string="Verdict",
    )
    recommendation_note = fields.Char(compute="_compute_results", store=True)

    _values_nonnegative = models.Constraint(
        "CHECK(target_margin_per_hour >= 0 "
        "AND toll_cost >= 0 AND fuel_cost >= 0 AND planned_travel_hours >= 0 "
        "AND planned_travel_km >= 0 "
        "AND travel_hourly_cost >= 0 AND ferry_cost >= 0 AND zone_cost >= 0 "
        "AND other_route_cost >= 0 AND manual_travel_total >= 0 "
        "AND planned_work_hours >= 0 AND work_hourly_cost >= 0 AND stall_rent >= 0 "
        "AND parking_cost >= 0 AND accommodation_cost >= 0 AND other_fixed_cost >= 0)",
        "Scenario cost values cannot be negative.",
    )

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            operation = self.env["mb.commercial.operation"].browse(values.get("operation_id"))
            if operation:
                values.setdefault("travel_estimate_id", operation.travel_estimate_id.id)
                values.setdefault(
                    "target_margin_per_hour",
                    operation.company_id.mb_market_target_margin_per_hour,
                )
        return super().create(values_list)

    @api.depends(
        "route_cost_mode", "travel_estimate_id.total_operating_cost", "toll_cost",
        "fuel_cost", "planned_travel_hours", "travel_hourly_cost", "ferry_cost",
        "zone_cost", "other_route_cost", "manual_travel_total", "planned_work_hours",
        "work_hourly_cost", "stall_rent", "parking_cost", "accommodation_cost",
        "other_fixed_cost", "calculation_mode", "target_margin_per_hour",
        "travel_estimate_id.duration_hours",
        "planned_travel_km",
        "travel_estimate_id.distance_km",
        "cost_line_ids.category", "cost_line_ids.calculation", "cost_line_ids.quantity",
        "cost_line_ids.planned_amount",
        "line_ids.expected_sold_qty", "line_ids.sale_price_excluded_tax",
        "line_ids.customer_price_incl_vat", "line_ids.channel_fee_unrounded",
        "line_ids.turnover_levy_unrounded", "line_ids.variable_cost_unrounded",
        "line_ids.unit_contribution_unrounded", "line_ids.calculation_blocked",
    )
    def _compute_results(self):
        for scenario in self:
            if scenario.route_cost_mode == "provider_total":
                travel = scenario.travel_estimate_id.total_operating_cost
            elif scenario.route_cost_mode == "components":
                travel = (
                    scenario.toll_cost + scenario.fuel_cost
                    + scenario.planned_travel_hours * scenario.travel_hourly_cost
                    + scenario.ferry_cost + scenario.zone_cost + scenario.other_route_cost
                )
            else:
                travel = scenario.manual_travel_total
            legacy_fixed = (
                travel + scenario.planned_work_hours * scenario.work_hourly_cost
                + scenario.stall_rent + scenario.parking_cost
                + scenario.accommodation_cost + scenario.other_fixed_cost
            )
            fixed = sum(scenario.cost_line_ids.mapped("planned_amount")) or legacy_fixed
            units = sum(scenario.line_ids.mapped("expected_sold_qty"))
            use_legacy_mix = not units and any(scenario.line_ids.mapped("mix_share"))
            sales = sum(
                line.sale_price_excluded_tax * line.expected_sold_qty
                for line in scenario.line_ids
            )
            receipts = sum(
                line.customer_price_incl_vat * line.expected_sold_qty
                for line in scenario.line_ids
            )
            variable_cost = sum(
                (line.channel_fee_unrounded + line.turnover_levy_unrounded
                 + line.variable_cost_unrounded) * line.expected_sold_qty
                for line in scenario.line_ids
            )
            contribution = sales - variable_cost
            if use_legacy_mix:
                mix_total = sum(scenario.line_ids.mapped("mix_share"))
                weighted_revenue = sum(
                    line.mix_share / 100.0 * line.net_unit_revenue for line in scenario.line_ids
                )
                weighted_contribution = sum(
                    line.mix_share / 100.0 * line.unit_contribution for line in scenario.line_ids
                )
            else:
                mix_total = 100.0 if units else 0.0
                weighted_revenue = sales / units if units else 0.0
                weighted_contribution = contribution / units if units else 0.0
            note = False
            blocked = False
            if not scenario.line_ids:
                blocked, note = True, _("Add at least one sales-mix line.")
            elif use_legacy_mix and float_compare(mix_total, 100.0, precision_digits=4) != 0:
                blocked, note = True, _("Sales-mix shares must total 100%%.")
            elif not use_legacy_mix and units <= 0:
                blocked, note = True, _("Expected sold quantity must be positive.")
            elif scenario.line_ids.filtered("calculation_blocked"):
                blocked, note = True, _("Complete the missing product costs and prices.")
            elif weighted_revenue <= 0 or weighted_contribution <= 0:
                blocked, note = True, _("Weighted revenue and contribution must be positive.")
            elif scenario.route_cost_mode == "provider_total" and (
                not scenario.travel_estimate_id
                or scenario.travel_estimate_id.state != "accepted"
                or scenario.travel_estimate_id.incomplete
                and not scenario.travel_estimate_id.incomplete_acknowledged
            ):
                blocked, note = True, _("Accept a complete or acknowledged TollQuote estimate.")
            scenario.accepted_travel_cost = scenario.currency_id.round(travel)
            scenario.fixed_event_cost = scenario.currency_id.round(fixed)
            scenario.weighted_unit_revenue = scenario.currency_id.round(weighted_revenue)
            scenario.weighted_unit_contribution = scenario.currency_id.round(weighted_contribution)
            scenario.contribution_margin_ratio = (
                weighted_contribution / weighted_revenue if weighted_revenue > 0 else 0.0
            )
            scenario.break_even_units = (
                math.ceil(fixed / weighted_contribution) if not blocked else 0
            )
            scenario.break_even_revenue = scenario.currency_id.round(
                fixed / scenario.contribution_margin_ratio
            ) if not blocked else 0.0
            scenario.planned_units = units
            scenario.sales_revenue_excl_vat = scenario.currency_id.round(sales)
            scenario.customer_receipts_incl_vat = scenario.currency_id.round(receipts)
            scenario.total_variable_cost = scenario.currency_id.round(variable_cost)
            scenario.projected_contribution = scenario.currency_id.round(contribution)
            scenario.projected_margin = scenario.currency_id.round(contribution - fixed)
            scenario.break_even_sales_excl_vat = scenario.break_even_revenue
            vat_factor = receipts / sales if sales > 0 else 1.0
            scenario.break_even_customer_receipts_incl_vat = scenario.currency_id.round(
                scenario.break_even_revenue * vat_factor
            ) if not blocked else 0.0
            scenario.calculation_blocked = blocked
            scenario.calculation_note = note
            work_hours = scenario._resolved_work_hours()
            travel_hours = scenario._resolved_travel_hours()
            effort_hours = work_hours + travel_hours
            margin = scenario.projected_margin
            scenario.effort_hours = effort_hours
            scenario.margin_per_effort_hour = scenario.currency_id.round(
                margin / effort_hours
            ) if effort_hours > 0 else 0.0
            scenario.margin_per_work_hour = scenario.currency_id.round(
                margin / work_hours
            ) if work_hours > 0 else 0.0
            travel_km = scenario._resolved_travel_km()
            scenario.travel_distance_km = travel_km
            # A market with no quote and no typed distance has no denominator, and a
            # stored 0 per kilometre would read as a market that earns nothing per
            # kilometre. Forms and the report hide the figure unless this flag is
            # set; the comparison list, which cannot hide one cell, shows the flag
            # in a column beside it.
            scenario.travel_distance_known = travel_km > 0
            scenario.margin_per_travel_km = scenario.currency_id.round(
                margin / travel_km
            ) if travel_km > 0 else 0.0
            if blocked:
                scenario.break_even_headroom_ratio = 0.0
            elif scenario.break_even_units:
                scenario.break_even_headroom_ratio = (
                    units - scenario.break_even_units
                ) / scenario.break_even_units
            else:
                # With no fixed costs, the first profitable sale is already above
                # break-even. Use a bounded sentinel that clears the headroom gate
                # instead of storing an undefined/infinite ratio.
                scenario.break_even_headroom_ratio = 1.0
            scenario.recommendation, scenario.recommendation_note = (
                scenario._evaluate_recommendation(blocked, note, use_legacy_mix, units)
            )

    def _resolved_work_hours(self):
        """Stand hours, from the scenario itself or its own hourly labour lines.

        Never from the operation: these feed stored computes, which are written by
        _write() and so never meet the immutability guard in write(). A scenario
        that read the operation's hours would have its approved margin per hour
        rewritten the next time somebody moved the market's dates.
        """
        self.ensure_one()
        return self.planned_work_hours or sum(
            line.quantity for line in self.cost_line_ids
            if line.category == "labour" and line.calculation == "hour"
        )

    def _resolved_travel_hours(self):
        """Door-to-door travel hours behind this scenario's own route cost."""
        self.ensure_one()
        if self.route_cost_mode == "provider_total":
            return self.travel_estimate_id.duration_hours
        return self.planned_travel_hours

    def _resolved_travel_km(self):
        """Kilometres behind the accepted route cost, mirroring _resolved_travel_hours."""
        self.ensure_one()
        if self.route_cost_mode == "provider_total":
            quoted = self.travel_estimate_id.distance_km
        else:
            # Per-kilometre cost lines are not additive as distance: two vehicles
            # costed separately drive the same road once, so take the longest leg
            # rather than their sum.
            quoted = self.planned_travel_km or max(
                (
                    line.quantity for line in self.cost_line_ids
                    if line.category == "travel" and line.calculation == "kilometre"
                ),
                default=0.0,
            )
        return quoted

    def _evaluate_recommendation(self, blocked, note, use_legacy_mix, units):
        """Turn the break-even figures into a verdict a stallholder can act on."""
        self.ensure_one()
        verdict, reason = self._verdict(
            blocked=blocked,
            judgeable=not use_legacy_mix and units > 0,
            margin=self.projected_margin,
            below_break_even=units < self.break_even_units,
            effort_hours=self.effort_hours,
            margin_per_hour=self.margin_per_effort_hour,
            target_per_hour=self.target_margin_per_hour,
            headroom_ratio=self.break_even_headroom_ratio,
        )

        def money(amount):
            return formatLang(self.env, amount, currency_obj=self.currency_id)

        headroom_percent = self.break_even_headroom_ratio * 100.0
        if reason == "blocked":
            return verdict, note or _("Complete the scenario before judging this market.")
        if reason == "not_judgeable":
            return verdict, _(
                "Enter expected sold quantities: an average-basket mix without volumes "
                "cannot be judged."
            )
        if reason == "below_break_even":
            return verdict, _(
                "Projected margin %(margin)s: %(units)s planned units against %(break_even)s "
                "needed to break even.",
                margin=money(self.projected_margin),
                units=round(units, 2),
                break_even=self.break_even_units,
            )
        if reason == "no_hours":
            return verdict, _(
                "%(margin)s above costs, but no work or travel hours are planned, so the "
                "hourly return cannot be checked.",
                margin=money(self.projected_margin),
            )
        if reason == "below_target":
            return verdict, _(
                "%(rate)s per hour over %(hours).1f hours of work and travel, below the "
                "%(target)s target.",
                rate=money(self.margin_per_effort_hour),
                hours=self.effort_hours,
                target=money(self.target_margin_per_hour),
            )
        if reason == "thin_headroom":
            return verdict, _(
                "Only %(headroom).0f%% above break-even (%(units)s planned against "
                "%(break_even)s): a slow day turns this into a loss.",
                headroom=headroom_percent,
                units=round(units, 2),
                break_even=self.break_even_units,
            )
        return verdict, _(
            "%(margin)s over %(hours).1f hours of work and travel (%(rate)s per hour), "
            "%(headroom).0f%% above break-even.",
            margin=money(self.projected_margin),
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
            operation = scenario.operation_id
            if operation.state not in ("draft", "quoted"):
                raise UserError(_("Reopen the operation before approving a new baseline."))
            operation.primary_scenario_id = scenario
            operation.action_approve()
        return True

    def _approve_as_primary(self):
        for scenario in self:
            if scenario.state != "draft":
                raise UserError(_("Only draft scenarios can be approved."))
            if scenario.calculation_blocked:
                raise ValidationError(scenario.calculation_note)
            scenario.operation_id.scenario_ids.filtered(
                lambda other, current=scenario:
                other != current and other.state == "approved"
            ).write({"state": "superseded"})
            scenario.write({
                "state": "approved", "approved_by_id": self.env.user.id,
                "approved_at": fields.Datetime.now(),
            })
            scenario.operation_id.with_context(mb_scenario_approval=True).write({
                "primary_scenario_id": scenario.id,
                "expected_revenue": scenario.sales_revenue_excl_vat,
            })

    def write(self, vals):
        protected = set(self._fields) - {
            "state", "approved_by_id", "approved_at", "message_follower_ids",
            "message_partner_ids",
        }
        if protected.intersection(vals) and self.filtered(lambda scenario: scenario.state != "draft"):
            raise UserError(_("Approved or superseded scenarios are immutable; create a new scenario."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        if self.filtered(lambda scenario: scenario.state != "draft"):
            raise UserError(_("Only draft profitability scenarios can be deleted."))


class MbCommercialProfitabilityScenarioLine(models.Model):
    _name = "mb.commercial.profitability.scenario.line"
    _description = "Commercial Profitability Sales Mix"
    _order = "sequence, id"
    _check_company_auto = True

    sequence = fields.Integer(default=10)
    scenario_id = fields.Many2one(
        "mb.commercial.profitability.scenario", required=True,
        ondelete="cascade", check_company=True, index=True,
    )
    company_id = fields.Many2one(related="scenario_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    product_id = fields.Many2one("product.product", check_company=True)
    source_stock_plan_line_id = fields.Many2one(
        "mb.market.stock.plan.line", ondelete="restrict", check_company=True,
        domain="[('operation_id', '=', parent.operation_id), ('target_type', '=', 'product')]",
    )
    mix_share = fields.Float(required=True, default=100.0, digits=(16, 4))
    expected_sold_qty = fields.Float(default=0.0)
    sale_price_excluded_tax = fields.Monetary(required=True)
    vat_rate = fields.Float(digits=(16, 4), help="Percentage applied to the customer price.")
    customer_price_incl_vat = fields.Monetary(compute="_compute_contribution", store=True)
    channel_fee_rate = fields.Float(digits=(16, 4), help="Percentage, e.g. 2.5 for 2.5%.")
    channel_fee_amount = fields.Monetary(compute="_compute_contribution", store=True)
    channel_fee_unrounded = fields.Float(compute="_compute_contribution", store=True, digits=(16, 8))
    turnover_levy_rate = fields.Float(digits=(16, 6))
    eligible_turnover_basis = fields.Monetary()
    turnover_levy_amount = fields.Monetary(compute="_compute_contribution", store=True)
    turnover_levy_unrounded = fields.Float(compute="_compute_contribution", store=True, digits=(16, 8))
    product_unit_cost = fields.Monetary(required=True, default=0.0)
    product_cost_mode = fields.Selection(
        [("amount", "Amount"), ("sales_percent", "Percentage of sales excluding VAT")],
        required=True, default="amount",
    )
    product_cost_rate = fields.Float(digits=(16, 4))
    product_cost_unrounded = fields.Float(compute="_compute_contribution", store=True, digits=(16, 8))
    other_variable_unit_cost = fields.Monetary()
    net_unit_revenue = fields.Monetary(compute="_compute_contribution", store=True)
    unit_contribution = fields.Monetary(compute="_compute_contribution", store=True)
    calculation_blocked = fields.Boolean(compute="_compute_contribution", store=True)
    variable_cost_unrounded = fields.Float(compute="_compute_contribution", store=True, digits=(16, 8))
    unit_contribution_unrounded = fields.Float(compute="_compute_contribution", store=True, digits=(16, 8))
    exclude_product_cost = fields.Boolean()
    cost_source = fields.Selection(
        [("product", "Odoo product cost"), ("planning", "Explicit planning cost"), ("proxy", "Sale-price proxy")],
        required=True,
        default="product",
    )
    cost_date = fields.Date(required=True, default=fields.Date.context_today)

    _values_nonnegative = models.Constraint(
        "CHECK(mix_share >= 0 AND expected_sold_qty >= 0 AND sale_price_excluded_tax >= 0 "
        "AND vat_rate >= 0 AND turnover_levy_rate >= 0 "
        "AND channel_fee_rate >= 0 AND channel_fee_rate <= 100 "
        "AND product_unit_cost >= 0 AND product_cost_rate >= 0 AND product_cost_rate <= 100 "
        "AND other_variable_unit_cost >= 0)",
        "Sales mix, prices, rates, and costs must be non-negative; fee rate cannot exceed 100%.",
    )

    @api.onchange("product_id")
    def _onchange_product_id(self):
        if self.product_id:
            self.sale_price_excluded_tax = self.product_id.lst_price
            self.product_unit_cost = self.product_id.standard_price
            self.cost_source = "product"
            self.cost_date = fields.Date.context_today(self)

    @api.model_create_multi
    def create(self, values_list):
        scenarios = self.env["mb.commercial.profitability.scenario"].browse(
            [values.get("scenario_id") for values in values_list if values.get("scenario_id")]
        )
        if scenarios.filtered(lambda scenario: scenario.state != "draft"):
            raise UserError(_("Approved scenario lines are immutable; create a revision."))
        return super().create(values_list)

    @api.onchange("source_stock_plan_line_id")
    def _onchange_source_stock_plan_line_id(self):
        if self.source_stock_plan_line_id:
            target = self.source_stock_plan_line_id
            self.product_id = target.product_id
            self.expected_sold_qty = target.expected_sold_qty
            self.sale_price_excluded_tax = target.expected_unit_price
            self.product_unit_cost = target.expected_unit_cost
            self.cost_source = target.cost_source
            self.cost_date = target.cost_date

    @api.depends(
        "sale_price_excluded_tax", "channel_fee_rate", "product_unit_cost",
        "other_variable_unit_cost", "cost_source", "cost_date", "expected_sold_qty",
        "vat_rate", "turnover_levy_rate", "eligible_turnover_basis",
        "exclude_product_cost", "product_cost_mode", "product_cost_rate",
    )
    def _compute_contribution(self):
        for line in self:
            fee = line.sale_price_excluded_tax * line.channel_fee_rate / 100.0
            levy_basis = line.eligible_turnover_basis or line.sale_price_excluded_tax
            levy = levy_basis * line.turnover_levy_rate / 100.0
            net = line.sale_price_excluded_tax - fee
            product_cost = (
                line.sale_price_excluded_tax * line.product_cost_rate / 100.0
                if line.product_cost_mode == "sales_percent" else line.product_unit_cost
            )
            variable = product_cost + line.other_variable_unit_cost
            contribution = net - levy - variable
            line.customer_price_incl_vat = line.currency_id.round(
                line.sale_price_excluded_tax * (1.0 + line.vat_rate / 100.0)
            )
            line.channel_fee_amount = line.currency_id.round(fee)
            line.channel_fee_unrounded = fee
            line.turnover_levy_amount = line.currency_id.round(levy)
            line.turnover_levy_unrounded = levy
            line.variable_cost_unrounded = variable
            line.product_cost_unrounded = product_cost
            line.unit_contribution_unrounded = contribution
            line.net_unit_revenue = line.currency_id.round(net)
            line.unit_contribution = line.currency_id.round(contribution)
            line.calculation_blocked = (
                not line.cost_date
                or line.sale_price_excluded_tax <= 0
                or line.product_unit_cost < 0
                or product_cost == 0 and not line.exclude_product_cost
            )

    def write(self, vals):
        if self.scenario_id.filtered(lambda scenario: scenario.state != "draft"):
            raise UserError(_("Approved scenario lines are immutable."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        if self.scenario_id.filtered(lambda scenario: scenario.state != "draft"):
            raise UserError(_("Approved scenario lines cannot be deleted."))

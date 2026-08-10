import math

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare


class MbCommercialProfitabilityScenario(models.Model):
    _name = "mb.commercial.profitability.scenario"
    _description = "Commercial Profitability Scenario"
    _inherit = ["mail.thread"]
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
        related="operation_id.travel_estimate_id", store=True,
    )
    toll_cost = fields.Monetary()
    fuel_cost = fields.Monetary()
    planned_travel_hours = fields.Float()
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
    calculation_blocked = fields.Boolean(compute="_compute_results", store=True)
    calculation_note = fields.Char(compute="_compute_results", store=True)

    _values_nonnegative = models.Constraint(
        "CHECK(toll_cost >= 0 AND fuel_cost >= 0 AND planned_travel_hours >= 0 "
        "AND travel_hourly_cost >= 0 AND ferry_cost >= 0 AND zone_cost >= 0 "
        "AND other_route_cost >= 0 AND manual_travel_total >= 0 "
        "AND planned_work_hours >= 0 AND work_hourly_cost >= 0 AND stall_rent >= 0 "
        "AND parking_cost >= 0 AND accommodation_cost >= 0 AND other_fixed_cost >= 0)",
        "Scenario cost values cannot be negative.",
    )

    @api.depends(
        "route_cost_mode", "travel_estimate_id.total_operating_cost", "toll_cost",
        "fuel_cost", "planned_travel_hours", "travel_hourly_cost", "ferry_cost",
        "zone_cost", "other_route_cost", "manual_travel_total", "planned_work_hours",
        "work_hourly_cost", "stall_rent", "parking_cost", "accommodation_cost",
        "other_fixed_cost", "line_ids.mix_share", "line_ids.net_unit_revenue",
        "line_ids.unit_contribution", "line_ids.calculation_blocked",
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
            fixed = (
                travel + scenario.planned_work_hours * scenario.work_hourly_cost
                + scenario.stall_rent + scenario.parking_cost
                + scenario.accommodation_cost + scenario.other_fixed_cost
            )
            mix_total = sum(scenario.line_ids.mapped("mix_share"))
            weighted_revenue = sum(
                line.mix_share / 100.0 * line.net_unit_revenue
                for line in scenario.line_ids
            )
            weighted_contribution = sum(
                line.mix_share / 100.0 * line.unit_contribution
                for line in scenario.line_ids
            )
            note = False
            blocked = False
            if not scenario.line_ids:
                blocked, note = True, _("Add at least one sales-mix line.")
            elif float_compare(mix_total, 100.0, precision_digits=4) != 0:
                blocked, note = True, _("Sales-mix shares must total 100%%.")
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
            scenario.calculation_blocked = blocked
            scenario.calculation_note = note

    def action_approve(self):
        for scenario in self:
            if scenario.state != "draft":
                raise UserError(_("Only draft scenarios can be approved."))
            if scenario.calculation_blocked:
                raise ValidationError(scenario.calculation_note)
            scenario.operation_id.scenario_ids.filtered(
                lambda other, current=scenario:
                other != current and other.state == "approved"
            ).write({"state": "superseded"})
            scenario.state = "approved"
        return True

    def write(self, vals):
        protected = set(self._fields) - {"state", "message_follower_ids", "message_partner_ids"}
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
    product_id = fields.Many2one("product.product", required=True, check_company=True)
    mix_share = fields.Float(required=True, default=100.0, digits=(16, 4))
    sale_price_excluded_tax = fields.Monetary(required=True)
    channel_fee_rate = fields.Float(digits=(16, 4), help="Percentage, e.g. 2.5 for 2.5%.")
    channel_fee_amount = fields.Monetary(compute="_compute_contribution", store=True)
    product_unit_cost = fields.Monetary(required=True)
    other_variable_unit_cost = fields.Monetary()
    net_unit_revenue = fields.Monetary(compute="_compute_contribution", store=True)
    unit_contribution = fields.Monetary(compute="_compute_contribution", store=True)
    calculation_blocked = fields.Boolean(compute="_compute_contribution", store=True)
    cost_source = fields.Selection(
        [("product", "Odoo product cost"), ("planning", "Explicit planning cost"), ("proxy", "Sale-price proxy")],
        required=True,
        default="product",
    )
    cost_date = fields.Date(required=True, default=fields.Date.context_today)

    _values_nonnegative = models.Constraint(
        "CHECK(mix_share >= 0 AND sale_price_excluded_tax >= 0 "
        "AND channel_fee_rate >= 0 AND channel_fee_rate <= 100 "
        "AND product_unit_cost >= 0 AND other_variable_unit_cost >= 0)",
        "Sales mix, prices, rates, and costs must be non-negative; fee rate cannot exceed 100%.",
    )

    @api.onchange("product_id")
    def _onchange_product_id(self):
        if self.product_id:
            self.sale_price_excluded_tax = self.product_id.lst_price
            self.product_unit_cost = self.product_id.standard_price
            self.cost_source = "product"
            self.cost_date = fields.Date.context_today(self)

    @api.depends(
        "sale_price_excluded_tax", "channel_fee_rate", "product_unit_cost",
        "other_variable_unit_cost", "cost_source", "cost_date",
    )
    def _compute_contribution(self):
        for line in self:
            fee = line.sale_price_excluded_tax * line.channel_fee_rate / 100.0
            net = line.sale_price_excluded_tax - fee
            contribution = net - line.product_unit_cost - line.other_variable_unit_cost
            line.channel_fee_amount = line.currency_id.round(fee)
            line.net_unit_revenue = line.currency_id.round(net)
            line.unit_contribution = line.currency_id.round(contribution)
            line.calculation_blocked = (
                not line.cost_date
                or line.sale_price_excluded_tax <= 0
                or line.product_unit_cost < 0
            )

    def write(self, vals):
        if self.scenario_id.filtered(lambda scenario: scenario.state != "draft"):
            raise UserError(_("Approved scenario lines are immutable."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        if self.scenario_id.filtered(lambda scenario: scenario.state != "draft"):
            raise UserError(_("Approved scenario lines cannot be deleted."))

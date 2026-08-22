from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class MbCommercialOperation(models.Model):
    _inherit = "mb.commercial.operation"

    operation_type = fields.Selection(
        selection_add=[
            ("depot_refill", "Depot Refill"),
            ("depot_permanence", "Depot Permanence"),
        ],
        ondelete={"depot_refill": "set default", "depot_permanence": "set default"},
    )
    depot_warehouse_id = fields.Many2one(
        "stock.warehouse",
        check_company=True,
        domain="[('is_depot', '=', True), ('company_id', '=', company_id)]",
        tracking=True,
    )
    recovery_scope = fields.Selection(
        [
            ("operation_only", "Operation-linked evidence only"),
            ("until_next_refill", "Depot sales until next approved refill"),
            ("contract_period", "Selected contract period"),
            ("informational", "Planning only"),
        ],
        required=True,
        default="operation_only",
        tracking=True,
    )
    recovery_date_from = fields.Datetime(tracking=True)
    recovery_date_to = fields.Datetime(tracking=True)
    comparison_window_revenue = fields.Monetary(
        compute="_compute_comparison_window_revenue",
        string="Contract Sales in Comparison Window",
    )

    def _recovery_bounds(self):
        self.ensure_one()
        start = self.recovery_date_from or self.actual_end or self.planned_start
        end = self.recovery_date_to
        if self.recovery_scope == "until_next_refill":
            next_refill = self.search(
                [
                    ("id", "!=", self.id),
                    ("contract_id", "=", self.contract_id.id),
                    ("operation_type", "=", "depot_refill"),
                    (
                        "state",
                        "in",
                        ("approved", "scheduled", "in_progress", "done", "financially_closed"),
                    ),
                    ("planned_start", ">", start),
                ],
                order="planned_start, id",
                limit=1,
            )
            end = next_refill.planned_start or end
        return start, end

    @api.constrains("recovery_scope", "recovery_date_from", "recovery_date_to", "contract_id")
    def _check_recovery_window(self):
        for operation in self.filtered(
            lambda item: item.recovery_scope in ("until_next_refill", "contract_period")
        ):
            start, end = operation._recovery_bounds()
            if operation.recovery_scope == "contract_period" and (not start or not end):
                raise ValidationError(_("Choose both boundaries for a contract recovery period."))
            if end and end <= start:
                raise ValidationError(_("The recovery period must end after it starts."))
            candidates = self.search(
                [
                    ("id", "!=", operation.id),
                    ("contract_id", "=", operation.contract_id.id),
                    ("recovery_scope", "in", ("until_next_refill", "contract_period")),
                ]
            )
            if any(
                (not other._recovery_bounds()[1] or other._recovery_bounds()[1] > start)
                and (not end or other._recovery_bounds()[0] < end)
                for other in candidates
            ):
                raise ValidationError(
                    _("Depot recovery windows for the same contract cannot overlap.")
                )

    def _get_planning_warnings(self, scenario=None):
        warnings = super()._get_planning_warnings(scenario)
        if self.recovery_scope == "contract_period" and not (
            self.recovery_date_from and self.recovery_date_to
        ):
            warnings.append(
                (
                    "missing_recovery_period",
                    "blocking",
                    _("Choose the depot recovery-period boundaries."),
                )
            )
        return warnings

    def _get_depot_comparison_items(self):
        self.ensure_one()
        items = []
        if (
            self.recovery_scope not in ("until_next_refill", "contract_period")
            or not self.contract_id
        ):
            return items
        start, end = self._recovery_bounds()
        domain = [
            ("report_id.commercial_contract_id", "=", self.contract_id.id),
            ("report_id.state", "in", ("processed", "reversal_required")),
            ("sold_at", ">=", start),
        ]
        if end:
            domain.append(("sold_at", "<", end))
        for line in self.env["mb.depot.sale.report.line"].search(domain):
            items.append(
                {
                    "model": line._name,
                    "res_id": line.id,
                    "component": "revenue",
                    "date": fields.Date.to_date(line.sold_at),
                    "amount": line.net_line_amount,
                    "currency": line.currency_id,
                }
            )
        return items

    def _compute_comparison_window_revenue(self):
        for operation in self:
            total = sum(
                operation._profitability_amount_company_currency(item)
                for item in operation._get_depot_comparison_items()
            )
            operation.comparison_window_revenue = operation.currency_id.round(total)

    def _ensure_market_location(self):
        self.ensure_one()
        if self.operation_type == "depot_refill" and self.depot_warehouse_id:
            if self.market_location_id != self.depot_warehouse_id.lot_stock_id:
                self.market_location_id = self.depot_warehouse_id.lot_stock_id
            return self.market_location_id
        return super()._ensure_market_location()

    def _stock_discrepancies(self):
        self.ensure_one()
        if self.operation_type == "depot_refill":
            if not self.preparation_picking_id or self.preparation_picking_id.state != "done":
                return [_("The refill transfer is not completed.")]
            return []
        return super()._stock_discrepancies()


class MbCommercialObligation(models.Model):
    _inherit = "mb.commercial.obligation"

    obligation_type = fields.Selection(
        selection_add=[
            ("depot_permanence", "Depot permanence"),
            ("depot_refill", "Depot refill visit"),
        ],
        ondelete={"depot_permanence": "set default", "depot_refill": "set default"},
    )


class MbCommercialObligationOccurrence(models.Model):
    _inherit = "mb.commercial.obligation.occurrence"

    def _prepare_operation_values(self):
        values = super()._prepare_operation_values()
        obligation_type = self.obligation_id.obligation_type
        if obligation_type in ("depot_permanence", "depot_refill"):
            values.update(
                {
                    "operation_type": obligation_type,
                    "depot_warehouse_id": self.contract_id.depot_warehouse_id.id,
                    "source_warehouse_id": self.contract_id.source_warehouse_id.id,
                }
            )
        return values

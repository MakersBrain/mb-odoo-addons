from odoo import fields, models, tools


class MbCommercialProfitabilityReport(models.Model):
    _name = "mb.commercial.profitability.report"
    _description = "Commercial Planned versus Actual Profitability"
    _auto = False
    _order = "operation_date desc, id desc"

    operation_id = fields.Many2one("mb.commercial.operation", readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)
    currency_id = fields.Many2one("res.currency", readonly=True)
    partner_id = fields.Many2one("res.partner", readonly=True)
    contract_id = fields.Many2one("mb.commercial.contract", readonly=True)
    operation_type = fields.Selection(related="operation_id.operation_type", readonly=True)
    state = fields.Selection(related="operation_id.state", readonly=True)
    operation_date = fields.Date(readonly=True)
    month = fields.Date(readonly=True)
    planned_revenue = fields.Monetary(readonly=True)
    planned_cost = fields.Monetary(readonly=True)
    planned_margin = fields.Monetary(readonly=True)
    actual_revenue = fields.Monetary(readonly=True)
    actual_cost = fields.Monetary(readonly=True)
    actual_margin = fields.Monetary(readonly=True)
    revenue_variance = fields.Monetary(readonly=True)
    cost_variance = fields.Monetary(readonly=True)
    margin_variance = fields.Monetary(readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE VIEW {self._table} AS
            WITH scoped_items AS (
                SELECT
                    line.mb_commercial_operation_id AS operation_id,
                    CASE WHEN line.amount > 0 THEN line.amount ELSE 0 END AS revenue,
                    CASE WHEN line.amount < 0 THEN -line.amount ELSE 0 END AS cost
                FROM account_analytic_line line
                WHERE line.mb_commercial_operation_id IS NOT NULL
                UNION ALL
                SELECT
                    operation.id AS operation_id,
                    CASE WHEN line.amount > 0 THEN line.amount ELSE 0 END AS revenue,
                    CASE WHEN line.amount < 0 THEN -line.amount ELSE 0 END AS cost
                FROM mb_commercial_operation operation
                JOIN account_analytic_line line ON line.task_id = operation.task_id
                WHERE line.mb_commercial_operation_id IS NULL
                UNION ALL
                SELECT
                    move.mb_commercial_operation_id AS operation_id,
                    CASE WHEN move.move_type = 'out_invoice'
                         THEN ABS(move.amount_untaxed_signed)
                         WHEN move.move_type = 'out_refund'
                         THEN -ABS(move.amount_untaxed_signed) ELSE 0 END AS revenue,
                    CASE WHEN move.move_type = 'in_invoice'
                         THEN ABS(move.amount_untaxed_signed)
                         WHEN move.move_type = 'in_refund'
                         THEN -ABS(move.amount_untaxed_signed) ELSE 0 END AS cost
                FROM account_move move
                WHERE move.mb_commercial_operation_id IS NOT NULL AND move.state = 'posted'
                UNION ALL
                SELECT
                    relation.operation_id,
                    CASE WHEN move.move_type = 'out_invoice'
                         THEN ABS(move.amount_untaxed_signed)
                         WHEN move.move_type = 'out_refund'
                         THEN -ABS(move.amount_untaxed_signed) ELSE 0 END AS revenue,
                    CASE WHEN move.move_type = 'in_invoice'
                         THEN ABS(move.amount_untaxed_signed)
                         WHEN move.move_type = 'in_refund'
                         THEN -ABS(move.amount_untaxed_signed) ELSE 0 END AS cost
                FROM mb_commercial_operation_account_move_rel relation
                JOIN account_move move ON move.id = relation.move_id AND move.state = 'posted'
                WHERE move.mb_commercial_operation_id IS NULL
            ), actual AS (
                SELECT operation_id, SUM(revenue) AS revenue, SUM(cost) AS cost
                FROM scoped_items GROUP BY operation_id
            )
            SELECT
                operation.id,
                operation.id AS operation_id,
                operation.company_id,
                company.currency_id,
                operation.partner_id,
                operation.contract_id,
                operation.planned_start::date AS operation_date,
                date_trunc('month', operation.planned_start)::date AS month,
                COALESCE(scenario.sales_revenue_excl_vat, 0) AS planned_revenue,
                operation.planned_cost,
                operation.planned_margin,
                COALESCE(actual.revenue, 0) AS actual_revenue,
                COALESCE(actual.cost, 0) AS actual_cost,
                COALESCE(actual.revenue, 0) - COALESCE(actual.cost, 0) AS actual_margin,
                COALESCE(actual.revenue, 0)
                    - COALESCE(scenario.sales_revenue_excl_vat, 0) AS revenue_variance,
                COALESCE(actual.cost, 0) - operation.planned_cost AS cost_variance,
                (COALESCE(actual.revenue, 0) - COALESCE(actual.cost, 0))
                    - operation.planned_margin AS margin_variance
            FROM mb_commercial_operation operation
            JOIN res_company company ON company.id = operation.company_id
            LEFT JOIN mb_commercial_profitability_scenario scenario
                ON scenario.id = operation.primary_scenario_id
            LEFT JOIN actual ON actual.operation_id = operation.id
        """)

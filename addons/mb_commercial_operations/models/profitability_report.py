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
            WITH actual AS (
                SELECT
                    account_id,
                    SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) AS revenue,
                    -SUM(CASE WHEN amount < 0 THEN amount ELSE 0 END) AS cost
                FROM account_analytic_line
                WHERE account_id IS NOT NULL
                GROUP BY account_id
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
                operation.expected_revenue AS planned_revenue,
                operation.planned_cost,
                operation.planned_margin,
                COALESCE(actual.revenue, 0) AS actual_revenue,
                COALESCE(actual.cost, 0) AS actual_cost,
                COALESCE(actual.revenue, 0) - COALESCE(actual.cost, 0) AS actual_margin,
                COALESCE(actual.revenue, 0) - operation.expected_revenue AS revenue_variance,
                COALESCE(actual.cost, 0) - operation.planned_cost AS cost_variance,
                (COALESCE(actual.revenue, 0) - COALESCE(actual.cost, 0))
                    - operation.planned_margin AS margin_variance
            FROM mb_commercial_operation operation
            JOIN res_company company ON company.id = operation.company_id
            JOIN project_project project ON project.id = operation.project_id
            LEFT JOIN actual ON actual.account_id = project.account_id
        """)

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class MbCommercialOperation(models.Model):
    _inherit = "mb.commercial.operation"

    expense_ids = fields.One2many(
        "hr.expense", "mb_commercial_operation_id", string="Expenses",
    )
    expenses_expected = fields.Boolean()
    expenses_complete = fields.Boolean(compute="_compute_expenses_complete")

    def _get_operation_profitability_items(self):
        self.ensure_one()
        items = super()._get_operation_profitability_items()
        for expense in self.expense_ids.filtered(
            lambda record: record.state not in ("draft", "submitted", "refused")
        ):
            items.append({
                "model": expense._name, "res_id": expense.id, "component": "cost",
                "date": expense.date, "amount": expense.total_amount_currency,
                "currency": expense.currency_id,
            })
        return items

    @api.depends("expenses_expected", "expense_ids.state")
    def _compute_expenses_complete(self):
        for operation in self:
            expenses = operation.expense_ids
            operation.expenses_complete = (
                not operation.expenses_expected
                or bool(expenses) and all(expense.state not in ("draft", "submitted", "refused") for expense in expenses)
            )

    def action_view_expenses(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("hr_expense.hr_expense_actions_my_all")
        action["domain"] = [("mb_commercial_operation_id", "=", self.id)]
        action["context"] = {
            "default_mb_commercial_operation_id": self.id,
            "default_company_id": self.company_id.id,
            "project_id": self.project_id.id,
        }
        return action

    def action_financial_close(self):
        incomplete = self.filtered(lambda operation: not operation.expenses_complete)
        if incomplete:
            raise UserError(_("Complete the expected operation expenses before financial close."))
        return super().action_financial_close()

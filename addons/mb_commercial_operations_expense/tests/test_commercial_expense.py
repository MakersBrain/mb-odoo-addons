from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCommercialExpense(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Fair"})
        cls.employee = cls.env.user.employee_id or cls.env["hr.employee"].create(
            {
                "name": "Expense User",
                "user_id": cls.env.user.id,
            }
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Parking",
                "type": "service",
                "can_be_expensed": True,
                "standard_price": 15.0,
            }
        )

    def _operation(self):
        start = fields.Datetime.now() + timedelta(days=10)
        return self.env["mb.commercial.operation"].create(
            {
                "name": "Fair",
                "partner_id": self.partner.id,
                "planned_start": start,
                "planned_end": start + timedelta(hours=6),
            }
        )

    def test_expense_link_sets_native_analytic_distribution(self):
        operation = self._operation()
        expense = self.env["hr.expense"].create(
            {
                "name": "Market parking",
                "employee_id": self.employee.id,
                "product_id": self.product.id,
                "total_amount_currency": 15.0,
                "mb_commercial_operation_id": operation.id,
            }
        )
        self.assertEqual(
            expense.analytic_distribution,
            {str(operation.analytic_account_id.id): 100.0},
        )
        self.assertEqual(operation.expense_ids, expense)

    def test_expected_draft_expense_blocks_financial_close(self):
        operation = self._operation()
        operation.expenses_expected = True
        self.env["hr.expense"].create(
            {
                "name": "Market parking",
                "employee_id": self.employee.id,
                "product_id": self.product.id,
                "total_amount_currency": 15.0,
                "mb_commercial_operation_id": operation.id,
            }
        )
        operation.action_approve()
        operation.action_done()
        with self.assertRaises(UserError):
            operation.action_financial_close()

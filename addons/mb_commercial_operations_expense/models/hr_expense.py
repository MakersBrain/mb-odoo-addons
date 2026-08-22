from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HrExpense(models.Model):
    _inherit = "hr.expense"

    mb_commercial_operation_id = fields.Many2one(
        "mb.commercial.operation",
        check_company=True,
        copy=False,
        index=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            operation = self.env["mb.commercial.operation"].browse(
                vals.get("mb_commercial_operation_id")
            )
            if operation:
                vals.setdefault(
                    "analytic_distribution",
                    {str(operation.analytic_account_id.id): 100.0},
                )
        return super().create(vals_list)

    def write(self, vals):
        if "mb_commercial_operation_id" in vals:
            operations = self.mb_commercial_operation_id | self.env[
                "mb.commercial.operation"
            ].browse(vals.get("mb_commercial_operation_id"))
            if operations.filtered(lambda operation: operation.state == "financially_closed"):
                raise UserError(
                    _("Reopen the financially closed operation before changing expense links.")
                )
            operation = self.env["mb.commercial.operation"].browse(
                vals.get("mb_commercial_operation_id")
            )
            if operation:
                vals.setdefault(
                    "analytic_distribution",
                    {str(operation.analytic_account_id.id): 100.0},
                )
        return super().write(vals)

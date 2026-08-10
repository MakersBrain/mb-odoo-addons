from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class MbDepotSaleReport(models.Model):
    _inherit = "mb.depot.sale.report"

    commercial_contract_id = fields.Many2one(
        "mb.commercial.contract",
        string="Commercial Contract",
        check_company=True,
        domain="[('depot_warehouse_id', '=', depot_warehouse_id), ('active', '=', True)]",
        tracking=True,
    )

    @api.onchange("depot_warehouse_id")
    def _onchange_depot_commercial_contract(self):
        for report in self:
            report.commercial_contract_id = report._active_commercial_contract()

    def _active_commercial_contract(self):
        self.ensure_one()
        if not self.depot_warehouse_id:
            return self.env["mb.commercial.contract"]
        # Depot sale processing is owned by the Depot Sale Manager role. That
        # role must not need broad access to commercial contracts merely for
        # this optional bridge to attach the matching analytic account.
        return self.env["mb.commercial.contract"].sudo().search([
            ("company_id", "=", self.company_id.id),
            ("depot_warehouse_id", "=", self.depot_warehouse_id.id),
            ("active", "=", True),
        ], limit=1)

    def _validate_configuration(self):
        result = super()._validate_configuration()
        for report in self:
            contract = (
                report.commercial_contract_id or report._active_commercial_contract()
            ).sudo()
            if contract and contract.depot_warehouse_id != report.depot_warehouse_id:
                raise ValidationError(_("The commercial contract does not belong to this depot."))
            if contract and not report.commercial_contract_id:
                report.commercial_contract_id = contract
        return result

    def _order_values(self, sold_at, lines):
        values = super()._order_values(sold_at, lines)
        contract = (
            self.commercial_contract_id or self._active_commercial_contract()
        ).sudo()
        if not contract:
            return values
        values["mb_commercial_contract_id"] = contract.id
        analytic_distribution = {str(contract.analytic_account_id.id): 100.0}
        for command in values["order_line"]:
            command[2]["analytic_distribution"] = analytic_distribution
        return values


class SaleOrder(models.Model):
    _inherit = "sale.order"

    mb_commercial_contract_id = fields.Many2one(
        "mb.commercial.contract", check_company=True, copy=False, index=True,
    )

    def action_confirm(self):
        for order in self.filtered("mb_commercial_contract_id"):
            if not order.warehouse_id.out_type_id.analytic_costs:
                raise ValidationError(_(
                    "Enable Analytic Costs on operation type %(operation_type)s before "
                    "processing depot sales, so sold stock is charged exactly once.",
                    operation_type=order.warehouse_id.out_type_id.display_name,
                ))
        result = super().action_confirm()
        for order in self.filtered("mb_commercial_contract_id"):
            contract = order.mb_commercial_contract_id.sudo()
            order.picking_ids.filtered(lambda picking: picking.state != "cancel").write({
                "project_id": contract.project_id.id,
            })
        return result

    def _prepare_invoice(self):
        values = super()._prepare_invoice()
        if self.mb_commercial_contract_id:
            values["mb_commercial_contract_id"] = self.mb_commercial_contract_id.id
        return values

    def _create_account_invoices(self, invoice_vals_list, final):
        invoices = super()._create_account_invoices(invoice_vals_list, final)
        for invoice in invoices:
            for line in invoice.invoice_line_ids.filtered(lambda item: item.display_type == "product"):
                contracts = line.sale_line_ids.order_id.mb_commercial_contract_id.sudo()
                if len(contracts) == 1:
                    line.analytic_distribution = {str(contracts.analytic_account_id.id): 100.0}
        return invoices


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    def _commercial_analytic_distribution(self):
        self.ensure_one()
        contract = self.order_id.mb_commercial_contract_id.sudo()
        return {str(contract.analytic_account_id.id): 100.0} if contract else False

    def _prepare_invoice_line(self, **optional_values):
        values = super()._prepare_invoice_line(**optional_values)
        if distribution := self._commercial_analytic_distribution():
            values["analytic_distribution"] = distribution
        return values

    def _prepare_invoice_lines_vals_list(self, **optional_values):
        values_list = super()._prepare_invoice_lines_vals_list(**optional_values)
        if distribution := self._commercial_analytic_distribution():
            for values in values_list:
                if values.get("display_type") in (False, "product"):
                    values["analytic_distribution"] = distribution
        return values_list


class AccountMove(models.Model):
    _inherit = "account.move"

    mb_commercial_contract_id = fields.Many2one(
        "mb.commercial.contract", check_company=True, copy=False, index=True,
    )

"""Report parsers for the planning and outcome packs."""

from odoo import api, models


class CommercialOperationReport(models.AbstractModel):
    _name = "report.mb_commercial_operations.report_commercial_operation"
    _description = "Commercial Operation Report Values"

    @api.model
    def _get_report_values(self, docids, data=None):
        operations = self.env["mb.commercial.operation"].browse(docids)
        kind = (data or {}).get("report_kind", "planning")
        return {
            "doc_ids": docids,
            "doc_model": operations._name,
            "docs": operations,
            "report_kind": kind,
        }


class CommercialOperationOutcomeReport(models.AbstractModel):
    _name = "report.mb_commercial_operations.operation_outcome"
    _description = "Commercial Operation Outcome Report Values"

    @api.model
    def _get_report_values(self, docids, data=None):
        operations = self.env["mb.commercial.operation"].browse(docids)
        return {
            "doc_ids": docids,
            "doc_model": operations._name,
            "docs": operations,
            "report_kind": "outcome",
        }

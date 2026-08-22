from odoo import _, models
from odoo.exceptions import UserError


class MbCommercialOperation(models.Model):
    _inherit = "mb.commercial.operation"

    def write(self, values):
        if "company_id" not in values:
            return super().write(values)

        changing_company = self.filtered(
            lambda operation: operation.company_id.id != values.get("company_id")
        )
        if not changing_company:
            return super().write(values)

        filed_source = (
            self.env["l10n.fr.micro.urssaf.declaration.source"]
            .sudo()
            .search(
                [
                    ("mb_commercial_operation_id", "in", changing_company.ids),
                    ("declaration_state", "=", "filed"),
                ],
                limit=1,
            )
        )
        if filed_source:
            raise UserError(
                _(
                    "A commercial operation referenced by filed URSSAF evidence "
                    "cannot be moved to another company."
                )
            )

        result = super().write(values)
        draft_sources = (
            self.env["l10n.fr.micro.urssaf.declaration.source"]
            .sudo()
            .search(
                [
                    ("declaration_state", "=", "draft"),
                    "|",
                    ("pos_order_id.mb_commercial_operation_id", "in", changing_company.ids),
                    ("origin_move_id.mb_commercial_operation_id", "in", changing_company.ids),
                ]
            )
        )
        draft_sources._mb_validate_and_sync_commercial_operation()
        return result

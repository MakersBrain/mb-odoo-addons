from odoo import api, fields, models


class MbCommercialOperation(models.Model):
    _inherit = "mb.commercial.operation"

    urssaf_recognition_status = fields.Selection(
        [
            ("not_applicable", "No Recognizable Revenue"),
            ("pending", "Pending Recognition"),
            ("computed", "Included in Draft Declaration"),
            ("filed", "Filed"),
        ],
        compute="_compute_urssaf_recognition_status",
        string="URSSAF Recognition",
    )
    urssaf_source_ids = fields.Many2many(
        "l10n.fr.micro.urssaf.declaration.source",
        compute="_compute_urssaf_recognition_status",
        string="URSSAF Evidence",
    )

    @api.depends("analytic_account_id", "company_id")
    def _compute_urssaf_recognition_status(self):
        source_model = self.env["l10n.fr.micro.urssaf.declaration.source"].sudo()
        for operation in self:
            account = operation.analytic_account_id
            if not account:
                operation.urssaf_source_ids = False
                operation.urssaf_recognition_status = "not_applicable"
                continue
            candidates = source_model.search([
                ("company_id", "=", operation.company_id.id),
            ])
            sources = candidates.filtered(
                lambda source, current_operation=operation: (
                    source.pos_order_id.mb_commercial_operation_id == current_operation
                    or source.origin_move_id.mb_commercial_operation_id == current_operation
                )
            )
            operation.urssaf_source_ids = sources
            if sources:
                operation.urssaf_recognition_status = (
                    "filed" if all(source.declaration_state == "filed" for source in sources)
                    else "computed"
                )
                continue
            has_revenue = any(
                item["component"] == "revenue"
                for item in operation._get_operation_profitability_items()
            )
            operation.urssaf_recognition_status = (
                "pending" if has_revenue else "not_applicable"
            )

    def action_view_urssaf_sources(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "l10n_fr_micro_urssaf.action_urssaf_declarations"
        )
        action["domain"] = [("id", "in", self.urssaf_source_ids.declaration_id.ids)]
        action["context"] = {"create": False}
        return action

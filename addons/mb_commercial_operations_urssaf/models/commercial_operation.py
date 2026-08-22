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
    urssaf_source_ids = fields.One2many(
        "l10n.fr.micro.urssaf.declaration.source",
        "mb_commercial_operation_id",
        string="URSSAF Evidence",
        readonly=True,
    )

    @api.depends(
        "analytic_account_id",
        "urssaf_source_ids",
        "urssaf_source_ids.declaration_state",
        # The `pending` branch asks whether any revenue exists yet, via
        # `_get_operation_profitability_items()`. That is a registry which
        # optional bridge addons extend, so no single addon can name its whole
        # dependency set; `analytic_evidence_ids` is the native revenue source
        # every installation has. An operation whose only revenue arrives
        # through another bridge's evidence may therefore read `pending` one
        # transaction late. That is a display lag on a computed indicator, not
        # a declared figure -- the declaration itself is built by
        # l10n_fr_micro_urssaf from the sources, not from this field.
        "analytic_evidence_ids.amount",
    )
    def _compute_urssaf_recognition_status(self):
        for operation in self:
            sources = operation.urssaf_source_ids
            if sources:
                operation.urssaf_recognition_status = (
                    "filed"
                    if all(source.declaration_state == "filed" for source in sources)
                    else "computed"
                )
                continue
            if not operation.analytic_account_id:
                operation.urssaf_recognition_status = "not_applicable"
                continue
            has_revenue = any(
                item["component"] == "revenue"
                for item in operation._get_operation_profitability_items()
            )
            operation.urssaf_recognition_status = "pending" if has_revenue else "not_applicable"

    def action_view_urssaf_sources(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "l10n_fr_micro_urssaf.action_urssaf_declarations"
        )
        action["domain"] = [("id", "in", self.urssaf_source_ids.declaration_id.ids)]
        action["context"] = {"create": False}
        return action

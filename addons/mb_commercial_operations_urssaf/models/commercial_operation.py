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
        # The recognizable-revenue hook deliberately owns its protected reads;
        # `analytic_evidence_ids` is the native source every installation has.
        # Optional bridges may add dependencies when extending the hook.
        "analytic_evidence_ids.amount",
    )
    def _compute_urssaf_recognition_status(self):
        for operation in self:
            # Elevate only the protected evidence read. In particular, never
            # invoke an extension registry with a sudoed operation record.
            sources = operation.sudo().urssaf_source_ids
            # Evidence outranks the analytic account: an operation a
            # declaration has already recognised is not "no recognizable
            # revenue" merely because its project carries no analytic account.
            if sources:
                operation.urssaf_recognition_status = (
                    "filed"
                    if all(source.declaration_state == "filed" for source in sources)
                    else "computed"
                )
                continue
            if not operation.sudo().analytic_account_id:
                operation.urssaf_recognition_status = "not_applicable"
                continue
            has_revenue = operation._mb_has_recognizable_revenue()
            operation.urssaf_recognition_status = "pending" if has_revenue else "not_applicable"

    def _mb_has_recognizable_revenue(self):
        """Extension hook whose implementations elevate only their own reads."""
        self.ensure_one()
        protected = self.sudo()
        if any(line.amount > 0 for line in protected.analytic_evidence_ids):
            return True
        if any(
            move.state == "posted" and move.move_type in ("out_invoice", "out_refund")
            for move in (protected.account_move_ids | protected.direct_account_move_ids)
        ):
            return True
        return bool(
            protected.pos_order_ids.filtered(
                lambda order: order.state not in ("cancel", "invoiced")
            )
        )

    def action_view_urssaf_sources(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "l10n_fr_micro_urssaf.action_urssaf_declarations"
        )
        action["domain"] = [("id", "in", self.urssaf_source_ids.declaration_id.ids)]
        action["context"] = {"create": False}
        return action

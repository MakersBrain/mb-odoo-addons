from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .snapshot_token import SNAPSHOT_TOKEN


class MbCommercialReportSnapshot(models.Model):
    _name = "mb.commercial.report.snapshot"
    _description = "Frozen Commercial Planning Report"
    _inherit = ["mail.thread"]
    _order = "generated_at desc, id desc"
    _check_company_auto = True

    name = fields.Char(required=True, readonly=True)
    operation_id = fields.Many2one(
        "mb.commercial.operation",
        required=True,
        ondelete="restrict",
        check_company=True,
        index=True,
        readonly=True,
    )
    scenario_id = fields.Many2one(
        "mb.commercial.profitability.scenario",
        ondelete="restrict",
        check_company=True,
        readonly=True,
    )
    company_id = fields.Many2one(related="operation_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    report_kind = fields.Selection(
        [("planning", "Planning Pack"), ("outcome", "Outcome Pack")],
        required=True,
        readonly=True,
    )
    revision = fields.Integer(required=True, readonly=True)
    state = fields.Selection(
        [("current", "Current"), ("superseded", "Superseded"), ("void", "Void")],
        required=True,
        default="current",
        readonly=True,
        tracking=True,
    )
    generated_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)
    generated_by_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user, readonly=True
    )
    payload = fields.Json(required=True, readonly=True)
    input_digest = fields.Char(required=True, readonly=True, index=True)
    pdf_digest = fields.Char(readonly=True)
    attachment_id = fields.Many2one("ir.attachment", ondelete="restrict", readonly=True)
    void_reason = fields.Text(tracking=True)
    voided_at = fields.Datetime(readonly=True)
    voided_by_id = fields.Many2one("res.users", readonly=True)

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("mb_snapshot_token") is not SNAPSHOT_TOKEN:
            raise AccessError(
                _("Snapshots can only be created by the controlled approval workflow.")
            )
        return super().create(values_list)

    @api.constrains("operation_id", "scenario_id")
    def _check_scenario_operation(self):
        for snapshot in self.filtered("scenario_id"):
            if snapshot.scenario_id.operation_id != snapshot.operation_id:
                raise ValidationError(_("The frozen scenario must belong to the operation."))

    def action_open_attachment(self):
        self.ensure_one()
        if not self.attachment_id:
            raise UserError(_("This snapshot has no PDF attachment."))
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{self.attachment_id.id}?download=true",
            "target": "self",
        }

    def action_void(self):
        if not self.env.user.has_group(
            "mb_commercial_operations.group_commercial_operations_manager"
        ):
            raise AccessError(_("Only a Commercial Operations Manager can void a snapshot."))
        for snapshot in self.filtered(lambda item: item.state != "void"):
            if not snapshot.void_reason:
                raise ValidationError(_("Enter a void reason before voiding this frozen report."))
            snapshot.with_context(mb_snapshot_token=SNAPSHOT_TOKEN).write(
                {
                    "state": "void",
                    "voided_at": fields.Datetime.now(),
                    "voided_by_id": self.env.user.id,
                }
            )
            message = _("Frozen report voided: %(reason)s", reason=snapshot.void_reason)
            snapshot.message_post(body=message)
            snapshot.operation_id.message_post(body=message)
        return True

    def write(self, vals):
        allowed = {
            "state",
            "void_reason",
            "voided_at",
            "voided_by_id",
            "attachment_id",
            "pdf_digest",
        }
        reason_only = (
            set(vals) <= {"void_reason"}
            and self.env.user.has_group(
                "mb_commercial_operations.group_commercial_operations_manager"
            )
            and not self.filtered(lambda snapshot: snapshot.state == "void")
        )
        if not reason_only and (
            self.env.context.get("mb_snapshot_token") is not SNAPSHOT_TOKEN or set(vals) - allowed
        ):
            raise UserError(_("Frozen report snapshots are immutable."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_never(self):
        raise UserError(_("Frozen report snapshots cannot be deleted; void them instead."))

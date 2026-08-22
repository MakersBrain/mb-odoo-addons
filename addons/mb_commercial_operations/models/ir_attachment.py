from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .snapshot_token import SNAPSHOT_TOKEN


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    mb_commercial_report_snapshot_id = fields.Many2one(
        "mb.commercial.report.snapshot",
        copy=False,
        index=True,
        ondelete="restrict",
    )

    def write(self, vals):
        if (
            self.filtered("mb_commercial_report_snapshot_id")
            and self.env.context.get("mb_snapshot_token") is not SNAPSHOT_TOKEN
        ):
            raise UserError(_("A frozen commercial report attachment cannot be changed."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_commercial_snapshot_attachment(self):
        if (
            self.filtered("mb_commercial_report_snapshot_id")
            and self.env.context.get("mb_snapshot_token") is not SNAPSHOT_TOKEN
        ):
            raise UserError(_("A frozen commercial report attachment cannot be deleted."))

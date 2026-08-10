from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class PosSession(models.Model):
    _inherit = "pos.session"

    mb_commercial_operation_id = fields.Many2one(
        "mb.commercial.operation", check_company=True, copy=False, index=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            config = self.env["pos.config"].browse(vals.get("config_id"))
            if config.mb_commercial_operation_id:
                vals.setdefault("mb_commercial_operation_id", config.mb_commercial_operation_id.id)
        return super().create(vals_list)

    def action_pos_session_open(self):
        for session in self.filtered("mb_commercial_operation_id"):
            operation = session.mb_commercial_operation_id
            if session.config_id.mb_commercial_operation_id != operation:
                raise ValidationError(_("The POS configuration no longer points to this session's market."))
            if session.config_id.picking_type_id != operation.pos_out_picking_type_id:
                raise ValidationError(_("Configure the market stock operation type before opening this POS session."))
        return super().action_pos_session_open()

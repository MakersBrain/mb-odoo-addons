from odoo import _, models
from odoo.exceptions import UserError


class MbFiring(models.Model):
    _inherit = "mb.firing"

    def action_mb_load(self):
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("Only a loading firing can receive work."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Load kiln"),
            "res_model": "mb.firing.load",
            "view_mode": "form",
            "target": "new",
            "context": {"default_firing_id": self.id},
        }

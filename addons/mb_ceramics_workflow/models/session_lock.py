from odoo import _, api, models
from odoo.exceptions import UserError


class MbCeramicsSessionMixin(models.AbstractModel):
    _name = "mb.ceramics.session.mixin"
    _description = "Completed ceramics session integrity"

    _mb_terminal_states = {"done", "cancel"}

    def write(self, values):
        if any(record.state in self._mb_terminal_states for record in self):
            raise UserError(
                _(
                    "A completed or cancelled workshop session is immutable. "
                    "Create a correcting session instead."
                )
            )
        return super().write(values)

    def unlink(self):
        if any(record.state in self._mb_terminal_states for record in self):
            raise UserError(_("A completed or cancelled workshop session cannot be deleted."))
        return super().unlink()


class MbCeramicsSessionLineMixin(models.AbstractModel):
    _name = "mb.ceramics.session.line.mixin"
    _description = "Completed ceramics session line integrity"

    def _mb_check_session_open(self, sessions=None):
        sessions = sessions or self.mapped("session_id")
        if any(session.state in session._mb_terminal_states for session in sessions):
            raise UserError(
                _(
                    "Lines of a completed or cancelled workshop session are immutable. "
                    "Create a correcting session instead."
                )
            )

    @api.model_create_multi
    def create(self, vals_list):
        session_ids = [values.get("session_id") for values in vals_list]
        sessions = self.env[self._fields["session_id"].comodel_name].browse(
            [session_id for session_id in session_ids if session_id]
        )
        self._mb_check_session_open(sessions)
        return super().create(vals_list)

    def write(self, values):
        sessions = self.mapped("session_id")
        if values.get("session_id"):
            sessions |= self.env[self._fields["session_id"].comodel_name].browse(
                values["session_id"]
            )
        self._mb_check_session_open(sessions)
        return super().write(values)

    def unlink(self):
        self._mb_check_session_open()
        return super().unlink()

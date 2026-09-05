from odoo import api, fields, models
from odoo.tools import SQL


class L10nFrMicroUrssafInvariantLock(models.Model):
    _name = "l10n.fr.micro.urssaf.invariant.lock"
    _description = "URSSAF invariant transaction mutex"
    _log_access = False

    name = fields.Char(required=True)

    _name_unique = models.Constraint("UNIQUE(name)", "Invariant lock names must be unique.")

    @api.model
    def lock(self, names):
        """Update stable mutex rows so stale REPEATABLE READ transactions abort."""
        for name in sorted(set(names)):
            self.env.cr.execute(
                SQL(
                    "UPDATE l10n_fr_micro_urssaf_invariant_lock SET name = name WHERE name = %s",
                    name,
                )
            )
            if self.env.cr.rowcount != 1:
                raise RuntimeError("Missing URSSAF invariant lock row: %s" % name)

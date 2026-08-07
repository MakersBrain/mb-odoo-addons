from odoo import fields, models


class MrpWorkorder(models.Model):
    _inherit = "mrp.workorder"

    mb_firing_id = fields.Many2one(
        comodel_name="mb.firing",
        string="Firing",
        index=True,
        copy=False,
        ondelete="set null",
        help="The physical firing this operation happened in. A Many2one here "
             "and a One2many there is the whole many-to-many: one firing holds "
             "work orders from several manufacturing orders, and each work "
             "order sits in exactly one firing.",
    )

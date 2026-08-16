from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    mb_pickup_ref = fields.Char(copy=False, index=True)
    mb_pickup_provider = fields.Char(copy=False, index=True)
    mb_pickup_service = fields.Char(copy=False)

    def _can_be_edited_by_current_customer(self, **kwargs):
        return (
            super()._can_be_edited_by_current_customer(**kwargs)
            and not any(self.mapped("mb_pickup_ref"))
        )

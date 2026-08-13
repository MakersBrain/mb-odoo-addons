from odoo import _, models
from odoo.exceptions import ValidationError


class MrpWorkorder(models.Model):
    _inherit = "mrp.workorder"

    def action_mb_recipe_documents(self):
        self.ensure_one()
        if not self.production_id.bom_id:
            raise ValidationError(_("This work order has no bill of materials."))
        return self.production_id.bom_id.action_mb_recipe_documents()

    def _mb_validate_firing(self, firing=None):
        result = super()._mb_validate_firing(firing)
        for workorder in self:
            load = firing or workorder.mb_firing_id
            if not load or not load.program_id.peak_temperature:
                continue
            products = (
                workorder.production_id.product_id
                | workorder.production_id.move_raw_ids.product_id
                | workorder.production_id.product_id.mb_clay_body_id
            )
            peak = load.program_id.peak_temperature
            for product in products:
                minimum = product.mb_firing_min_temperature
                maximum = product.mb_firing_max_temperature
                if minimum and peak < minimum:
                    raise ValidationError(_(
                        "%(program)s peaks below %(product)s's minimum firing "
                        "temperature of %(minimum)s C.",
                        program=load.program_id.display_name,
                        product=product.display_name,
                        minimum=minimum,
                    ))
                if maximum and peak > maximum:
                    raise ValidationError(_(
                        "%(program)s peaks above %(product)s's maximum firing "
                        "temperature of %(maximum)s C.",
                        program=load.program_id.display_name,
                        product=product.display_name,
                        maximum=maximum,
                    ))
        return result

    def button_finish(self):
        result = super().button_finish()
        for production in self.production_id:
            next_order = production.workorder_ids.filtered(
                lambda workorder: workorder.state not in ("done", "cancel"))[:1]
            production.mb_board_content_ids.filtered(
                lambda content: content.state == "current").write({
                    "current_workorder_id": next_order.id or False,
                })
        return result

from odoo import _, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def action_mb_create_label(self):
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "name": _("Create Product Label"),
            "tag": "mb_label.editor",
            "context": {"default_product_tmpl_id": self.id},
        }

    def action_mb_print_label(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Print Product Label"),
            "res_model": "mb.label.print.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_product_tmpl_id": self.id},
        }


class ProductProduct(models.Model):
    _inherit = "product.product"

    def action_mb_create_label(self):
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "name": _("Create Product Label"),
            "tag": "mb_label.editor",
            "context": {"default_product_id": self.id},
        }

    def action_mb_print_label(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Print Product Label"),
            "res_model": "mb.label.print.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_product_id": self.id},
        }

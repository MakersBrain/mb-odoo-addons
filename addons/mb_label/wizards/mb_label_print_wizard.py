import base64

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class MbLabelPrintWizard(models.TransientModel):
    _name = "mb.label.print.wizard"
    _description = "Choose Label Template and Subject"

    product_tmpl_id = fields.Many2one("product.template", string="Product")
    product_id = fields.Many2one(
        "product.product",
        string="Variant",
        required=True,
        domain="[('product_tmpl_id', '=', product_tmpl_id)]",
    )
    lot_id = fields.Many2one(
        "stock.lot", string="Lot or Serial", domain="[('product_id', '=', product_id)]"
    )
    template_id = fields.Many2one(
        "mb.label.template",
        required=True,
        domain="[('company_id', '=', company_id), ('active', '=', True)]",
    )
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    copies = fields.Integer(default=1, required=True)
    manual_values_json = fields.Json(string="Manual Values", default=dict)
    preview_html = fields.Html(compute="_compute_preview_html")
    preview_png = fields.Binary(compute="_compute_preview", readonly=True)
    preview_error = fields.Char(compute="_compute_preview", readonly=True)

    @api.model
    def default_get(self, names):
        values = super().default_get(names)
        template = self.env["mb.label.template"].search(
            [
                ("company_id", "=", self.env.company.id),
                ("is_default", "=", True),
                ("active", "=", True),
            ],
            limit=1,
        )
        if not template:
            template = self.env["mb.label.template"].search(
                [("company_id", "=", self.env.company.id), ("active", "=", True)], limit=1
            )
        if template:
            values.setdefault("template_id", template.id)
        product_template_id = values.get("product_tmpl_id")
        if product_template_id and not values.get("product_id"):
            product_template = self.env["product.template"].browse(product_template_id)
            if len(product_template.product_variant_ids) == 1:
                values["product_id"] = product_template.product_variant_id.id
        product_id = values.get("product_id")
        if product_id:
            values.setdefault(
                "product_tmpl_id", self.env["product.product"].browse(product_id).product_tmpl_id.id
            )
        return values

    @api.onchange("product_tmpl_id")
    def _onchange_product_template(self):
        variants = self.product_tmpl_id.product_variant_ids
        if self.product_id not in variants:
            self.product_id = variants if len(variants) == 1 else False
        if self.lot_id and self.lot_id.product_id != self.product_id:
            self.lot_id = False

    @api.onchange("product_id")
    def _onchange_product(self):
        if self.lot_id and self.lot_id.product_id != self.product_id:
            self.lot_id = False

    @api.depends("template_id", "product_id", "lot_id")
    def _compute_preview_html(self):
        for wizard in self:
            if (
                not wizard.template_id
                or not wizard.template_id.current_version_id
                or not wizard.product_id
            ):
                wizard.preview_html = Markup(
                    "<p class='text-muted'>Choose a saved template and product.</p>"
                )
                continue
            wizard.preview_html = Markup(
                "<div class='alert alert-info mb-0'>{} × {} mm · {} · v{}</div>"
            ).format(
                wizard.template_id.width_mm,
                wizard.template_id.height_mm,
                wizard.product_id.display_name,
                wizard.template_id.current_version_id.number,
            )

    @api.depends("template_id", "product_id", "lot_id", "manual_values_json")
    def _compute_preview(self):
        renderer = self.env["mb.label.render.service"]
        for wizard in self:
            wizard.preview_png = False
            wizard.preview_error = False
            version = wizard.template_id.current_version_id
            if not version or not wizard.product_id:
                continue
            try:
                values = renderer.bindings_for(
                    wizard.product_id, wizard.lot_id, wizard.manual_values_json or {}
                )
                wizard.preview_png = base64.b64encode(
                    renderer.render_png(version, values, version.dpi)
                )
            except (UserError, ValidationError) as error:
                wizard.preview_error = str(error)

    @api.constrains("copies")
    def _check_copies(self):
        if any(not 1 <= wizard.copies <= 99 for wizard in self):
            raise ValidationError(_("Copies must be between 1 and 99."))

    def _create_job(self):
        self.ensure_one()
        if not self.template_id.current_version_id:
            raise UserError(_("Save the template in Label Studio before printing it."))
        payload = self.env["mb.label.print.job"].create_rendered(
            self.product_id.id,
            self.lot_id.id,
            self.template_id.id,
            self.copies,
            self.manual_values_json or {},
        )
        return self.env["mb.label.print.job"].browse(payload["id"])

    def action_download_pdf(self):
        job = self._create_job()
        return {
            "type": "ir.actions.act_url",
            "url": "/mb_label/job/%s/label.pdf?download=1" % job.id,
            "target": "self",
        }

    def action_browser_print(self):
        job = self._create_job()
        return {
            "type": "ir.actions.act_url",
            "url": "/mb_label/job/%s/print?autoprint=1" % job.id,
            "target": "new",
        }

    def action_device_print(self):
        return self._create_job().action_device_print()

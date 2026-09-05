import base64

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class MbLabelPrintJob(models.Model):
    _name = "mb.label.print.job"
    _description = "Label Print Job"
    _order = "create_date desc"
    _check_company_auto = True

    name = fields.Char(compute="_compute_name", store=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    product_id = fields.Many2one(
        "product.product", required=True, ondelete="restrict", check_company=True, index=True
    )
    lot_id = fields.Many2one("stock.lot", ondelete="restrict", check_company=True, index=True)
    template_version_id = fields.Many2one(
        "mb.label.template.version", required=True, ondelete="restrict", check_company=True
    )
    alias_id = fields.Many2one("mb.label.qr.alias", readonly=True, ondelete="restrict")
    copies = fields.Integer(required=True, default=1)
    dpi = fields.Integer(required=True)
    width_mm = fields.Float(required=True)
    height_mm = fields.Float(required=True)
    bindings_snapshot = fields.Json(
        required=True, default=lambda self: {"pending": True}, readonly=True
    )
    manual_values = fields.Json(default=lambda self: {})
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("rendered", "Rendered"),
            ("printed", "Printed"),
            ("failed", "Failed"),
        ],
        required=True,
        default="draft",
        index=True,
    )
    preview_png = fields.Binary(attachment=True, readonly=True)
    artifact_pdf = fields.Binary(attachment=True, readonly=True)
    artifact_name = fields.Char(readonly=True)
    error = fields.Text(readonly=True)
    printed_at = fields.Datetime(readonly=True)
    printer_adapter = fields.Selection(
        [("system", "System / PDF"), ("phomemo", "Phomemo BLE"), ("niimbot", "NIIMBOT BLE")],
        readonly=True,
    )

    @api.depends("product_id", "lot_id", "template_version_id")
    def _compute_name(self):
        for record in self:
            subject = record.product_id.display_name or _("Label")
            if record.lot_id:
                subject = "%s — %s" % (subject, record.lot_id.name)
            record.name = "%s (v%s)" % (subject, record.template_version_id.number or "-")

    @api.constrains("copies")
    def _check_copies(self):
        for record in self:
            if not 1 <= record.copies <= 99:
                raise ValidationError(_("Copies must be between 1 and 99."))

    @api.constrains("lot_id", "product_id")
    def _check_lot_product(self):
        for record in self.filtered("lot_id"):
            if record.lot_id.product_id != record.product_id:
                raise ValidationError(_("The lot or serial does not belong to this product."))

    @api.model
    def create_rendered(self, product_id, lot_id, template_id, copies=1, manual_values=None):
        template = self.env["mb.label.template"].browse(template_id).exists()
        product = self.env["product.product"].browse(product_id).exists()
        lot = self.env["stock.lot"].browse(lot_id).exists() if lot_id else self.env["stock.lot"]
        if not template or not template.active or not template.current_version_id or not product:
            raise UserError(_("Choose a product and a saved label template."))
        version = template.current_version_id
        job = self.create(
            {
                "company_id": self.env.company.id,
                "product_id": product.id,
                "lot_id": lot.id or False,
                "template_version_id": version.id,
                "copies": copies,
                "dpi": version.dpi,
                "width_mm": version.width_mm,
                "height_mm": version.height_mm,
                "manual_values": manual_values or {},
                "bindings_snapshot": {"pending": True},
            }
        )
        job.action_render()
        return job.device_payload()

    def action_render(self):
        renderer = self.env["mb.label.render.service"]
        for job in self:
            values = renderer.bindings_for(
                job.product_id, job.lot_id, job.manual_values, job.template_version_id.qr_url_prefix
            )
            qr_value = renderer.resolve(job.template_version_id.qr_payload_template, values)
            # The value minted into the durable alias must be exactly the value
            # encoded by every QR element in the rendered artifact.
            values["qr"] = qr_value
            alias = self.env["mb.label.qr.alias"].mint(
                qr_value, job.product_id.id, job.lot_id.id, job.template_version_id.id
            )
            png = renderer.render_png(job.template_version_id, values, job.dpi)
            pdf = renderer.render_pdf(png, job.width_mm, job.height_mm, job.copies)
            filename = "label-%s%s.pdf" % (
                job.product_id.default_code or job.product_id.id,
                "-%s" % job.lot_id.name if job.lot_id else "",
            )
            job.with_context(_mb_label_internal=True).write(
                {
                    "alias_id": alias.id,
                    "bindings_snapshot": values,
                    "preview_png": base64.b64encode(png),
                    "artifact_pdf": base64.b64encode(pdf),
                    "artifact_name": filename,
                    "state": "rendered",
                    "error": False,
                }
            )
        return True

    def device_payload(self):
        self.ensure_one()
        if self.state != "rendered":
            self.action_render()
        return {
            "id": self.id,
            "name": self.name,
            "copies": self.copies,
            "width_mm": self.width_mm,
            "height_mm": self.height_mm,
            "dpi": self.dpi,
            "printer_target": self.template_version_id.printer_target or "system",
            "png_url": "/mb_label/job/%s/preview.png" % self.id,
            "pdf_url": "/mb_label/job/%s/label.pdf" % self.id,
            "print_url": "/mb_label/job/%s/print" % self.id,
        }

    def action_device_print(self):
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "mb_label.device_print",
            "name": _("Print Label"),
            "target": "new",
            "context": {"job_id": self.id},
        }

    def mark_printed(self, adapter):
        for job in self:
            job.with_context(_mb_label_internal=True).write(
                {
                    "state": "printed",
                    "printed_at": fields.Datetime.now(),
                    "printer_adapter": adapter,
                }
            )
        return True

    def write(self, vals):
        if not self.env.context.get("_mb_label_internal"):
            protected = {
                "company_id",
                "product_id",
                "lot_id",
                "template_version_id",
                "alias_id",
                "bindings_snapshot",
                "preview_png",
                "artifact_pdf",
                "artifact_name",
                "dpi",
                "width_mm",
                "height_mm",
                "state",
                "printed_at",
                "printer_adapter",
            }
            if protected.intersection(vals):
                raise UserError(
                    _("Print-job audit fields can only be changed by the rendering service.")
                )
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_unrendered(self):
        if self.filtered(lambda job: job.state in ("rendered", "printed")):
            raise UserError(_("Rendered print jobs are audit records and cannot be deleted."))

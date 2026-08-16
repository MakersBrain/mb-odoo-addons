import base64

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class CarrierManifest(models.Model):
    _name = "mb.carrier.manifest"
    _description = "Carrier handover manifest"
    _order = "date desc, id desc"

    name = fields.Char(required=True, readonly=True, default="New")
    company_id = fields.Many2one("res.company", required=True, index=True, ondelete="cascade")
    carrier_id = fields.Many2one("delivery.carrier", required=True, ondelete="restrict")
    date = fields.Date(required=True, default=fields.Date.context_today)
    shipment_ids = fields.Many2many("mb.carrier.shipment", string="Shipments")
    provider_ref = fields.Char(copy=False)
    document_id = fields.Many2one("ir.attachment", copy=False, ondelete="set null")
    state = fields.Selection([
        ("draft", "Draft"), ("ready", "Ready"), ("failed", "Failed")
    ], default="draft", required=True, copy=False)
    last_error = fields.Char(copy=False)

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            if not values.get("name") or values.get("name") == "New":
                values["name"] = _("Local handover worksheet %(date)s", date=values.get("date") or fields.Date.today())
        return super().create(values_list)

    @api.constrains("shipment_ids", "carrier_id", "company_id")
    def _check_shipments(self):
        for manifest in self:
            company = manifest.company_id
            carrier = manifest.carrier_id
            invalid = manifest.shipment_ids.filtered(
                lambda shipment, company=company, carrier=carrier: shipment.company_id != company
                or shipment.carrier_id != carrier
                or shipment.direction != "outbound"
                or shipment.state != "label_ready"
            )
            if invalid:
                raise ValidationError(
                    _("A handover worksheet may include only label-ready outbound shipments for its carrier and company.")
                )

    def action_ready(self):
        report = self.env.ref("mb_webshop_carrier_base.action_report_local_handover")
        for manifest in self:
            if not manifest.shipment_ids:
                raise ValidationError(_("Select at least one label-ready shipment."))
            manifest.state = "ready"
            pdf, _content_type = self.env["ir.actions.report"]._render_qweb_pdf(
                report.report_name, res_ids=manifest.ids
            )
            attachment_values = {
                "name": _("Local handover worksheet - %(date)s.pdf", date=manifest.date),
                "type": "binary",
                "datas": base64.b64encode(pdf),
                "mimetype": "application/pdf",
                "res_model": manifest._name,
                "res_id": manifest.id,
            }
            if manifest.document_id:
                manifest.document_id.sudo().write(attachment_values)
            else:
                manifest.document_id = self.env["ir.attachment"].sudo().create(
                    attachment_values
                )
        return report.report_action(self)

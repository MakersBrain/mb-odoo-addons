from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .label_template import normalize_qr


class MbLabelQrAlias(models.Model):
    _name = "mb.label.qr.alias"
    _description = "Durable Printed QR Alias"
    _order = "create_date desc"
    _check_company_auto = True

    value = fields.Char(required=True, index=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True)
    product_id = fields.Many2one(
        "product.product", required=True, ondelete="restrict", check_company=True, index=True)
    lot_id = fields.Many2one("stock.lot", ondelete="restrict", check_company=True, index=True)
    lot_name = fields.Char(related="lot_id.name", store=True, readonly=True)
    template_version_id = fields.Many2one(
        "mb.label.template.version", required=True, ondelete="restrict", check_company=True)
    qr_url_prefix = fields.Char(
        related="template_version_id.qr_url_prefix", store=True, readonly=True)
    active = fields.Boolean(default=True)
    retired_by_id = fields.Many2one("res.users", readonly=True)
    retired_at = fields.Datetime(readonly=True)

    _value_company_unique = models.Constraint(
        "UNIQUE(company_id, value)", "This printed QR value already belongs to another identity.")

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            values["value"] = normalize_qr(values.get("value"))
        return super().create(vals_list)

    @api.constrains("lot_id", "product_id")
    def _check_lot_product(self):
        for record in self.filtered("lot_id"):
            if record.lot_id.product_id != record.product_id:
                raise ValidationError(_("The lot or serial does not belong to the selected product."))

    @api.model
    def mint(self, value, product_id, lot_id, template_version_id):
        value = normalize_qr(value)
        company = self.env.company
        existing = self.with_context(active_test=False).search(
            [("company_id", "=", company.id), ("value", "=", value)], limit=1)
        if existing:
            if existing.product_id.id != product_id or (existing.lot_id.id or False) != (lot_id or False):
                raise ValidationError(_("QR collision: '%s' already identifies another product or piece.", value))
            if not existing.active:
                raise ValidationError(_(
                    "QR alias '%s' was retired and cannot be printed again until an administrator reactivates it.",
                    value))
            return existing
        return self.create({
            "value": value,
            "company_id": company.id,
            "product_id": product_id,
            "lot_id": lot_id or False,
            "template_version_id": template_version_id,
        })

    def action_retire(self):
        if not self.env.user.has_group("mb_label.group_mb_label_manager"):
            raise UserError(_("Only a Label Designer can retire printed QR aliases."))
        self.write({
            "active": False,
            "retired_by_id": self.env.user.id,
            "retired_at": fields.Datetime.now(),
        })

    def action_reactivate(self):
        if not self.env.user.has_group("mb_label.group_mb_label_manager"):
            raise UserError(_("Only a Label Designer can reactivate printed QR aliases."))
        self.write({"active": True, "retired_by_id": False, "retired_at": False})

    def unlink(self):
        raise UserError(_("Printed QR aliases are audit records and cannot be deleted."))

from odoo import api, fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    mb_label_qr_prefixes = fields.Json(compute="_compute_mb_label_qr_prefixes")

    def _compute_mb_label_qr_prefixes(self):
        templates = self.env["mb.label.template"].search([
            ("active", "=", True),
            ("company_id", "in", self.mapped("company_id").ids),
        ])
        by_company = {}
        for template in templates:
            prefix = template.current_version_id.qr_url_prefix or template.qr_url_prefix
            if prefix:
                by_company.setdefault(template.company_id.id, set()).add(prefix)
        for config in self:
            config.mb_label_qr_prefixes = sorted(by_company.get(config.company_id.id, set()))

    @api.model
    def _load_pos_data_fields(self, config):
        fields_to_load = super()._load_pos_data_fields(config)
        # Odoo 19 uses an empty list here as the sentinel for reading every
        # non-manual field. Replacing it with a one-field list would starve the
        # POS bootstrap of standard fields such as use_pricelist.
        if not fields_to_load:
            return fields_to_load
        return [*fields_to_load, "mb_label_qr_prefixes"]

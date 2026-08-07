from odoo import api, models


class PosSession(models.Model):
    _inherit = "pos.session"

    @api.model
    def _load_pos_data_models(self, config):
        models_to_load = super()._load_pos_data_models(config)
        if "mb.label.qr.alias" not in models_to_load:
            models_to_load.append("mb.label.qr.alias")
        return models_to_load

from odoo import fields, models


class CarrierRequestLog(models.Model):
    _name = "mb.carrier.request.log"
    _description = "Privacy-sanitized carrier request log"
    _order = "create_date desc"

    company_id = fields.Many2one("res.company", required=True, index=True, ondelete="cascade")
    provider_code = fields.Char(required=True, index=True)
    operation = fields.Char(required=True, index=True)
    shipment_id = fields.Many2one("mb.carrier.shipment", index=True, ondelete="set null")
    picking_id = fields.Many2one("stock.picking", index=True, ondelete="set null")
    http_status = fields.Integer()
    duration_ms = fields.Integer()
    outcome = fields.Selection(
        [
            ("success", "Success"),
            ("validation", "Validation error"),
            ("auth", "Authentication error"),
            ("transient", "Transient error"),
            ("unavailable", "Unavailable"),
            ("unknown", "Unknown outcome"),
        ],
        required=True,
    )
    diagnostic = fields.Char(help="Bounded code/message without credentials or customer data.")
    correlation_id = fields.Char(index=True)

    def _cron_purge(self):
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), days=90)
        self.sudo().search([("create_date", "<", cutoff)]).unlink()

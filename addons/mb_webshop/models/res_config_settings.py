from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    mb_webshop_enabled = fields.Boolean(
        related="website_id.mb_webshop_enabled",
        readonly=True,
    )
    mb_cart_hold_minutes = fields.Integer(
        related="website_id.mb_cart_hold_minutes",
        readonly=False,
    )
    mb_return_window_days = fields.Integer(
        related="website_id.mb_return_window_days",
        readonly=False,
    )
    mb_ready_catalog = fields.Boolean(related="website_id.mb_ready_catalog")
    mb_ready_online_payment = fields.Boolean(
        related="website_id.mb_ready_online_payment"
    )
    mb_ready_fulfilment = fields.Boolean(related="website_id.mb_ready_fulfilment")
    mb_ready_sender = fields.Boolean(related="website_id.mb_ready_sender")
    mb_ready_domain = fields.Boolean(related="website_id.mb_ready_domain")
    mb_ready_returns = fields.Boolean(related="website_id.mb_ready_returns")
    mb_launch_ready = fields.Boolean(related="website_id.mb_launch_ready")
    mb_ready_product_count = fields.Integer(
        related="website_id.mb_ready_product_count"
    )
    mb_ready_payment_count = fields.Integer(
        related="website_id.mb_ready_payment_count"
    )
    mb_ready_fulfilment_count = fields.Integer(
        related="website_id.mb_ready_fulfilment_count"
    )

    def action_mb_open_products(self):
        return self.env["ir.actions.actions"]._for_xml_id(
            "website_sale.product_template_action_website"
        )

    def action_mb_open_payment_providers(self):
        return self.env["ir.actions.actions"]._for_xml_id(
            "payment.action_payment_provider"
        )

    def action_mb_open_delivery_methods(self):
        return self.env["ir.actions.actions"]._for_xml_id(
            "delivery.action_delivery_carrier_form"
        )

    def action_mb_open_mail_servers(self):
        return self.env["ir.actions.actions"]._for_xml_id(
            "base.action_ir_mail_server_list"
        )

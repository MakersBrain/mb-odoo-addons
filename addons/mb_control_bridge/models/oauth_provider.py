from odoo import fields, models


class AuthOAuthProvider(models.Model):
    _inherit = "auth.oauth.provider"

    mb_code_flow = fields.Boolean(string="MakersBrain authorization-code flow")
    mb_issuer = fields.Char(string="Exact OIDC issuer")
    mb_token_endpoint = fields.Char(string="OIDC token endpoint")

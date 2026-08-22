from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    mb_clay_body_id = fields.Many2one(
        comodel_name="product.product",
        string="Clay body",
        help="The body this piece is made from, as the material product itself "
        "rather than a code, so it joins to the master catalogue.",
    )

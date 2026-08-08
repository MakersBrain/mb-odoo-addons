from odoo import api, models
from odoo.tools.misc import format_amount


def append_sale_selector_price(products):
    if not (
        products.env.context.get("mb_show_product_selector_price")
        or products.env.context.get("mb_show_sale_selector_price")
    ):
        return

    pricelist_id = products.env.context.get("mb_sale_pricelist_id")
    currency_id = products.env.context.get("mb_sale_currency_id")
    pricelist = products.env["product.pricelist"].browse(pricelist_id).exists()
    currency = products.env["res.currency"].browse(currency_id).exists()
    if not currency:
        currency = pricelist.currency_id if pricelist else products.env.company.currency_id

    for product in products:
        price = (
            pricelist._get_product_price(product, 1.0)
            if pricelist
            else product.list_price
        )
        formatted_price = format_amount(
            products.env, price, currency, trailing_zeroes=False)
        product.display_name = f"{product.display_name} — {formatted_price}"


class ProductTemplate(models.Model):
    _inherit = "product.template"

    @api.depends("name", "default_code", "list_price")
    @api.depends_context(
        "formatted_display_name",
        "display_default_code",
        "mb_show_sale_selector_price",
        "mb_show_product_selector_price",
        "mb_sale_pricelist_id",
        "mb_sale_currency_id",
    )
    def _compute_display_name(self):
        super()._compute_display_name()
        append_sale_selector_price(self)


class ProductProduct(models.Model):
    _inherit = "product.product"

    @api.depends("name", "default_code", "product_tmpl_id", "list_price")
    @api.depends_context(
        "display_default_code",
        "seller_id",
        "company_id",
        "partner_id",
        "formatted_display_name",
        "lang",
        "mb_show_sale_selector_price",
        "mb_show_product_selector_price",
        "mb_sale_pricelist_id",
        "mb_sale_currency_id",
    )
    def _compute_display_name(self):
        super()._compute_display_name()
        append_sale_selector_price(self)

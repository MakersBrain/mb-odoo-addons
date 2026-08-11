from . import controllers
from . import models


def post_init_hook(env):
    env["product.product"].sudo().search([("barcode", "!=", False)])._register_mb_primary_barcodes()

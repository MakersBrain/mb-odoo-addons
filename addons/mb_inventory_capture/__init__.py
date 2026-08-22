from . import controllers
from . import models


def post_init_hook(env):
    env["product.product"].sudo()._register_mb_existing_primary_barcodes()

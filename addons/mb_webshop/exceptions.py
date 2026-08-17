from odoo.exceptions import ValidationError


class WebshopStockUnavailable(ValidationError):
    """The webshop's atomic stock reservation cannot be reacquired."""

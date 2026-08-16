import werkzeug

from odoo import models
from odoo.http import request


def webshop_path_is_gated(path):
    """Return whether *path* belongs to the public shop/checkout surface."""
    normalized = "/" + (path or "").lstrip("/")
    return normalized == "/shop" or normalized.startswith("/shop/")


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    @classmethod
    def _pre_dispatch(cls, rule, arguments):
        super()._pre_dispatch(rule, arguments)
        website = getattr(request, "website", False)
        if (
            website
            and not website.sudo().mb_webshop_enabled
            and (
                webshop_path_is_gated(request.httprequest.path)
                or webshop_path_is_gated(getattr(rule, "rule", ""))
            )
        ):
            raise werkzeug.exceptions.NotFound()

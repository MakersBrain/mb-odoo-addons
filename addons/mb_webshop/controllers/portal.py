from odoo import http
from odoo.exceptions import AccessError, MissingError, ValidationError
from odoo.http import request

from odoo.addons.sale.controllers import portal as sale_portal


class WebshopCustomerPortal(sale_portal.CustomerPortal):
    def _sale_order_get_page_view_values(
        self, order_sudo, access_token, values, history_session_key, **kwargs
    ):
        values = super()._sale_order_get_page_view_values(
            order_sudo, access_token, values, history_session_key, **kwargs
        )
        values.update(
            {
                "mb_returns": request.env["mb.webshop.return"]
                .sudo()
                .search(
                    [
                        ("order_id", "=", order_sudo.id),
                    ]
                ),
                "mb_can_request_return": bool(order_sudo._mb_returnable_lines()),
                "mb_return_submitted": kwargs.get("return_submitted"),
            }
        )
        return values

    @http.route(
        "/my/orders/<int:order_id>/return",
        type="http",
        auth="public",
        website=True,
        methods=["GET", "POST"],
    )
    def portal_order_return(self, order_id, access_token=None, **post):
        try:
            order = self._document_check_access("sale.order", order_id, access_token=access_token)
        except (AccessError, MissingError):
            return request.redirect("/my")

        returnable = order._mb_returnable_lines()
        error = False
        if request.httprequest.method == "POST":
            quantities = {}
            for line in returnable:
                raw = post.get(f"line_{line.id}", "0")
                try:
                    quantity = float(raw or 0)
                except (TypeError, ValueError):
                    quantity = -1
                if quantity:
                    quantities[line.id] = quantity
            try:
                request.env["mb.webshop.return"].sudo().create_from_portal(
                    order, quantities, post.get("reason", "")
                )
            except ValidationError as exc:
                error = exc.args[0]
            else:
                return request.redirect(order.get_portal_url(query_string="&return_submitted=1"))

        values = {
            "sale_order": order,
            "returnable_lines": returnable,
            "returnable_quantities": {
                line.id: order._mb_returnable_quantity(line) for line in returnable
            },
            "access_token": access_token,
            "error": error,
            "page_name": "order_return",
            "res_company": order.company_id,
        }
        return request.render("mb_webshop.portal_order_return", values)

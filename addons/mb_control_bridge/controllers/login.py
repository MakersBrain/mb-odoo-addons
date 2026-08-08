from odoo import http
from odoo.http import request
from odoo.addons.web.controllers.utils import ensure_db

try:
    from odoo.addons.auth_oidc.controllers.main import OpenIDLogin as OAuthLoginBase
except ImportError:
    from odoo.addons.auth_oauth.controllers.main import OAuthLogin as OAuthLoginBase


def should_redirect_to_makersbrain(method, authenticated, params):
    return (
        method == "GET"
        and not authenticated
        and params.get("local") != "1"
        and not params.get("oauth_error")
    )


class MakersBrainLogin(OAuthLoginBase):
    @http.route()
    def web_login(self, *args, **kwargs):
        ensure_db()
        if should_redirect_to_makersbrain(
            request.httprequest.method,
            bool(request.session.uid),
            request.params,
        ):
            provider_id = int(
                request.env["ir.config_parameter"]
                .sudo()
                .get_param("mb_control.oidc_provider_id", "0")
                or 0
            )
            provider = next(
                (
                    candidate
                    for candidate in self.list_providers()
                    if candidate["id"] == provider_id
                ),
                None,
            )
            if provider:
                return request.redirect(provider["auth_link"], 303, local=False)
        return super().web_login(*args, **kwargs)

    def get_state(self, provider):
        state = super().get_state(provider)
        configured_provider = int(
            request.env["ir.config_parameter"]
            .sudo()
            .get_param("mb_control.oidc_provider_id", "0")
            or 0
        )
        if provider["id"] == configured_provider:
            state["c"] = {**state.get("c", {}), "no_user_creation": True}
        return state

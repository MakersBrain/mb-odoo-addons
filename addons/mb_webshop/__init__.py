from . import controllers
from . import models


def post_init_hook(env):
    """Project the immutable platform host without replacing a custom domain."""
    websites = env["website"].sudo().search([
        ("domain", "=", False),
        ("company_id.mb_control_public_hostname", "!=", False),
    ])
    for website in websites:
        website.domain = website.company_id.mb_control_public_hostname

from . import controllers
from . import models
from . import wizard


def post_init_hook(env):
    env["mb.label.template"]._ensure_company_seed_templates(env["res.company"].search([]))

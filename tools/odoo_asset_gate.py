"""Compile the Odoo asset consumers that carry MakersBrain frontend code.

Run this file through ``odoo shell``.  The shell injects ``env``; keeping the
gate here makes the local Make target and GitHub Actions execute identical
logic.
"""

import json
from typing import Any

from odoo import SUPERUSER_ID, api

env: Any = globals()["env"]

PRIMARY_BUNDLE = "web._assets_primary_variables"
BRAND_TOKENS = "/mb_brand/static/src/scss/mb_tokens.scss"
PRIMARY_VARIABLES = "/mb_brand/static/src/scss/primary_variables.scss"
CONSUMER_BUNDLES = (
    "web.assets_backend",
    "web.assets_frontend",
    "point_of_sale._assets_pos",
    "web.assets_unit_tests",
)


def asset_paths(bundle):
    params = env["ir.asset"]._get_asset_params()
    return [
        path
        for path, _full_path, _source_bundle, _modified in env["ir.asset"]._get_asset_paths(
            bundle=bundle, assets_params=params
        )
    ]


attachments = env["ir.attachment"].sudo().search([("url", "like", "/web/assets/%")])
removed_attachments = len(attachments)
attachments.unlink()
env.cr.commit()
env.registry.clear_cache("assets")

primary_paths = asset_paths(PRIMARY_BUNDLE)
try:
    token_index = primary_paths.index(BRAND_TOKENS)
    variables_index = primary_paths.index(PRIMARY_VARIABLES)
except ValueError as error:
    raise AssertionError(
        f"{PRIMARY_BUNDLE} does not contain both MakersBrain SCSS inputs: {primary_paths}"
    ) from error
if token_index >= variables_index:
    raise AssertionError(f"{BRAND_TOKENS} must precede {PRIMARY_VARIABLES} in {PRIMARY_BUNDLE}")

compiled = {}
qweb = env["ir.qweb"]
for bundle in CONSUMER_BUNDLES:
    asset_bundle = qweb._get_asset_bundle(bundle, css=True, js=True, debug_assets=False)
    if asset_bundle.has_css and asset_bundle.stylesheets:
        asset_bundle.css()
    if asset_bundle.has_js and asset_bundle.javascripts:
        asset_bundle.js()
    links = asset_bundle.get_links()
    if not links:
        raise AssertionError(f"{bundle} compiled to no asset links")
    compiled[bundle] = [str(link) for link in links]

env.cr.commit()
compiled_urls = sorted(
    {url for links in compiled.values() for url in links if "/web/assets/" in url}
)
with env.registry.cursor() as cursor:
    check_env = api.Environment(cursor, SUPERUSER_ID, {})
    generated = check_env["ir.attachment"].search([("url", "in", compiled_urls)])
    if not generated:
        raise AssertionError(f"asset compilation created no attachments for {compiled_urls}")
    compiler_errors = [
        attachment.url
        for attachment in generated
        if b"/* ## CSS error message ##*/" in (attachment.raw or b"")
    ]
    generated_attachment_count = len(generated)
if compiler_errors:
    raise AssertionError(f"Sass compilation errors were embedded in {compiler_errors}")

print(
    json.dumps(
        {
            "removed_attachments": removed_attachments,
            "primary_order": {
                "tokens": token_index,
                "primary_variables": variables_index,
            },
            "compiled_links": {name: len(links) for name, links in compiled.items()},
            "generated_attachments": generated_attachment_count,
        },
        sort_keys=True,
    )
)

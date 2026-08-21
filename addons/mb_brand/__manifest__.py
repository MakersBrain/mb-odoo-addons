{
    "name": "MakersBrain Brand",
    "summary": "The MakersBrain visual identity, applied to Odoo through its own theming seams.",
    "description": """
Odoo already has a supported way to be recoloured, and this addon uses it and
nothing else. That restraint is the design.

**Variables, not selectors.** `web._assets_primary_variables` is where Odoo
declares `$o-brand-primary`, the font families and the rest, every one of them
`!default`. Prepending a file to that bundle sets them first, so core's
declarations no-op and every button, link, highlight and focus ring in the web
client follows without a single override. The alternative — chasing Odoo's own
class names with `!important` — breaks on each upgrade, and it breaks silently,
because a stylesheet that no longer matches anything still compiles.

So the rule here is: if branding cannot be expressed as a variable, it does not
belong in this addon. The two exceptions below are both cases where no variable
exists, and both are deliberately small.

**The login page gets a wordmark; it keeps the workshop's logo.** Odoo's
`web.login_layout` renders `/web/binary/company_logo`, which is the artisan's
own identity, and replacing it with ours would be the wrong trade — the person
signing in works at that pottery, not at MakersBrain. So the company logo stays
where it is and a MakersBrain lockup sits under the card, which is the honest
arrangement: their workshop, our software.

**Fonts are shipped, not linked.** Bitter for headings, IBM Plex Sans for the
interface, both SIL OFL and both self-hosted in `static/src/fonts`. A webfont
CDN would put a third party in the request path of every backend page load, and
a workshop with a poor connection would watch the interface reflow.

The source of truth for every value here is `brand/tokens.css` at the root of
this repository, and `brand/design-chart.html` documents what the values mean.
This addon is a translation of that system into Odoo's variables, so a change
belongs upstream in the tokens first.

Deliberately not done: the app switcher, the list and form views, and the rest
of the web client keep Odoo's own layout. Fighting an upstream theme wholesale
is a cost that never stops being paid, and the recolour above already makes the
product read as MakersBrain.
""",
    "version": "19.0.1.0.1",
    "license": "LGPL-3",
    "category": "Technical",
    "author": "MakersBrain",
    "depends": [
        # The asset bundles this addon prepends to are all declared by `web`.
        "web",
    ],
    "data": [
        "views/mb_brand_login_templates.xml",
    ],
    "assets": {
        # Prepend: these must be set before core's `!default` declarations, or
        # they lose to them. Order within the bundle is the whole mechanism.
        "web._assets_primary_variables": [
            ("prepend", "mb_brand/static/src/scss/primary_variables.scss"),
        ],
        # The faces themselves have to reach both the web client and the public
        # pages, and neither bundle includes the other.
        "web.assets_backend": [
            "mb_brand/static/src/scss/fonts.scss",
        ],
        "web.assets_frontend": [
            "mb_brand/static/src/scss/fonts.scss",
            "mb_brand/static/src/scss/login.scss",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}

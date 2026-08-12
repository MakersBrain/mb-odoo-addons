# Landing page

The marketing site for makersbrain.app. One self-contained file.

```sh
python3 brand/build-pages.py    # writes landing/index.html from index.src.html
```

`index.html` is a build artefact — edit `index.src.html`. The build inlines the
fonts and the real `brand/tokens.css` and `brand/ui.css`, so the page has zero
external requests and cannot drift from the product's own design system.
Deploying is copying one file.

## What it claims, and why each claim is safe

Everything on the page is traceable to code that exists. The capability grid
names the module behind each item, and the copy was written from `SPEC.md`,
which is itself written from the manifests and the running database rather than
from intent.

The "Where it is today" band exists because the honest version is more
persuasive than the usual one, and because a workshop that adopts this on a
false impression churns. It says plainly that the depth is in ceramics, that the
tax work is French only, and that there is no open sign-up.

Deliberately absent:

- **No pricing.** There is no price list yet, and inventing tiers would be a
  commitment made by a web page rather than by a person.
- **No testimonials, logos or customer counts.** There are no customers to quote.
- **No screenshots.** The interface is still moving; a stale screenshot is a
  promise you have to keep.

## Before it goes live

- [ ] **Confirm the contact address.** The CTA links to `hello@makersbrain.app`,
      which is a placeholder. It is marked with a comment in `index.src.html`.
- [ ] Decide whether "Powered by Odoo" attribution belongs in the footer. LGPL-3
      does not require it; the page currently says what it is built on in prose,
      which is the more useful version anyway.
- [ ] Add a privacy notice if any form is added later. There is no form today —
      the CTA is a `mailto:` — so nothing is collected and none is needed yet.

## Structure

The page is built on the product's own idea rather than on a template. The
middle band is a literal thread: a rule down the left with a node at each stage
from raw material to filed declaration, because that continuity is the actual
claim MakersBrain makes and the thing competitors do not do. It is numbered by
position rather than by label because it is a genuine sequence — the one case
where sequence markers carry information instead of decorating.

Type runs at the marketing scale (17px body, up to 56px display) rather than the
product's 15px interface scale. Everything else — colour, spacing, buttons,
radius — is the shared system unchanged. The `lp-` prefix marks the handful of
classes that exist only here.

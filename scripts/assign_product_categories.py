#!/usr/bin/env python3
"""Put the atelier's own pieces in a category, by form.

49 of 50 product templates carry no category at all. That is not cosmetic:
`categ_id` is where the costing method and the valuation setting live, so an
uncategorised product silently falls back to the company default rather than
anything anybody chose.

The existing tree describes what the atelier *buys*:

    Goods / Ceramic materials / {Clay bodies, Glazes, Oxides, Underglazes, ...}

This adds the mirror for what it *makes*:

    Goods / Ceramic pieces / {Boxes, Tableware, Decorative, Accessories}

The form comes from the SKU prefix, which is already a clean code: `BA-GP-0001`
is prefix BA, clay body GP, sequence 0001. Prefix is the piece's form and is
mapped below by hand - deliberately, because it is the one part a person should
be able to read and correct. Titles are useless as a key here (three products
called "Boite Baleine", three called "Sculpture Poulpe") and the archive's own
`product_type` and `category` columns are populated on 2 rows out of 48.

Clay body is a second axis and is NOT a category - a product has one category
but the atelier throws the same form in GP and GL, so it belongs on
`product_tag_ids`. Not done here; ask for it if you want it.

The new categories are created with the same costing and valuation settings the
existing sixteen already carry (standard / periodic), so assigning a category
changes how a product is grouped and reported, and nothing about how it is
valued.

Usage:

    python3 scripts/assign_product_categories.py --dry-run
    python3 scripts/assign_product_categories.py
"""

import argparse
import json
import subprocess
import sys

ODOO_CONTAINER = "mb-odoo-web"
PARENT = "Ceramic pieces"

# SKU prefix -> subcategory. The prefix is the form, the middle token is the
# clay body. BRM covers both "Boite Raie Menta" and "Boite Requin Marteau";
# they are both boxes, so the collision is harmless.
FORMS = {
    "Boxes": ["BA", "BB", "BD", "BO", "BP", "BRM", "BTL", "BTV"],
    "Tableware": ["CO", "GS", "MD", "MH", "MP", "MT",
                  "TH", "TM", "TP", "TRM", "TTV"],
    "Decorative": ["LM", "PDB", "PDC", "PDP", "PDT", "SP", "VA"],
    "Accessories": ["GAS", "GAT", "OPE", "PAS", "PC", "PRC", "RC", "SLP"],
}

ASSIGN_TEMPLATE = '''
import json

CONFIG = json.loads({config!r})
DRY_RUN = {dry_run!r}
PARENT = CONFIG["parent"]

Category = env["product.category"]
Template = env["product.template"]

goods = Category.search([("name", "=", "Goods"), ("parent_id", "=", False)], limit=1)
if not goods:
    raise SystemExit("no root 'Goods' category")

# Match the settings the sixteen existing categories already carry, so that
# giving a product a category does not quietly change how it is valued.
sibling = Category.search([("name", "=", "Ceramic materials")], limit=1) or goods
defaults = {{"property_cost_method": sibling.property_cost_method,
            "property_valuation": sibling.property_valuation}}
print("INFO inheriting", defaults["property_cost_method"], "/",
      defaults["property_valuation"], "from", sibling.complete_name)


def ensure_category(name, parent, parent_label=None):
    """One category under its parent. Idempotent.

    Under --dry-run the parent may not exist yet, so `parent_label` carries the
    path it would have had - otherwise the subcategories go unreported and the
    dry run looks like it does less than it does.
    """
    if not parent:
        print("CATEGORY would create", (parent_label or "?") + " / " + name)
        return Category
    found = Category.search([("name", "=", name),
                             ("parent_id", "=", parent.id)], limit=1)
    if found:
        print("CATEGORY exists", found.complete_name)
        return found
    if DRY_RUN:
        print("CATEGORY would create", parent.complete_name + " / " + name)
        return Category
    created = Category.create(dict(defaults, name=name, parent_id=parent.id))
    print("CATEGORY created", created.complete_name)
    return created


parent = ensure_category(PARENT, goods)
subcategories = {{}}
for name in CONFIG["forms"]:
    subcategories[name] = ensure_category(
        name, parent, parent_label=goods.complete_name + " / " + PARENT)

# --- map every template by its SKU prefix -----------------------------------
prefix_to_form = {{}}
for form, prefixes in CONFIG["forms"].items():
    for prefix in prefixes:
        prefix_to_form[prefix] = form

counts = {{}}
unmapped = []
for template in Template.search([]):
    code = template.default_code
    if not code or "-" not in code:
        if not template.categ_id:
            unmapped.append((code or template.name, "no SKU prefix"))
        continue
    form = prefix_to_form.get(code.split("-")[0])
    if not form:
        unmapped.append((code, "prefix not mapped"))
        continue
    target = subcategories[form]
    if template.categ_id and template.categ_id == target:
        continue
    was = template.categ_id.complete_name or "(none)"
    if not DRY_RUN:
        template.categ_id = target.id
    counts[form] = counts.get(form, 0) + 1
    print("ASSIGN", code, was, "->", PARENT + " / " + form)

for code, why in unmapped:
    print("SKIP", code, "-", why)

if not DRY_RUN:
    env.cr.commit()

for form in CONFIG["forms"]:
    category = subcategories[form]
    held = Template.search_count([("categ_id", "=", category.id)]) if category else 0
    print("TOTAL", form, counts.get(form, 0), "moved,", held, "now in category")
print("TOTAL uncategorised remaining",
      Template.search_count([("categ_id", "=", False)]))
'''


def run_in_odoo(script, database, prefixes):
    """Pipe a script into `odoo shell` and echo the lines it meant to report."""
    result = subprocess.run(
        ["docker", "exec", "-i", ODOO_CONTAINER, "odoo", "shell",
         "-d", database, "--log-level=error", "--http-port=8199", "--no-http"],
        input=script, capture_output=True, text=True)
    for line in result.stdout.splitlines():
        if line.startswith(prefixes):
            print("  " + line)
    if result.returncode != 0:
        sys.exit(result.stderr.strip()[-2000:])


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database", default="odoo")
    parser.add_argument("--parent", default=PARENT)
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change, write nothing")
    options = parser.parse_args()

    script = ASSIGN_TEMPLATE.format(
        config=json.dumps({"parent": options.parent, "forms": FORMS}),
        dry_run=options.dry_run)
    print(f"{'checking' if options.dry_run else 'assigning'} categories "
          f"in '{options.database}' ...")
    run_in_odoo(script, options.database,
                prefixes=("INFO", "CATEGORY", "ASSIGN", "SKIP", "TOTAL"))


if __name__ == "__main__":
    main()

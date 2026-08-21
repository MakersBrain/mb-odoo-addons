#!/usr/bin/env python3
"""Clear what the demo fixtures left behind.

Three unrelated kinds of residue, each harmless-looking and each capable of
biting later:

`ir.model.data` rows whose record is gone. Odoo's own demo products were
deleted without their external ids, so 78 rows point at nothing. Nothing breaks
today; the next `-u product` either fails on them or quietly recreates the demo
products they name. `seed_from_catalogue.py --purge` already deletes the xmlids
of the products it removes, for exactly this reason - these came out another
way. Only rows whose model is present in the registry are touched: a missing
model means the module is uninstalled, and its xmlids are dormant rather than
dangling.

Leftover fixture products, and the bills of materials that hang off them. A BoM
has to go first or the product will not delete.

Storage categories nothing points at.

Products are deleted where Odoo allows and archived where it does not - a
product that any stock move refers to is part of a history, and Odoo refuses to
delete it rather than take that history with it. That refusal is correct, so it
is reported and worked around, not defeated.

Usage:

    python3 scripts/cleanup_demo_residue.py --dry-run
    python3 scripts/cleanup_demo_residue.py
"""

import argparse
import json
import subprocess
import sys

ODOO_CONTAINER = "mb-odoo-web"

# Fixture products to remove, by name. Deliberately a name list and not a
# pattern: everything else in this database is real stock.
FIXTURE_PRODUCTS = ["Bisque Template"]

CLEANUP_TEMPLATE = '''
import json
import collections

CONFIG = json.loads({config!r})
DRY_RUN = {dry_run!r}

Data = env["ir.model.data"]
Template = env["product.template"]
Category = env["stock.storage.category"]

# --- 1. external ids pointing at nothing ------------------------------------
# Grouped by model so existence is one query per model rather than per row.
rows_by_model = collections.defaultdict(list)
for row in Data.search([]):
    rows_by_model[row.model].append(row)

dangling = Data
skipped_models = []
for model, rows in rows_by_model.items():
    if model not in env:
        skipped_models.append(model)
        continue
    ids = [r.res_id for r in rows]
    alive = set(env[model].with_context(active_test=False).browse(ids).exists().ids)
    for row in rows:
        if row.res_id not in alive:
            dangling |= row

by_module = collections.Counter(dangling.mapped("module"))
for module, count in sorted(by_module.items()):
    print("XMLID", count, "dangling in", module)
if skipped_models:
    print("XMLID skipped", len(skipped_models), "rows whose model is not installed")
if dangling and not DRY_RUN:
    dangling.unlink()
print("XMLID", ("would remove" if DRY_RUN else "removed"), len(dangling), "rows")

# --- 2. fixture products, and their bills of materials ----------------------
for name in CONFIG["fixture_products"]:
    template = Template.with_context(active_test=False).search(
        [("name", "=", name)], limit=1)
    if not template:
        print("PRODUCT absent", name)
        continue
    variants = template.product_variant_ids
    boms = env["mrp.bom"].with_context(active_test=False).search(
        [("product_tmpl_id", "=", template.id)])
    moves = env["stock.move"].search_count([("product_id", "in", variants.ids)])
    quants = env["stock.quant"].search_count([("product_id", "in", variants.ids)])
    print("PRODUCT", name, "- boms:", len(boms), "moves:", moves, "quants:", quants)
    if DRY_RUN:
        print("PRODUCT would remove", name, "and", len(boms), "BoM")
        continue
    if boms:
        boms.unlink()
        print("PRODUCT removed BoM for", name)
    try:
        template.unlink()
        print("PRODUCT removed", name)
    except Exception as error:
        # Stock history holds it. Archiving keeps the history intact and takes
        # the product out of every list, which is the outcome that was wanted.
        env.cr.rollback()
        template.active = False
        print("PRODUCT archived instead of removed:", name, "-",
              str(error).strip().split(chr(10))[0][:100])

# --- 3. storage categories nothing points at --------------------------------
Location = env["stock.location"].with_context(active_test=False)
for category in Category.search([]):
    used = Location.search_count([("storage_category_id", "=", category.id)])
    capacity = env["stock.storage.category.capacity"].search_count(
        [("storage_category_id", "=", category.id)])
    if used or capacity:
        continue
    print("CATEGORY", ("would remove" if DRY_RUN else "removed"),
          category.name, "- no locations, no capacity rules")
    if not DRY_RUN:
        category.unlink()

if not DRY_RUN:
    env.cr.commit()

# Recounted from a fresh read. The cached rows above were just deleted, and
# touching them raises rather than reporting zero.
remaining = collections.defaultdict(list)
for row in Data.search([]):
    remaining[row.model].append(row.res_id)
still = 0
for model, ids in remaining.items():
    if model not in env:
        continue
    alive = set(env[model].with_context(active_test=False).browse(ids).exists().ids)
    still += sum(1 for res_id in ids if res_id not in alive)
print("DONE dangling xmlids now", still)
print("DONE storage categories:", Category.search([]).mapped("name"))
print("DONE uncategorised products:",
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
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change, write nothing")
    options = parser.parse_args()

    script = CLEANUP_TEMPLATE.format(
        config=json.dumps({"fixture_products": FIXTURE_PRODUCTS}),
        dry_run=options.dry_run)
    print(f"{'checking' if options.dry_run else 'cleaning'} demo residue "
          f"in '{options.database}' ...")
    run_in_odoo(script, options.database,
                prefixes=("XMLID", "PRODUCT", "CATEGORY", "DONE"))


if __name__ == "__main__":
    main()

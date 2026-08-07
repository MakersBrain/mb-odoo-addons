#!/usr/bin/env python3
"""Set on-hand stock in Odoo from an Ateliera tenant archive.

The archive carries a movement ledger, not a stock level: `core/stock_movements`
holds signed quantities with a type of production, purchase or removal. Summing
the ones that are not soft-deleted gives on-hand per product at the instant the
archive was taken, and that figure is what an inventory adjustment writes.

This deliberately does NOT replay the ledger as dated stock moves. An adjustment
states what is on the shelf now; a replay would state how it got there, needs
every product costed, and the archive prices nothing - `unit_cost_minor` is null
on every movement and `cost_minor` on every product. Valuation therefore lands
at whatever standard_price each product already carries.

Lots are dropped on purpose. 47 of the 49 live movements carry a stock_lot_id
across 6 firing lots, but Odoo requires a lot per product, so preserving them
means ~47 stock.lot records and flipping every product to tracking='lot'. That
is a decision to take deliberately, not a side effect of an import. Stock landed
flat here can be lot-tracked later: flipping tracking with stock on hand works,
and an existing no-lot quant can be re-lotted by zeroing it and re-adding it
against a lot. The one thing no-lot stock cannot do is leave - a delivery or a
dépôt transfer for a lot-tracked product refuses to validate without a lot - so
if the products are ever switched to tracking='lot', that re-lot step has to
happen before anything can be shipped.

Products are matched on the archive variant's `sku` against Odoo's
`default_code`. Not on title: the archive has three products called "Boite
Baleine" and three called "Sculpture Poulpe". Not on the archive's product
`code` either, which is null for 21 of 48.

Raw materials are skipped - `product_type == 'raw_material'` in the archive, the
clay. Finished pieces go to AT/Stock/Finished, the only location the atelier
sells from.

Usage:

    python3 scripts/import_ateliera_stock.py ~/Downloads/cmarteau-ceramics-*.tar.gz --dry-run
    python3 scripts/import_ateliera_stock.py ~/Downloads/cmarteau-ceramics-*.tar.gz
"""

import argparse
import collections
import json
import subprocess
import sys
import tarfile

ODOO_CONTAINER = "odoo-poc-web"
TARGET_LOCATION = "AT/Stock/Finished"

# Locations whose stock this import owns and may zero. Anything the archive does
# not mention, inside these, is stale and goes to zero. Dépôts is deliberately
# not in here: consigned pieces are physically with a gallery, the archive has
# nothing to say about them, and silently zeroing them would write off stock
# that exists.
OWNED_ROOTS = ["AT", "AT-WIP"]


def read_archive(path):
    """on-hand per SKU, from the movement ledger."""
    wanted = {
        "data/core/stock_movements.ndjson": "movements",
        "data/core/products.ndjson": "products",
        "data/core/product_variants.ndjson": "variants",
    }
    tables = {}
    with tarfile.open(path, "r:gz") as archive:
        for member, key in wanted.items():
            handle = archive.extractfile(member)
            if handle is None:
                sys.exit(f"{path} has no {member} - is this an Ateliera archive?")
            tables[key] = [json.loads(line) for line in
                           handle.read().decode().splitlines() if line.strip()]

    products = {p["id"]: p for p in tables["products"]}
    sku_by_product = {}
    for variant in tables["variants"]:
        # One default variant per product in this archive. Prefer it explicitly
        # rather than trusting iteration order.
        if variant["sku"] and (variant["is_default"]
                               or variant["product_id"] not in sku_by_product):
            sku_by_product[variant["product_id"]] = variant["sku"]

    on_hand = collections.Counter()
    skipped_raw = collections.Counter()
    live = [m for m in tables["movements"] if not m["deleted_at"]]
    for movement in live:
        product = products.get(movement["product_id"])
        if product is None:
            continue
        sku = sku_by_product.get(movement["product_id"])
        if not sku:
            continue
        if product.get("product_type") == "raw_material":
            skipped_raw[sku] += movement["quantity"]
            continue
        on_hand[sku] += movement["quantity"]

    titles = {sku_by_product[pid]: p["title"]
              for pid, p in products.items() if pid in sku_by_product}
    return {
        "on_hand": {sku: qty for sku, qty in on_hand.items()},
        "titles": titles,
        "skipped_raw": dict(skipped_raw),
        "movements_total": len(tables["movements"]),
        "movements_live": len(live),
    }


IMPORT_TEMPLATE = '''
import json

PAYLOAD = json.loads({payload!r})
DRY_RUN = {dry_run!r}
TARGET = {target!r}
OWNED_ROOTS = json.loads({owned!r})

Location = env["stock.location"]
Quant = env["stock.quant"]
Product = env["product.product"]

target = Location.search([("complete_name", "=", TARGET)], limit=1)
if not target:
    raise SystemExit("no location %s - run setup_workshop_locations.py first" % TARGET)
roots = Location.search([("complete_name", "in", OWNED_ROOTS)])
if len(roots) != len(OWNED_ROOTS):
    raise SystemExit("missing one of %s" % OWNED_ROOTS)

on_hand = PAYLOAD["on_hand"]
products = Product.search([("default_code", "in", list(on_hand))])
by_code = {{p.default_code: p for p in products}}
missing = sorted(set(on_hand) - set(by_code))
for sku in missing:
    print("UNMATCHED", sku, PAYLOAD["titles"].get(sku, ""))

# Consigned stock for these products is real and is not ours to touch. Say so
# rather than quietly leaving an inconsistency. `child_of` has no negation as
# an operator, so resolve the owned subtree to ids and exclude those.
owned = Location.search([("id", "child_of", roots.ids)])
depot_quants = Quant.search([
    ("product_id", "in", products.ids),
    ("location_id.usage", "=", "internal"),
    ("location_id", "not in", owned.ids)])
for quant in depot_quants:
    print("OUTSIDE", quant.product_id.default_code, quant.quantity,
          "at", quant.location_id.complete_name, "- left alone")

# --- clear whatever is stale inside the locations this import owns -----------
# Zeroed quants linger as rows, so re-running would otherwise report clearing
# stock that is already gone.
stale = Quant.search([
    ("product_id", "in", products.ids),
    ("location_id", "in", owned.ids),
    ("location_id.usage", "=", "internal"),
    ("location_id", "!=", target.id),
    ("quantity", "!=", 0)])
for quant in stale:
    print("CLEARED", quant.product_id.default_code, quant.quantity,
          "at", quant.location_id.complete_name)
if stale and not DRY_RUN:
    stale = stale.with_context(inventory_mode=True)
    stale.write({{"inventory_quantity": 0}})
    stale.action_apply_inventory()

# --- write the archive figures ----------------------------------------------
written = 0
for sku, quantity in sorted(on_hand.items()):
    product = by_code.get(sku)
    if not product:
        continue
    existing = Quant.search([("product_id", "=", product.id),
                             ("location_id", "=", target.id)], limit=1)
    before = existing.quantity if existing else 0.0
    if DRY_RUN:
        print("SET", sku, before, "->", quantity)
        written += 1
        continue
    if existing:
        quant = existing.with_context(inventory_mode=True)
        quant.inventory_quantity = quantity
    else:
        quant = Quant.with_context(inventory_mode=True).create({{
            "product_id": product.id, "location_id": target.id,
            "inventory_quantity": quantity}})
    quant.action_apply_inventory()
    print("SET", sku, before, "->", quantity)
    written += 1

if not DRY_RUN:
    env.cr.commit()

total = sum(Quant.search([("location_id", "=", target.id)]).mapped("quantity"))
print("TOTAL", written, "products,", total, "units in", TARGET)
print("TOTAL unmatched", len(missing))
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
    parser.add_argument("archive", help="path to a cmarteau-ceramics-*.tar.gz")
    parser.add_argument("--database", default="odoo")
    parser.add_argument("--location", default=TARGET_LOCATION)
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change, write nothing")
    options = parser.parse_args()

    data = read_archive(options.archive)
    on_hand = data["on_hand"]
    positive = {sku: qty for sku, qty in on_hand.items() if qty}
    print(f"{data['movements_live']} live movements of {data['movements_total']} "
          f"-> {len(positive)} products, {sum(positive.values())} units")
    for sku, qty in sorted(data["skipped_raw"].items()):
        print(f"  skipped raw material {sku}: {qty}")

    script = IMPORT_TEMPLATE.format(
        payload=json.dumps({"on_hand": on_hand, "titles": data["titles"]}),
        dry_run=options.dry_run, target=options.location,
        owned=json.dumps(OWNED_ROOTS))
    print(f"{'checking' if options.dry_run else 'writing'} stock into "
          f"'{options.database}' at {options.location} ...")
    run_in_odoo(script, options.database,
                prefixes=("UNMATCHED", "OUTSIDE", "CLEARED", "SET", "TOTAL"))


if __name__ == "__main__":
    main()

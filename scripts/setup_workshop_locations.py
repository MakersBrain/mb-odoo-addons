#!/usr/bin/env python3
"""Build the atelier's location tree: raw materials, drying racks, finished stock.

The shape, and why it is this shape:

    AT                      view        the warehouse
    AT/Stock                internal    lot_stock_id
    AT/Stock/Clay           internal    RAW-CLAY
    AT/Stock/Glaze          internal    RAW-GLAZE
    AT/Stock/Finished       internal    FINISHED    <- the only sellable stock
    AT-WIP                  view        the racks, deliberately outside AT
    AT-WIP/DAMP-01..03      internal    DAMP
    AT-WIP/DRY-PLANCHES     internal    DRYING
    AT-WIP/DRY-SERRE        internal    DRYING
    AT-WIP/BISQUE-01        internal    BISQUE
    AT-WIP/GLAZE-01         internal    GLAZE
    Dépôts/*                internal    FINISHED    consigned, sold by others

Two decisions in here are not obvious and are worth stating, because the
obvious alternatives are both wrong.

`Finished` hangs off `AT/Stock` rather than off `AT`. A sibling of `AT/Stock`
would look tidier, but the stock Delivery Orders and `Mise en dépôt` operation
types both source from `AT/Stock`, and reservation only descends. Finished
pieces parked in a sibling reserve nothing at all: the delivery sits at
`confirmed` with `reserved=0` and the sale can never be picked.

`AT-WIP` sits at the root rather than under `AT`, which is the one place this
tree disagrees with the physical workshop - the racks are of course in the
atelier. It has to, because in Odoo "is inside the warehouse" and "counts as
sellable" are the same switch. `_get_domain_locations_new` resolves a warehouse
context to a plain recursive descendants query on `location_id`, with no filter
on usage, so anything under `AT` is stock a salesperson can promise no matter
what type the location is - Internal, Production, Transit and Inventory all
behave identically here. Pieces still drying would show as free stock, the
quotation would confirm against them, and the delivery would then be
unreservable forever. Hanging the racks off the root is what makes the
availability figure honest. The name keeps the association the tree gives up.

Storage categories are labels, not rules: on their own they block nothing.
Putaway rules are what would read them, and none exist yet. The guarantee that
a drying piece cannot be sold comes from the tree above, not from the DAMP tag.

Usage:

    python3 scripts/setup_workshop_locations.py
    python3 scripts/setup_workshop_locations.py --database odoo --dry-run
"""

import argparse
import json
import subprocess
import sys

ODOO_CONTAINER = "odoo-poc-web"

# name -> storage category, per rack. Order is the order pieces travel in.
WIP_RACKS = [
    ("DAMP-01", "DAMP"),
    ("DAMP-02", "DAMP"),
    ("DAMP-03", "DAMP"),
    ("DRY-PLANCHES", "DRYING"),
    ("DRY-SERRE", "DRYING"),
    ("BISQUE-01", "BISQUE"),
    ("GLAZE-01", "GLAZE"),
]
STOCK_CHILDREN = [
    ("Clay", "RAW-CLAY"),
    ("Glaze", "RAW-GLAZE"),
    ("Finished", "FINISHED"),
]
CATEGORIES = ["RAW-CLAY", "RAW-GLAZE", "DAMP", "DRYING", "BISQUE", "GLAZE", "FINISHED"]

# Categories that already exist under a different spelling. Renaming rather than
# creating a second one keeps the locations that already point at them attached.
CATEGORY_RENAMES = {"Bisque": "BISQUE"}

# Locations that already exist somewhere else. Moved rather than recreated, so
# that any stock, move history or putaway rule on them travels along.
#   current complete_name -> (new parent, new name, category)
MIGRATIONS = [
    ("AT/Bisque", "AT-WIP", "BISQUE-01", "BISQUE"),
    ("AT/WIP-DAMP-01", "AT-WIP", "DAMP-01", "DAMP"),
]

SETUP_TEMPLATE = '''
import json

CONFIG = json.loads({config!r})
DRY_RUN = {dry_run!r}

Location = env["stock.location"]
Category = env["stock.storage.category"]

warehouse = env["stock.warehouse"].search([], limit=1)
if not warehouse:
    raise SystemExit("no warehouse")
AT = warehouse.view_location_id
AT_STOCK = warehouse.lot_stock_id
print("INFO warehouse", warehouse.name, "code", warehouse.code,
      "view", AT.complete_name, "lot_stock", AT_STOCK.complete_name)


def by_complete_name(name):
    return Location.with_context(active_test=False).search(
        [("complete_name", "=", name)], limit=1)


# --- storage categories -----------------------------------------------------
# Odoo 19 has no group_stock_storage_categories - it went away, and asking
# has_group() for a missing xmlid answers False rather than raising, which
# reads convincingly like a disabled feature. What actually gates both the
# Configuration > Storage Categories menu and the field on the location form is
# group_stock_multi_locations. Check that, and only that.
if not env.user.has_group("stock.group_stock_multi_locations"):
    print("SETTING Storage Locations is OFF - categories will be invisible in "
          "the interface; enable it in Inventory > Configuration > Settings")
else:
    print("SETTING Storage Locations on, categories visible")

for old, new in CONFIG["category_renames"].items():
    existing = Category.search([("name", "=", old)], limit=1)
    if existing and not Category.search([("name", "=", new)], limit=1):
        if not DRY_RUN:
            existing.name = new
        print("CATEGORY renamed", old, "->", new)

categories = {{}}
for name in CONFIG["categories"]:
    found = Category.search([("name", "=", name)], limit=1)
    if not found and not DRY_RUN:
        found = Category.create({{"name": name}})
        print("CATEGORY created", name)
    elif found:
        print("CATEGORY exists", name)
    categories[name] = found


def ensure(name, parent, usage="internal", category=None, root=False, label=None):
    """One location, by name under its parent. Idempotent.

    `label` names the parent for reporting. Under --dry-run the parent may not
    exist yet, so there is no complete_name to quote and the configured name is
    all we have.
    """
    where = "(root)" if root else (parent.complete_name if parent else label)
    if not root and not parent:
        # Parent is still hypothetical, so this location is too.
        print("LOCATION would create", name, "under", where,
              ("[" + category + "]") if category else "")
        return Location
    domain = [("name", "=", name),
              ("location_id", "=", False if root else parent.id)]
    location = Location.with_context(active_test=False).search(domain, limit=1)
    values = {{"name": name, "usage": usage,
              "location_id": False if root else parent.id}}
    if category and categories[category]:
        values["storage_category_id"] = categories[category].id
    if location:
        def current(key):
            value = location[key]
            if location._fields[key].type == "many2one":
                return value.id or False
            return value
        changed = {{k: v for k, v in values.items() if current(k) != v}}
        # A category that does not exist yet cannot be compared by id, but the
        # intent to set it is still worth reporting.
        if category and not categories[category] and \\
                location.storage_category_id.name != category:
            changed["storage_category_id"] = category
        verb = "would update" if DRY_RUN else "updated"
        if changed and not DRY_RUN:
            location.write({{k: v for k, v in changed.items()
                            if k != "storage_category_id" or v != category}})
        print("LOCATION exists", location.complete_name,
              (verb + " " + ",".join(sorted(changed))) if changed else "")
        return location
    if DRY_RUN:
        print("LOCATION would create", name, "under", where,
              ("[" + category + "]") if category else "")
        return Location
    location = Location.create(values)
    print("LOCATION created", location.complete_name,
          ("[" + category + "]") if category else "")
    return location


# --- the WIP view, then anything that has to move into it -------------------
wip_root = ensure(CONFIG["wip_root"], None, usage="view", root=True)

for current, parent_name, new_name, category in CONFIG["migrations"]:
    location = by_complete_name(current)
    if not location:
        print("MIGRATE skipped", current, "- not found")
        continue
    parent = by_complete_name(parent_name) or wip_root
    if DRY_RUN:
        print("MIGRATE would move", current, "->", parent_name + "/" + new_name)
        continue
    quantity = sum(env["stock.quant"].search(
        [("location_id", "=", location.id)]).mapped("quantity"))
    location.write({{"name": new_name, "location_id": parent.id,
                    "storage_category_id": categories[category].id}})
    print("MIGRATE moved", current, "->", location.complete_name,
          "carrying", quantity, "units")

for name, category in CONFIG["wip_racks"]:
    ensure(name, wip_root, category=category, label=CONFIG["wip_root"])

# --- raw materials and finished goods, inside the warehouse -----------------
for name, category in CONFIG["stock_children"]:
    ensure(name, AT_STOCK, category=category)

# --- dépôts ------------------------------------------------------------------
depots_root = by_complete_name(CONFIG["depots_root"])
if not depots_root:
    print("DEPOT skipped - no", CONFIG["depots_root"], "view location")
else:
    for name in CONFIG["depots"]:
        stray = Location.with_context(active_test=False).search(
            [("name", "=", name), ("location_id", "=", False)], limit=1)
        if stray:
            if not DRY_RUN:
                stray.write({{"location_id": depots_root.id,
                             "storage_category_id": categories["FINISHED"].id}})
            print("DEPOT reparented", name, "-> under", CONFIG["depots_root"])
        else:
            ensure(name, depots_root, category="FINISHED")

    # A depot is more than a location: mb_depot needs the partner and route set
    # before a quotation can source from it. Report, do not invent.
    for location in depots_root.child_ids:
        if "is_depot" not in location._fields:
            break
        missing = [f for f in ("is_depot", "depot_partner_id", "depot_route_id")
                   if not location[f]]
        if missing:
            print("DEPOT incomplete", location.complete_name,
                  "missing", ",".join(missing))

if not DRY_RUN:
    env.cr.commit()

# --- what the tree looks like now -------------------------------------------
print("TREE")
for location in Location.search([], order="complete_name"):
    if location.usage in ("internal", "view"):
        print("TREE   %-32s %-9s %s" % (
            location.complete_name, location.usage,
            location.storage_category_id.name or ""))

unused = Category.search([]).filtered(
    lambda c: not Location.search_count([("storage_category_id", "=", c.id)]))
for category in unused:
    print("CATEGORY unused", category.name)
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
    parser.add_argument("--wip-root", default="AT-WIP",
                        help="name of the root-level view holding the racks")
    parser.add_argument("--depots-root", default="Dépôts")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change, write nothing")
    options = parser.parse_args()

    config = {
        "categories": CATEGORIES,
        "category_renames": CATEGORY_RENAMES,
        "wip_root": options.wip_root,
        "wip_racks": WIP_RACKS,
        "stock_children": STOCK_CHILDREN,
        "depots_root": options.depots_root,
        "depots": ["Galerie Démo", "La Méduse Électrique Sète"],
        "migrations": [(c, options.wip_root, n, g) for c, _, n, g in MIGRATIONS],
    }
    script = SETUP_TEMPLATE.format(
        config=json.dumps(config), dry_run=options.dry_run)
    print(f"{'checking' if options.dry_run else 'building'} the location tree "
          f"in '{options.database}' ...")
    run_in_odoo(script, options.database,
                prefixes=("INFO", "SETTING", "CATEGORY", "LOCATION",
                          "MIGRATE", "DEPOT", "TREE"))


if __name__ == "__main__":
    main()

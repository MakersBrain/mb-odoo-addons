#!/usr/bin/env python3
"""Load a workshop's own online shop into Odoo, from a catalogue-ceramics dump.

`mb_catalogue_sync` brings in what the atelier *buys* - the supplier catalogue,
keyed by manufacturer SKU. This is the other direction: the potter's own
storefront, one Odoo product per purchasable variant, with the shop's price and
its exact on-hand count. The input is a `ceramics.catalogue_item.v2` dump
produced by ../catalogue-ceramics:

    catalogue-dump --source emily-alarcon --out .../emily-alarcon
    python3 scripts/import_shop_catalogue.py .../emily-alarcon.ndjson.gz --dry-run

Everything travels over docker exec, like the other scripts here, so the two
compose stacks need not share a network.

What it decides, and why:

**The SKU.** A handmade shop publishes no article numbers, so the code is
derived from the shop's own URL slug (`EA-TASSE-BLEUE`), plus the variant name
where a product has several. That is the only identifier the shop guarantees to
be stable, and it is what a re-run matches on - together with an `ir.model.data`
entry under `__mb_shop__`, the same belt-and-braces `mb_catalogue_sync` uses.

**The price.** Written as published. A SumUp storefront quotes the price the
buyer pays, and a micro-entreprise en franchise en base charges no VAT on it, so
there is nothing to convert - see `--net-of-vat` if the workshop is registered.
Because that price is gross, created products get **no sales tax** unless
`--keep-taxes` says otherwise: leaving the company's 20% default on a price that
already includes it would overcharge every line by a fifth.

**What is refreshed, and what is not.** Stock always: it is a fact, it changes
daily and Odoo has no other source for it. Name and category on creation only -
the artisan renames a piece to what they call it on the shelf, and a re-run that
renamed it back would be a bug they cannot fix. Price likewise, unless
`--update-prices` asks for it.

**Stock the shop does not count.** SumUp publishes a quantity for every variant
but only means it when the merchant switched tracking on; the dump nulls the
rest. Those products are created and left alone rather than set to zero - an
untracked product is not an empty shelf. They are listed as SKIPPED.

**Nothing is piped blind.** What reaches Odoo is generated code carrying the
whole payload, so every run writes that script to `build/imports/` first and
says where; `--script-only` stops there, for reading it before it is trusted.

Usage:

    python3 scripts/import_shop_catalogue.py DUMP --emit fixtures/shop.json
    python3 scripts/import_shop_catalogue.py DUMP --script-only
    python3 scripts/import_shop_catalogue.py DUMP --dry-run
    python3 scripts/import_shop_catalogue.py DUMP --images
"""

import argparse
import collections
import gzip
import json
import re
import subprocess
import sys
import tempfile
import unicodedata
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
#: Where the generated odoo shell scripts are left. Not committed: each one
#: carries the whole payload, so it is an artifact of a run rather than an
#: input to one - the inputs are the dump and this file.
SCRIPT_DIR = ROOT / "build" / "imports"
ODOO_CONTAINER = "odoo-poc-web"
IMD_MODULE = "__mb_shop__"
TARGET_LOCATION = "AT/Stock/Finished"
GOODS_CATEGORY = "Ceramic pieces"
#: A shop department whose products are not things on a shelf. Matched on the
#: category the shop itself publishes, casefolded.
SERVICE_CATEGORIES = ("cours et ateliers",)
BROWSER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/136.0.0.0 Safari/537.36"


def read_dump(path):
    """The rows of a catalogue dump, gzipped or not."""
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    if not rows:
        sys.exit(f"{path} holds no records")
    return rows


def slug(value, limit=40):
    """A SKU-safe token: ASCII, uppercase, hyphenated, bounded."""
    folded = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", folded).strip("-").upper()
    return cleaned[:limit].strip("-")


def code_for(row, prefix):
    """`EA-TASSE-BLEUE`, from the shop's URL slug and the variant name.

    The slug, not the title: two of this shop's listings share a title exactly
    ("Gobelet à paille ptits coeurs"), and the URL is what tells them apart.
    """
    tail = (row.get("product_url") or "").rstrip("/").rsplit("/", 1)[-1]
    parts = [prefix, slug(tail)]
    if row.get("variant_title"):
        parts.append(slug(row["variant_title"], limit=16))
    return "-".join(part for part in parts if part)


def build_payload(rows, prefix, net_of_vat):
    """One product per dump row, plus the counts worth printing first."""
    products = []
    seen = {}
    for row in rows:
        code = code_for(row, prefix)
        if code in seen:
            sys.exit(
                f"two rows resolve to the SKU {code}: {seen[code]} and "
                f"{row.get('product_url')} - the shop's slugs are not unique, "
                "pass a different --prefix or fix the dump")
        seen[code] = row.get("product_url")
        category = (row.get("category_path") or [None])[0]
        price = row.get("price")
        if price is not None and net_of_vat:
            price = round(price / (1 + net_of_vat), 2)
        products.append({
            "code": code,
            # `name` already carries the variant ("Petite coupelle Bleu"); the
            # variant title is only wanted in the SKU, where it disambiguates.
            "name": row.get("name"),
            "price": price,
            "currency": row.get("currency"),
            "category": category,
            "is_service": (category or "").casefold() in SERVICE_CATEGORIES,
            # None means "the shop is not counting this one", which is not zero.
            "stock": row.get("stock_quantity"),
            "image_url": row.get("image_url"),
            "product_url": row.get("product_url"),
        })
    currencies = {product["currency"] for product in products}
    if len(currencies) > 1:
        sys.exit(f"the dump mixes currencies {sorted(currencies)}; import them separately")
    return {
        "source": rows[0].get("source"),
        "currency": currencies.pop(),
        "products": sorted(products, key=lambda product: product["code"]),
    }


IMPORT_TEMPLATE = '''
import json

PAYLOAD = json.loads({payload!r})
DRY_RUN = {dry_run!r}
TARGET = {target!r}
GOODS = {goods!r}
IMD_MODULE = {module!r}
UPDATE_PRICES = {update_prices!r}
KEEP_TAXES = {keep_taxes!r}

Category = env["product.category"]
Template = env["product.template"]
Tag = env["product.tag"]
Location = env["stock.location"]
Quant = env["stock.quant"]
Data = env["ir.model.data"]

products = PAYLOAD["products"]

# --- where the goods are filed ----------------------------------------------
# Same rule assign_product_categories.py uses: inherit the costing and valuation
# of the categories that already exist, so filing a product changes how it is
# grouped and nothing about how it is valued.
goods_root = Category.search([("name", "=", "Goods"), ("parent_id", "=", False)], limit=1)
sibling = Category.search([("name", "=", "Ceramic materials")], limit=1) or goods_root
pieces = Category.search([("name", "=", GOODS), ("parent_id", "=", goods_root.id)], limit=1) \\
    if goods_root else Category
if goods_root and not pieces:
    if DRY_RUN:
        print("CATEGORY would create", goods_root.complete_name + " / " + GOODS)
    else:
        pieces = Category.create({{
            "name": GOODS, "parent_id": goods_root.id,
            "property_cost_method": sibling.property_cost_method,
            "property_valuation": sibling.property_valuation}})
        print("CATEGORY created", pieces.complete_name)
elif pieces:
    print("CATEGORY exists", pieces.complete_name)
if not goods_root:
    print("CATEGORY none - no root 'Goods'; products keep the Odoo default")

target = Location.search([("complete_name", "=", TARGET)], limit=1)
if not target:
    raise SystemExit("no location %s - run setup_workshop_locations.py first" % TARGET)


def tag_for(name):
    """The shop's own department, as a tag.

    Not as a category: a product has one category and the shop's departments are
    merchandising ("vente flash" is a promotion, not a kind of object), so they
    belong on the axis that allows several and carries no accounting.
    """
    found = Tag.search([("name", "=", name)], limit=1)
    if found or DRY_RUN:
        return found
    return Tag.create({{"name": name}})


def existing(code):
    """The template this row wrote last time, by external id then by code."""
    data = Data.search([("module", "=", IMD_MODULE), ("name", "=", code.lower().replace("-", "_")),
                        ("model", "=", "product.template")], limit=1)
    if data:
        return Template.browse(data.res_id).exists()
    return Template.search([("default_code", "=", code)], limit=1)


created = updated = 0
by_code = {{}}
for product in products:
    template = existing(product["code"])
    values = {{"list_price": product["price"]}} if (UPDATE_PRICES or not template) else {{}}
    if not template:
        values.update({{
            "name": product["name"],
            "default_code": product["code"],
            "type": "service" if product["is_service"] else "consu",
            "is_storable": not product["is_service"],
            "sale_ok": True,
            "purchase_ok": False,
        }})
        if pieces and not product["is_service"]:
            values["categ_id"] = pieces.id
        if not KEEP_TAXES:
            # The shop's price is what the buyer pays. A company default of 20%
            # on top of it would overcharge every line by a fifth.
            values["taxes_id"] = [(5, 0, 0)]
        if DRY_RUN:
            print("CREATE", product["code"], product["price"], product["name"])
            created += 1
            continue
        template = Template.create(values)
        Data.create({{
            "module": IMD_MODULE, "name": product["code"].lower().replace("-", "_"),
            "model": "product.template", "res_id": template.id,
            # Theirs once imported: an upgrade must not overwrite what the
            # artisan has since edited.
            "noupdate": True}})
        print("CREATE", product["code"], product["price"], product["name"])
        created += 1
    else:
        if values and template.list_price != product["price"]:
            if not DRY_RUN:
                template.write(values)
            print("PRICE", product["code"], template.list_price, "->", product["price"])
            updated += 1
        else:
            print("EXISTS", product["code"], template.name)
    if template and product["category"] and not DRY_RUN:
        tag = tag_for(product["category"])
        if tag and tag not in template.product_tag_ids:
            template.product_tag_ids = [(4, tag.id)]
    if template:
        by_code[product["code"]] = template

# --- on-hand ----------------------------------------------------------------
counted = [product for product in products
           if product["stock"] is not None and not product["is_service"]]
for product in products:
    if product["stock"] is None and not product["is_service"]:
        print("SKIPPED", product["code"], "- the shop is not counting this one")

written = 0
for product in counted:
    template = by_code.get(product["code"])
    if DRY_RUN:
        # A product this run would create has no variant to read a quant from,
        # so the figure it would replace is unknown rather than zero. Reported
        # all the same: a dry run that stayed silent about 77 stock levels
        # would look like it did a fraction of what it does.
        variant = template.product_variant_id if template else None
        quant = Quant.search([("product_id", "=", variant.id),
                              ("location_id", "=", target.id)], limit=1) if variant else None
        print("SET", product["code"], quant.quantity if quant else "?", "->", product["stock"])
        written += 1
        continue
    if not template:
        continue
    variant = template.product_variant_id
    quant = Quant.search([("product_id", "=", variant.id),
                          ("location_id", "=", target.id)], limit=1)
    before = quant.quantity if quant else 0.0
    if before == product["stock"]:
        continue
    if quant:
        quant = quant.with_context(inventory_mode=True)
        quant.inventory_quantity = product["stock"]
    else:
        quant = Quant.with_context(inventory_mode=True).create({{
            "product_id": variant.id, "location_id": target.id,
            "inventory_quantity": product["stock"]}})
    quant.action_apply_inventory()
    print("SET", product["code"], before, "->", product["stock"])
    written += 1

if not DRY_RUN:
    env.cr.commit()

print("TOTAL", created, "created,", updated, "repriced,", written, "stock levels,",
      len(products) - len(counted), "uncounted")
'''

IMAGE_TEMPLATE = '''
import base64
import json

RECORDS = json.loads({records!r})
OVERWRITE = {overwrite!r}

imported = skipped = missing = 0
for record in RECORDS:
    template = env["product.template"].search([("default_code", "=", record["code"])], limit=1)
    if not template:
        missing += 1
        print("IMAGE missing", record["code"])
        continue
    if template.image_1920 and not OVERWRITE:
        skipped += 1
        continue
    with open(record["path"], "rb") as handle:
        template.image_1920 = base64.b64encode(handle.read())
    imported += 1
env.cr.commit()
print("TOTAL images", imported, "set,", skipped, "already had one,", missing, "unmatched")
'''


def save_script(script, path, label):
    """Put the generated shell script on disk before anything runs it.

    What reaches Odoo is generated code holding this shop's whole payload, and
    "what exactly did that write?" is not a question to answer from scrollback.
    Every run leaves the file it fed in, so the answer is a diff away - and the
    file can be read, or run by hand, before it is trusted.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(script, encoding="utf-8")
    print(f"  wrote {label} to {path} ({len(script.splitlines())} lines)")
    return path


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


def fetch_images(products, directory):
    """Download each product photo once, and report what did not arrive."""
    records = []
    for product in products:
        url = product.get("image_url")
        if not url:
            continue
        path = directory / f"{product['code']}.img"
        request = urllib.request.Request(url, headers={"user-agent": BROWSER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                path.write_bytes(response.read())
        except OSError as error:
            print(f"  IMAGE failed {product['code']}: {error}")
            continue
        records.append({"code": product["code"], "filename": path.name})
    return records


def import_images(products, database, overwrite, script_out):
    with tempfile.TemporaryDirectory(prefix="shop-images-") as temporary:
        directory = Path(temporary) / "shop-images"
        directory.mkdir()
        records = fetch_images(products, directory)
        if not records:
            print("  no images to import")
            return
        subprocess.run(["docker", "cp", str(directory), f"{ODOO_CONTAINER}:/tmp"], check=True)
        payload = [{"code": record["code"], "path": f"/tmp/shop-images/{record['filename']}"}
                   for record in records]
        script = IMAGE_TEMPLATE.format(records=json.dumps(payload), overwrite=overwrite)
        save_script(script, script_out, "the image script")
        run_in_odoo(script, database, prefixes=("IMAGE", "TOTAL"))


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dump", help="a catalogue dump .ndjson or .ndjson.gz for one source")
    parser.add_argument("--prefix", default=None,
                        help="SKU prefix; defaults to the initials of the source name")
    parser.add_argument("--database", default="odoo")
    parser.add_argument("--location", default=TARGET_LOCATION)
    parser.add_argument("--emit", type=Path, default=None,
                        help="write the payload as JSON and stop, importing nothing")
    parser.add_argument("--script-out", type=Path, default=None, metavar="PATH",
                        help="where to leave the generated odoo shell script "
                             f"(default {SCRIPT_DIR}/<source>-import.py)")
    parser.add_argument("--script-only", action="store_true",
                        help="write that script and stop, without reaching Odoo")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change, write nothing")
    parser.add_argument("--update-prices", action="store_true",
                        help="also refresh the price of products that already exist")
    parser.add_argument("--keep-taxes", action="store_true",
                        help="leave the company's default sales tax on created products")
    parser.add_argument("--net-of-vat", type=float, default=None, metavar="RATE",
                        help="divide published prices by 1+RATE (e.g. 0.20) for a VAT-registered workshop")
    parser.add_argument("--images", action="store_true",
                        help="after importing, download each product photo and set it")
    parser.add_argument("--overwrite-images", action="store_true")
    options = parser.parse_args()
    if options.overwrite_images and not options.images:
        parser.error("--overwrite-images requires --images")

    rows = read_dump(options.dump)
    source = rows[0].get("source") or "shop"
    prefix = options.prefix or "".join(part[0] for part in source.split("-") if part).upper()
    payload = build_payload(rows, prefix, options.net_of_vat)
    products = payload["products"]

    counted = [product for product in products if product["stock"] is not None]
    services = [product for product in products if product["is_service"]]
    departments = collections.Counter(product["category"] for product in products)
    print(f"{source}: {len(products)} products in {payload['currency']}, "
          f"{len(counted)} with a counted stock of {sum(p['stock'] for p in counted)} units, "
          f"{len(services)} service(s)")
    for department, count in departments.most_common():
        print(f"  {department or '(no category)'}: {count}")
    if options.net_of_vat:
        print(f"  prices divided by {1 + options.net_of_vat} for VAT")

    if options.emit:
        options.emit.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
        print(f"wrote {options.emit}")
        return

    script = IMPORT_TEMPLATE.format(
        payload=json.dumps(payload), dry_run=options.dry_run, target=options.location,
        goods=GOODS_CATEGORY, module=IMD_MODULE, update_prices=options.update_prices,
        keep_taxes=options.keep_taxes)
    save_script(script, options.script_out or SCRIPT_DIR / f"{source}-import.py",
                "the odoo shell script")
    if options.script_only:
        print("  --script-only: nothing was sent to Odoo")
        return
    print(f"{'checking' if options.dry_run else 'writing'} products into "
          f"'{options.database}', stock at {options.location} ...")
    run_in_odoo(script, options.database,
                prefixes=("CATEGORY", "CREATE", "PRICE", "EXISTS", "SKIPPED", "SET", "TOTAL"))

    if options.images and not options.dry_run:
        print("importing images ...")
        import_images(products, options.database, options.overwrite_images,
                      SCRIPT_DIR / f"{source}-images.py")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Fill a tenant's product list from the master catalogue, without the service.

`mb_catalogue_sync` reads its products over HTTP from the catalogue service, and
that service does not exist yet. This script plays its part: it reads the same
`catalogue.canonical_catalogue` view the service would serve, and calls the same
model methods the addon would call. It is a development tool, not the product -
when the service is running, this goes away and nothing in the addon changes.

Everything travels over docker exec, so nothing needs the two compose stacks to
share a network:

    catalogue-postgres  --psql-->  this script  --odoo shell-->  odoo-poc-web

Usage:

    python3 scripts/seed_from_catalogue.py --manufacturer mayco --limit 40
    python3 scripts/seed_from_catalogue.py --database odoo --sku SC74,SC15,PC-20
    python3 scripts/seed_from_catalogue.py --list-sources
"""

import argparse
import json
import subprocess
import sys

CATALOGUE_CONTAINER = "catalogue-postgres"
CATALOGUE_USER = "catalogue"
CATALOGUE_DB = "ateliera"
ODOO_CONTAINER = "odoo-poc-web"

# The standard VAT rate of the country each shop sells from, used to convert its
# published gross prices to the net figure Odoo stores.
#
# These are seed values for a development database and they are not a tax
# opinion: a real workshop's rate depends on what it is registered for, on
# reverse charge for cross-border purchases, and on reduced rates. The addon
# refuses an offer whose basis it does not know rather than guessing, and this
# script is the "someone configured it" step - so anything it writes here is
# exactly as good as this table.
VAT_BY_COUNTRY = {
    "FR": 20.0, "BE": 21.0, "NL": 21.0, "DE": 19.0, "ES": 21.0, "PT": 23.0,
    "IT": 22.0, "PL": 23.0, "SE": 25.0, "DK": 25.0, "AT": 20.0, "IE": 23.0,
    "FI": 25.5, "LT": 21.0, "LV": 21.0, "CZ": 21.0, "SK": 23.0, "HU": 27.0,
    "RO": 21.0, "GR": 24.0, "MT": 18.0, "GB": 20.0, "CH": 8.1, "NO": 25.0,
}
# Countries whose shops publish prices without tax. Everywhere else in this set
# is retail-facing and publishes gross.
VAT_EXCLUSIVE_COUNTRIES = {"US", "CA"}

PRODUCTS_SQL = """
with chosen as (
  select distinct c.canonical_product_id
    from catalogue.canonical_catalogue c
   where true {manufacturer_filter} {sku_filter}
   order by c.canonical_product_id
   limit {limit}
)
select coalesce(jsonb_agg(product), '[]'::jsonb)
  from (
    select jsonb_build_object(
             'canonical_product_id', c.canonical_product_id::text,
             'brand', min(c.brand),
             'manufacturer_sku', min(c.manufacturer_sku),
             'canonical_name', min(c.canonical_name),
             'family', min(c.family),
             'firing_range', min(c.firing_range),
             'offers', jsonb_agg(jsonb_build_object(
                 'source_id', c.source_id,
                 'supplier_name', c.supplier_name,
                 'supplier_reference', c.supplier_reference,
                 'price', c.price,
                 'currency', c.currency,
                 'vat_status', c.vat_status,
                 'package_quantity', c.package_quantity,
                 'package_unit', c.package_unit))
           ) as product
      from catalogue.canonical_catalogue c
      join chosen using (canonical_product_id)
     group by c.canonical_product_id
  ) products;
"""

SOURCES_SQL = """
select coalesce(jsonb_object_agg(id, jsonb_build_object(
         'label', coalesce(label, id),
         'country', metadata->>'country',
         'homepage_url', homepage_url)), '{}'::jsonb)
  from catalogue.sources
 where id <> 'ecb-fx';
"""


def psql(sql):
    result = subprocess.run(
        ["docker", "exec", "-i", CATALOGUE_CONTAINER, "psql",
         "-U", CATALOGUE_USER, "-d", CATALOGUE_DB, "-tAc", sql],
        capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"catalogue query failed:\n{result.stderr.strip()}")
    return json.loads(result.stdout)


def literal(value):
    """A SQL string literal. The inputs are command-line arguments."""
    return "'" + str(value).replace("'", "''") + "'"


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


def vendor_config(source_id, sources):
    """What this shop's prices mean, from the country it sells in."""
    country = (sources.get(source_id) or {}).get("country")
    if country in VAT_EXCLUSIVE_COUNTRIES:
        return {"vat_status": "exclusive", "vat_rate": 0.0}
    rate = VAT_BY_COUNTRY.get(country)
    if rate is None:
        # Left unset on purpose. The addon will refuse this vendor's prices and
        # say so, which is the correct outcome for a country nobody has decided
        # about yet - it is not the same as a zero rate.
        return {}
    return {"vat_status": "inclusive", "vat_rate": rate}


SEED_TEMPLATE = '''
import json

from odoo import fields

products = json.loads({products!r})
vendors = json.loads({vendors!r})

partners = env["res.partner"]
mapping = env["mb.catalogue.supplier"]
created_vendors = 0
for source_id, config in vendors.items():
    if mapping.search([("source_id", "=", source_id)], limit=1):
        continue
    partner = partners.search([("name", "=", config["label"]), ("is_company", "=", True)], limit=1)
    if not partner:
        partner = partners.create({{
            "name": config["label"], "is_company": True,
            "website": config.get("homepage_url") or False,
            "supplier_rank": 1,
        }})
    values = {{"source_id": source_id, "partner_id": partner.id}}
    if config.get("vat_status"):
        values["vat_status"] = config["vat_status"]
        values["vat_rate"] = config.get("vat_rate", 0.0)
    mapping.create(values)
    created_vendors += 1

service = env["mb.catalogue.service"].search([], limit=1)
if not service:
    service = env["mb.catalogue.service"].create({{
        "name": "Makersbrain catalogue (seeded locally)",
        "base_url": "http://catalogue.invalid/seeded-by-script",
    }})

template_model = env["product.template"]
summary = {{"imported": 0, "updated": 0, "offers": 0, "refused": {{}}}}
for record in products:
    template, created = template_model._mb_upsert_canonical(record)
    summary["imported" if created else "updated"] += 1
    offers, refused = template._mb_sync_supplier_offers(record.get("offers") or [])
    summary["offers"] += offers
    for reason, count in refused.items():
        summary["refused"][reason] = summary["refused"].get(reason, 0) + count

service.write({{
    "last_import_at": fields.Datetime.now(),
    "last_import_summary": service._format_summary(summary),
}})
env.cr.commit()

print("VENDORS", created_vendors, "new of", len(vendors))
print("PRODUCTS", summary["imported"], "created,", summary["updated"], "updated")
print("VARIANTS", sum(len(t.product_variant_ids) for t in template_model.search([("mb_canonical_id", "!=", False)])))
print("SUPPLIER PRICES", summary["offers"])
for reason, count in sorted(summary["refused"].items()):
    print("REFUSED", reason, count)
'''


PURGE_TEMPLATE = '''
manufacturer = {manufacturer!r}

domain = [("mb_canonical_id", "!=", False)]
if manufacturer:
    domain.append(("mb_manufacturer", "=ilike", manufacturer))
templates = env["product.template"].search(domain)
variants = templates.mapped("product_variant_ids")

# A product that anything else in the database points at is not a stray import
# any more - it is part of a stock history, an order, or a valuation, and
# deleting it would either fail loudly or take that history with it.
used_ids = set()
for model, field in [
    ("stock.move.line", "product_id"), ("stock.move", "product_id"),
    ("stock.quant", "product_id"), ("purchase.order.line", "product_id"),
    ("sale.order.line", "product_id"), ("account.move.line", "product_id"),
    ("mrp.bom.line", "product_id"),
]:
    if model not in env:
        continue
    rows = env[model].sudo().search([(field, "in", variants.ids)])
    used_ids.update(rows.mapped(field + ".product_tmpl_id").ids)

keep = env["product.template"].browse(sorted(used_ids))
drop = templates - keep

# The external ids go with them. ir.model.data enforces unique (module, name), so
# a row left pointing at a deleted product makes the next import of that same
# catalogue product fail on a name that is taken by nothing.
data = env["ir.model.data"].sudo().search([
    ("module", "=", "__mb_catalogue__"),
    ("model", "=", "product.template"),
    ("res_id", "in", drop.ids),
])

print("FOUND", len(templates), "imported products")
print("IN USE", len(keep), "kept")
print("DELETING", len(drop), "products,", len(drop.mapped("product_variant_ids")), "variants")
for template in keep[:10]:
    print("  KEPT", template.default_code or "-", template.name)

data.unlink()
drop.unlink()
env.cr.commit()
print("REMAINING", env["product.template"].search_count([("mb_canonical_id", "!=", False)]))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database", default="odoo", help="Odoo database to seed")
    parser.add_argument("--manufacturer", help="catalogue manufacturer id, e.g. mayco")
    parser.add_argument("--sku", help="comma-separated manufacturer codes")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--list-sources", action="store_true",
                        help="print the catalogue sources and their VAT basis, seed nothing")
    parser.add_argument("--purge", action="store_true",
                        help="delete previously imported products, keeping any that "
                             "stock, orders or a bill of materials refer to")
    options = parser.parse_args()

    if options.purge:
        script = PURGE_TEMPLATE.format(manufacturer=options.manufacturer)
        print(f"purging imported products from '{options.database}' ...")
        return run_in_odoo(script, options.database,
                           prefixes=("FOUND", "IN USE", "DELETING", "REMAINING", "  KEPT"))

    sources = psql(SOURCES_SQL)

    if options.list_sources:
        for source_id in sorted(sources):
            config = vendor_config(source_id, sources)
            basis = config.get("vat_status", "unconfigured - prices will be refused")
            rate = f" {config['vat_rate']}%" if config.get("vat_rate") else ""
            print(f"  {source_id:26s} {sources[source_id].get('country') or '--':3s} {basis}{rate}")
        return

    manufacturer_filter = ""
    if options.manufacturer:
        manufacturer_filter = f"and c.manufacturer_id = {literal(options.manufacturer)}"
    sku_filter = ""
    if options.sku:
        codes = ",".join(literal(code.strip().upper()) for code in options.sku.split(","))
        sku_filter = f"and upper(c.manufacturer_sku) in ({codes})"

    products = psql(PRODUCTS_SQL.format(
        manufacturer_filter=manufacturer_filter,
        sku_filter=sku_filter,
        limit=int(options.limit)))
    if not products:
        sys.exit("no canonical products matched - has the promotion been run?")

    # Only the shops that actually sell what is being imported.
    wanted = {offer["source_id"] for product in products for offer in product["offers"]}
    vendors = {
        source_id: {**sources.get(source_id, {"label": source_id}),
                    **vendor_config(source_id, sources)}
        for source_id in sorted(wanted)
    }

    script = SEED_TEMPLATE.format(
        products=json.dumps(products), vendors=json.dumps(vendors))
    print(f"seeding {len(products)} products from {len(vendors)} sources "
          f"into '{options.database}' ...")
    run_in_odoo(script, options.database,
                prefixes=("VENDORS", "PRODUCTS", "VARIANTS", "SUPPLIER", "REFUSED"))


if __name__ == "__main__":
    main()

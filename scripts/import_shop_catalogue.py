#!/usr/bin/env python3
"""Validate or stage a catalogue-ceramics scraper artifact in Odoo.

This is a transitional command-line companion to ``mb_shop_import``. It never
creates products, changes inventory, or downloads images. With no option it
validates the artifact locally and prints its normalized summary. ``--stage``
uploads it as an Odoo review batch and runs only the parse/staging step.

Examples:

    scripts/import_shop_catalogue.py emily-alarcon.ndjson.gz
    scripts/import_shop_catalogue.py emily-alarcon.ndjson.gz --emit /tmp/emily.json
    scripts/import_shop_catalogue.py emily-alarcon.ndjson.gz --stage \
        --database odoo --location "Atelier/Stock/Finished"

The inputs are scraper NDJSON/NDJSON.GZ or scraper CSV, not an official SumUp
merchant export.
"""

from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import subprocess
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "addons" / "mb_shop_import" / "models" / "adapters.py"
DEFAULT_CONTAINER = "odoo-poc-web"


def load_adapters():
    spec = importlib.util.spec_from_file_location("mb_shop_import_adapters_cli", ADAPTER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def summarize(artifact, service_categories):
    services = {name.casefold() for name in service_categories}
    categories = collections.Counter(
        (row["category_path"][0] if row["category_path"] else "")
        for row in artifact.rows
    )
    physical = [
        row for row in artifact.rows
        if not row["category_path"] or row["category_path"][0].casefold() not in services
    ]
    tracked = [row for row in physical if row["stock_is_tracked"]]
    return {
        "adapter": artifact.adapter_key,
        "source": artifact.source_key,
        "currency": artifact.currency,
        "records": len(artifact.rows),
        "services": len(artifact.rows) - len(physical),
        "tracked_physical": len(tracked),
        "tracked_units": sum(row["stock_quantity"] or 0 for row in tracked),
        "untracked_physical": len(physical) - len(tracked),
        "categories": dict(categories),
    }


def shell_program(options, container_path, source_key, prefix):
    values = {
        "path": container_path,
        "file_name": options.dump.name,
        "source_key": source_key,
        "source_name": options.source_name or source_key.replace("-", " ").title(),
        "prefix": prefix,
        "location": options.location,
        "category": options.category,
        "update_prices": options.update_prices,
        "import_images": options.images,
        "snapshot_hours": options.snapshot_max_age_hours,
        "service_categories": "\n".join(options.service_category),
        "image_hosts": "\n".join(options.image_host),
    }
    encoded = repr(json.dumps(values))
    return f"""
import base64
import json

VALUES = json.loads({encoded})
Source = env["mb.shop.source"]
Batch = env["mb.shop.import.batch"]

module = env["ir.module.module"].search([("name", "=", "mb_shop_import")], limit=1)
if module.state != "installed":
    raise SystemExit("mb_shop_import is not installed in this database")
source = Source.search([
    ("company_id", "=", env.company.id),
    ("provider_key", "=", "sumup"),
    ("source_key", "=", VALUES["source_key"]),
], limit=1)
if not source:
    source = Source.create({{
        "name": VALUES["source_name"],
        "provider_key": "sumup",
        "source_key": VALUES["source_key"],
        "sku_prefix": VALUES["prefix"],
        "service_category_names": VALUES["service_categories"],
        "allowed_image_hosts": VALUES["image_hosts"],
    }})
elif source.sku_prefix != VALUES["prefix"]:
    raise SystemExit("the existing scraper source uses another SKU prefix")

location = env["stock.location"].search([
    ("complete_name", "=", VALUES["location"]),
    ("usage", "=", "internal"),
    ("company_id", "=", env.company.id),
], limit=1)
if not location:
    raise SystemExit("the requested company stock location does not exist")
if VALUES["category"]:
    category = env["product.category"].search([
        ("complete_name", "=", VALUES["category"]),
    ], limit=1)
else:
    category = env.ref(
        "mb_ceramics_base.categ_finished_ceramics", raise_if_not_found=False
    )
if not category:
    raise SystemExit("pass --category, or install mb_ceramics_base")

with open(VALUES["path"], "rb") as handle:
    payload = base64.b64encode(handle.read())
batch = Batch.create({{
    "source_file": payload,
    "file_name": VALUES["file_name"],
    "source_id": source.id,
    "target_location_id": location.id,
    "product_category_id": category.id,
    "update_existing_prices": VALUES["update_prices"],
    "import_images": VALUES["import_images"],
    "snapshot_max_age_hours": VALUES["snapshot_hours"],
}})
batch.action_parse()
env.cr.commit()
print("STAGED", batch.id, batch.name, len(batch.line_ids), batch.state)
"""


def stage(options, artifact, prefix):
    temporary = f"/tmp/mb-shop-import-{uuid.uuid4().hex}{options.dump.suffix}"
    subprocess.run(
        ["docker", "cp", str(options.dump), f"{options.container}:{temporary}"],
        check=True,
    )
    try:
        result = subprocess.run(
            [
                "docker", "exec", "-i", options.container, "odoo", "shell",
                "-d", options.database, "--log-level=error", "--no-http",
            ],
            input=shell_program(options, temporary, artifact.source_key, prefix),
            text=True,
            capture_output=True,
        )
        if result.returncode:
            raise SystemExit(result.stderr.strip()[-2_000:] or result.stdout.strip()[-2_000:])
        staged = next((line for line in result.stdout.splitlines() if line.startswith("STAGED ")), None)
        if not staged:
            raise SystemExit("Odoo did not return a staged batch reference")
        print(staged)
        print("No products or stock were changed; open this batch in Odoo for review and validation.")
    finally:
        subprocess.run(
            ["docker", "exec", options.container, "rm", "-f", temporary],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("dump", type=Path)
    parser.add_argument("--emit", type=Path, help="write normalized rows as JSON and stop")
    parser.add_argument("--stage", action="store_true", help="create and parse an Odoo review batch")
    parser.add_argument("--database", default="odoo")
    parser.add_argument("--container", default=DEFAULT_CONTAINER)
    parser.add_argument("--source-name")
    parser.add_argument("--source-key", help="required for scraper CSV; NDJSON carries it")
    parser.add_argument("--prefix", help="uppercase SKU prefix; defaults to source initials")
    parser.add_argument("--location", help="exact complete name of the target internal location")
    parser.add_argument("--category", help="exact complete category name; ceramics default if omitted")
    parser.add_argument("--update-prices", action="store_true")
    parser.add_argument("--images", action="store_true", help="request safe image import after approval")
    parser.add_argument("--snapshot-max-age-hours", type=int, default=72)
    parser.add_argument("--service-category", action="append", default=["Cours et ateliers"])
    parser.add_argument("--image-host", action="append", default=["images.sumup.com"])
    options = parser.parse_args()
    if not options.dump.is_file():
        parser.error(f"artifact does not exist: {options.dump}")
    if options.stage and not options.location:
        parser.error("--stage requires --location")
    if options.snapshot_max_age_hours < 0:
        parser.error("--snapshot-max-age-hours cannot be negative")

    adapters = load_adapters()
    data = options.dump.read_bytes()
    try:
        detected = adapters.detect(data, options.dump.name)
        if detected == "catalogue_csv" and not options.source_key:
            parser.error("scraper CSV staging requires --source-key")
        artifact = adapters.parse(data, options.dump.name, options.source_key or "", detected)
    except adapters.AdapterError as error:
        parser.error(str(error))
    if not artifact.source_key:
        parser.error("the artifact does not identify one scraper source")
    prefix = options.prefix or "".join(
        part[0] for part in artifact.source_key.split("-") if part
    ).upper()
    if not prefix:
        parser.error("pass --prefix for a source without usable initials")

    summary = summarize(artifact, options.service_category)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if options.emit:
        options.emit.write_text(
            json.dumps(list(artifact.rows), ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        print(f"WROTE {options.emit}")
    if options.stage:
        stage(options, artifact, prefix)


if __name__ == "__main__":
    main()

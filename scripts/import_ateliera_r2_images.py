#!/usr/bin/env python3
"""Restore legacy Ateliera R2 product pictures into Odoo by retained SKU.

The R2 credentials remain inside ``atelier-api``. The old database supplies the
product UUID-to-code mapping, and Odoo receives only verified image bytes and
SKUs. Existing Odoo images are skipped unless ``--overwrite`` is explicit.
"""

import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import uuid


ROOT = Path(__file__).resolve().parents[1]
EXPORTER = ROOT / "scripts" / "ateliera_r2_image_export.mjs"
ATELIER_API = "atelier-api"
ATELIER_DB = "atelier-postgres"
ODOO = "odoo-poc-web"


def run(command, **kwargs):
	return subprocess.run(command, check=True, text=True, capture_output=True, **kwargs)


def tenant_id_for_slug(slug):
	if not slug.replace("-", "").isalnum():
		raise SystemExit("invalid tenant slug")
	sql = f"select id from control.tenants where slug='{slug}' and deleted_at is null"
	command = [
		"docker", "exec", ATELIER_DB, "sh", "-lc",
		f'PGPASSWORD="$POSTGRES_PASSWORD" psql -h /var/run/postgresql -U "$POSTGRES_USER" -d ceramics -Atc "{sql}"',
	]
	value = run(command).stdout.strip()
	try:
		return str(uuid.UUID(value))
	except ValueError as error:
		raise SystemExit(f"tenant not found or ambiguous: {slug}") from error


def product_codes(tenant_id):
	sql = (
		"select coalesce(json_object_agg(id::text,code),'{}') "
		f"from app.products where tenant_id='{tenant_id}'::uuid and deleted_at is null"
	)
	command = [
		"docker", "exec", ATELIER_DB, "sh", "-lc",
		f'PGPASSWORD="$POSTGRES_PASSWORD" psql -h /var/run/postgresql -U "$POSTGRES_USER" -d ceramics -Atc "{sql}"',
	]
	return json.loads(run(command).stdout)


def export_images(tenant_id, host_parent):
	run(["docker", "cp", str(EXPORTER), f"{ATELIER_API}:/tmp/ateliera_r2_image_export.mjs"])
	directory = f"ateliera-r2-image-export-{uuid.uuid4()}"
	container_path = f"/tmp/{directory}"
	result = run([
		"docker", "exec", ATELIER_API, "node", "--experimental-strip-types", "/tmp/ateliera_r2_image_export.mjs",
		tenant_id, container_path,
	])
	run(["docker", "cp", f"{ATELIER_API}:{container_path}", str(host_parent)])
	return host_parent / directory, json.loads(result.stdout)


def apply_to_odoo(export_directory, records, database, overwrite):
	container_directory = f"/tmp/{export_directory.name}"
	run(["docker", "cp", str(export_directory), f"{ODOO}:/tmp"])
	payload = [{**record, "path": f"{container_directory}/{record['filename']}"} for record in records]
	script = f'''\
import base64
import json

records = json.loads({json.dumps(json.dumps(payload))})
overwrite = {overwrite!r}
summary = {{"imported": 0, "existing": 0, "missing": [], "ambiguous": []}}
for record in records:
\ttemplates = env["product.template"].search([("default_code", "=", record["code"])])
\tif not templates:
\t\tsummary["missing"].append(record["code"])
\t\tcontinue
\tif len(templates) != 1:
\t\tsummary["ambiguous"].append(record["code"])
\t\tcontinue
\ttemplate = templates.ensure_one()
\tif template.image_1920 and not overwrite:
\t\tsummary["existing"] += 1
\t\tcontinue
\twith open(record["path"], "rb") as image_file:
\t\ttemplate.image_1920 = base64.b64encode(image_file.read())
\tsummary["imported"] += 1
env.cr.commit()
print("ATELIERA_R2_IMPORT", json.dumps(summary, sort_keys=True))
'''
	result = subprocess.run(
		["docker", "exec", "-i", ODOO, "odoo", "shell", "-d", database, "--no-http", "--log-level=error"],
		input=script, check=True, text=True, capture_output=True,
	)
	line = next((line for line in result.stdout.splitlines() if line.startswith("ATELIERA_R2_IMPORT ")), None)
	if not line:
		raise SystemExit(result.stderr[-2000:] or "Odoo import did not return a summary")
	return json.loads(line.removeprefix("ATELIERA_R2_IMPORT "))


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--tenant", default="cmarteau-ceramics")
	parser.add_argument("--database", default="odoo")
	parser.add_argument("--apply", action="store_true")
	parser.add_argument("--overwrite", action="store_true")
	args = parser.parse_args()
	if args.overwrite and not args.apply:
		parser.error("--overwrite requires --apply")

	tenant_id = tenant_id_for_slug(args.tenant)
	codes = product_codes(tenant_id)
	with tempfile.TemporaryDirectory(prefix="ateliera-r2-import-") as temporary:
		export_directory, export_summary = export_images(tenant_id, Path(temporary))
		manifest = json.loads((export_directory / "manifest.json").read_text())
		records = [{**image, "code": codes.get(image["productUid"])} for image in manifest["images"]]
		matched = [record for record in records if record["code"]]
		unmatched = [record["productUid"] for record in records if not record["code"]]
		print(json.dumps({**export_summary, "matched": len(matched), "unmatched": unmatched}, indent=2, sort_keys=True))
		if args.apply:
			print(json.dumps(apply_to_odoo(export_directory, matched, args.database, args.overwrite), indent=2, sort_keys=True))


if __name__ == "__main__":
	main()

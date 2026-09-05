#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root"

database=${DISPOSABLE_DB:-mb_scratch}
case "$database" in
  mb_scratch|mb_ci|mb_test) ;;
  *) echo "refusing non-disposable database: $database" >&2; exit 2 ;;
esac

predecessor=${PREDECESSOR_SHA:-632e043e166d15ceceb8846fea120e3d6e928023}
git cat-file -e "${predecessor}^{commit}"
python3 tools/check_migration_matrix.py
mkdir -p oca

fixture_root=$(mktemp -d)
cleanup() {
  rm -rf "$fixture_root"
}
trap cleanup EXIT
git archive "$predecessor" | tar -x -C "$fixture_root"

docker compose up -d db odoo
make --no-print-directory reset-test-db DISPOSABLE_DB="$database"

predecessor_modules=$(find "$fixture_root/addons" -mindepth 2 -maxdepth 2 \
  -name __manifest__.py -printf '%h\n' | xargs -n1 basename | sort | paste -sd, -)
candidate_modules=$(python3 -c \
  'import json; print(",".join(sorted({e["module"] for e in json.load(open("docs/migration-matrix.json"))})))')

docker compose run --rm -T --no-deps \
  -v "$fixture_root/addons:/tmp/predecessor-addons:ro" \
  odoo odoo --addons-path=/tmp/predecessor-addons,/usr/lib/python3/dist-packages/odoo/addons \
  -d "$database" -i "$predecessor_modules" --without-demo --stop-after-init \
  --http-port=0 --gevent-port=0 --log-level=warn
docker compose run --rm -T --no-deps \
  -v "$fixture_root/addons:/tmp/predecessor-addons:ro" \
  odoo odoo --addons-path=/tmp/predecessor-addons,/usr/lib/python3/dist-packages/odoo/addons \
  shell -d "$database" --no-http --log-level=warn < tools/upgrade_fixture.py

docker compose exec -T odoo odoo -d "$database" -u "$candidate_modules" \
  --without-demo --stop-after-init --http-port=0 --gevent-port=0 --log-level=warn
docker compose exec -T -e MB_UPGRADE_ASSERT_MODE=record odoo \
  odoo shell -d "$database" --no-http --log-level=warn < tools/upgrade_assertions.py

docker compose exec -T odoo odoo -d "$database" -u "$candidate_modules" \
  --without-demo --stop-after-init --http-port=0 --gevent-port=0 --log-level=warn
docker compose exec -T -e MB_UPGRADE_ASSERT_MODE=verify odoo \
  odoo shell -d "$database" --no-http --log-level=warn < tools/upgrade_assertions.py

echo "OK  predecessor $predecessor upgraded twice on $database"

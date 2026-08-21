#!/usr/bin/env bash
# Coordinator integration run for the English/French translation work.
#
# One clean database, French loaded before anything is installed, all addons
# installed together, followed by the runtime and catalogue validation gates.
#
#   tools/i18n_integration.sh [DB]      default DB: mb_i18n_integration
#
# It is destructive about the integration database only, and never touches an
# agent's scratch database.
set -euo pipefail

DB="${1:-mb_i18n_integration}"
CONTAINER="${ODOO_CONTAINER:-makersbrain-odoo-web}"
DB_CONTAINER="${ODOO_DB_CONTAINER:-makersbrain-odoo-db}"
CONF="/etc/odoo/odoo.conf"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

case "$DB" in
    mb_i18n_integration|mb_i18n_integration_*) ;;
    *) echo "refusing to rebuild '$DB': only mb_i18n_integration* is disposable here" >&2; exit 1 ;;
esac

mapfile -t MODULES < <(ls addons)
CSV=$(IFS=,; echo "${MODULES[*]}")
TAGS=$(printf '/%s,' "${MODULES[@]}"); TAGS=${TAGS%,}

step() { printf '\n=== %s ===\n' "$1"; }
odoo() { docker exec "$CONTAINER" odoo "$@"; }

step "Dropping $DB"
docker exec "$DB_CONTAINER" psql -U odoo -d postgres -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$DB'" >/dev/null
docker exec "$DB_CONTAINER" dropdb -U odoo --if-exists "$DB"

step "Static gates"
uv run --no-project --with ruff ruff check .
python3 tools/check_addons.py
uv run --no-project --with polib python tools/check_i18n.py --all --summary
git diff --check

step "Clean install with fr_FR loaded first"
odoo -c "$CONF" -d "$DB" -i base --stop-after-init --without-demo=all --log-level=warn
odoo i18n loadlang -c "$CONF" -d "$DB" -l fr_FR
odoo -c "$CONF" -d "$DB" -i "$CSV" --stop-after-init --without-demo=all --log-level=warn

step "Upgrade in place"
odoo -c "$CONF" -d "$DB" -u "$CSV" --stop-after-init --log-level=warn

step "Catalogue freshness: re-export every POT and assert zero drift"
# This export is the authoritative one. A per-agent scratch database holds only
# that agent's modules, and Odoo attributes an inherited term to whichever module
# is installed, so a term can appear only once the whole set is installed
# together. It is also the only step that compares the POT against the current
# source rather than against itself: tools/check_i18n.py compares the PO to the
# committed POT and cannot see that the POT itself has gone stale.
#
# Compared against a snapshot rather than with `git diff`, for two reasons: a POT
# that is not yet tracked is invisible to `git diff`, which would make this gate
# pass by looking at nothing on exactly the run that introduces the catalogues;
# and `git add -N` fixes that only by making every untracked file diff as wholly
# new. The two date headers are rewritten on every export and are not drift.
SNAPSHOT="$(mktemp -d)"
trap 'rm -rf "$SNAPSHOT"' EXIT
for module in "${MODULES[@]}"; do
    [ -f "addons/$module/i18n/$module.pot" ] || continue
    sed -E '/^"(POT-Creation-Date|PO-Revision-Date)/d' "addons/$module/i18n/$module.pot" > "$SNAPSHOT/$module.pot"
done

tools/i18n.sh pot "$DB" "${MODULES[@]}"

drift=0
for module in "${MODULES[@]}"; do
    fresh="$SNAPSHOT/$module.fresh"
    sed -E '/^"(POT-Creation-Date|PO-Revision-Date)/d' "addons/$module/i18n/$module.pot" > "$fresh"
    if [ ! -f "$SNAPSHOT/$module.pot" ]; then
        echo "POT drift: $module had no committed POT" >&2
        drift=1
    elif ! diff -q "$SNAPSHOT/$module.pot" "$fresh" >/dev/null; then
        echo "POT drift in $module:" >&2
        diff -u "$SNAPSHOT/$module.pot" "$fresh" | head -20 >&2
        drift=1
    fi
done
if [ "$drift" -ne 0 ]; then
    echo "The committed catalogues do not match the current source." >&2
    exit 1
fi
echo "no drift across ${#MODULES[@]} catalogues"

step "Import every fr.po with overwrite, then upgrade again"
tools/i18n.sh import "$DB" "${MODULES[@]}"
odoo -c "$CONF" -d "$DB" -u "$CSV" --stop-after-init --log-level=warn

step "Repository test suite"
odoo -c "$CONF" -d "$DB" -u "$CSV" --test-tags "$TAGS" \
    --stop-after-init --http-port=0 --gevent-port=0 --log-level=test

step "Bilingual sentinels"
uv run --no-project --with polib python tools/i18n_sentinels.py --check "$DB"

step "Report matrix: HTML and PDF, both languages"
uv run --no-project --with polib python tools/i18n_reports.py "$DB"

printf '\nIntegration run complete on %s\n' "$DB"

#!/usr/bin/env bash
# Translation workflow helper: one disposable work database per translation
# task, with French loaded before install and POT exported through the mounted
# addons path.
#
#   tools/i18n.sh setup   DB MODULE...   create DB, load fr_FR, install MODULEs
#   tools/i18n.sh upgrade DB MODULE...   upgrade MODULEs in DB
#   tools/i18n.sh pot     DB MODULE...   export addons/<mod>/i18n/<mod>.pot
#   tools/i18n.sh import  DB MODULE...   import addons/<mod>/i18n/fr.po (overwrite)
#   tools/i18n.sh refresh DB MODULE...   upgrade + pot, the loop you run while editing
#   tools/i18n.sh drop    DB             drop the scratch database
#
# The container runs Odoo as uid 100, so an i18n/ directory that does not exist
# yet cannot be created by the exporter through the read/write bind mount. This
# script creates it on the host first.
set -euo pipefail

CONTAINER="${ODOO_CONTAINER:-mb-odoo-web}"
DB_CONTAINER="${ODOO_DB_CONTAINER:-mb-odoo-db}"
CONF="/etc/odoo/odoo.conf"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() { sed -n '2,16p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 2; }

odoo() { docker exec "$CONTAINER" odoo "$@"; }

join_commas() { local IFS=,; echo "$*"; }

# The exporter runs as uid 100 inside the container and writes through the bind
# mount, so it needs write permission on the directory to create a catalogue and
# on the file itself to overwrite one. A fresh clone or a branch checkout leaves
# the POT owned by the host user at 0644, which is why the file mode is set here
# and not only the directory's.
ensure_i18n_dirs() {
    local module
    for module in "$@"; do
        mkdir -p "$REPO/addons/$module/i18n"
        chmod 777 "$REPO/addons/$module/i18n"
        chmod a+w "$REPO/addons/$module/i18n/$module.pot" 2>/dev/null || true
    done
}

[ $# -ge 2 ] || usage
command="$1"; shift
db="$1"; shift
modules=("$@")

case "$command" in
setup)
    [ ${#modules[@]} -gt 0 ] || usage
    # French first, so the install path imports each addon's fr.po the way a
    # real deployment does rather than leaving the catalogues unloaded.
    odoo -c "$CONF" -d "$db" -i base --stop-after-init --without-demo=all --log-level=warn
    odoo i18n loadlang -c "$CONF" -d "$db" -l fr_FR
    ensure_i18n_dirs "${modules[@]}"
    odoo -c "$CONF" -d "$db" -i "$(join_commas "${modules[@]}")" \
        --stop-after-init --without-demo=all --log-level=warn
    ;;
upgrade)
    [ ${#modules[@]} -gt 0 ] || usage
    odoo -c "$CONF" -d "$db" -u "$(join_commas "${modules[@]}")" \
        --stop-after-init --log-level=warn
    ;;
pot)
    [ ${#modules[@]} -gt 0 ] || usage
    ensure_i18n_dirs "${modules[@]}"
    odoo i18n export -c "$CONF" -d "$db" "${modules[@]}" -l pot
    ;;
import)
    [ ${#modules[@]} -gt 0 ] || usage
    for module in "${modules[@]}"; do
        [ -f "$REPO/addons/$module/i18n/fr.po" ] || { echo "no fr.po for $module" >&2; exit 1; }
        odoo i18n import -c "$CONF" -d "$db" -l fr_FR -w \
            "/mnt/mb-addons/$module/i18n/fr.po"
    done
    ;;
refresh)
    [ ${#modules[@]} -gt 0 ] || usage
    "$0" upgrade "$db" "${modules[@]}"
    "$0" pot "$db" "${modules[@]}"
    ;;
drop)
    docker exec "$DB_CONTAINER" psql -U odoo -d postgres -c \
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$db'" >/dev/null
    docker exec "$DB_CONTAINER" dropdb -U odoo --if-exists "$db"
    ;;
*)
    usage
    ;;
esac

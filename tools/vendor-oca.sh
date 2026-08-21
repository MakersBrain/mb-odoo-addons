#!/usr/bin/env bash
# Vendor the OCA modules this repository can make use of into ./oca.
#
# None of them is a dependency. `make install` and `make test` pass with ./oca
# empty, and that is checked in CI — see SPEC.md, "Licence boundary": every
# addon here is LGPL-3 and none may depend on an AGPL-3 module. What these are
# for is the workflow around the addons. `sale_order_global_stock_route` is the
# one mb_depot names: without it the depot route exists and is set on an order
# line by hand.
#
# OCA ships one repository per functional area, each holding dozens of modules.
# We want a handful, so each is cloned blobless and sparse - only the listed
# directories land on disk - and pinned to a commit rather than tracking the
# 19.0 branch head, so today's checkout is the same code as last week's.
#
# ./oca is gitignored. Run this after a fresh checkout, then restart the stack
# with `make down && make up`.
#
# To add a module: put it in the MODULES field of its repository below, bump the
# pinned commit if the module landed after it, and re-run.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dest="${here}/oca"
branch="19.0"

# repo|commit|space-separated modules
repos=(
  "stock-logistics-workflow|958bd44360721678091eb3ee5a968459c279f7c6|sale_order_global_stock_route stock_restrict_lot stock_picking_filter_lot"
  "stock-logistics-warehouse|dfa8bad1d176b4a811fd92aee9ea2f1c46802798|stock_inventory"
  "stock-logistics-reporting|bd8bab6ed4007d998a6a8895203eb98ab4065077|stock_picking_report_valued"
  "sale-workflow|98acc4b3281d59bc9c412e0b181a5b2b151efdae|sale_invoice_frequency"
)

mkdir -p "$dest"

for entry in "${repos[@]}"; do
  IFS='|' read -r repo commit modules <<<"$entry"
  path="${dest}/${repo}"

  if [ ! -d "${path}/.git" ]; then
    echo "==> cloning ${repo}"
    git clone --filter=blob:none --no-checkout --sparse \
      "https://github.com/OCA/${repo}.git" "$path"
  fi

  git -C "$path" sparse-checkout set $modules
  # The pinned commit is usually behind the branch tip, so fetch the branch and
  # then detach onto the commit.
  git -C "$path" fetch --filter=blob:none origin "$branch" --quiet
  git -C "$path" checkout --quiet "$commit"

  echo "==> ${repo} @ ${commit:0:8}"
  for m in $modules; do
    if [ -f "${path}/${m}/__manifest__.py" ]; then
      echo "      ${m}"
    else
      echo "      ${m}  MISSING - not on ${branch} at this commit" >&2
      exit 1
    fi
  done
done

echo
echo "Vendored into ${dest}."
echo "Restart Odoo (make down && make up), then install from Apps with the filter cleared."

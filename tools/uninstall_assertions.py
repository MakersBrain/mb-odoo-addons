"""Assert that the Odoo 19 module CLI fully uninstalled repository add-ons."""

import os
from typing import Any

env: Any = globals()["env"]
modules = os.environ["MB_UNINSTALL_MODULES"].split()
remaining = env["ir.module.module"].search(
    [("name", "in", modules), ("state", "!=", "uninstalled")], order="name"
)
assert not remaining, f"repository addons still active after uninstall: {remaining.mapped('name')}"
print(f"OK  uninstalled {len(modules)} repository addons")

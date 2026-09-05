"""Assert the installed repository-module inventory after the server suite.

Run through ``odoo shell``; the shell injects ``env``.
"""

import json
import os
from typing import Any

env: Any = globals()["env"]

expected = {name for name in os.environ["MB_SERVER_MODULES"].split(",") if name}
installed = set(
    env["ir.module.module"]
    .search([("name", "in", sorted(expected)), ("state", "=", "installed")])
    .mapped("name")
)
missing = sorted(expected - installed)
unexpected_count = len(installed) - len(expected)
if missing or unexpected_count:
    raise AssertionError(
        f"repository module installation mismatch: missing={missing}, "
        f"expected={len(expected)}, installed={len(installed)}"
    )

print(json.dumps({"installed_repository_modules": len(installed)}, sort_keys=True))

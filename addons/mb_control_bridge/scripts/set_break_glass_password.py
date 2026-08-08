import os
from pathlib import Path

# Odoo injects ``env`` into files executed through ``odoo shell --shell-file``.
# ruff: noqa: F821

password_file = Path(os.environ["MB_BREAK_GLASS_PASSWORD_FILE"])
password = password_file.read_text(encoding="utf-8").strip()
if len(password) < 32:
    raise RuntimeError("break-glass password is missing or too short")

administrator = env.ref("base.user_admin").sudo()
administrator.with_context(no_reset_password=True).password = password
env.cr.execute("SELECT password FROM res_users WHERE id = %s", [administrator.id])
encrypted_password = env.cr.fetchone()[0]
if not administrator._crypt_context().verify(password, encrypted_password):
    raise RuntimeError("break-glass password verification failed")
env.cr.commit()

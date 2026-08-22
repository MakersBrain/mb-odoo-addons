#!/usr/bin/env python3
"""Translation-catalogue gate for the addons in this repository.

Every installable addon must ship `i18n/<module>.pot` (the extracted English
source catalogue) and `i18n/fr.po` (the French translation of it). This script
is the repository authority on whether that pair is complete and safe. It is
deliberately stricter than `msgfmt`: Odoo's exporter does not tag entries with
the `#, python-format` flags gettext needs, so placeholder validation has to be
done here or not at all.

Run it with polib available:

    uv run --no-project --with polib python tools/check_i18n.py

Modes:

    (default)    catalogue checks over addons/*/i18n
    --source     scan Python/JS/XML for user-facing text that extraction misses
    --all        both

Scope it to one addon while working:

    ... tools/check_i18n.py --module mb_depot
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

try:
    import polib
except ImportError:  # pragma: no cover - the message is the whole point
    sys.exit(
        "polib is missing. Run this through uv:\n"
        "  uv run --no-project --with polib python tools/check_i18n.py"
    )

REPO = Path(__file__).resolve().parent.parent
ADDONS = REPO / "addons"
ALLOWLIST_PATH = REPO / "docs" / "i18n" / "i18n_allowlist.json"

# Header keys every fr.po must carry, with the value each must have. Odoo's own
# exporter writes these; a hand-written catalogue that omits Plural-Forms makes
# every plural entry unusable at runtime without failing to parse.
REQUIRED_HEADERS = {
    "Project-Id-Version": "Odoo Server 19.0",
    "Language": "fr",
    "Content-Type": "text/plain; charset=UTF-8",
    "Plural-Forms": "nplurals=2; plural=(n > 1);",
}

# printf-style conversions, including Odoo's named form `%(key)s` and the
# literal `%%`. Anything matched here must survive translation unchanged.
#
# The space flag is deliberately absent from the flag set. It is legal printf —
# `"% d" % 3` is `" 3"` — and no string in this repository uses it, while
# accepting it makes every UI label that starts "% of sales" or "% de ventes"
# look like a conversion, so no French rendering of one could ever match. A
# missed `% d` is a cosmetic defect; a false positive here blocks a correct
# translation outright.
PRINTF = re.compile(
    r"%(?:%|"
    r"(?:\((?P<key>[^)]*)\))?"
    r"(?P<flags>[-+#0]*)"
    r"(?P<width>\*|\d+)?"
    r"(?:\.(?P<prec>\*|\d+))?"
    r"(?P<len>[hlL])?"
    r"(?P<conv>[diouxXeEfFgGcrsa])"
    r")"
)
# `{}`, `{0}`, `{name}`, `{name!r:>10}` and QWeb/OWL `{{ expr }}`.
BRACE = re.compile(r"\{\{[^{}]*\}\}|\{[^{}]*\}")
TAG = re.compile(r"</?\s*([A-Za-z][-\w]*)((?:\s+[^<>]*?)?)/?>")
UNSAFE_URL = re.compile(
    r"""(?:href|src|action|xlink:href)\s*=\s*["']?\s*(javascript|data|vbscript):""", re.I
)
EVENT_ATTR = re.compile(r"\son[a-z]+\s*=", re.I)
SCRIPT_TAG = re.compile(r"<\s*(script|iframe|object|embed)\b", re.I)
# Void elements never carry a closing tag, so they must not count when the
# opening and closing multisets are compared.
VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
    "t-esc",
    "t-out",
    "t-raw",
}
HAS_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.notes: list[str] = []

    def fail(self, where: str, message: str) -> None:
        self.failures.append(f"{where}: {message}")

    def note(self, message: str) -> None:
        self.notes.append(message)


def load_allowlist() -> dict:
    if not ALLOWLIST_PATH.exists():
        return {}
    with ALLOWLIST_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def installable_addons() -> list[Path]:
    found = []
    for path in sorted(ADDONS.iterdir()):
        manifest = path / "__manifest__.py"
        if not manifest.is_file():
            continue
        try:
            data = ast.literal_eval(manifest.read_text(encoding="utf-8"))
        except (ValueError, SyntaxError):
            continue
        if isinstance(data, dict) and data.get("installable", True):
            found.append(path)
    return found


def entry_key(entry) -> tuple[str, str, str]:
    return (entry.msgctxt or "", entry.msgid, entry.msgid_plural or "")


def short(text: str, limit: int = 68) -> str:
    flat = text.replace("\n", "\\n")
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def placeholder_counts(text: str, pattern: re.Pattern) -> dict[str, int]:
    counts: dict[str, int] = {}
    for match in pattern.finditer(text):
        token = match.group(0)
        counts[token] = counts.get(token, 0) + 1
    return counts


def tag_multiset(text: str) -> tuple[dict[str, int], dict[str, int]]:
    opening: dict[str, int] = {}
    closing: dict[str, int] = {}
    for match in TAG.finditer(text):
        name = match.group(1).lower()
        raw = match.group(0)
        if name in VOID_TAGS or raw.endswith("/>"):
            continue
        target = closing if raw.startswith("</") else opening
        target[name] = target.get(name, 0) + 1
    return opening, closing


def check_markup(where: str, msgid: str, msgstr: str, report: Report) -> None:
    if "<" not in msgid and "<" not in msgstr:
        if SCRIPT_TAG.search(msgstr) or EVENT_ATTR.search(msgstr):
            report.fail(where, "translation introduces markup the source does not have")
        return

    source_open, source_close = tag_multiset(msgid)
    target_open, target_close = tag_multiset(msgstr)
    if source_open != target_open or source_close != target_close:
        report.fail(
            where,
            f"HTML tags differ: source {sorted(source_open.items())} "
            f"vs translation {sorted(target_open.items())}",
        )
    for name, count in target_open.items():
        if target_close.get(name, 0) != count and name not in VOID_TAGS:
            report.fail(where, f"unbalanced <{name}> in the translation")
    if SCRIPT_TAG.search(msgstr) and not SCRIPT_TAG.search(msgid):
        report.fail(where, "translation introduces a script/iframe/object tag")
    if EVENT_ATTR.search(msgstr) and not EVENT_ATTR.search(msgid):
        report.fail(where, "translation introduces an inline event handler attribute")
    if UNSAFE_URL.search(msgstr) and not UNSAFE_URL.search(msgid):
        report.fail(where, "translation introduces an unsafe URL scheme")


def check_pair(where: str, msgid: str, msgstr: str, report: Report, allow_identical: bool) -> None:
    if not msgstr.strip():
        report.fail(where, "empty translation")
        return

    source_printf = placeholder_counts(msgid, PRINTF)
    target_printf = placeholder_counts(msgstr, PRINTF)
    if source_printf != target_printf:
        report.fail(
            where,
            f"printf placeholders differ: source {sorted(source_printf.items())} "
            f"vs translation {sorted(target_printf.items())}",
        )
    else:
        # Positional `%s` cannot be reordered; named ones can.
        positional = [
            m.group(0) for m in PRINTF.finditer(msgid) if not m.group("key") and m.group(0) != "%%"
        ]
        if len(positional) > 1:
            translated = [
                m.group(0)
                for m in PRINTF.finditer(msgstr)
                if not m.group("key") and m.group(0) != "%%"
            ]
            if positional != translated:
                report.fail(
                    where, "positional placeholders reordered; use named placeholders instead"
                )

    source_brace = placeholder_counts(msgid, BRACE)
    target_brace = placeholder_counts(msgstr, BRACE)
    if source_brace != target_brace:
        report.fail(
            where,
            f"brace placeholders differ: source {sorted(source_brace.items())} "
            f"vs translation {sorted(target_brace.items())}",
        )

    if msgid.count("\n") != msgstr.count("\n"):
        report.fail(where, "newline structure changed")
    if msgid.startswith("\n") != msgstr.startswith("\n") or msgid.endswith("\n") != msgstr.endswith(
        "\n"
    ):
        report.fail(where, "leading/trailing newline changed")

    check_markup(where, msgid, msgstr, report)

    if msgid == msgstr and HAS_LETTER.search(msgid) and not allow_identical:
        report.fail(where, f"translation identical to source: {short(msgid)}")


def check_module(module: Path, allowlist: dict, report: Report) -> tuple[int, int]:
    name = module.name
    pot_path = module / "i18n" / f"{name}.pot"
    po_path = module / "i18n" / "fr.po"
    rel_po = po_path.relative_to(REPO)

    if not pot_path.exists():
        report.fail(str(module.relative_to(REPO)), f"missing i18n/{name}.pot")
        return (0, 0)
    if not po_path.exists():
        report.fail(str(module.relative_to(REPO)), "missing i18n/fr.po")
        return (0, 0)

    for path in (pot_path, po_path):
        try:
            path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            report.fail(str(path.relative_to(REPO)), "not valid UTF-8")
            return (0, 0)

    # `_global` covers terms whose French is identical in every addon — "ID",
    # "Journal", "Code" — which Odoo exports into each module's catalogue
    # separately. Repeating them per addon would be 29 copies of one decision.
    module_allow = allowlist.get(name, {})
    shared = allowlist.get("_global", {})
    identical_ok = set(shared.get("identical", [])) | set(module_allow.get("identical", []))
    stale_ok = set(shared.get("stale", [])) | set(module_allow.get("stale", []))

    try:
        pot = polib.pofile(str(pot_path))
        po = polib.pofile(str(po_path))
    except OSError as exc:
        report.fail(str(rel_po), f"cannot be parsed: {exc}")
        return (0, 0)

    metadata = po.metadata
    for key, expected in REQUIRED_HEADERS.items():
        actual = metadata.get(key)
        if actual is None:
            report.fail(str(rel_po), f"header {key} is missing")
        elif actual.strip() != expected:
            report.fail(str(rel_po), f"header {key} is {actual!r}, expected {expected!r}")

    pot_keys = {entry_key(e) for e in pot if not e.obsolete}
    po_by_key: dict[tuple[str, str, str], list] = {}
    for entry in po:
        if entry.obsolete:
            report.fail(str(rel_po), f"obsolete entry left in the catalogue: {short(entry.msgid)}")
            continue
        po_by_key.setdefault(entry_key(entry), []).append(entry)

    for entry_key_, entries in po_by_key.items():
        if len(entries) > 1:
            report.fail(str(rel_po), f"duplicate entry: {short(entry_key_[1])}")

    translated = 0
    for _key, entries in po_by_key.items():
        entry = entries[0]
        where = f"{rel_po}:{entry.linenum}"
        if "fuzzy" in entry.flags:
            report.fail(where, f"fuzzy entry: {short(entry.msgid)}")
            continue
        allow_identical = entry.msgid in identical_ok
        if entry.msgid_plural:
            for index in (0, 1):
                value = entry.msgstr_plural.get(index, "")
                source = entry.msgid if index == 0 else entry.msgid_plural
                if not value.strip():
                    report.fail(where, f"plural form {index} is empty: {short(source)}")
                else:
                    check_pair(where, source, value, report, allow_identical)
            if all(entry.msgstr_plural.get(i, "").strip() for i in (0, 1)):
                translated += 1
        else:
            check_pair(where, entry.msgid, entry.msgstr, report, allow_identical)
            if entry.msgstr.strip():
                translated += 1

    for missing_key in sorted(pot_keys - set(po_by_key)):
        report.fail(str(rel_po), f"POT entry absent from the catalogue: {short(missing_key[1])}")
    for stale_key in sorted(set(po_by_key) - pot_keys):
        if stale_key[1] in stale_ok:
            continue
        report.fail(str(rel_po), f"stale entry not in the POT: {short(stale_key[1])}")

    return (translated, len(pot_keys))


# --------------------------------------------------------------------------
# Source scanner
# --------------------------------------------------------------------------

# Python calls whose first positional argument reaches the user unchanged.
#
# `warning` is in the list because Odoo's onchange protocol returns
# `{"warning": {"title": ..., "message": ...}}`, and `.warning(` is how several
# of those are built. A logger call spells the same word, so the pattern rejects
# a `logger.`/`logging.` receiver: log text is for operators reading a file, is
# never translated, and flagging it trains people to ignore the scanner.
PY_USER_FACING = re.compile(
    r"\b(UserError|ValidationError|AccessError|MissingError|RedirectWarning|"
    r"warning|danger|Warning)\s*\(\s*(?P<quote>['\"])"
)
# The receiver in front of such a call, when it is a logger.
LOGGER_RECEIVER = re.compile(r"(?:^|[^\w.])(?:_?logger|logging|_log)\s*\.\s*$")
# Odoo notification helper, whose message and title are both user-facing.
PY_NOTIFY = re.compile(
    r"['\"](?:message|title)['\"]\s*:\s*(?P<quote>['\"])(?P<text>[^'\"]{4,})(?P=quote)"
)
JS_USER_FACING = re.compile(
    r"\b(?:notification\.add|this\.notification\.add|dialog\.add|alert|confirm)\s*\(\s*(?P<quote>[`'\"])"
)
JS_LABEL = re.compile(
    r"\b(?:title|label|body|message|confirmLabel|cancelLabel)\s*:\s*(?P<quote>[`'\"])(?P<text>[^`'\"]{4,})(?P=quote)"
)
PROSE = re.compile(r"^[A-ZÀ-ÖØ-Þ][\w'’,.\- ]{6,}$")
# Words that make a literal a technical token rather than prose.
TECHNICAL_HINT = re.compile(r"[_/\\{}<>$#@|]|^[a-z0-9.]+$|^\d|https?:|^[A-Z0-9_]+$")


def looks_like_prose(text: str) -> bool:
    text = text.strip()
    if len(text) < 7 or len(text) > 200:
        return False
    if TECHNICAL_HINT.search(text):
        return False
    if " " not in text:
        return False
    return bool(PROSE.match(text))


class SourceExemptions:
    """Reviewed reasons a literal is not a translation defect.

    `files` are repository-relative path prefixes whose content is data rather
    than interface — a protocol constant table, a device capability map. `texts`
    are exact literals that stay English everywhere: barcode symbology names,
    device model names, and other technical tokens that happen to read like
    prose. Both are decisions recorded in docs/i18n/i18n_allowlist.json, not a
    way to make a finding go away.
    """

    def __init__(self, module_allow: dict) -> None:
        source = module_allow.get("source", {})
        self.files = tuple(source.get("files", []))
        self.texts = set(source.get("texts", []))

    def skips(self, path: Path) -> bool:
        if not self.files:
            return False
        return str(path.relative_to(REPO)).startswith(self.files)

    def allows(self, text: str) -> bool:
        return text.strip() in self.texts


def scan_python(path: Path, report: Report, exempt: SourceExemptions) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "_(" in line or "_lt(" in line:
            continue
        match = PY_USER_FACING.search(line)
        if match and not LOGGER_RECEIVER.search(line[: match.start()]):
            report.fail(
                f"{path.relative_to(REPO)}:{number}", "user-facing message not wrapped in _()"
            )
            continue
        notify = PY_NOTIFY.search(line)
        if (
            notify
            and looks_like_prose(notify.group("text"))
            and not exempt.allows(notify.group("text"))
        ):
            report.fail(
                f"{path.relative_to(REPO)}:{number}",
                f"notification text not wrapped in _(): {short(notify.group('text'))}",
            )


def scan_javascript(path: Path, report: Report, exempt: SourceExemptions) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith(("//", "*")):
            continue
        if "_t(" in line:
            continue
        if JS_USER_FACING.search(line):
            report.fail(
                f"{path.relative_to(REPO)}:{number}", "user-facing call not wrapped in _t()"
            )
            continue
        label = JS_LABEL.search(line)
        if (
            label
            and looks_like_prose(label.group("text"))
            and not exempt.allows(label.group("text"))
        ):
            report.fail(
                f"{path.relative_to(REPO)}:{number}",
                f"UI label not wrapped in _t(): {short(label.group('text'))}",
            )


FRENCH_MARKER = re.compile(
    r"\b(?:le|la|les|des|une|un|du|de la|au|aux|est|sont|avec|pour|dans|sur|par|"
    r"nombre|quantité|référence|dépôt|facture|produit|vente|montant|cuisson)\b",
    re.IGNORECASE,
)


def scan_french_source(path: Path, report: Report) -> None:
    """French prose in source is a bug: source is English, French lives in fr.po."""
    text = path.read_text(encoding="utf-8", errors="replace")
    for number, line in enumerate(text.splitlines(), start=1):
        if (
            "é" not in line
            and "è" not in line
            and "à" not in line
            and "ç" not in line
            and "ê" not in line
        ):
            continue
        stripped = line.strip()
        if stripped.startswith(("#", "//", "*")):
            continue
        if FRENCH_MARKER.search(line):
            report.fail(
                f"{path.relative_to(REPO)}:{number}",
                f"French literal in source, move it to fr.po: {short(stripped)}",
            )


def is_scannable(path: Path) -> bool:
    """Files whose text can reach a user."""
    return "tests" not in path.parts


def scan_module_source(module: Path, allowlist: dict, report: Report) -> None:
    exempt = SourceExemptions(allowlist.get(module.name, {}))
    for path in sorted(module.rglob("*.py")):
        if not is_scannable(path) or path.name.startswith("test_") or exempt.skips(path):
            continue
        scan_python(path, report, exempt)
        scan_french_source(path, report)
    static = module / "static" / "src"
    for path in sorted(static.rglob("*.js")) if static.exists() else []:
        if exempt.skips(path):
            continue
        scan_javascript(path, report, exempt)
        scan_french_source(path, report)
    for path in sorted(module.rglob("*.xml")):
        if not is_scannable(path) or exempt.skips(path):
            continue
        scan_french_source(path, report)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--module", action="append", default=[], help="restrict to these addon names"
    )
    parser.add_argument(
        "--source",
        action="store_true",
        help="run the source scanner instead of the catalogue checks",
    )
    parser.add_argument(
        "--all", action="store_true", help="run both the catalogue checks and the source scanner"
    )
    parser.add_argument(
        "--summary", action="store_true", help="print per-addon translated/total counts"
    )
    args = parser.parse_args()

    modules = installable_addons()
    if args.module:
        wanted = set(args.module)
        modules = [m for m in modules if m.name in wanted]
        missing = wanted - {m.name for m in modules}
        if missing:
            print(f"unknown addon(s): {', '.join(sorted(missing))}", file=sys.stderr)
            return 2

    allowlist = load_allowlist()
    report = Report()
    counts: list[tuple[str, int, int]] = []

    run_catalogue = args.all or not args.source
    run_source = args.all or args.source

    for module in modules:
        if run_catalogue:
            translated, total = check_module(module, allowlist, report)
            counts.append((module.name, translated, total))
        if run_source:
            scan_module_source(module, allowlist, report)

    if args.summary and counts:
        print("addon                                    translated / entries")
        for name, translated, total in counts:
            flag = "" if translated == total else "  <-- incomplete"
            print(f"{name:<40} {translated:>6} / {total:<6}{flag}")
        print()

    for failure in report.failures:
        print(failure)

    if report.failures:
        print(f"\n{len(report.failures)} problem(s) in {len(modules)} addon(s)")
        return 1

    print(f"i18n OK: {len(modules)} addon(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

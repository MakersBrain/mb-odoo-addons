#!/usr/bin/env python3
"""Fail if the Odoo SCSS mirror holds a colour the brand package no longer has.

    python3 tools/check_brand_scss.py

`addons/mb_brand/static/src/scss/primary_variables.scss` mirrors values from
`@makersbrain/brand`'s `tokens.css` by hand, and it has to: SCSS cannot read CSS
custom properties at compile time, so there is no way to make the Odoo bundle
derive from the tokens rather than copy them. That is a real constraint and this
script does not remove it.

What it removes is the *silence*. Every hex literal in the SCSS must still exist
somewhere in the package's palette. So when a token changes upstream and nobody
carries it into Odoo, the old value stops matching anything and this fails --
instead of the backend quietly keeping last season's clay while every other
surface moves.

It is deliberately a containment check rather than a variable-by-variable
comparison. Mapping `$o-gray-500` to `--mb-sand-500` by name would be a second
mirror to maintain, with the same failure mode as the first.

What it does not catch: a value that is still in the palette but is now the
wrong token for that slot -- swapping clay-600 for clay-700 keeps both in the
palette. The comments in the SCSS name the token each value came from, and that
is what a reviewer reads.
"""

import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BRAND_ROOT = ROOT
SCSS = ROOT / "addons/mb_brand/static/src/scss/primary_variables.scss"

HEX = re.compile(r"#[0-9a-fA-F]{6}")


def resolve(subpath: str) -> pathlib.Path:
    script = f'process.stdout.write(require.resolve("@makersbrain/brand/{subpath}"))'
    try:
        out = subprocess.run(
            ["node", "-e", script],
            cwd=BRAND_ROOT, check=True, capture_output=True, text=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        print(
            f"cannot resolve @makersbrain/brand/{subpath}; "
            f"run `npm install` in {BRAND_ROOT}. Skipping.",
            file=sys.stderr,
        )
        raise SystemExit(0) from None
    return pathlib.Path(out)


# Not every colour in the mirror is ours to control. Odoo's `base-2` palette is
# copied in verbatim so Website's map-merge has something to read, and it has to
# keep Odoo's stock values -- it is the palette a user picks to get away from our
# branding. Regions between these markers are skipped.
UPSTREAM_START = re.compile(r"//\s*brand-check:\s*upstream-start\b")
UPSTREAM_END = re.compile(r"//\s*brand-check:\s*upstream-end\b")


def brand_lines(text: str):
    """Yield (line_number, line) for lines that should mirror brand tokens."""
    depth = 0
    opened_at = 0
    for number, line in enumerate(text.splitlines(), 1):
        if UPSTREAM_START.search(line):
            if depth == 0:
                opened_at = number
            depth += 1
            continue
        if UPSTREAM_END.search(line):
            if depth == 0:
                raise ValueError(
                    f"line {number}: `brand-check: upstream-end` without a matching start"
                )
            depth -= 1
            continue
        if depth == 0:
            yield number, line
    if depth:
        # An unclosed region would silently exempt the rest of the file.
        raise ValueError(
            f"line {opened_at}: `brand-check: upstream-start` is never closed"
        )


def main() -> int:
    tokens = resolve("tokens.css")
    palette = {m.lower() for m in HEX.findall(tokens.read_text())}

    try:
        candidates = list(brand_lines(SCSS.read_text()))
    except ValueError as error:
        print(f"{SCSS.relative_to(ROOT)}: {error}", file=sys.stderr)
        return 1

    stale = []
    for number, line in candidates:
        code = line.split("//", 1)[0]
        for value in HEX.findall(code):
            if value.lower() not in palette:
                stale.append((number, value, line.strip()))

    if stale:
        version = json.loads(resolve("package.json").read_text())["version"]
        print(
            f"{SCSS.relative_to(ROOT)} holds colours that are not in "
            f"@makersbrain/brand@{version}:\n",
            file=sys.stderr,
        )
        for number, value, text in stale:
            print(f"  line {number}: {value}\n    {text}", file=sys.stderr)
        print(
            "\nEither a token changed upstream and was never carried into the "
            "Odoo bundle -- update the SCSS by hand, since SCSS cannot read the "
            "tokens -- or this colour is deliberately Odoo's rather than ours, "
            "in which case wrap it in `// brand-check: upstream-start` and "
            "`// brand-check: upstream-end` and say why.",
            file=sys.stderr,
        )
        return 1

    print(
        f"{len(palette)} palette values; every brand colour in the Odoo mirror "
        f"is current ({len(candidates)} lines checked)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

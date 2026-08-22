#!/usr/bin/env python3
"""Validate the private sample ZIP and score provider-normalized results.

The script never extracts originals to disk. It decodes each image, applies
orientation, strips metadata by re-encoding in memory, and reports only sizes
and SHA-256 digests. Optional result JSON is keyed by filename and may contain
``barcode``, ``lot`` and ``product`` strings.
"""

import argparse
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path, PurePosixPath

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 15 * 1024 * 1024
MAX_DECODE_PIXELS = 50_000_000
MAX_SANITIZED_PIXELS = 12_000_000
EXPECTED = Path(__file__).parents[1] / "fixtures" / "inventory_capture_expected.json"


def sanitize(source: bytes) -> tuple[bytes, int, int, str]:
    if not source or len(source) > MAX_BYTES:
        raise ValueError("source exceeds the 15 MB bound")
    try:
        with Image.open(io.BytesIO(source)) as probe:
            if getattr(probe, "n_frames", 1) != 1:
                raise ValueError("multi-frame image")
            image_format = probe.format
            width, height = probe.size
            probe.verify()
        if width * height > MAX_DECODE_PIXELS:
            raise ValueError("source exceeds the safe decode bound")
        with Image.open(io.BytesIO(source)) as opened:
            image = ImageOps.exif_transpose(opened)
            if image.width * image.height > MAX_SANITIZED_PIXELS:
                scale = (MAX_SANITIZED_PIXELS / (image.width * image.height)) ** 0.5
                image = image.resize(
                    (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
                    Image.Resampling.LANCZOS,
                )
            output = io.BytesIO()
            if image_format in {"JPEG", "JPG"}:
                image.convert("RGB").save(output, "JPEG", quality=90, optimize=True)
                mimetype = "image/jpeg"
            elif image_format == "PNG":
                image.convert("RGBA" if "A" in image.getbands() else "RGB").save(
                    output, "PNG", optimize=True
                )
                mimetype = "image/png"
            else:
                raise ValueError("unsupported image format")
            width, height = image.size
            sanitized = output.getvalue()
            if len(sanitized) > MAX_BYTES:
                raise ValueError("sanitized image exceeds the 15 MB bound")
            return sanitized, width, height, mimetype
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError("unsafe or undecodable image") from error


def score(expected: dict, actual: dict) -> dict:
    fields = ("barcode", "lot", "product")
    totals = dict.fromkeys(fields, 0)
    correct = dict.fromkeys(fields, 0)
    for filename, wanted in expected.items():
        found = actual.get(filename, {})
        for field in fields:
            if wanted.get(field) is None:
                continue
            totals[field] += 1
            if str(found.get(field, "")).casefold() == str(wanted[field]).casefold():
                correct[field] += 1
    return {field: {"correct": correct[field], "total": totals[field]} for field in fields}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("zip_path", type=Path)
    parser.add_argument("--results", type=Path)
    args = parser.parse_args()
    expected = json.loads(EXPECTED.read_text())
    report = {"images": {}, "missing": [], "unexpected": []}
    with zipfile.ZipFile(args.zip_path) as archive:
        members = {
            PurePosixPath(info.filename).name: info
            for info in archive.infolist()
            if not info.is_dir()
            and PurePosixPath(info.filename).suffix.lower() in {".jpg", ".jpeg", ".png"}
        }
        report["missing"] = sorted(set(expected) - set(members))
        report["unexpected"] = sorted(set(members) - set(expected))
        for filename in sorted(set(expected) & set(members)):
            source = archive.read(members[filename])
            sanitized, width, height, mimetype = sanitize(source)
            report["images"][filename] = {
                "width": width,
                "height": height,
                "mimetype": mimetype,
                "received_sha256": hashlib.sha256(source).hexdigest(),
                "sanitized_sha256": hashlib.sha256(sanitized).hexdigest(),
                "sanitized_bytes": len(sanitized),
            }
    if args.results:
        report["score"] = score(expected, json.loads(args.results.read_text()))
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 1 if report["missing"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

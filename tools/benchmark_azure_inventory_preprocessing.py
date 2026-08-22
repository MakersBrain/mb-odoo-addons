#!/usr/bin/env python3
"""Compare deterministic OCR preprocessing variants on private sample photos."""

import argparse
import hashlib
import io
import json
import os
import sys
import time
import urllib.parse
import zipfile
from pathlib import Path, PurePosixPath

from benchmark_azure_inventory_capture import analyze, evaluate, result_text
from evaluate_inventory_capture import EXPECTED, MAX_BYTES, sanitize
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

VARIANTS = ("grayscale_autocontrast", "grayscale_high_contrast", "black_white")


def otsu_threshold(image: Image.Image) -> int:
    histogram = image.histogram()
    total = sum(histogram)
    weighted_total = sum(value * count for value, count in enumerate(histogram))
    background_count = 0
    background_weight = 0
    best_threshold = 127
    best_variance = -1.0
    for threshold, count in enumerate(histogram):
        background_count += count
        if not background_count:
            continue
        foreground_count = total - background_count
        if not foreground_count:
            break
        background_weight += threshold * count
        background_mean = background_weight / background_count
        foreground_mean = (weighted_total - background_weight) / foreground_count
        variance = background_count * foreground_count * (background_mean - foreground_mean) ** 2
        if variance > best_variance:
            best_variance = variance
            best_threshold = threshold
    return best_threshold


def preprocess(source: bytes, variant: str) -> tuple[bytes, str]:
    with Image.open(io.BytesIO(source)) as opened:
        grayscale = ImageOps.grayscale(opened)
        contrasted = ImageOps.autocontrast(grayscale, cutoff=1)
        if variant == "grayscale_autocontrast":
            output_image = contrasted.filter(
                ImageFilter.UnsharpMask(radius=1.2, percent=125, threshold=3)
            )
            image_format = "JPEG"
            mimetype = "image/jpeg"
        elif variant == "grayscale_high_contrast":
            output_image = (
                ImageEnhance.Contrast(contrasted)
                .enhance(1.8)
                .filter(ImageFilter.UnsharpMask(radius=1.5, percent=160, threshold=2))
            )
            image_format = "JPEG"
            mimetype = "image/jpeg"
        elif variant == "black_white":
            threshold = otsu_threshold(contrasted)
            output_image = contrasted.point(
                [0 if value <= threshold else 255 for value in range(256)], mode="L"
            )
            image_format = "PNG"
            mimetype = "image/png"
        else:
            raise ValueError(f"unknown preprocessing variant {variant}")
        output = io.BytesIO()
        if image_format == "JPEG":
            output_image.save(output, image_format, quality=92, optimize=True)
        else:
            output_image.save(output, image_format, optimize=True)
        payload = output.getvalue()
        if not payload or len(payload) > MAX_BYTES:
            raise ValueError("preprocessed image exceeds the 15 MB bound")
        return payload, mimetype


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("zip_path", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--only", action="append", required=True)
    parser.add_argument("--variant", action="append", choices=VARIANTS)
    args = parser.parse_args()

    endpoint = os.environ.get("AZURE_DOCUMENT_ENDPOINT", "").strip()
    key = os.environ.get("AZURE_DOCUMENT_KEY", "").strip()
    parsed = urllib.parse.urlsplit(endpoint)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.endswith(".cognitiveservices.azure.com")
    ):
        raise SystemExit(
            "AZURE_DOCUMENT_ENDPOINT must be an Azure Cognitive Services HTTPS endpoint"
        )
    if not key:
        raise SystemExit("AZURE_DOCUMENT_KEY is required")

    expected = json.loads(EXPECTED.read_text())
    unknown = sorted(set(args.only) - set(expected))
    if unknown:
        raise SystemExit(f"unknown sample name(s): {', '.join(unknown)}")
    variants = args.variant or list(VARIANTS)
    report = {"images": {}, "variants": variants}
    with zipfile.ZipFile(args.zip_path) as archive:
        members = {
            PurePosixPath(info.filename).name: info
            for info in archive.infolist()
            if not info.is_dir()
            and PurePosixPath(info.filename).suffix.lower() in {".jpg", ".jpeg", ".png"}
        }
        for filename in args.only:
            source = archive.read(members[filename])
            sanitized, _, _, _ = sanitize(source)
            image_report = {}
            for variant in variants:
                enhanced, mimetype = preprocess(sanitized, variant)
                started = time.monotonic()
                result, deleted = analyze(endpoint, key, enhanced, mimetype)
                content, word_count = result_text(result)
                image_report[variant] = {
                    "enhanced_sha256": hashlib.sha256(enhanced).hexdigest(),
                    "enhanced_bytes": len(enhanced),
                    "word_count": word_count,
                    "elapsed_seconds": round(time.monotonic() - started, 2),
                    "result_deleted": deleted,
                    "matches": evaluate(content, expected[filename]),
                }
                print(f"tested {filename} {variant}", file=sys.stderr)
            report["images"][filename] = image_report

    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered)
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

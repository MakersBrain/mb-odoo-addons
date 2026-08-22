#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11,<3.13"
# dependencies = [
#   "numpy>=2,<3",
#   "opencv-contrib-python-headless>=4.10,<5",
#   "pillow>=11,<13",
#   "pytesseract>=0.3.13,<0.4",
#   "zxing-cpp>=2.2,<3",
# ]
# ///
"""Experimental evaluator: isolate, rotate, and enhance barcode and lot-label regions.

The source ZIP is read without extracting its members. Sanitized images and
derived evidence crops are written only beneath the explicitly supplied output
directory. OCR output is a candidate, never an inventory mutation.
"""

import argparse
import hashlib
import io
import json
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import cv2
import numpy as np
import pytesseract
import zxingcpp
from evaluate_inventory_capture import sanitize
from PIL import Image
from pytesseract import Output

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
ROTATIONS = (0, 90, 180, 270)
MAX_LOT_REGIONS = 10
MIN_OCR_CONFIDENCE = 15.0
MARKER_RE = re.compile(r"\b(?:lot|batch|lotto|charge)\b", re.IGNORECASE)
CODE_RE = re.compile(r"(?<![A-Z0-9])(?:[A-Z]*\d[A-Z0-9._/-]*){1,}(?![A-Z0-9])", re.IGNORECASE)


@dataclass(frozen=True)
class OcrLine:
    rotation: int
    text: str
    confidence: float
    box: tuple[int, int, int, int]


def rotate(image: np.ndarray, degrees: int) -> np.ndarray:
    if degrees == 0:
        return image
    if degrees == 90:
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    if degrees == 180:
        return cv2.rotate(image, cv2.ROTATE_180)
    if degrees == 270:
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    raise ValueError(f"unsupported rotation: {degrees}")


def crop_with_margin(
    image: np.ndarray,
    box: tuple[int, int, int, int],
    horizontal: float,
    vertical: float,
) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    x, y, width, height = box
    pad_x = max(12, round(width * horizontal))
    pad_y = max(12, round(height * vertical))
    left = max(0, x - pad_x)
    top = max(0, y - pad_y)
    right = min(image.shape[1], x + width + pad_x)
    bottom = min(image.shape[0], y + height + pad_y)
    return image[top:bottom, left:right], (left, top, right - left, bottom - top)


def crop_barcode_context(
    image: np.ndarray, box: tuple[int, int, int, int], context_scale: float = 0.7
) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """Expand mainly perpendicular to barcode bars, including nearby lot text."""
    x, y, width, height = box
    long_side = max(width, height)
    if width >= height:
        pad_x, pad_y = round(width * 0.15), round(long_side * context_scale)
    else:
        pad_x, pad_y = round(long_side * context_scale), round(height * 0.15)
    left = max(0, x - max(12, pad_x))
    top = max(0, y - max(12, pad_y))
    right = min(image.shape[1], x + width + max(12, pad_x))
    bottom = min(image.shape[0], y + height + max(12, pad_y))
    return image[top:bottom, left:right], (left, top, right - left, bottom - top)


def enhance_variants(image: np.ndarray) -> dict[str, np.ndarray]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if max(gray.shape) < 1600:
        scale = min(3.0, 1600 / max(gray.shape))
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8)).apply(gray)
    blurred = cv2.GaussianBlur(clahe, (0, 0), 1.1)
    sharpened = cv2.addWeighted(clahe, 1.7, blurred, -0.7, 0)
    thresholded = cv2.adaptiveThreshold(
        clahe,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        41,
        9,
    )
    return {
        "gray": gray,
        "clahe": clahe,
        "sharpened": sharpened,
        "adaptive_threshold": thresholded,
    }


def digits(value: str) -> str:
    return "".join(character for character in value if character.isdigit())


def gs1_check_digit_valid(value: str) -> bool:
    number = digits(value)
    if len(number) not in {8, 12, 13, 14}:
        return False
    payload, check = number[:-1], int(number[-1])
    total = sum(
        int(character) * (3 if offset % 2 == 0 else 1)
        for offset, character in enumerate(reversed(payload))
    )
    return (10 - total % 10) % 10 == check


def normalized_gtin(value: str) -> str:
    number = digits(value)
    if len(number) == 13 and number.startswith("0") and gs1_check_digit_valid(number):
        return number[1:]
    return number


def point_box(position) -> tuple[int, int, int, int]:
    points = [position.top_left, position.top_right, position.bottom_right, position.bottom_left]
    xs = [int(point.x) for point in points]
    ys = [int(point.y) for point in points]
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def detect_barcodes(image: np.ndarray) -> list[dict]:
    found: dict[str, dict] = {}
    for rotation in ROTATIONS:
        oriented = rotate(image, rotation)
        for variant_name, variant in {
            "color": oriented,
            "clahe": enhance_variants(oriented)["clahe"],
        }.items():
            for result in zxingcpp.read_barcodes(variant):
                value = normalized_gtin(result.text)
                if not gs1_check_digit_valid(value):
                    continue
                candidate = {
                    "value": value,
                    "format": str(result.format).split(".")[-1],
                    "rotation": rotation,
                    "variant": variant_name,
                    "box": point_box(result.position),
                }
                found.setdefault(value, candidate)
    return list(found.values())


def ocr_lines(image: np.ndarray) -> list[OcrLine]:
    lines: list[OcrLine] = []
    for rotation in ROTATIONS:
        oriented = rotate(image, rotation)
        gray = enhance_variants(oriented)["clahe"]
        data = pytesseract.image_to_data(gray, config="--oem 3 --psm 11", output_type=Output.DICT)
        grouped: dict[tuple[int, int, int], list[int]] = {}
        for index in range(len(data["text"])):
            text = str(data["text"][index]).strip()
            try:
                confidence = float(data["conf"][index])
            except (TypeError, ValueError):
                continue
            if text and confidence >= MIN_OCR_CONFIDENCE:
                key = (
                    int(data["block_num"][index]),
                    int(data["par_num"][index]),
                    int(data["line_num"][index]),
                )
                grouped.setdefault(key, []).append(index)
        for indexes in grouped.values():
            left = min(int(data["left"][index]) for index in indexes)
            top = min(int(data["top"][index]) for index in indexes)
            right = max(int(data["left"][index]) + int(data["width"][index]) for index in indexes)
            bottom = max(int(data["top"][index]) + int(data["height"][index]) for index in indexes)
            text = " ".join(str(data["text"][index]).strip() for index in indexes)
            confidence = sum(float(data["conf"][index]) for index in indexes) / len(indexes)
            lines.append(
                OcrLine(rotation, text, confidence, (left, top, right - left, bottom - top))
            )
    return lines


def ocr_orientation(image: np.ndarray) -> tuple[np.ndarray, dict]:
    attempts: list[dict[str, Any]] = []
    for degrees in ROTATIONS:
        candidate = rotate(image, degrees)
        gray = enhance_variants(candidate)["clahe"]
        data = pytesseract.image_to_data(gray, config="--oem 3 --psm 6", output_type=Output.DICT)
        words = []
        score = 0.0
        for text, raw_confidence in zip(data["text"], data["conf"], strict=True):
            text = str(text).strip()
            try:
                confidence = float(raw_confidence)
            except (TypeError, ValueError):
                continue
            if text and confidence > 0:
                words.append(text)
                score += len(text) * confidence
        rendered = " ".join(words)
        if MARKER_RE.search(rendered):
            score += 1000
        attempts.append({"degrees": degrees, "text": rendered, "score": round(score, 2)})
    best = max(attempts, key=lambda item: item["score"])
    return rotate(image, best["degrees"]), {
        "selected_degrees": best["degrees"],
        "attempts": attempts,
    }


def candidate_codes(text: str, barcodes: set[str]) -> list[str]:
    values = []
    for match in CODE_RE.finditer(text):
        value = match.group(0).strip("._/-")
        compact = re.sub(r"[^A-Z0-9]", "", value.upper())
        digit_count = sum(character.isdigit() for character in compact)
        if not (4 <= len(compact) <= 16 and digit_count >= 4):
            continue
        if compact in barcodes or (len(compact) >= 8 and gs1_check_digit_valid(compact)):
            continue
        values.append(compact)
    return list(dict.fromkeys(values))


def score_line(line: OcrLine, codes: list[str]) -> float:
    score = min(2.0, line.confidence / 50)
    if MARKER_RE.search(line.text):
        score += 5
    for code in codes:
        score += 2 if 6 <= len(code) <= 10 else 0.5
    return score


def propose_lot_regions(image: np.ndarray, barcodes: list[dict]) -> list[dict]:
    barcode_values = {candidate["value"] for candidate in barcodes}
    proposals = [
        {
            "source": "barcode_context",
            "rotation": candidate["rotation"],
            "ocr_text": "",
            "ocr_confidence": 0.0,
            "codes": [],
            "score": 4.0,
            "box": candidate["box"],
        }
        for candidate in barcodes
    ]
    for line in ocr_lines(image):
        codes = candidate_codes(line.text, barcode_values)
        if not codes and not MARKER_RE.search(line.text):
            continue
        proposals.append(
            {
                "source": "ocr_line",
                "rotation": line.rotation,
                "ocr_text": line.text,
                "ocr_confidence": round(line.confidence / 100, 3),
                "codes": codes,
                "score": round(score_line(line, codes), 3),
                "box": line.box,
            }
        )
    proposals.sort(key=lambda item: item["score"], reverse=True)
    deduplicated = []
    seen = set()
    for proposal in proposals:
        key = (proposal["rotation"], tuple(proposal["codes"]), proposal["ocr_text"].casefold())
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(proposal)
        if len(deduplicated) == MAX_LOT_REGIONS:
            break
    return deduplicated


def safe_stem(filename: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).stem)


def write_image(path: Path, image: np.ndarray) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    success, encoded = cv2.imencode(".png", image)
    if not success:
        raise RuntimeError(f"could not encode {path.name}")
    payload = encoded.tobytes()
    path.write_bytes(payload)
    return {
        "path": str(path),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "width": int(image.shape[1]),
        "height": int(image.shape[0]),
    }


def extract_crop_codes(
    variants: dict[str, np.ndarray], barcodes: set[str]
) -> tuple[list[str], list[dict]]:
    values = []
    attempts: list[dict[str, Any]] = []
    for variant_name, variant in variants.items():
        for page_segmentation in (6, 11):
            text = pytesseract.image_to_string(
                variant, config=f"--oem 3 --psm {page_segmentation}"
            ).strip()
            codes = candidate_codes(text, barcodes)
            values.extend(codes)
            attempts.append(
                {"variant": variant_name, "psm": page_segmentation, "text": text, "codes": codes}
            )
    return list(dict.fromkeys(values)), attempts


def process_image(image: np.ndarray, filename: str, output_directory: Path) -> dict:
    stem = safe_stem(filename)
    barcodes = detect_barcodes(image)
    barcode_values = {candidate["value"] for candidate in barcodes}
    for index, candidate in enumerate(barcodes, start=1):
        oriented = rotate(image, candidate["rotation"])
        crop, expanded_box = crop_barcode_context(oriented, tuple(candidate["box"]), 0.35)
        candidate["expanded_box"] = expanded_box
        candidate["evidence"] = write_image(
            output_directory / stem / f"barcode-{index:02d}-original.png", crop
        )
        candidate["variants"] = {
            name: write_image(output_directory / stem / f"barcode-{index:02d}-{name}.png", variant)
            for name, variant in enhance_variants(crop).items()
        }

    lot_regions = propose_lot_regions(image, barcodes)
    for index, proposal in enumerate(lot_regions, start=1):
        oriented = rotate(image, proposal["rotation"])
        if proposal["source"] == "barcode_context":
            crop, expanded_box = crop_barcode_context(oriented, tuple(proposal["box"]))
        else:
            crop, expanded_box = crop_with_margin(oriented, tuple(proposal["box"]), 0.45, 2.5)
        proposal["expanded_box"] = expanded_box
        proposal["evidence"] = write_image(
            output_directory / stem / f"lot-{index:02d}-original.png", crop
        )
        normalized, orientation = ocr_orientation(crop)
        proposal["orientation"] = orientation
        proposal["normalized_evidence"] = write_image(
            output_directory / stem / f"lot-{index:02d}-normalized.png", normalized
        )
        variants = enhance_variants(normalized)
        proposal["variants"] = {
            name: write_image(output_directory / stem / f"lot-{index:02d}-{name}.png", variant)
            for name, variant in variants.items()
        }
        proposal["extracted_codes"], proposal["ocr_attempts"] = extract_crop_codes(
            variants, barcode_values
        )
    return {"barcodes": barcodes, "lot_regions": lot_regions}


def exact_score(report: dict, expected: dict) -> dict:
    totals = {"barcode": 0, "lot_candidate": 0}
    matched = {"barcode": 0, "lot_candidate": 0}
    for filename, result in report["images"].items():
        wanted = expected.get(filename, {})
        barcode = wanted.get("barcode")
        if barcode:
            totals["barcode"] += 1
            values = {item["value"] for item in result["barcodes"]}
            matched["barcode"] += barcode in values
        lot = wanted.get("lot")
        if lot:
            totals["lot_candidate"] += 1
            values = {
                code
                for region in result["lot_regions"]
                for code in [*region["codes"], *region["extracted_codes"]]
            }
            matched["lot_candidate"] += lot in values
    return {field: {"matched": matched[field], "expected": totals[field]} for field in totals}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("zip_path", type=Path)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expected", type=Path)
    parser.add_argument("--only", action="append")
    args = parser.parse_args()

    if shutil.which("tesseract") is None:
        raise SystemExit("tesseract is required on PATH")
    output_directory = args.output_directory.resolve()
    report_path = args.report.resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"images": {}, "output_directory": str(output_directory)}
    selected = set(args.only or [])
    with zipfile.ZipFile(args.zip_path) as archive:
        members = [
            info
            for info in archive.infolist()
            if not info.is_dir()
            and PurePosixPath(info.filename).suffix.lower() in IMAGE_SUFFIXES
            and (not selected or PurePosixPath(info.filename).name in selected)
        ]
        if selected:
            missing = selected - {PurePosixPath(info.filename).name for info in members}
            if missing:
                raise SystemExit(f"missing selected images: {', '.join(sorted(missing))}")
        for info in sorted(members, key=lambda item: item.filename):
            filename = PurePosixPath(info.filename).name
            sanitized, width, height, _ = sanitize(archive.read(info))
            pil_image = Image.open(io.BytesIO(sanitized)).convert("RGB")
            image = cv2.cvtColor(np.asarray(pil_image), cv2.COLOR_RGB2BGR)
            result = process_image(image, filename, output_directory)
            result.update(
                {
                    "sanitized_sha256": hashlib.sha256(sanitized).hexdigest(),
                    "width": width,
                    "height": height,
                }
            )
            report["images"][filename] = result
            print(
                f"processed {filename}: {len(result['barcodes'])} barcode(s), "
                f"{len(result['lot_regions'])} lot region(s)",
                file=sys.stderr,
            )
    if args.expected:
        report["score"] = exact_score(report, json.loads(args.expected.read_text()))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

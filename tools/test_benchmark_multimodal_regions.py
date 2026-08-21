from benchmark_multimodal_regions import region_priority, select_crop_paths


def region(source, score, path, text=""):
    return {
        "source": source,
        "score": score,
        "ocr_text": text,
        "ocr_attempts": [],
        "normalized_evidence": {"path": path},
    }


def test_marker_beats_barcode_context_and_noise():
    image = {
        "lot_regions": [
            region("ocr_line", 9, "/tmp/noise.png"),
            region("barcode_context", 4, "/tmp/barcode.png"),
            region("ocr_line", 2, "/tmp/lot.png", "Lot# 1234"),
        ]
    }
    assert select_crop_paths(image) == [
        __import__("pathlib").Path("/tmp/lot.png"),
        __import__("pathlib").Path("/tmp/barcode.png"),
    ]


def test_region_priority_recognizes_lot_marker_in_crop_ocr():
    candidate = region("ocr_line", 1, "/tmp/a.png")
    candidate["ocr_attempts"] = [{"text": "LOT # A001"}]
    assert region_priority(candidate)[0] == 2

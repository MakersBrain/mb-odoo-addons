import pytest

from benchmark_upcitemdb_lookup import (
    LookupCache,
    candidate_matches,
    chunks,
    comparison_gtin,
    gs1_check_digit_valid,
    normalize_item,
)


def test_gtin_validation_and_comparison_padding():
    assert gs1_check_digit_valid("097539118054")
    assert comparison_gtin("097539118054") == "00097539118054"
    assert comparison_gtin("0097539118054") == "00097539118054"
    with pytest.raises(ValueError):
        comparison_gtin("097539118055")


def test_trial_batches_contain_at_most_two_identifiers():
    assert chunks(["1", "2", "3", "4", "5"], 2) == [["1", "2"], ["3", "4"], ["5"]]


def test_normalize_item_rejects_a_different_identifier():
    with pytest.raises(ValueError):
        normalize_item(
            {"upc": "039672394025", "title": "Wrong product"},
            "097539118054",
            "2026-08-11T00:00:00+00:00",
        )


def test_normalize_and_score_complete_product():
    candidate = normalize_item(
        {
            "ean": "0039672354340",
            "upc": "039672354340",
            "title": "AMACO Potter's Choice PC-33 Iron Lustre Pint",
            "brand": "AMACO",
            "model": "PC-33",
            "category": "Ceramic glaze",
            "elid": "123",
        },
        "039672354340",
        "2026-08-11T00:00:00+00:00",
    )
    assert candidate["manufacturer_sku"] == "PC-33"
    assert candidate["source_record_id"] == "00039672354340"
    assert candidate_matches(
        candidate,
        {"barcode": "039672354340", "product": "AMACO PC-33 Iron Lustre"},
    ) == {"exact_identifier": True, "complete_expected_terms": True}


def test_cache_positive_negative_expiry_and_upsert(tmp_path):
    cache = LookupCache(tmp_path / "lookup.sqlite3")
    candidate = {
        "identifier": "039672354340",
        "identifier_type": "GTIN-12",
        "brand": "AMACO",
        "manufacturer_sku": "PC-33",
        "name": "Iron Lustre",
        "pack": "Pint",
        "category": "Glaze",
        "source_record_id": "123",
        "provider": "upcitemdb",
        "retrieved_at": "2026-08-11T00:00:00+00:00",
    }
    try:
        cache.put("039672354340", candidate, ttl_seconds=100, now=1_000)
        assert cache.get("039672354340", now=1_050)["candidate"] == candidate
        assert cache.get("039672354340", now=1_100) is None

        cache.put("039672354340", None, ttl_seconds=20, now=2_000)
        assert cache.get("039672354340", now=2_010)["status"] == "not_found"

        cache.put("039672354340", candidate, ttl_seconds=50, now=3_000)
        assert cache.get("039672354340", now=3_001)["status"] == "found"
    finally:
        cache.close()

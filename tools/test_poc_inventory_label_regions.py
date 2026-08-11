from poc_inventory_label_regions import candidate_codes, gs1_check_digit_valid, normalized_gtin


def test_gs1_check_digit_validation():
    assert gs1_check_digit_valid("097539118054")
    assert gs1_check_digit_valid("0039672394025")
    assert not gs1_check_digit_valid("097539118055")


def test_normalized_gtin_removes_upc_ean_padding():
    assert normalized_gtin("0 97539 11805 4") == "097539118054"


def test_candidate_codes_rejects_known_barcodes():
    assert candidate_codes("LOT# 24111042", {"097539118054"}) == ["24111042"]
    assert candidate_codes("097539118054", {"097539118054"}) == []


def test_candidate_codes_keeps_leading_zeroes_and_secondary_codes():
    assert candidate_codes("0507625 0704", set()) == ["0507625", "0704"]

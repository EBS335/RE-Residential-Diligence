"""
Tests for modules/rent_stab_registry.py — ground-truth rent-stabilized
building lookup (Site Finder tab improvements: exact BBL match for the
majority of the bundled NYC RGB list, normalized-address fallback for
rows lacking BLOCK/LOT, including the "1" vs "One" case called out
explicitly in the request).

Uses a small synthetic in-memory workbook fixture (not the full bundled
49k-row file) for test speed and determinism.
"""

import openpyxl
import pytest

from modules.rent_stab_registry import (
    _Registry,
    check_rent_stabilized,
    normalize_street,
    split_address,
    _parse_building_no_range,
    _word_to_number,
    _ordinal_word_to_digit_str,
)
import modules.rent_stab_registry as rsr


_HEADER = ["BUILDING_NO", "STREET", "BOROUGH", "ZIP", "BLOCK", "LOT", "COUNTY",
           "CITY", "STATUS1", "STATUS2", "STATUS3", "LATITUDE", "LONGITUDE"]


def _build_workbook(rows, tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "All"
    ws.append(_HEADER)
    for row in rows:
        ws.append(row)
    path = tmp_path / "synthetic.xlsx"
    wb.save(path)
    return str(path)


@pytest.fixture
def loaded_registry(tmp_path, monkeypatch):
    rows = [
        # Exact-BBL row
        (246, "10th Avenue", "Manhattan", 10001, 722, 3, 62, "NEW YORK", "MULTIPLE DWELLING A", None, None, 40.75, -74.0),
        # No block/lot -> address-fallback row, plain digit building number
        (43, "West 27th Street", "Manhattan", 10001, None, None, 62, "NEW YORK", "MULTIPLE DWELLING A", None, None, 40.75, -74.0),
        # No block/lot -> address-fallback row, low building number for word-number test
        (1, "Main Street", "Brooklyn", 11201, None, None, 61, "BROOKLYN", "MULTIPLE DWELLING B", "421-A (1-15)", None, 40.69, -73.99),
        # No block/lot -> range building number
        ("303 TO 309", "Elm Street", "Bronx", 10451, None, None, 60, "BRONX", "MULTIPLE DWELLING A", "J-51", None, 40.82, -73.91),
    ]
    path = _build_workbook(rows, tmp_path)
    reg = _Registry()
    reg.load(path)
    monkeypatch.setattr(rsr, "_registry", reg)
    return reg


# ── Loader / registry construction ──────────────────────────────────────────

def test_loader_builds_bbl_and_address_indexes(loaded_registry):
    assert loaded_registry.load_error is None
    assert loaded_registry.loaded is True
    assert len(loaded_registry.bbl_index) == 1
    assert len(loaded_registry.address_index) == 3  # 3 rows lacking block/lot


def test_loader_missing_file_reports_error_never_raises(tmp_path):
    reg = _Registry()
    reg.load(str(tmp_path / "does_not_exist.xlsx"))
    assert reg.load_error is not None
    assert reg.loaded is True


# ── check_rent_stabilized: exact BBL path ───────────────────────────────────

def test_exact_bbl_match(loaded_registry):
    result = check_rent_stabilized("1", 722, 3, "246 10th Avenue")
    assert result["status"] == "confirmed"
    assert result["match_type"] == "bbl"
    assert "MULTIPLE DWELLING A" in result["notes"]


def test_bbl_no_match_falls_through_to_not_found(loaded_registry):
    result = check_rent_stabilized("1", 999, 999, "1 Nonexistent Ave")
    assert result["status"] == "not_found"
    assert result["match_type"] is None


# ── check_rent_stabilized: address fallback ─────────────────────────────────

def test_address_fallback_plain_number(loaded_registry):
    result = check_rent_stabilized("1", None, None, "43 West 27th Street")
    assert result["status"] == "confirmed"
    assert result["match_type"] == "address"


def test_word_number_vs_digit_number(loaded_registry):
    # This is the exact case called out in the request: "1" in the source
    # list must match a query address spelled "One".
    # Source list has building_no=1 ("Main Street", Brooklyn). Query with
    # the spelled-out word "One" instead of the digit "1".
    result = check_rent_stabilized("3", None, None, "One Main Street")
    assert result["status"] == "confirmed"
    assert result["match_type"] == "address"
    assert "421-A (1-15)" in result["notes"]


def test_address_fallback_range_building_number(loaded_registry):
    result = check_rent_stabilized("2", None, None, "305 Elm Street")
    assert result["status"] == "confirmed"
    assert "J-51" in result["notes"]


def test_address_fallback_outside_range_no_match(loaded_registry):
    result = check_rent_stabilized("2", None, None, "400 Elm Street")
    assert result["status"] == "not_found"


def test_address_fallback_wrong_borough_no_match(loaded_registry):
    # Same street/number as the Brooklyn "Main Street" row, but queried
    # against Manhattan — must not cross-match.
    result = check_rent_stabilized("1", None, None, "1 Main Street")
    assert result["status"] == "not_found"


# ── Normalization helpers ───────────────────────────────────────────────────

def test_normalize_street_expands_suffix_and_directional():
    assert normalize_street("W 42nd St") == "west 42nd street"
    assert normalize_street("10th Ave") == "10th avenue"


def test_normalize_street_ordinal_word_to_digit():
    assert normalize_street("First Avenue") == "1st avenue"
    assert normalize_street("Twenty-First Street") == "21st street"


def test_split_address_digit_and_word():
    assert split_address("123 Main St") == ("123", "Main St")
    assert split_address("One Main St") == ("One", "Main St")


def test_word_to_number():
    assert _word_to_number("one") == 1
    assert _word_to_number("twenty") == 20
    assert _word_to_number("twenty-one") == 21
    assert _word_to_number("notanumber") is None


def test_ordinal_word_to_digit_str():
    assert _ordinal_word_to_digit_str("first") == "1st"
    assert _ordinal_word_to_digit_str("second") == "2nd"
    assert _ordinal_word_to_digit_str("third") == "3rd"
    assert _ordinal_word_to_digit_str("eleventh") == "11th"
    assert _ordinal_word_to_digit_str("twenty-first") == "21st"
    assert _ordinal_word_to_digit_str("notordinal") is None


def test_parse_building_no_range():
    assert _parse_building_no_range("303 TO 309") == (303, 309)
    assert _parse_building_no_range(123) == (123, 123)
    assert _parse_building_no_range("123") == (123, 123)
    assert _parse_building_no_range("87-15") is None  # opaque, not numeric
    assert _parse_building_no_range(None) is None


# ── check_rent_stabilized never raises ──────────────────────────────────────

def test_check_rent_stabilized_never_raises_on_garbage_input(loaded_registry):
    result = check_rent_stabilized(None, "not-a-number", object(), None)
    assert result["status"] in ("not_found", "unavailable")
    assert result["error"] is None or isinstance(result["error"], str)

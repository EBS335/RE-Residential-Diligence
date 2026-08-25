"""
Tests for modules/property_search.py — the `lot_type` (corner/mid-block)
field extraction, and `fetch_properties_by_bbls()` (Batch 0 of the
Site Finder Finding/Sourcing/Organizing/Viewing feature set — a new
BBL-list fetch primitive shared by "bring your own list", owner-portfolio
expansion, and "more like this").
"""

from unittest.mock import patch

from modules.property_search import _normalize_row, fetch_properties_by_bbls


def _raw_row(**overrides):
    base = {
        "bbl": "1000010001", "borough": "MN", "block": "1", "lot": "1",
        "address": "123 MAIN ST", "zipcode": "10001", "cd": "101",
        "zonedist1": "R6", "landuse": "02", "bldgclass": "C1",
        "lotarea": "5000", "bldgarea": "10000", "yearbuilt": "1930",
        "numfloors": "5", "unitsres": "10", "unitstotal": "10",
        "builtfar": "2.0", "residfar": "3.0", "commfar": "0",
        "assessland": "100000", "assesstot": "300000",
        "exemptland": "0", "exempttot": "0",
        "latitude": "40.7", "longitude": "-74.0",
    }
    base.update(overrides)
    return base


def test_lot_type_corner():
    row = _normalize_row(_raw_row(lottype="1"))
    assert row["lot_type"] == "Corner"


def test_lot_type_through():
    row = _normalize_row(_raw_row(lottype="2"))
    assert row["lot_type"] == "Through"


def test_lot_type_interior():
    row = _normalize_row(_raw_row(lottype="3"))
    assert row["lot_type"] == "Interior"


def test_lot_type_other():
    row = _normalize_row(_raw_row(lottype="4"))
    assert row["lot_type"] == "Other"


def test_lot_type_inside_condo():
    row = _normalize_row(_raw_row(lottype="5"))
    assert row["lot_type"] == "Inside (Condo)"


def test_lot_type_missing_defaults_to_dash():
    row = _normalize_row(_raw_row(lottype=None))
    assert row["lot_type"] == "—"


def test_lot_type_unrecognized_code_degrades_gracefully():
    row = _normalize_row(_raw_row(lottype="9"))
    assert row["lot_type"] == "9"  # falls back to the raw code, doesn't raise


# ── fetch_properties_by_bbls() ──────────────────────────────────────────────

def test_fetch_properties_by_bbls_empty_list_returns_empty_no_fetch():
    with patch("modules.property_search._get_page") as mock_get:
        rows, status = fetch_properties_by_bbls([])
    assert rows == []
    assert status["total_fetched"] == 0
    assert status["error"] is None
    mock_get.assert_not_called()


def test_fetch_properties_by_bbls_dedups_and_sanitizes_malformed_input():
    seen_where = {}

    def _fake_get_page(where_clause, offset, limit):
        seen_where["clause"] = where_clause
        return [_raw_row(bbl="1000010001")]

    with patch("modules.property_search._get_page", side_effect=_fake_get_page):
        rows, status = fetch_properties_by_bbls(["1000010001", "1000010001", "BBL 1000010001", None, ""])

    assert status["error"] is None
    assert status["total_fetched"] == 1
    assert rows[0]["bbl"] == "1000010001"
    # Only one distinct sanitized BBL should have reached the $where clause.
    assert seen_where["clause"].count("1000010001") == 1


def test_fetch_properties_by_bbls_mocked_returns_normalized_rows():
    with patch("modules.property_search._get_page", return_value=[_raw_row(bbl="2000020002", address="1 A AVE")]):
        rows, status = fetch_properties_by_bbls(["2000020002"])
    assert len(rows) == 1
    assert rows[0]["bbl"] == "2000020002"
    assert rows[0]["address"]  # normalized (title-cased) but present
    assert status["total_fetched"] == 1
    assert status["truncated"] is False


def test_fetch_properties_by_bbls_propagates_fetch_errors_without_raising():
    with patch("modules.property_search._get_page", side_effect=RuntimeError("boom")):
        rows, status = fetch_properties_by_bbls(["1000010001"])
    assert rows == []
    assert status["error"] == "boom"

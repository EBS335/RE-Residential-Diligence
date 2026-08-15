"""
Tests for modules/property_search.py — currently just the `lot_type`
(corner/mid-block) field extraction added for the Site Finder tab
improvements (reuses modules/zola_fetcher.LOT_TYPE_LABELS rather than
duplicating the mapping).
"""

from modules.property_search import _normalize_row


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

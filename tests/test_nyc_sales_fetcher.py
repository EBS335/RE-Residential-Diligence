from unittest.mock import patch, MagicMock

import requests

from modules import nyc_sales_fetcher as sf


def _fake_response(json_data, ok=True):
    r = MagicMock()
    if ok:
        r.raise_for_status = lambda: None
    else:
        r.raise_for_status = MagicMock(side_effect=requests.HTTPError("error"))
    r.json = lambda: json_data
    r.ok = ok
    return r


_ROW = {
    "address": "123 Test St", "sale_price": "3,000,000", "gross_sq_ft": "10,000",
    "sale_date": "2024-05-01T00:00:00.000", "building_class_category": "07 RENTALS",
    "zip_code": "11201", "borough": "3", "block": "123", "lot": "45",
    "residential_units": "10", "commercial_units": "0", "total_units": "10",
    "latitude": "40.69", "longitude": "-73.99",
}


def test_fetch_nyc_sales_parses_total_units_and_price_per_unit():
    with patch.object(sf.requests, "get", return_value=_fake_response([_ROW])):
        listings, status = sf.fetch_nyc_sales(40.69, -73.99, 0.25, zip_code="11201")
    assert status == "live"
    assert len(listings) == 1
    row = listings[0]
    assert row["total_units"] == 10
    assert row["price_per_unit"] == 300_000.0
    assert row["price_psf"] == 300.0


def test_fetch_nyc_sales_no_units_field_price_per_unit_none():
    row = dict(_ROW)
    row["total_units"] = "0"
    with patch.object(sf.requests, "get", return_value=_fake_response([row])):
        listings, _ = sf.fetch_nyc_sales(40.69, -73.99, 0.25, zip_code="11201")
    assert listings[0]["total_units"] is None
    assert listings[0]["price_per_unit"] is None


def test_fetch_nyc_sales_degrades_through_geo_then_base_then_minimal():
    # First two calls (geo select, then base+units select) raise HTTPError;
    # the third (minimal select, no units/geo columns) succeeds — the
    # 3-tier fallback cascade must not raise and must still return data,
    # just without total_units/price_per_unit.
    responses = [
        _fake_response(None, ok=False),
        _fake_response(None, ok=False),
        _fake_response([{k: v for k, v in _ROW.items()
                          if k not in ("residential_units", "commercial_units",
                                       "total_units", "latitude", "longitude")}]),
    ]
    with patch.object(sf.requests, "get", side_effect=responses):
        listings, status = sf.fetch_nyc_sales(40.69, -73.99, 0.25, zip_code="11201")
    assert status == "live"
    assert len(listings) == 1
    assert listings[0]["total_units"] is None
    assert listings[0]["price_per_unit"] is None
    assert listings[0]["distance_miles"] is None


def test_fetch_nyc_sales_no_filter_returns_empty():
    listings, status = sf.fetch_nyc_sales(40.69, -73.99, 0.25)
    assert listings == []
    assert status == "no_filter"


def test_fetch_nyc_sales_total_failure_never_raises():
    with patch.object(sf.requests, "get", side_effect=Exception("boom")):
        listings, status = sf.fetch_nyc_sales(40.69, -73.99, 0.25, zip_code="11201")
    assert listings == []
    assert status.startswith("error")

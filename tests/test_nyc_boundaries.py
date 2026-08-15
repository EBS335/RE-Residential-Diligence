"""
Tests for modules/nyc_boundaries.py — the Site Finder map "search extent"
boundary fetcher (borough/ZIP GeoJSON, client-side filtered since the
exact live column names couldn't be confirmed from this sandbox).
"""

from unittest.mock import patch, MagicMock

import requests

from modules import nyc_boundaries as nb


def _fake_response(json_data, ok=True):
    r = MagicMock()
    if ok:
        r.raise_for_status = lambda: None
    else:
        r.raise_for_status = MagicMock(side_effect=requests.HTTPError("error"))
    r.json = lambda: json_data
    return r


_BOROUGH_FC = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "properties": {"boro_name": "Manhattan"}, "geometry": {"type": "Polygon", "coordinates": []}},
        {"type": "Feature", "properties": {"boro_name": "Brooklyn"}, "geometry": {"type": "Polygon", "coordinates": []}},
        {"type": "Feature", "properties": {"boro_name": "Queens"}, "geometry": {"type": "Polygon", "coordinates": []}},
    ],
}

_ZIP_FC = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "properties": {"modzcta": "10001"}, "geometry": {"type": "Polygon", "coordinates": []}},
        {"type": "Feature", "properties": {"modzcta": "11201"}, "geometry": {"type": "Polygon", "coordinates": []}},
    ],
}


# ── fetch_borough_boundaries ─────────────────────────────────────────────────

def test_borough_single_match():
    with patch.object(nb.requests, "get", return_value=_fake_response(_BOROUGH_FC)):
        geo, ok = nb.fetch_borough_boundaries(["Manhattan"])
    assert ok is True
    assert geo is not None
    assert len(geo["features"]) == 1
    assert geo["features"][0]["properties"]["boro_name"] == "Manhattan"


def test_borough_multiple_match():
    with patch.object(nb.requests, "get", return_value=_fake_response(_BOROUGH_FC)):
        geo, ok = nb.fetch_borough_boundaries(["Manhattan", "Brooklyn"])
    assert len(geo["features"]) == 2


def test_borough_case_insensitive_match():
    with patch.object(nb.requests, "get", return_value=_fake_response(_BOROUGH_FC)):
        geo, ok = nb.fetch_borough_boundaries(["manhattan"])
    assert geo is not None
    assert len(geo["features"]) == 1


def test_borough_no_match_returns_none_but_ok():
    with patch.object(nb.requests, "get", return_value=_fake_response(_BOROUGH_FC)):
        geo, ok = nb.fetch_borough_boundaries(["Staten Island"])
    assert geo is None
    assert ok is True


def test_borough_empty_input_returns_none_ok_no_request():
    with patch.object(nb.requests, "get") as mock_get:
        geo, ok = nb.fetch_borough_boundaries([])
    assert geo is None
    assert ok is True
    mock_get.assert_not_called()


def test_borough_request_failure_distinguishable():
    with patch.object(nb.requests, "get", side_effect=requests.exceptions.Timeout("simulated")):
        geo, ok = nb.fetch_borough_boundaries(["Manhattan"])
    assert geo is None
    assert ok is False


def test_borough_malformed_response_degrades_gracefully():
    with patch.object(nb.requests, "get", return_value=_fake_response({"not": "geojson"})):
        geo, ok = nb.fetch_borough_boundaries(["Manhattan"])
    assert geo is None
    assert ok is False


def test_borough_alternate_property_key_still_matches():
    fc = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {"BoroName": "Bronx"}, "geometry": {}}],
    }
    with patch.object(nb.requests, "get", return_value=_fake_response(fc)):
        geo, ok = nb.fetch_borough_boundaries(["Bronx"])
    assert geo is not None
    assert len(geo["features"]) == 1


# ── fetch_zip_boundaries ─────────────────────────────────────────────────────

def test_zip_match():
    with patch.object(nb.requests, "get", return_value=_fake_response(_ZIP_FC)):
        geo, ok = nb.fetch_zip_boundaries(["10001"])
    assert ok is True
    assert len(geo["features"]) == 1


def test_zip_no_match():
    with patch.object(nb.requests, "get", return_value=_fake_response(_ZIP_FC)):
        geo, ok = nb.fetch_zip_boundaries(["99999"])
    assert geo is None
    assert ok is True


def test_zip_normalizes_trailing_decimal():
    fc = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {"modzcta": "10001.0"}, "geometry": {}}],
    }
    with patch.object(nb.requests, "get", return_value=_fake_response(fc)):
        geo, ok = nb.fetch_zip_boundaries(["10001"])
    assert geo is not None


def test_zip_normalizes_plus4_suffix():
    with patch.object(nb.requests, "get", return_value=_fake_response(_ZIP_FC)):
        geo, ok = nb.fetch_zip_boundaries(["10001-1234"])
    assert geo is not None
    assert len(geo["features"]) == 1


def test_zip_request_failure():
    with patch.object(nb.requests, "get", side_effect=requests.exceptions.ConnectionError("simulated")):
        geo, ok = nb.fetch_zip_boundaries(["10001"])
    assert geo is None
    assert ok is False


def test_zip_empty_input_no_request():
    with patch.object(nb.requests, "get") as mock_get:
        geo, ok = nb.fetch_zip_boundaries([])
    assert geo is None
    assert ok is True
    mock_get.assert_not_called()

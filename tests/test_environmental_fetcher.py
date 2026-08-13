from unittest.mock import patch, MagicMock

import requests

from modules import environmental_fetcher as ef


def _fake_response(json_data, ok=True):
    r = MagicMock()
    if ok:
        r.raise_for_status = lambda: None
    else:
        r.raise_for_status = MagicMock(side_effect=requests.HTTPError("error"))
    r.json = lambda: json_data
    return r


# ── fetch_flood_zone ─────────────────────────────────────────────────────────

def test_flood_zone_sfha_ae():
    with patch.object(ef.requests, "get", return_value=_fake_response(
        {"features": [{"attributes": {"FLD_ZONE": "AE"}}]}
    )):
        result = ef.fetch_flood_zone(40.7, -73.9)
    assert result["flood_zone"] == "AE"
    assert result["in_special_flood_hazard_area"] is True
    assert result["error"] is None


def test_flood_zone_minimal_risk_x():
    with patch.object(ef.requests, "get", return_value=_fake_response(
        {"features": [{"attributes": {"FLD_ZONE": "X"}}]}
    )):
        result = ef.fetch_flood_zone(40.7, -73.9)
    assert result["flood_zone"] == "X"
    assert result["in_special_flood_hazard_area"] is False


def test_flood_zone_no_features_not_an_error():
    with patch.object(ef.requests, "get", return_value=_fake_response({"features": []})):
        result = ef.fetch_flood_zone(40.7, -73.9)
    assert result["error"] is None
    assert result["flood_zone"] is None


def test_flood_zone_missing_latlon():
    result = ef.fetch_flood_zone(None, None)
    assert result["error"] is not None


def test_flood_zone_request_failure_distinguishable_from_empty():
    def fake_get(*a, **kw):
        raise requests.exceptions.Timeout("simulated")
    with patch.object(ef.requests, "get", side_effect=fake_get):
        result = ef.fetch_flood_zone(40.7, -73.9)
    assert result["error"] is not None
    # Distinguishable from the "no features" (error=None) case above.


def test_flood_zone_unknown_code_degrades_gracefully():
    with patch.object(ef.requests, "get", return_value=_fake_response(
        {"features": [{"attributes": {"FLD_ZONE": "ZZ"}}]}
    )):
        result = ef.fetch_flood_zone(40.7, -73.9)
    assert result["error"] is None
    assert result["flood_zone"] == "ZZ"
    assert result["in_special_flood_hazard_area"] is None


# ── fetch_dec_spill_incidents ────────────────────────────────────────────────

def test_dec_spills_maps_borough_to_county():
    with patch.object(ef.requests, "get", return_value=_fake_response(
        [{"spill_number": "123", "spill_date": "2020-01-01", "material_name": "Diesel"}]
    )):
        result = ef.fetch_dec_spill_incidents("Brooklyn")
    assert result["county"] == "Kings"
    assert result["count"] == 1
    assert result["incidents"][0]["material"] == "Diesel"


def test_dec_spills_unrecognized_borough():
    result = ef.fetch_dec_spill_incidents("Not A Real Borough")
    assert result["error"] is not None
    assert result["count"] == 0


def test_dec_spills_always_includes_search_tool_url():
    result = ef.fetch_dec_spill_incidents("Queens")
    assert result["search_tool_url"].startswith("https://")


def test_dec_spills_never_claims_verified():
    with patch.object(ef.requests, "get", return_value=_fake_response([])):
        result = ef.fetch_dec_spill_incidents("Manhattan")
    assert result["verified"] is False


def test_dec_spills_request_failure():
    def fake_get(*a, **kw):
        raise requests.exceptions.ConnectionError("simulated")
    with patch.object(ef.requests, "get", side_effect=fake_get):
        result = ef.fetch_dec_spill_incidents("Bronx")
    assert result["error"] is not None
    assert result["county"] == "Bronx"

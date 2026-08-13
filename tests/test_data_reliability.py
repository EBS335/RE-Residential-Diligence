"""
Regression tests for the data-reliability fixes: a genuinely empty/clean
fetch result must be distinguishable from a failed/rate-limited one across
acris_fetcher, pip_fetcher, nyc_sales_fetcher, and nearby_developments.
"""

from unittest.mock import patch, MagicMock

import requests


# ── acris_fetcher ────────────────────────────────────────────────────────────

def test_acris_clean_empty_vs_failed_fetch_are_distinguishable():
    from modules.acris_fetcher import fetch_acris

    def fake_get_empty(url, params=None, timeout=None):
        r = MagicMock()
        r.raise_for_status = lambda: None
        r.json = lambda: []
        return r

    with patch("modules.acris_fetcher.requests.get", side_effect=fake_get_empty):
        clean = fetch_acris("1001234567")
    assert clean["error"] is None

    def fake_get_fail(url, params=None, timeout=None):
        raise requests.exceptions.Timeout("simulated timeout")

    with patch("modules.acris_fetcher.requests.get", side_effect=fake_get_fail):
        failed = fetch_acris("1001234567")
    assert failed["error"] is not None
    assert clean["error"] != failed["error"]


def test_acris_invalid_bbl_still_returns_fixed_shape():
    from modules.acris_fetcher import fetch_acris
    result = fetch_acris("not-a-bbl")
    assert result["error"] is not None
    assert result["confidence"] == "None"
    assert result["summary"]["total_docs"] == 0


# ── pip_fetcher ──────────────────────────────────────────────────────────────

def test_pip_clean_empty_vs_failed_fetch_are_distinguishable():
    from modules.pip_fetcher import fetch_property_history

    def fake_get_empty(url, params=None, headers=None, timeout=None):
        r = MagicMock()
        r.status_code = 200
        r.json = lambda: []
        return r

    with patch("modules.pip_fetcher.requests.get", side_effect=fake_get_empty):
        clean = fetch_property_history("1001234567", borough_name="Manhattan")
    assert clean["error"] is None

    def fake_get_fail(url, params=None, headers=None, timeout=None):
        raise requests.exceptions.ConnectionError("simulated connection error")

    with patch("modules.pip_fetcher.requests.get", side_effect=fake_get_fail):
        failed = fetch_property_history("1001234567", borough_name="Manhattan")
    assert failed["error"] is not None


def test_pip_invalid_bbl_returns_fixed_shape():
    from modules.pip_fetcher import fetch_property_history
    # An empty/non-digit BBL yields no digits at all after cleaning (unlike
    # e.g. "123", which zero-pads to a syntactically valid 10-digit BBL).
    result = fetch_property_history("", borough_name="Manhattan")
    assert result["error"] == "Invalid BBL"
    assert result["permits"] == []


# ── ownership_research ──────────────────────────────────────────────────────

def test_enrich_ownership_batch_paces_between_properties():
    import modules.ownership_research as own

    props = [{"bbl": str(1000000000 + i), "address": f"{i} Test St", "borough": "Brooklyn"} for i in range(5)]

    with patch.object(own, "enrich_ownership",
                       side_effect=lambda p, borough_name="": {**p, "acris_error": None, "pip_error": None}), \
         patch.object(own.time, "sleep") as mock_sleep:
        own.enrich_ownership_batch(props, batch_size=5)

    assert mock_sleep.call_count == len(props) - 1


def test_enrich_ownership_batch_records_failure_rollup():
    import modules.ownership_research as own

    props = [{"bbl": str(1000000000 + i), "address": f"{i} Test St", "borough": "Brooklyn"} for i in range(5)]

    def fake_enrich(p, borough_name=""):
        err = "timeout" if p["bbl"].endswith("2") else None
        return {**p, "acris_error": err, "pip_error": None}

    captured = {}

    def fake_record_status(name, ok, detail):
        captured.update(name=name, ok=ok, detail=detail)

    with patch.object(own, "enrich_ownership", side_effect=fake_enrich), \
         patch.object(own.time, "sleep"), \
         patch.object(own, "record_source_status", side_effect=fake_record_status):
        own.enrich_ownership_batch(props, batch_size=5)

    assert captured["ok"] is False
    assert "1 of 5" in captured["detail"]


def test_enrich_ownership_batch_all_clean_reports_ok():
    import modules.ownership_research as own

    props = [{"bbl": str(2000000000 + i), "address": f"{i} Clean St"} for i in range(3)]
    captured = {}

    def fake_record_status(name, ok, detail):
        captured.update(ok=ok, detail=detail)

    with patch.object(own, "enrich_ownership",
                       side_effect=lambda p, borough_name="": {**p, "acris_error": None, "pip_error": None}), \
         patch.object(own.time, "sleep"), \
         patch.object(own, "record_source_status", side_effect=fake_record_status):
        own.enrich_ownership_batch(props, batch_size=3)

    assert captured["ok"] is True
    assert "cleanly" in captured["detail"]


# ── nearby_developments ─────────────────────────────────────────────────────

def test_nearby_developments_total_failure_reports_error_not_no_results():
    import modules.nearby_developments as nd

    with patch.object(nd, "_fetch_dob", return_value=([], "error: boom")), \
         patch.object(nd, "_fetch_google_news", return_value=([], "error: boom")), \
         patch.object(nd, "_fetch_trd", return_value=([], "error: boom")), \
         patch.object(nd, "_fetch_commercial_observer", return_value=([], "error: boom")), \
         patch.object(nd, "_fetch_bisnow", return_value=([], "error: boom")), \
         patch.object(nd.time, "sleep"):
        devs, status = nd.fetch_nearby_developments(40.7, -73.9, 0.5)

    assert devs == []
    assert status["overall"] == "error"


def test_nearby_developments_genuine_empty_reports_no_results():
    import modules.nearby_developments as nd

    with patch.object(nd, "_fetch_dob", return_value=([], "no_results")), \
         patch.object(nd, "_fetch_google_news", return_value=([], "no_results")), \
         patch.object(nd, "_fetch_trd", return_value=([], "no_results")), \
         patch.object(nd, "_fetch_commercial_observer", return_value=([], "no_results")), \
         patch.object(nd, "_fetch_bisnow", return_value=([], "no_results")), \
         patch.object(nd.time, "sleep"):
        devs, status = nd.fetch_nearby_developments(40.7, -73.9, 0.5)

    assert devs == []
    assert status["overall"] == "no_results"


def test_nearby_developments_blocked_takes_priority_over_error():
    import modules.nearby_developments as nd

    with patch.object(nd, "_fetch_dob", return_value=([], "blocked")), \
         patch.object(nd, "_fetch_google_news", return_value=([], "error: boom")), \
         patch.object(nd, "_fetch_trd", return_value=([], "no_results")), \
         patch.object(nd, "_fetch_commercial_observer", return_value=([], "no_results")), \
         patch.object(nd, "_fetch_bisnow", return_value=([], "no_results")), \
         patch.object(nd.time, "sleep"):
        devs, status = nd.fetch_nearby_developments(40.7, -73.9, 0.5)

    assert status["overall"] == "blocked"


# ── nyc_sales_fetcher ────────────────────────────────────────────────────────

def test_sale_price_where_clause_is_unquoted_numeric():
    from modules import nyc_sales_fetcher as nsf

    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured.update(params or {})
        r = MagicMock()
        r.raise_for_status = lambda: None
        r.json = lambda: []
        return r

    with patch.object(nsf.requests, "get", side_effect=fake_get):
        nsf.fetch_nyc_sales(40.69, -73.99, 0.5, zip_code="11201")

    assert "sale_price > 10000" in captured["$where"]
    assert "'10000'" not in captured["$where"]


def test_geo_select_success_sorts_by_distance():
    from modules import nyc_sales_fetcher as nsf

    rows = [
        {"address": "Far", "sale_price": "500000", "gross_sq_ft": "1000", "sale_date": "2024-01-01",
         "building_class_category": "01 ONE FAMILY", "zip_code": "11201", "borough": "BROOKLYN",
         "latitude": "40.75", "longitude": "-73.95"},
        {"address": "Near", "sale_price": "600000", "gross_sq_ft": "1000", "sale_date": "2024-01-02",
         "building_class_category": "01 ONE FAMILY", "zip_code": "11201", "borough": "BROOKLYN",
         "latitude": "40.691", "longitude": "-73.991"},
    ]

    def fake_get(url, params=None, timeout=None):
        r = MagicMock()
        r.raise_for_status = lambda: None
        r.json = lambda: rows
        return r

    with patch.object(nsf.requests, "get", side_effect=fake_get):
        listings, status = nsf.fetch_nyc_sales(40.69, -73.99, 0.5, zip_code="11201")

    assert status == "live"
    assert listings[0]["address"].startswith("Near")
    assert listings[0]["distance_miles"] is not None
    assert listings[0]["distance_miles"] <= listings[1]["distance_miles"]


def test_geo_select_400_falls_back_to_base_select():
    from modules import nyc_sales_fetcher as nsf

    call_count = {"n": 0}

    def fake_get(url, params=None, timeout=None):
        call_count["n"] += 1
        r = MagicMock()
        if "latitude" in (params or {}).get("$select", ""):
            r.raise_for_status = MagicMock(side_effect=requests.HTTPError("400 client error"))
        else:
            r.raise_for_status = lambda: None
            r.json = lambda: [{
                "address": "Fallback St", "sale_price": "400000", "gross_sq_ft": "900",
                "sale_date": "2024-01-01", "building_class_category": "01 ONE FAMILY",
                "zip_code": "11201", "borough": "BROOKLYN",
            }]
        return r

    with patch.object(nsf.requests, "get", side_effect=fake_get):
        listings, status = nsf.fetch_nyc_sales(40.69, -73.99, 0.5, zip_code="11201")

    assert call_count["n"] == 2  # geo attempt, then fallback
    assert status == "live"
    assert listings[0]["distance_miles"] is None  # no geo columns available


def test_all_requests_fail_returns_distinguishable_error():
    from modules import nyc_sales_fetcher as nsf

    def fake_get(url, params=None, timeout=None):
        raise requests.exceptions.Timeout("simulated timeout")

    with patch.object(nsf.requests, "get", side_effect=fake_get):
        listings, status = nsf.fetch_nyc_sales(40.69, -73.99, 0.5, zip_code="11201")

    assert listings == []
    assert status.startswith("error")

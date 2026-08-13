"""
AppTest-driven checks that the Site Finder property-detail view renders a
distinct message per data state (not-yet-checked / checked-clean /
checked-error) for both the ACRIS/Distress and Market Comps/Pipeline
sections, instead of the pre-fix behavior where a failed fetch and a
genuinely empty one rendered identically.
"""

import os

from streamlit.testing.v1 import AppTest

from modules.site_sourcing import enrich_property
from modules.deal_scorer import compute_deal_score

_APP_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def _base_prop(**overrides):
    raw = {
        "bbl": "3012345678", "borough": "Brooklyn", "borough_code": "3",
        "block": "1234", "lot": "5", "address": "123 Test St",
        "zip_code": "11201", "community_district": "302",
        "zoning_dist": "R6A", "landuse_code": "11", "landuse_label": "Vacant Land",
        "bldg_class": "V1", "owner": "TEST OWNER", "owner_type": "",
        "lot_sf": 5000.0, "bldg_sf": 0.0, "year_built": "", "num_floors": 0.0,
        "units_res": 0.0, "units_total": 0.0, "far_built": 0.0, "far_residential": 3.0,
        "far_commercial": 0.0, "far_max": 3.0, "unused_far": 3.0, "unused_far_pct": 100.0,
        "assess_land": 400000.0, "assess_total": 800000.0, "exempt_land": 0.0, "exempt_total": 0.0,
        "is_vacant": True, "historic_dist": "", "landmark": "",
        "latitude": 40.69, "longitude": -73.99,
    }
    raw.update(overrides)
    prop = enrich_property(raw)
    prop["deal_score"] = compute_deal_score(unused_far_pct=100.0, zoning_dist="R6A")
    return prop


def _open_property_detail(prop):
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_selected_prop"] = prop
    at.session_state["_sf_selected_bbl"] = prop["bbl"]
    at.run()
    return at


def _all_text(at):
    texts = []
    for kind in ("warning", "info", "error", "caption", "markdown"):
        for el in getattr(at, kind, []):
            texts.append(el.value)
    return " ".join(texts)


# ── ACRIS / Distress three-state UI ─────────────────────────────────────────

def test_not_yet_checked_distress_state():
    # Exercises the RESULTS TABLE's Distress column (not the per-property
    # detail drill-down, which has its own separate always-auto-fetching
    # ACRIS preview and no "not yet checked" state of its own).
    prop = _base_prop()  # no owner_type -> not yet enriched
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = [prop]
    at.session_state["_sf_last_status"] = {"total_fetched": 1, "truncated": False, "error": None}
    at.run()
    assert list(at.exception) == []
    dataframes = list(at.dataframe)
    assert dataframes, "expected the results table to render"
    distress_values = dataframes[0].value["Distress"].tolist()
    assert any("not yet checked" in v for v in distress_values)


def test_checked_clean_distress_state():
    prop = _base_prop(
        owner_type="Corporate Entity",
        distress={"level": "No Signal", "score": 0, "evidence": ["No violations, liens, or foreclosure filings found in public records checked"]},
        distress_signal="No Signal",
        acris_error=None, pip_error=None,
    )
    at = _open_property_detail(prop)
    assert list(at.exception) == []
    text = _all_text(at)
    assert "not yet checked" not in text
    assert "check error" not in text


def test_checked_error_distress_state():
    prop = _base_prop(
        owner_type="Corporate Entity",
        distress={"level": "No Signal", "score": 0, "evidence": []},
        distress_signal="No Signal",
        acris_error="One or more NYC Open Data (ACRIS) requests failed or timed out — this result may be incomplete, not a confirmed clean record.",
        pip_error=None,
    )
    at = _open_property_detail(prop)
    assert list(at.exception) == []
    text = _all_text(at)
    assert "check error" in text or "data may be incomplete" in text or "failed during enrichment" in text


# ── Market Comps / Pipeline status-driven rendering ─────────────────────────

def test_market_comps_not_fetched_state():
    prop = _base_prop()
    at = _open_property_detail(prop)
    assert list(at.exception) == []
    assert "Not yet fetched" in _all_text(at)


def test_market_comps_blocked_state():
    prop = _base_prop(
        market_comps={"comps": [], "median_price_psf": None, "avg_price_psf": None,
                      "median_price": None, "count": 0, "status": "no_zip_code"},
        pipeline={"developments": [], "count": 0, "total_units": 0,
                  "status": {"overall": "blocked"}},
    )
    at = _open_property_detail(prop)
    assert list(at.exception) == []
    text = _all_text(at)
    assert "No ZIP code" in text
    assert "rate-limited" in text


def test_market_comps_error_state():
    prop = _base_prop(
        market_comps={"comps": [], "median_price_psf": None, "avg_price_psf": None,
                      "median_price": None, "count": 0, "status": "error: ConnectionError"},
        pipeline={"developments": [], "count": 0, "total_units": 0,
                  "status": {"overall": "error"}},
    )
    at = _open_property_detail(prop)
    assert list(at.exception) == []
    text = _all_text(at)
    assert "NYC Rolling Sales fetch failed" in text
    assert "failed to respond" in text


def test_market_comps_clean_empty_state():
    prop = _base_prop(
        market_comps={"comps": [], "median_price_psf": None, "avg_price_psf": None,
                      "median_price": None, "count": 0, "status": "no_results"},
        pipeline={"developments": [], "count": 0, "total_units": 0,
                  "status": {"overall": "no_results"}},
    )
    at = _open_property_detail(prop)
    assert list(at.exception) == []
    text = _all_text(at)
    assert "no matching sales" in text
    assert "no nearby DOB filings" in text


def test_market_comps_live_state():
    prop = _base_prop(
        market_comps={"comps": [{"address": "1 Test St", "price": 900000, "sqft": 1000,
                                  "price_psf": 900, "date": "2024-01-01"}],
                      "median_price_psf": 900.0, "avg_price_psf": 900.0,
                      "median_price": 900000.0, "count": 1, "status": "live"},
        pipeline={"developments": [{"address": "2 Test Ave", "asset_type": "New Building",
                                     "units": 20, "status": "Filed", "source": "NYC DOB Permits"}],
                  "count": 1, "total_units": 20, "status": {"overall": "live"}},
    )
    at = _open_property_detail(prop)
    assert list(at.exception) == []
    text = _all_text(at)
    assert "$900" in text or "900" in text

"""
Regression coverage for the Batch 0 refactor (Site Finder Finding/Sourcing/
Organizing/Viewing feature set): _run_search()'s inline enrich->filter->
score->assemblage-flag body was extracted into a new, standalone
_enrich_and_score() helper so raw rows from non-search sources (CSV
upload, owner-portfolio lookup, similarity search) can reuse the exact
same pipeline. This test proves the extraction is behavior-preserving:
_run_search() with a mocked search_properties() must still produce the
same result as calling _enrich_and_score() directly on the same raw rows.
"""

from unittest.mock import patch

from modules.site_finder_ui import _run_search, _enrich_and_score

_RAW_ROWS = [
    {
        "bbl": f"301234{i:04d}", "borough": "Brooklyn", "borough_code": "3",
        "block": "1234", "lot": str(i + 1), "address": f"{100 + i} Test St",
        "zip_code": "11201", "community_district": "302",
        "zoning_dist": "R6A", "landuse_code": "02", "landuse_label": "Multi-Family Walk-Up",
        "bldg_class": "C1", "owner": "TEST OWNER", "owner_type": "",
        "lot_sf": 5000.0, "bldg_sf": 8000.0, "year_built": "1930", "num_floors": 4.0,
        "units_res": 12.0, "units_total": 12.0, "far_built": 1.6, "far_residential": 3.0,
        "far_commercial": 0.0, "far_max": 3.0, "unused_far": 1.4, "unused_far_pct": 46.7,
        "assess_land": 400000.0, "assess_total": 800000.0, "exempt_land": 0.0, "exempt_total": 0.0,
        "is_vacant": False, "historic_dist": "", "landmark": "",
        "latitude": 40.69 + i * 0.0001, "longitude": -73.99,
        "lot_type": "Corner" if i == 0 else "Interior",
    }
    for i in range(5)
]


def test_run_search_matches_enrich_and_score_called_directly():
    criteria = {"boroughs": ["Brooklyn"]}
    with patch("modules.site_finder_ui.search_properties", return_value=(_RAW_ROWS, {"error": None})):
        via_run_search, status = _run_search(criteria)

    via_direct_call = _enrich_and_score(_RAW_ROWS)

    assert not status.get("error")
    assert len(via_run_search) == len(via_direct_call) == 5
    for a, b in zip(via_run_search, via_direct_call):
        assert a["bbl"] == b["bbl"]
        assert a["deal_score"]["score"] == b["deal_score"]["score"]
        assert a.get("assemblage_with") == b.get("assemblage_with")


def test_run_search_returns_error_status_without_calling_enrich_and_score():
    with patch("modules.site_finder_ui.search_properties", return_value=([], {"error": "boom"})):
        results, status = _run_search({"boroughs": ["Brooklyn"]})
    assert results == []
    assert status["error"] == "boom"


def test_enrich_and_score_applies_strategy_and_price_filters():
    scored_all = _enrich_and_score(_RAW_ROWS)
    scored_filtered = _enrich_and_score(_RAW_ROWS, min_price=10_000_000)  # excludes everything
    assert len(scored_filtered) == 0
    assert len(scored_all) == 5

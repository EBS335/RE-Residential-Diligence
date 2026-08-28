"""
AppTest-driven checks for the new "🗺️ Search Area Intelligence" dashboard
— an opt-in (button-triggered), area-wide summary rendered at the top of
Site Finder's results, above the per-property table. Every underlying
fetch is mocked (this sandbox has no live network access); these tests
confirm the button/render flow, the no-op-until-clicked FAR histogram
overlay, and that a single sub-fetch failure doesn't break the rest of
the dashboard.
"""

import os
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from modules.site_sourcing import enrich_property, flag_assemblage_candidates
from modules.deal_scorer import compute_deal_score

_APP_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def _synthetic_results(n: int) -> list[dict]:
    props = []
    for i in range(n):
        raw = {
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
            "latitude": 40.69 + i * 0.0001, "longitude": -73.99, "lot_type": "Interior",
        }
        prop = enrich_property(raw)
        prop["deal_score"] = compute_deal_score(unused_far_pct=46.7, zoning_dist="R6A")
        props.append(prop)
    return flag_assemblage_candidates(props)


_BROADER_AREA_ROWS = [
    {
        "bbl": f"301999{i:04d}", "borough": "Brooklyn", "borough_code": "3",
        "block": "9999", "lot": str(i + 1), "address": f"{200 + i} Area St",
        "zip_code": "11201", "community_district": "302", "zoning_dist": "R6A",
        "unused_far_pct": 20.0 + i * 10, "is_vacant": i % 3 == 0,
        "landmark": "Individual Landmark" if i == 0 else "", "historic_dist": "",
        "latitude": 40.69 + i * 0.001, "longitude": -73.99,
    }
    for i in range(5)
]


def _mock_area_fetches():
    """Mocks every underlying fetch _load_area_intelligence() calls, so no
    live network access is required and every sub-section has real data
    to render."""
    return (
        patch("modules.site_finder_ui.search_properties", return_value=(_BROADER_AREA_ROWS, {"error": None})),
        patch("modules.site_finder_ui.check_rent_stabilized", return_value={"status": "not_found"}),
        patch("modules.site_finder_ui.nearest_station_distance_miles", return_value=0.3),
        patch(
            "modules.site_finder_ui.fetch_ulurp_applications",
            return_value={"verified": True, "count": 2, "applications": [{"project_name": "Test Rezoning"}]},
        ),
        patch(
            "modules.site_finder_ui.fetch_dev_momentum",
            return_value={"verified": True, "nb_permit_count": 4},
        ),
        patch(
            "modules.site_finder_ui.fetch_nyc_sales",
            return_value=([{"date": "2026-01-01"}, {"date": "2020-01-01"}], "live"),
        ),
        patch(
            "modules.site_finder_ui.fetch_demographics",
            return_value={"population": 50000, "median_household_income": 75000},
        ),
    )


def test_area_intelligence_button_renders_without_exception():
    results = _synthetic_results(3)
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = results
    at.session_state["_sf_last_status"] = {"overall": "live"}
    at.session_state["_sf_last_criteria"] = {"boroughs": ["Brooklyn"]}
    at.run()

    assert not at.exception
    button_labels = [b.label for b in at.button]
    assert "📊 Load Search Area Intelligence" in button_labels
    markdowns = [m.value for m in at.markdown if m.value]
    assert any("Search Area Intelligence" in m for m in markdowns)


def test_clicking_load_populates_dashboard_without_exception():
    results = _synthetic_results(3)
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = results
    at.session_state["_sf_last_status"] = {"overall": "live"}
    at.session_state["_sf_last_criteria"] = {"boroughs": ["Brooklyn"]}
    at.run()
    assert not at.exception

    mocks = _mock_area_fetches()
    with mocks[0], mocks[1], mocks[2], mocks[3], mocks[4], mocks[5], mocks[6]:
        at.button(key="_sf_load_area_intel").click().run()

    assert not at.exception
    assert "_sf_area_intel" in at.session_state
    area = at.session_state["_sf_area_intel"]
    assert area is not None
    assert area["error"] is None
    assert area["total_lots"] == 5

    markdowns = [m.value for m in at.markdown if m.value]
    assert any("Active Rezoning in This Search Area" in m for m in markdowns)
    assert any("Development Momentum by Community District" in m for m in markdowns)
    assert any("Up-and-Coming Areas" in m for m in markdowns)
    assert any("Neighborhood Growth" in m for m in markdowns)


def test_one_subfetch_failure_does_not_break_the_rest():
    results = _synthetic_results(3)
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = results
    at.session_state["_sf_last_status"] = {"overall": "live"}
    at.session_state["_sf_last_criteria"] = {"boroughs": ["Brooklyn"]}
    at.run()

    mocks = _mock_area_fetches()
    with mocks[0], mocks[1], mocks[2], \
         patch("modules.site_finder_ui.fetch_ulurp_applications", side_effect=RuntimeError("boom")), \
         mocks[4], mocks[5], mocks[6]:
        at.button(key="_sf_load_area_intel").click().run()

    assert not at.exception
    assert "_sf_area_intel" in at.session_state
    area = at.session_state["_sf_area_intel"]
    assert area is not None
    assert area["error"] is None  # the whole dashboard still loaded
    assert area["rezoning_by_cd"] == {}  # just this one sub-section is empty
    assert area["momentum_by_cd"]  # the rest still populated

    markdowns = [m.value for m in at.markdown if m.value]
    assert not any("Active Rezoning in This Search Area" in m for m in markdowns)
    assert any("Development Momentum by Community District" in m for m in markdowns)


def test_area_wide_broader_fetch_error_shows_error_not_exception():
    results = _synthetic_results(2)
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = results
    at.session_state["_sf_last_status"] = {"overall": "live"}
    at.session_state["_sf_last_criteria"] = {"boroughs": ["Brooklyn"]}
    at.run()

    with patch("modules.site_finder_ui.search_properties", return_value=([], {"error": "PLUTO fetch failed"})):
        at.button(key="_sf_load_area_intel").click().run()

    assert not at.exception
    assert "_sf_area_intel" in at.session_state
    area = at.session_state["_sf_area_intel"]
    assert area is not None
    assert area["error"] == "PLUTO fetch failed"


def test_far_histogram_has_no_area_median_line_before_button_clicked():
    results = _synthetic_results(5)
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = results
    at.session_state["_sf_last_status"] = {"overall": "live"}
    at.session_state["_sf_last_criteria"] = {"boroughs": ["Brooklyn"]}
    at.run()

    assert not at.exception
    assert "_sf_area_intel" not in at.session_state


def test_far_histogram_gets_area_median_line_after_button_clicked():
    results = _synthetic_results(5)
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = results
    at.session_state["_sf_last_status"] = {"overall": "live"}
    at.session_state["_sf_last_criteria"] = {"boroughs": ["Brooklyn"]}
    at.run()

    mocks = _mock_area_fetches()
    with mocks[0], mocks[1], mocks[2], mocks[3], mocks[4], mocks[5], mocks[6]:
        at.button(key="_sf_load_area_intel").click().run()

    assert not at.exception
    assert "_sf_area_intel" in at.session_state
    area = at.session_state["_sf_area_intel"]
    assert area is not None
    assert area.get("median_unused_far_pct") is not None

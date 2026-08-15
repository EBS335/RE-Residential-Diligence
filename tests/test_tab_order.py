"""
Confirms the top-level tab order change (Site Finder moved to the first
tab, to test whether Streamlit's non-first-tab component-mounting quirk
was responsible for the Site Finder results map rendering as zero-height
blank space). This is a deliberate hypothesis test, not a guaranteed fix
— see the plan file / commit message for the full rationale and the risk
that Property Analysis's own maps could be affected by moving to a
non-first tab instead. This test only confirms the mechanical reorder
happened correctly and that both tabs still render without exceptions;
it cannot verify real-browser map rendering.
"""

import os

from streamlit.testing.v1 import AppTest

_APP_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def test_site_finder_is_now_the_first_tab():
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    assert not at.exception
    labels = [t.label for t in at.tabs]
    assert labels == ["🔍 Site Finder", "🏢 Property Analysis", "📁 Portfolio"]


def test_site_finder_results_table_still_renders_on_first_tab():
    # Mirrors tests/test_site_finder_results_table.py's seeding pattern —
    # confirms the results table/map code path still runs without
    # exceptions now that it's under the first tab instead of the second.
    from modules.site_sourcing import enrich_property, flag_assemblage_candidates
    from modules.deal_scorer import compute_deal_score

    raw = {
        "bbl": "3012345678", "borough": "Brooklyn", "borough_code": "3",
        "block": "1234", "lot": "5", "address": "123 Test St",
        "zip_code": "11201", "community_district": "302",
        "zoning_dist": "R6A", "landuse_code": "02", "landuse_label": "Multi-Family Walk-Up",
        "bldg_class": "C1", "owner": "TEST OWNER", "owner_type": "",
        "lot_sf": 5000.0, "bldg_sf": 8000.0, "year_built": "1930", "num_floors": 4.0,
        "units_res": 12.0, "units_total": 12.0, "far_built": 1.6, "far_residential": 3.0,
        "far_commercial": 0.0, "far_max": 3.0, "unused_far": 1.4, "unused_far_pct": 46.7,
        "assess_land": 400000.0, "assess_total": 800000.0, "exempt_land": 0.0, "exempt_total": 0.0,
        "is_vacant": False, "historic_dist": "", "landmark": "",
        "latitude": 40.69, "longitude": -73.99, "lot_type": "Corner",
    }
    prop = enrich_property(raw)
    prop["deal_score"] = compute_deal_score(unused_far_pct=46.7, zoning_dist="R6A")
    results = flag_assemblage_candidates([prop])

    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = results
    at.session_state["_sf_last_status"] = {"overall": "live"}
    at.run()
    assert not at.exception


def test_property_analysis_tab_still_renders_on_second_tab():
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    assert not at.exception
    # Property Analysis's content (address search form etc.) still builds
    # without exceptions now that it's the second tab.
    assert len(at.text_input) > 0 or len(at.button) > 0

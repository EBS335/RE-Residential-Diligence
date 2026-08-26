"""
AppTest-driven checks for the new "📊 Data Visualizations" section
(charts + a geographic heat map) appended at the bottom of Site Finder's
results table. AppTest has no dedicated accessor for st.plotly_chart
elements, so these tests confirm the section renders without exception
(exercising every go.Figure construction + st.plotly_chart/st.pydeck_chart
call) and that its markdown headers/captions appear, mirroring how other
non-widget UI sections in this file are already tested.
"""

import os

from streamlit.testing.v1 import AppTest

from modules.site_sourcing import enrich_property, flag_assemblage_candidates
from modules.deal_scorer import compute_deal_score

_APP_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def _synthetic_results(n: int) -> list[dict]:
    props = []
    for i in range(n):
        raw = {
            "bbl": f"301234{i:04d}", "borough": ["Brooklyn", "Queens", "Manhattan"][i % 3],
            "borough_code": "3", "block": "1234", "lot": str(i + 1), "address": f"{100 + i} Test St",
            "zip_code": "11201", "community_district": "302",
            "zoning_dist": "R6A", "landuse_code": "02", "landuse_label": "Multi-Family Walk-Up",
            "bldg_class": "C1", "owner": "TEST OWNER", "owner_type": "",
            "lot_sf": 5000.0, "bldg_sf": 8000.0, "year_built": "1930", "num_floors": 4.0,
            "units_res": 12.0, "units_total": 12.0, "far_built": 1.6, "far_residential": 3.0,
            "far_commercial": 0.0, "far_max": 3.0, "unused_far": 1.4, "unused_far_pct": 40.0 + i * 5,
            "assess_land": 400000.0, "assess_total": 800000.0, "exempt_land": 0.0, "exempt_total": 0.0,
            "is_vacant": i % 2 == 0, "historic_dist": "", "landmark": "",
            "latitude": 40.69 + i * 0.001, "longitude": -73.99 + i * 0.001,
            "lot_type": "Corner" if i == 0 else "Interior",
        }
        prop = enrich_property(raw)
        prop["deal_score"] = compute_deal_score(unused_far_pct=40.0 + i * 5, zoning_dist="R6A")
        props.append(prop)
    return flag_assemblage_candidates(props)


def test_data_visualizations_section_renders_without_exception():
    results = _synthetic_results(8)
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = results
    at.session_state["_sf_last_status"] = {"overall": "live"}
    at.run()

    assert not at.exception
    markdowns = [m.value for m in at.markdown if m.value]
    assert any("Data Visualizations" in m for m in markdowns)
    assert any("Deal Score Density Heat Map" in m for m in markdowns)


def test_data_visualizations_section_handles_single_result_without_exception():
    results = _synthetic_results(1)
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = results
    at.session_state["_sf_last_status"] = {"overall": "live"}
    at.run()
    assert not at.exception


def test_data_visualizations_section_handles_empty_results_without_exception():
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = []
    at.session_state["_sf_last_status"] = {"overall": "live"}
    at.run()
    assert not at.exception


def test_data_visualizations_section_handles_no_strategy_tags_without_exception():
    # Every property has an empty "strategies" list — the Strategy Mix
    # bar chart must fall back to a caption, not raise on an empty figure.
    results = _synthetic_results(3)
    for p in results:
        p["strategies"] = []
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = results
    at.session_state["_sf_last_status"] = {"overall": "live"}
    at.run()
    assert not at.exception
    markdowns = [m.value for m in at.markdown if m.value]
    assert any("Data Visualizations" in m for m in markdowns)

"""
AppTest-driven checks for:
  1. The Subway line / Major avenue corridor filter now living in the
     LIVE "🔎 Filter Results" panel (not the pre-search criteria form) —
     the fix for the reported bug where selecting a line/avenue did not
     update the results, because those widgets used to live inside
     st.form(...) and only took effect on the next full search submit.
  2. The new "⚖️ Customize Deal Score Weights (optional)" search-section
     panel.
"""

import os
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from modules.site_finder_ui import load_saved_criteria_into_widgets
from modules.site_sourcing import enrich_property, flag_assemblage_candidates
from modules.deal_scorer import compute_deal_score

_APP_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def _synthetic_results(coords: list[tuple[float, float]]) -> list[dict]:
    props = []
    for i, (lat, lon) in enumerate(coords):
        raw = {
            "bbl": f"301234{i:04d}", "borough": "Manhattan", "borough_code": "1",
            "block": "1234", "lot": str(i + 1), "address": f"{100 + i} Test St",
            "zip_code": "10001", "community_district": "105",
            "zoning_dist": "R6A", "landuse_code": "02", "landuse_label": "Multi-Family Walk-Up",
            "bldg_class": "C1", "owner": "TEST OWNER", "owner_type": "",
            "lot_sf": 5000.0, "bldg_sf": 8000.0, "year_built": "1930", "num_floors": 4.0,
            "units_res": 12.0, "units_total": 12.0, "far_built": 1.6, "far_residential": 3.0,
            "far_commercial": 0.0, "far_max": 3.0, "unused_far": 1.4, "unused_far_pct": 46.7,
            "assess_land": 400000.0, "assess_total": 800000.0, "exempt_land": 0.0, "exempt_total": 0.0,
            "is_vacant": False, "historic_dist": "", "landmark": "",
            "latitude": lat, "longitude": lon, "lot_type": "Interior",
        }
        prop = enrich_property(raw)
        prop["deal_score"] = compute_deal_score(unused_far_pct=46.7, zoning_dist="R6A")
        props.append(prop)
    return flag_assemblage_candidates(props)


# ── Corridor filter has moved out of the pre-search form ────────────────

def test_criteria_form_no_longer_has_corridor_selectboxes():
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    assert not at.exception
    selectbox_labels = [sb.label for sb in at.selectbox]
    assert "Subway line" not in selectbox_labels
    assert "Major avenue" not in selectbox_labels


def test_filter_panel_has_corridor_selectboxes_once_results_exist():
    # Broadway (Manhattan)'s first waypoint, from modules/major_avenues.py.
    results = _synthetic_results([(40.7038, -74.0132), (40.9000, -73.7000)])
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = results
    at.session_state["_sf_last_status"] = {"overall": "live"}
    at.run()

    assert not at.exception
    selectbox_labels = [sb.label for sb in at.selectbox]
    assert "Subway line" in selectbox_labels
    assert "Major avenue" in selectbox_labels

    captions = [c.value for c in at.caption if c.value]
    assert any("not a continuous" in c for c in captions)


# ── The core regression test: selecting narrows results on the SAME rerun ──

def test_selecting_an_avenue_narrows_results_without_resubmitting_search():
    # One property sits exactly on Broadway (Manhattan)'s first waypoint
    # (40.7038, -74.0132); the other is far away in NYC (~15+ miles).
    results = _synthetic_results([(40.7038, -74.0132), (40.9000, -73.7000)])
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = results
    at.session_state["_sf_last_status"] = {"overall": "live"}
    at.run()
    assert not at.exception

    dataframes = [el.value for el in at.dataframe]
    results_df_before = max(dataframes, key=len)
    assert len(results_df_before) == 2

    # Selecting the avenue filter is a plain (non-form) widget change —
    # a single .run() must be enough for the table to narrow, with NO
    # search-form resubmission involved.
    at.selectbox(key="_sf_filter_avenue").set_value("Broadway (Manhattan)")
    at.run()
    assert not at.exception

    dataframes_after = [el.value for el in at.dataframe]
    results_df_after = max(dataframes_after, key=len)
    assert len(results_df_after) == 1
    assert results_df_after.iloc[0]["Address"] == "100 Test St"


def test_selecting_a_subway_line_filters_via_is_near_line():
    # is_near_line()'s actual matching depends on live station data (not
    # available in this sandbox) — mock it directly to test the wiring:
    # selecting a line calls is_near_line() per property and narrows the
    # table by its result, on the same rerun.
    results = _synthetic_results([(40.70, -74.00), (40.90, -73.70)])
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = results
    at.session_state["_sf_last_status"] = {"overall": "live"}
    at.run()
    assert not at.exception

    def _fake_is_near_line(lat, lon, line, buffer_miles=0.5):
        return lat == 40.70  # only the first synthetic property matches

    with patch("modules.site_finder_ui.is_near_line", side_effect=_fake_is_near_line):
        at.selectbox(key="_sf_filter_transitline").set_value("7")
        at.run()

    assert not at.exception
    dataframes = [el.value for el in at.dataframe]
    results_df = max(dataframes, key=len)
    assert len(results_df) == 1
    assert results_df.iloc[0]["Address"] == "100 Test St"


# ── "⚖️ Customize Deal Score Weights (optional)" search-section panel ────

def test_customize_weights_panel_renders_without_exception():
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    assert not at.exception
    checkbox_labels = [c.label for c in at.checkbox]
    assert "Use custom weights for this search" in checkbox_labels
    number_input_labels = [ni.label for ni in at.number_input]
    for component in ["Unused FAR", "Distress Signals", "Location Demand", "Zoning Flexibility", "Listing Activity"]:
        assert component in number_input_labels


def test_custom_weights_round_trip_through_load_saved_criteria():
    import streamlit as st

    criteria = {
        "boroughs": ["Brooklyn"],
        "deal_score_weights": {
            "Unused FAR": 50, "Distress Signals": 20, "Location Demand": 15,
            "Zoning Flexibility": 10, "Listing Activity": 5,
        },
    }
    load_saved_criteria_into_widgets(criteria)  # direct unit call — no exception
    assert st.session_state["_sf_use_custom_weights"] is True
    assert st.session_state["_sf_customweight_Unused FAR"] == 50
    assert st.session_state["_sf_customweight_Distress Signals"] == 20


def test_custom_weights_default_when_absent_from_saved_criteria():
    import streamlit as st

    # A saved-search criteria dict from before this feature existed has
    # no deal_score_weights key — round-trip must fall back to the
    # engine's own default maxes with the checkbox off.
    load_saved_criteria_into_widgets({"boroughs": ["Bronx"]})
    assert st.session_state["_sf_use_custom_weights"] is False
    assert st.session_state["_sf_customweight_Unused FAR"] == 30
    assert st.session_state["_sf_customweight_Distress Signals"] == 25
    assert st.session_state["_sf_customweight_Location Demand"] == 20
    assert st.session_state["_sf_customweight_Zoning Flexibility"] == 15
    assert st.session_state["_sf_customweight_Listing Activity"] == 10

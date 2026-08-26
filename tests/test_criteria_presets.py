"""
Tests for modules/criteria_presets.py — the combinable "Build a Search"
category dimensions (Borough, Neighborhood, Strategy, Property Type,
Risk), replacing the earlier fixed-button THESIS_PRESETS design per
direct request. Covers the pure combine logic and the new "🧭 Build a
Search" expander's AppTest rendering/round-trip behavior.
"""

import os

from streamlit.testing.v1 import AppTest

from modules.criteria_presets import (
    STRATEGY_OPTIONS, NEIGHBORHOODS_BY_BOROUGH,
    neighborhoods_for_boroughs, build_criteria_from_selections,
)
from modules.site_finder_ui import load_saved_criteria_into_widgets

_APP_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


# ── STRATEGY_OPTIONS / NEIGHBORHOODS_BY_BOROUGH ─────────────────────────

def test_strategy_options_includes_all_four_strategies():
    assert len(STRATEGY_OPTIONS) == 4
    assert "Ground-Up (Vacant)" in STRATEGY_OPTIONS
    assert "Vacant / Underutilized" in STRATEGY_OPTIONS
    assert "Demolition Candidate" in STRATEGY_OPTIONS
    assert "Conversion / Redevelopment" in STRATEGY_OPTIONS


def test_neighborhoods_by_borough_uses_valid_borough_keys():
    from modules.property_search import BOROUGH_CODES

    for b in NEIGHBORHOODS_BY_BOROUGH:
        assert b in BOROUGH_CODES, b


def test_neighborhoods_by_borough_every_neighborhood_has_at_least_one_zip():
    for borough, neighborhoods in NEIGHBORHOODS_BY_BOROUGH.items():
        assert neighborhoods, borough
        for name, zips in neighborhoods.items():
            assert zips, f"{borough} / {name}"
            for z in zips:
                assert z.isdigit() and len(z) == 5, f"{borough}/{name}: bad zip {z!r}"


# ── neighborhoods_for_boroughs() ────────────────────────────────────────

def test_neighborhoods_for_boroughs_filters_to_selected_borough():
    result = neighborhoods_for_boroughs(["Brooklyn"])
    assert "Williamsburg" in result
    assert "Astoria" not in result  # Queens neighborhood, must not leak in
    assert result == sorted(result)


def test_neighborhoods_for_boroughs_union_across_multiple_boroughs():
    result = neighborhoods_for_boroughs(["Brooklyn", "Queens"])
    assert "Williamsburg" in result
    assert "Astoria" in result


def test_neighborhoods_for_boroughs_empty_returns_every_neighborhood():
    result = neighborhoods_for_boroughs(None)
    assert "Williamsburg" in result
    assert "Astoria" in result
    assert "Harlem" in result
    result2 = neighborhoods_for_boroughs([])
    assert result2 == result


# ── build_criteria_from_selections() ────────────────────────────────────

def test_build_criteria_from_selections_all_empty_returns_empty_dict():
    assert build_criteria_from_selections() == {}


def test_build_criteria_from_selections_boroughs_only():
    result = build_criteria_from_selections(boroughs=["Brooklyn"])
    assert result == {"boroughs": ["Brooklyn"]}


def test_build_criteria_from_selections_neighborhood_fills_zip_codes():
    result = build_criteria_from_selections(neighborhoods=["Williamsburg"])
    assert "zip_codes" in result
    assert set(result["zip_codes"]) == set(NEIGHBORHOODS_BY_BOROUGH["Brooklyn"]["Williamsburg"])
    assert "boroughs" not in result


def test_build_criteria_from_selections_unknown_neighborhood_omits_zip_codes():
    result = build_criteria_from_selections(neighborhoods=["Not A Real Place"])
    assert "zip_codes" not in result


def test_build_criteria_from_selections_combines_every_dimension():
    result = build_criteria_from_selections(
        boroughs=["Queens"],
        neighborhoods=["Astoria"],
        strategies=["Ground-Up (Vacant)", "Conversion / Redevelopment"],
        property_types=["Multifamily"],
        risk="High",
    )
    assert result["boroughs"] == ["Queens"]
    assert set(result["zip_codes"]) == set(NEIGHBORHOODS_BY_BOROUGH["Queens"]["Astoria"])
    assert result["strategies"] == ["Ground-Up (Vacant)", "Conversion / Redevelopment"]
    assert result["property_types"] == ["Multifamily"]
    assert result["risk"] == "High"


def test_build_criteria_from_selections_round_trips_through_load_saved_criteria():
    combined = build_criteria_from_selections(boroughs=["Bronx"], strategies=["Demolition Candidate"], risk="Low")
    load_saved_criteria_into_widgets(combined)  # must not raise
    import streamlit as st
    assert st.session_state["_sf_boroughs"] == ["Bronx"]
    assert st.session_state["_sf_strategies"] == ["Demolition Candidate"]
    assert st.session_state["_sf_risk"] == "Low"


# ── UI: "🧭 Build a Search" expander ─────────────────────────────────────

def test_build_a_search_expander_renders_without_exception():
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    assert not at.exception

    multiselect_labels = [ms.label for ms in at.multiselect]
    assert "Borough" in multiselect_labels
    assert "Neighborhood" in multiselect_labels
    assert "Strategy" in multiselect_labels
    assert "Property Type" in multiselect_labels

    button_labels = [b.label for b in at.button]
    assert "✅ Apply to Search Form" in button_labels


def test_selecting_a_borough_narrows_neighborhood_options():
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    assert not at.exception

    at.multiselect(key="_sf_thesis_boroughs").set_value(["Brooklyn"])
    at.run()
    assert not at.exception

    neighborhood_ms = at.multiselect(key="_sf_thesis_neighborhoods")
    assert "Williamsburg" in neighborhood_ms.options
    assert "Astoria" not in neighborhood_ms.options


def test_clicking_apply_loads_combined_criteria_into_the_form():
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    assert not at.exception

    at.multiselect(key="_sf_thesis_boroughs").set_value(["Manhattan"])
    at.multiselect(key="_sf_thesis_strategies").set_value(["Ground-Up (Vacant)"])
    at.run()
    at.button(key="_sf_thesis_apply").click().run()
    assert not at.exception

    assert at.session_state["_sf_boroughs"] == ["Manhattan"]
    assert at.session_state["_sf_strategies"] == ["Ground-Up (Vacant)"]

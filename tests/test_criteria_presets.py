"""
Tests for modules/criteria_presets.py (Batch G, Feature 16 — Criteria
"Thesis" Presets): each curated bundle round-trips cleanly through
load_saved_criteria_into_widgets() — the same reuse point the Portfolio
tab's "Re-run" button already uses for user-saved searches — and the new
"Start from a Thesis Preset" expander renders without exception.
"""

import os

import streamlit as st
from streamlit.testing.v1 import AppTest

from modules.criteria_presets import THESIS_PRESETS
from modules.site_finder_ui import load_saved_criteria_into_widgets

_APP_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def test_every_thesis_preset_round_trips_without_exception():
    for name, preset in THESIS_PRESETS.items():
        load_saved_criteria_into_widgets(preset)  # must not raise
        if "boroughs" in preset:
            assert st.session_state["_sf_boroughs"] == preset["boroughs"], name
        if "property_types" in preset:
            assert st.session_state["_sf_ptypes"] == preset["property_types"], name
        if "strategies" in preset:
            assert st.session_state["_sf_strategies"] == preset["strategies"], name
        if "risk" in preset:
            assert st.session_state["_sf_risk"] == preset["risk"], name
        if "min_far" in preset:
            assert st.session_state["_sf_minfar"] == preset["min_far"], name
        if "min_units" in preset:
            assert st.session_state["_sf_minunits"] == preset["min_units"], name
        if "max_units" in preset:
            assert st.session_state["_sf_maxunits"] == preset["max_units"], name


def test_thesis_presets_use_valid_borough_and_risk_values():
    from modules.property_search import BOROUGH_CODES

    valid_risk = {"Low", "Moderate", "High"}
    for name, preset in THESIS_PRESETS.items():
        for b in preset.get("boroughs", []):
            assert b in BOROUGH_CODES, f"{name}: invalid borough {b!r}"
        if "risk" in preset:
            assert preset["risk"] in valid_risk, f"{name}: invalid risk {preset['risk']!r}"


def test_thesis_preset_expander_renders_and_has_a_button_per_preset():
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    assert not at.exception

    button_labels = [b.label for b in at.button]
    for name in THESIS_PRESETS:
        assert name in button_labels


def test_clicking_a_thesis_preset_button_loads_criteria_into_the_form():
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    assert not at.exception

    preset_name = next(iter(THESIS_PRESETS))
    preset = THESIS_PRESETS[preset_name]
    at.button(key=f"_sf_thesis_{preset_name}").click().run()
    assert not at.exception

    if "boroughs" in preset:
        assert at.session_state["_sf_boroughs"] == preset["boroughs"]
    if "risk" in preset:
        assert at.session_state["_sf_risk"] == preset["risk"]

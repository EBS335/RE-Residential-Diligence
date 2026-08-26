"""
AppTest-driven checks for the Site Finder "🚇 Transit & Avenue Corridor
(optional)" criteria section:
  - the expander renders without exception, with both the subway-line and
    major-avenue selectboxes present
  - transit_line / avenue / transit_buffer_miles round-trip through
    load_saved_criteria_into_widgets() without exception
"""

import os

import streamlit as st
from streamlit.testing.v1 import AppTest

from modules.site_finder_ui import load_saved_criteria_into_widgets

_APP_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def test_transit_avenue_corridor_expander_renders_without_exception():
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    assert not at.exception

    selectbox_labels = [sb.label for sb in at.selectbox]
    assert "Subway line" in selectbox_labels
    assert "Major avenue" in selectbox_labels

    # A caption somewhere on the page explains the buffer-vs-corridor caveat.
    captions = [c.value for c in at.caption]
    assert any("not a continuous" in c for c in captions)


def test_transit_avenue_corridor_caption_mentions_fallback_list_always_complete():
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    assert not at.exception
    captions = [c.value for c in at.caption]
    assert any("always complete" in c for c in captions)


def test_transit_criteria_round_trips_without_exception():
    criteria = {
        "boroughs": ["Brooklyn"],
        "zip_codes": ["11201"],
        "transit_line": "7",
        "avenue": "Flatbush Avenue",
        "transit_buffer_miles": 1.0,
    }
    load_saved_criteria_into_widgets(criteria)  # direct unit call — no exception
    assert st.session_state["_sf_transitline"] == "7"
    assert st.session_state["_sf_avenue"] == "Flatbush Avenue"
    assert st.session_state["_sf_transitbuffer"] == 1.0


def test_transit_criteria_defaults_when_absent_from_saved_criteria():
    # A saved-search criteria dict from before this feature existed has
    # neither key — round-trip must still fall back cleanly.
    load_saved_criteria_into_widgets({"boroughs": ["Bronx"]})
    assert st.session_state["_sf_transitline"] == "Any"
    assert st.session_state["_sf_avenue"] == "Any"
    assert st.session_state["_sf_transitbuffer"] == 0.5


def test_transit_criteria_seeded_into_apptest_selectbox_survives_rerun():
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    assert not at.exception

    # "Any" is always a valid selectbox option for both fields regardless
    # of whether list_available_lines() found any live subway lines in
    # this network-less sandbox — list_available_avenues() is pure static
    # data so it's always populated. 0.25 is always a valid slider option.
    at.session_state["_sf_transitline"] = "Any"
    at.session_state["_sf_avenue"] = "Broadway (Manhattan)"
    at.session_state["_sf_transitbuffer"] = 0.25
    at.run()

    assert not at.exception
    assert at.session_state["_sf_transitline"] == "Any"
    assert at.session_state["_sf_avenue"] == "Broadway (Manhattan)"
    assert at.session_state["_sf_transitbuffer"] == 0.25

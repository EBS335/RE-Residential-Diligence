"""
Tests for the Site Finder map's "search extent" boundary overlay and
auto-fit view (modules/site_finder_ui.py::_render_results_map()) — the
map draws the borough/ZIP boundary the user actually searched (when one
was specified) and fits the view to it, instead of a fixed zoom level.

Rendered via st.pydeck_chart() (a native Streamlit element, not a
third-party custom component — see _render_results_map()'s docstring for
why). pydeck Layer/Deck objects are plain, inspectable Python before
rendering, so these assertions verify construction without needing a
browser.
"""

from unittest.mock import patch

import modules.site_finder_ui as sf


_BOROUGH_FC = {
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature", "properties": {"boro_name": "Brooklyn"},
        "geometry": {"type": "Polygon", "coordinates": [[
            [-74.0, 40.6], [-73.9, 40.6], [-73.9, 40.75], [-74.0, 40.75], [-74.0, 40.6],
        ]]},
    }],
}


def _prop(address, lat, lon):
    return {
        "bbl": "3000010001", "borough": "Brooklyn", "address": address,
        "latitude": lat, "longitude": lon,
        "deal_score": {"score": 80, "tier": "Strong Lead"}, "strategies": [],
    }


def _render_and_capture(props, criteria):
    """Call _render_results_map() with st.pydeck_chart mocked, and return
    the pdk.Deck object it was called with."""
    captured = {}

    def _fake_pydeck_chart(deck, **kw):
        captured["deck"] = deck
        captured["kw"] = kw

    with patch.object(sf.st, "pydeck_chart", side_effect=_fake_pydeck_chart), \
         patch.dict(sf.st.session_state, {}, clear=True):
        sf._render_results_map(props, criteria)
    return captured.get("deck"), captured.get("kw")


def _layers_of_type(deck, layer_type):
    return [l for l in deck.layers if l.type == layer_type]


# ── Boundary overlay presence ────────────────────────────────────────────────

def test_boundary_overlay_added_when_criteria_has_boroughs():
    props = [_prop("1 Test St", 40.65, -73.95)]
    with patch("modules.nyc_boundaries.fetch_borough_boundaries", return_value=(_BOROUGH_FC, True)):
        deck, _ = _render_and_capture(props, {"boroughs": ["Brooklyn"], "zip_codes": []})
    assert len(_layers_of_type(deck, "GeoJsonLayer")) == 1
    assert len(_layers_of_type(deck, "ScatterplotLayer")) == 1


def test_boundary_overlay_zip_takes_priority_over_borough():
    props = [_prop("1 Test St", 40.65, -73.95)]
    with patch("modules.nyc_boundaries.fetch_zip_boundaries", return_value=(_BOROUGH_FC, True)) as mock_zip, \
         patch("modules.nyc_boundaries.fetch_borough_boundaries") as mock_boro:
        _render_and_capture(props, {"boroughs": ["Brooklyn"], "zip_codes": ["11201"]})
    mock_zip.assert_called_once()
    mock_boro.assert_not_called()


def test_no_boundary_overlay_when_no_geographic_filter():
    props = [_prop("1 Test St", 40.65, -73.95)]
    with patch("modules.nyc_boundaries.fetch_borough_boundaries") as mock_boro, \
         patch("modules.nyc_boundaries.fetch_zip_boundaries") as mock_zip:
        deck, _ = _render_and_capture(props, {"boroughs": [], "zip_codes": []})
    mock_boro.assert_not_called()
    mock_zip.assert_not_called()
    assert len(_layers_of_type(deck, "GeoJsonLayer")) == 0
    assert len(_layers_of_type(deck, "ScatterplotLayer")) == 1


def test_no_boundary_overlay_when_criteria_is_none():
    props = [_prop("1 Test St", 40.65, -73.95)]
    with patch("modules.nyc_boundaries.fetch_borough_boundaries") as mock_boro:
        deck, _ = _render_and_capture(props, None)
    mock_boro.assert_not_called()
    assert len(_layers_of_type(deck, "GeoJsonLayer")) == 0


def test_boundary_fetch_failure_degrades_gracefully():
    props = [_prop("1 Test St", 40.65, -73.95)]
    with patch("modules.nyc_boundaries.fetch_borough_boundaries", return_value=(None, False)):
        # Must not raise — map still renders with markers only.
        deck, kw = _render_and_capture(props, {"boroughs": ["Brooklyn"], "zip_codes": []})
    assert len(_layers_of_type(deck, "GeoJsonLayer")) == 0
    assert len(_layers_of_type(deck, "ScatterplotLayer")) == 1
    assert kw == {"width": "stretch", "height": 420}


def test_boundary_result_cached_in_session_state():
    props = [_prop("1 Test St", 40.65, -73.95)]
    with patch("modules.nyc_boundaries.fetch_borough_boundaries", return_value=(_BOROUGH_FC, True)) as mock_fetch, \
         patch.object(sf.st, "pydeck_chart"), \
         patch.dict(sf.st.session_state, {}, clear=True):
        sf._render_results_map(props, {"boroughs": ["Brooklyn"], "zip_codes": []})
        sf._render_results_map(props, {"boroughs": ["Brooklyn"], "zip_codes": []})
    mock_fetch.assert_called_once()  # second call hits the session_state cache


# ── Marker construction ──────────────────────────────────────────────────────

def test_marker_layer_has_tier_colored_rows():
    props = [
        _prop("A", 40.60, -74.00),
        {**_prop("B", 40.70, -73.90), "deal_score": {"score": 40, "tier": "Watch"}},
    ]
    deck, _ = _render_and_capture(props, None)
    scatter = _layers_of_type(deck, "ScatterplotLayer")[0]
    colors = {row["address"]: row["color"] for row in scatter.data}
    assert colors["A"] == sf._TIER_MARKER_COLOR["Strong Lead"]
    assert colors["B"] == sf._TIER_MARKER_COLOR["Watch"]


def test_unrecognized_tier_falls_back_to_default_color():
    props = [{**_prop("A", 40.60, -74.00), "deal_score": {"score": 10, "tier": "Unknown Tier"}}]
    deck, _ = _render_and_capture(props, None)
    scatter = _layers_of_type(deck, "ScatterplotLayer")[0]
    assert scatter.data[0]["color"] == sf._DEFAULT_MARKER_COLOR


def test_no_coordinates_renders_caption_only_no_chart():
    props = [{"bbl": "1", "address": "No Coords", "latitude": None, "longitude": None,
              "deal_score": {"score": 1, "tier": "Pass"}, "strategies": []}]
    with patch.object(sf.st, "pydeck_chart") as mock_chart, \
         patch.object(sf.st, "caption") as mock_caption:
        sf._render_results_map(props, None)
    mock_chart.assert_not_called()
    mock_caption.assert_called_once()


# ── View/bounds computation ──────────────────────────────────────────────────

def test_view_fits_boundary_when_present():
    props = [_prop("Far away", 41.5, -73.0)]  # deliberately outside the boundary polygon
    with patch("modules.nyc_boundaries.fetch_borough_boundaries", return_value=(_BOROUGH_FC, True)):
        deck, _ = _render_and_capture(props, {"boroughs": ["Brooklyn"], "zip_codes": []})
    boundary_bounds = sf._geojson_bounds(_BOROUGH_FC)
    expected_view = sf.compute_view([[lon, lat] for lat, lon in boundary_bounds])
    assert deck.initial_view_state.latitude == expected_view.latitude
    assert deck.initial_view_state.longitude == expected_view.longitude


def test_view_falls_back_to_markers_without_boundary():
    props = [_prop("A", 40.60, -74.00), _prop("B", 40.70, -73.90)]
    with patch("modules.nyc_boundaries.fetch_borough_boundaries"):
        deck, _ = _render_and_capture(props, {"boroughs": [], "zip_codes": []})
    expected_view = sf.compute_view([[-74.00, 40.60], [-73.90, 40.70]])
    assert deck.initial_view_state.latitude == expected_view.latitude
    assert deck.initial_view_state.longitude == expected_view.longitude

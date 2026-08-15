"""
Tests for the Site Finder map's "search extent" boundary overlay and
auto-fit zoom (modules/site_finder_ui.py::_render_results_map()) — the
map now draws the borough/ZIP boundary the user actually searched (when
one was specified) and fits the view to it, instead of a fixed zoom
level. Folium objects are plain, inspectable Python before rendering, so
these assertions verify construction without needing a browser.
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


def _geojson_layers(m):
    return [c for c in m._children.values() if type(c).__name__ == "GeoJson"]


def test_boundary_overlay_added_when_criteria_has_boroughs():
    props = [_prop("1 Test St", 40.65, -73.95)]
    with patch("modules.nyc_boundaries.fetch_borough_boundaries", return_value=(_BOROUGH_FC, True)), \
         patch.object(sf, "folium_static") as mock_render, \
         patch.dict(sf.st.session_state, {}, clear=True):
        sf._render_results_map(props, {"boroughs": ["Brooklyn"], "zip_codes": []})
    m = mock_render.call_args[0][0]
    assert len(_geojson_layers(m)) == 1


def test_boundary_overlay_zip_takes_priority_over_borough():
    props = [_prop("1 Test St", 40.65, -73.95)]
    with patch("modules.nyc_boundaries.fetch_zip_boundaries", return_value=(_BOROUGH_FC, True)) as mock_zip, \
         patch("modules.nyc_boundaries.fetch_borough_boundaries") as mock_boro, \
         patch.object(sf, "folium_static"), \
         patch.dict(sf.st.session_state, {}, clear=True):
        sf._render_results_map(props, {"boroughs": ["Brooklyn"], "zip_codes": ["11201"]})
    mock_zip.assert_called_once()
    mock_boro.assert_not_called()


def test_no_boundary_overlay_when_no_geographic_filter():
    props = [_prop("1 Test St", 40.65, -73.95)]
    with patch("modules.nyc_boundaries.fetch_borough_boundaries") as mock_boro, \
         patch("modules.nyc_boundaries.fetch_zip_boundaries") as mock_zip, \
         patch.object(sf, "folium_static") as mock_render, \
         patch.dict(sf.st.session_state, {}, clear=True):
        sf._render_results_map(props, {"boroughs": [], "zip_codes": []})
    mock_boro.assert_not_called()
    mock_zip.assert_not_called()
    m = mock_render.call_args[0][0]
    assert len(_geojson_layers(m)) == 0


def test_no_boundary_overlay_when_criteria_is_none():
    props = [_prop("1 Test St", 40.65, -73.95)]
    with patch("modules.nyc_boundaries.fetch_borough_boundaries") as mock_boro, \
         patch.object(sf, "folium_static") as mock_render, \
         patch.dict(sf.st.session_state, {}, clear=True):
        sf._render_results_map(props, None)
    mock_boro.assert_not_called()
    m = mock_render.call_args[0][0]
    assert len(_geojson_layers(m)) == 0


def test_boundary_fetch_failure_degrades_gracefully():
    props = [_prop("1 Test St", 40.65, -73.95)]
    with patch("modules.nyc_boundaries.fetch_borough_boundaries", return_value=(None, False)), \
         patch.object(sf, "folium_static") as mock_render, \
         patch.dict(sf.st.session_state, {}, clear=True):
        # Must not raise — map still renders with markers only.
        sf._render_results_map(props, {"boroughs": ["Brooklyn"], "zip_codes": []})
    m = mock_render.call_args[0][0]
    assert len(_geojson_layers(m)) == 0
    mock_render.assert_called_once()


def test_boundary_result_cached_in_session_state():
    props = [_prop("1 Test St", 40.65, -73.95)]
    with patch("modules.nyc_boundaries.fetch_borough_boundaries", return_value=(_BOROUGH_FC, True)) as mock_fetch, \
         patch.object(sf, "folium_static"), \
         patch.dict(sf.st.session_state, {}, clear=True):
        sf._render_results_map(props, {"boroughs": ["Brooklyn"], "zip_codes": []})
        sf._render_results_map(props, {"boroughs": ["Brooklyn"], "zip_codes": []})
    mock_fetch.assert_called_once()  # second call hits the session_state cache


def test_geojson_bounds_used_to_fit_map_when_boundary_present():
    # A marker far outside the boundary polygon shouldn't shrink the fit —
    # fit_bounds should be called with the BOUNDARY's bounds, not the
    # markers', when a boundary is available.
    props = [_prop("Far away", 41.5, -73.0)]
    with patch("modules.nyc_boundaries.fetch_borough_boundaries", return_value=(_BOROUGH_FC, True)), \
         patch.object(sf, "folium_static"), \
         patch.dict(sf.st.session_state, {}, clear=True):
        with patch("folium.Map.fit_bounds") as mock_fit:
            sf._render_results_map(props, {"boroughs": ["Brooklyn"], "zip_codes": []})
    called_bounds = mock_fit.call_args[0][0]
    boundary_bounds = sf._geojson_bounds(_BOROUGH_FC)
    assert called_bounds == boundary_bounds


def test_fit_bounds_falls_back_to_markers_without_boundary():
    props = [_prop("A", 40.60, -74.00), _prop("B", 40.70, -73.90)]
    with patch("modules.nyc_boundaries.fetch_borough_boundaries") as mock_boro, \
         patch.object(sf, "folium_static"), \
         patch.dict(sf.st.session_state, {}, clear=True):
        with patch("folium.Map.fit_bounds") as mock_fit:
            sf._render_results_map(props, {"boroughs": [], "zip_codes": []})
    called_bounds = mock_fit.call_args[0][0]
    assert called_bounds == [[40.60, -74.00], [40.70, -73.90]]

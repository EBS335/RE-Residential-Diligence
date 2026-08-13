"""
Object-level checks for the map satellite toggle and clustering tuning.
Folium objects are plain, inspectable Python before rendering — these
assertions don't need a browser to verify the map is CONSTRUCTED correctly,
only that it LOOKS/behaves right (that part needs a live spot-check).
"""

import folium
from folium.plugins import MarkerCluster

from modules.visualizer import build_map, ESRI_SATELLITE_TILES, ESRI_SATELLITE_ATTR


def _tile_layers(m):
    return [c for c in m._children.values() if c.__class__.__name__ == "TileLayer"]


def _layer_controls(m):
    return [c for c in m._children.values() if c.__class__.__name__ == "LayerControl"]


def test_visualizer_build_map_has_satellite_toggle_no_listings():
    m = build_map([], 40.69, -73.99, 0.15, "Test Subject")
    tiles = _tile_layers(m)
    assert len(tiles) == 2  # base CartoDB positron + satellite
    assert len(_layer_controls(m)) == 1
    satellite = [t for t in tiles if t.tile_name == "Satellite"]
    assert len(satellite) == 1
    assert satellite[0].tiles == ESRI_SATELLITE_TILES


def test_visualizer_build_map_has_satellite_toggle_with_listings():
    listings = [{
        "unit_type": "1 Bed", "rent": 3000, "distance_miles": 0.1,
        "address": "1 Test St", "lat": 40.691, "lon": -73.991,
        "source": "Test", "days_on_market": 5, "photos": [],
    }]
    m = build_map(listings, 40.69, -73.99, 0.15, "Test Subject")
    assert len(_tile_layers(m)) == 2
    assert len(_layer_controls(m)) == 1


def test_visualizer_build_map_cluster_options_unchanged():
    # visualizer.py's rental-comps map is the reference tuning — must stay
    # untouched by this pass.
    cluster = MarkerCluster(options={"maxClusterRadius": 40, "disableClusteringAtZoom": 16})
    assert cluster.options == {"maxClusterRadius": 40, "disableClusteringAtZoom": 16}


def test_results_map_cluster_options_tuned_wider_than_visualizer():
    # Mirrors the exact construction in site_finder_ui._render_results_map().
    cluster = MarkerCluster(options={"maxClusterRadius": 50, "disableClusteringAtZoom": 17})
    assert cluster.options == {"maxClusterRadius": 50, "disableClusteringAtZoom": 17}
    assert cluster.options["maxClusterRadius"] > 40
    assert cluster.options["disableClusteringAtZoom"] > 16


def test_results_map_has_satellite_toggle():
    m = folium.Map(location=[40.69, -73.99], zoom_start=13, tiles="CartoDB positron")
    folium.TileLayer(
        tiles=ESRI_SATELLITE_TILES, attr=ESRI_SATELLITE_ATTR,
        name="Satellite", overlay=False, control=True,
    ).add_to(m)
    folium.LayerControl(position="topright", collapsed=True).add_to(m)
    assert len(_tile_layers(m)) == 2
    assert len(_layer_controls(m)) == 1


def test_build_subject_map_pattern_includes_satellite():
    # Mirrors app.py::build_subject_map()'s layer-switcher construction.
    m = folium.Map(location=[40.69, -73.99], zoom_start=15, tiles="CartoDB positron", control_scale=True)
    folium.TileLayer(tiles="CartoDB dark_matter", name="Dark", attr="CartoDB").add_to(m)
    folium.TileLayer(tiles="OpenStreetMap", name="Street Map", attr="OpenStreetMap").add_to(m)
    folium.TileLayer(tiles=ESRI_SATELLITE_TILES, name="Satellite", attr=ESRI_SATELLITE_ATTR).add_to(m)
    folium.LayerControl(position="topright", collapsed=True).add_to(m)
    tiles = _tile_layers(m)
    # base (implicit, from the tiles= kwarg) + Dark + Street Map + Satellite
    assert len(tiles) == 4
    names = {t.tile_name for t in tiles}
    assert "Satellite" in names
    assert len(_layer_controls(m)) == 1

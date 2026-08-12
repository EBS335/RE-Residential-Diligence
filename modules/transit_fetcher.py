"""
Transit Proximity Fetcher — NYC Subway Stations (NYC Open Data).

Source: DOITT's "Subway Stations" dataset on NYC Open Data (Socrata),
resource id `arq3-7z49` — a free, keyless GeoJSON-typed dataset of all
current MTA subway station entrances/positions, with NAME/LINE/URL fields
and a `the_geom` Point geometry column
(https://data.cityofnewyork.us/Transportation/Subway-Stations/arq3-7z49).
Station positions are MTA-provided and optimized for cartography (approximate),
per the dataset's own documentation.

House fetcher-module contract: module-level URL/timeout constants, a
private `_get()` helper that swallows exceptions, and a public function
that always returns the same fixed dict shape, never raises.

Unlike the per-property fetchers elsewhere in the app, the station list
itself is static reference data shared by every property — it's fetched
and cached once per process (module-level `_station_cache`), not
per-BBL/per-call, to avoid re-downloading ~500 stations on every property
view.
"""

from __future__ import annotations

import math
import requests

from modules.app_logging import get_logger

log = get_logger(__name__)

_STATIONS_URL = "https://data.cityofnewyork.us/resource/arq3-7z49.json"
_TIMEOUT = 15
_HALF_MILE = 0.5

_station_cache: list[dict] | None = None


def _get(url: str, params: dict) -> list[dict]:
    try:
        r = requests.get(url, params=params, timeout=_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, list) else []
    except Exception as exc:
        log.debug("transit_fetcher: request to %s failed: %s", url, exc)
    return []


def _extract_point(row: dict) -> tuple[float, float] | None:
    """Socrata GeoJSON-typed columns are usually returned as
    {"type": "Point", "coordinates": [lon, lat]} under a geometry key that
    can vary by dataset (commonly 'the_geom'). Fall back to flat lat/lon
    fields if present, since dataset schemas do drift."""
    geom = row.get("the_geom") or row.get("geometry") or row.get("point")
    if isinstance(geom, dict):
        coords = geom.get("coordinates")
        if isinstance(coords, (list, tuple)) and len(coords) == 2:
            try:
                lon, lat = float(coords[0]), float(coords[1])
                return lat, lon
            except (TypeError, ValueError):
                pass
    for lat_key, lon_key in (("latitude", "longitude"), ("lat", "lon"), ("y", "x")):
        if row.get(lat_key) and row.get(lon_key):
            try:
                return float(row[lat_key]), float(row[lon_key])
            except (TypeError, ValueError):
                continue
    return None


def _load_station_index() -> list[dict]:
    """Lazily fetch and cache the full station list once per process."""
    global _station_cache
    if _station_cache is not None:
        return _station_cache

    rows = _get(_STATIONS_URL, {"$limit": 1000})
    stations = []
    for r in rows:
        pt = _extract_point(r)
        if not pt:
            continue
        name = r.get("name") or r.get("NAME") or r.get("stop_name") or ""
        line = r.get("line") or r.get("LINE") or r.get("routes") or ""
        stations.append({"name": name, "line": line, "lat": pt[0], "lon": pt[1]})

    _station_cache = stations
    if not stations:
        log.warning("transit_fetcher: station index fetch returned 0 usable rows")
    return _station_cache


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r_miles = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r_miles * math.asin(min(1.0, math.sqrt(a)))


def fetch_transit_proximity(lat: float, lon: float) -> dict:
    """
    Nearest-subway-station distance for a given point.

    Returns (always this shape, never raises):
        {
          "nearest_station": str | None,
          "nearest_lines": list[str],
          "distance_miles": float | None,
          "stations_within_half_mile": int,
          "verified": True,
          "source": "NYC Subway Stations (NYC Open Data, DOITT)",
          "error": str | None,
        }
    """
    base = {
        "nearest_station": None,
        "nearest_lines": [],
        "distance_miles": None,
        "stations_within_half_mile": 0,
        "verified": True,
        "source": "NYC Subway Stations (NYC Open Data, DOITT)",
        "error": None,
    }
    try:
        if lat is None or lon is None:
            return {**base, "error": "missing lat/lon"}
        lat, lon = float(lat), float(lon)

        stations = _load_station_index()
        if not stations:
            return {**base, "error": "station index unavailable"}

        nearest = None
        nearest_dist = None
        within_half = 0
        for s in stations:
            d = _haversine_miles(lat, lon, s["lat"], s["lon"])
            if d <= _HALF_MILE:
                within_half += 1
            if nearest_dist is None or d < nearest_dist:
                nearest_dist = d
                nearest = s

        if nearest is None:
            return {**base, "error": "no stations found"}

        lines = nearest.get("line", "")
        lines_list = [ln.strip() for ln in str(lines).replace("/", "-").split("-") if ln.strip()] if lines else []

        return {
            **base,
            "nearest_station": nearest.get("name") or None,
            "nearest_lines": lines_list,
            "distance_miles": round(nearest_dist, 2),
            "stations_within_half_mile": within_half,
        }
    except Exception as exc:
        log.warning("fetch_transit_proximity failed: %s", exc)
        return {**base, "error": str(exc)}

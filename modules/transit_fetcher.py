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

from modules.app_logging import get_logger, record_source_status

log = get_logger(__name__)

_STATIONS_URL = "https://data.cityofnewyork.us/resource/arq3-7z49.json"
_TIMEOUT = 15
_HALF_MILE = 0.5

_station_cache: list[dict] | None = None

# Fallback list of every current NYC Subway revenue-service line letter/
# number, used ONLY when list_available_lines() is called and the live-
# fetched station index is empty (fetch failed, dataset unreachable, or
# any other reason _load_station_index() returned nothing) — guarantees
# the "Subway line" dropdown in Site Finder's criteria form always has a
# real, correct set of options regardless of live-fetch health. Matches
# the plain letter/number tokens the live dataset itself uses (no express
# "<X>" diamond notation). Deliberately excludes "SIR" — the Staten
# Island Railway is a separate NYC Open Data resource, not part of this
# dataset (arq3-7z49), so it would never appear from a live fetch either;
# omitting it keeps the two code paths' output semantically consistent.
_FALLBACK_LINES: list[str] = [
    "1", "2", "3", "4", "5", "6", "7",
    "A", "B", "C", "D", "E", "F", "G", "J", "L", "M", "N", "Q", "R", "S", "W", "Z",
]


def _get(url: str, params: dict) -> list[dict]:
    try:
        r = requests.get(url, params=params, timeout=_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, list) else []
        log.warning("transit_fetcher: request to %s returned status %s", url, r.status_code)
    except Exception as exc:
        log.warning("transit_fetcher: request to %s failed: %s", url, exc)
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
    """
    Lazily fetch and cache the full station list once per process.

    Only a NON-EMPTY result is cached permanently. A failed/empty fetch is
    NOT cached — it's retried on the next call — so one transient network
    hiccup (timeout, rate-limit, cold start) doesn't permanently poison
    the station index (and therefore the "Subway line" dropdown) for the
    rest of the process's life, which is what an unconditional
    `if _station_cache is not None` guard would otherwise do (an empty
    list is not None).
    """
    global _station_cache
    if _station_cache:
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

    if stations:
        _station_cache = stations
        record_source_status("NYC Subway Stations", ok=True)
    else:
        log.warning("transit_fetcher: station index fetch returned 0 usable rows")
        record_source_status("NYC Subway Stations", ok=False, detail="station index fetch returned 0 usable rows")
    return stations


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


def _line_tokens(line_field) -> list[str]:
    """Split a raw station 'line' field into individual line letter/number
    tokens — the exact same '/'-and-'-'-splitting logic fetch_transit_
    proximity() already applies when building `nearest_lines`, extracted
    here so stations_for_line()/list_available_lines() reuse it instead of
    duplicating the parsing rule."""
    if not line_field:
        return []
    return [ln.strip() for ln in str(line_field).replace("/", "-").split("-") if ln.strip()]


def stations_for_line(line: str) -> list[dict]:
    """
    All stations (from the same cached station index fetch_transit_
    proximity() uses) whose line field includes the given line letter/
    number — a case-insensitive token match against the same '/'-and-'-'
    split fetch_transit_proximity() already applies to `nearest_lines`.

    Never raises; returns [] if the station index is unavailable or
    `line` is blank.
    """
    if not line or not str(line).strip():
        return []
    wanted = str(line).strip().upper()
    try:
        stations = _load_station_index()
    except Exception as exc:
        log.warning("stations_for_line failed: %s", exc)
        return []
    if not stations:
        return []

    matches = []
    for s in stations:
        tokens = [t.upper() for t in _line_tokens(s.get("line", ""))]
        if wanted in tokens:
            matches.append(s)
    return matches


def is_near_line(lat: float, lon: float, line: str, buffer_miles: float = 0.5) -> bool:
    """
    True if (lat, lon) is within `buffer_miles` of ANY station on `line`
    (a buffer around each individual station — not a continuous corridor
    polyline, since no NYC subway-line geometry/GTFS-shapes dataset is
    available anywhere in this app). Reuses _haversine_miles(), the same
    distance helper fetch_transit_proximity() uses internally.

    Never raises; returns False on missing coordinates, an unavailable
    station index, or any other error.
    """
    try:
        if lat is None or lon is None:
            return False
        lat, lon = float(lat), float(lon)
        candidates = stations_for_line(line)
        if not candidates:
            return False
        return any(
            _haversine_miles(lat, lon, s["lat"], s["lon"]) <= buffer_miles
            for s in candidates
        )
    except Exception as exc:
        log.warning("is_near_line failed: %s", exc)
        return False


def nearest_station_distance_miles(lat: float, lon: float) -> float | None:
    """
    Distance in miles from (lat, lon) to the nearest subway station, or
    None if coordinates/station index are unavailable. Reuses the same
    cached station index and haversine helper fetch_transit_proximity()
    uses internally — a small public wrapper so callers that only need
    the raw distance (e.g. an area-wide average) don't need the rest of
    fetch_transit_proximity()'s per-point payload.

    Never raises.
    """
    try:
        if lat is None or lon is None:
            return None
        lat, lon = float(lat), float(lon)
        stations = _load_station_index()
        if not stations:
            return None
        return min(_haversine_miles(lat, lon, s["lat"], s["lon"]) for s in stations)
    except Exception:
        return None


def list_available_lines() -> list[str]:
    """
    The distinct, sorted set of line tokens across the full station index
    — parsed with the exact same _line_tokens() split fetch_transit_
    proximity() already applies to `nearest_lines`.

    Never raises. If the live station index is unavailable (fetch failed,
    empty, or any other error), falls back to _FALLBACK_LINES — a static
    list of every current NYC Subway revenue-service line — so the
    dropdown this feeds always has real options. NOTE: this fallback only
    affects which OPTIONS are listed; is_near_line()'s actual proximity
    matching still depends on live station data, so selecting a
    fallback-sourced line while the live fetch is down returns zero
    matching properties (not an error) until live data is back.
    """
    try:
        stations = _load_station_index()
    except Exception as exc:
        log.warning("list_available_lines failed: %s", exc)
        stations = []

    if not stations:
        return list(_FALLBACK_LINES)

    lines: set[str] = set()
    for s in stations:
        lines.update(_line_tokens(s.get("line", "")))
    return sorted(lines)

"""
Major NYC Avenues/Boulevards — static waypoint reference data for the Site
Finder "Transit & Avenue Corridor" search option.

No free/open NYC avenue-geometry or arterial-classification dataset
exists (the same constraint modules/zoning_rules.py's classify_street_type()
docstring already documents for its own, unrelated address-suffix
heuristic). This module applies the same approximation the app already
accepts for subway-line search (modules/transit_fetcher.py): each avenue
is represented as a short, hand-curated list of (lat, lon) waypoints
along its real-world length, and "near this avenue" means "within a
buffer of ANY of its waypoints" — a discrete-point approximation, not a
true continuous corridor polygon. Waypoint coordinates are approximate
(general geographic knowledge of each avenue's route), not survey-grade.

House fetcher-module contract mirrors modules/transit_fetcher.py's
stations_for_line()/is_near_line()/list_available_lines() API shape so
the criteria form can treat "Subway line" and "Major Avenue" as parallel,
independently-combinable corridor filters. This module makes no network
calls — MAJOR_AVENUES is pure static data — so none of its functions can
fail on a fetch and none of them need the never-raises defensive wrapper
convention live fetchers use.
"""

from __future__ import annotations

import math

# Borough -> avenue/boulevard name -> ordered list of (lat, lon) waypoints
# along its approximate real-world route (south/west end to north/east end).
MAJOR_AVENUES: dict[str, list[tuple[float, float]]] = {
    # Manhattan
    "Broadway (Manhattan)": [
        (40.7038, -74.0132), (40.7359, -73.9911), (40.7580, -73.9855),
        (40.7738, -73.9819), (40.7935, -73.9722), (40.8496, -73.9378),
        (40.8677, -73.9212),
    ],
    "5th Avenue": [
        (40.7308, -73.9975), (40.7484, -73.9857), (40.7644, -73.9736),
        (40.7935, -73.9587), (40.8115, -73.9440),
    ],
    "Park Avenue": [
        (40.7368, -73.9847), (40.7527, -73.9764), (40.7754, -73.9631),
        (40.8005, -73.9440),
    ],
    "Lexington Avenue": [
        (40.7364, -73.9832), (40.7527, -73.9707), (40.7823, -73.9548),
        (40.8115, -73.9370),
    ],
    "Madison Avenue": [
        (40.7429, -73.9878), (40.7587, -73.9733), (40.7823, -73.9601),
        (40.8033, -73.9469),
    ],
    "Amsterdam Avenue": [
        (40.7738, -73.9848), (40.7935, -73.9757), (40.8153, -73.9535),
    ],
    "Columbus Avenue": [
        (40.7738, -73.9800), (40.7935, -73.9683), (40.8033, -73.9613),
    ],
    "3rd Avenue": [
        (40.7364, -73.9808), (40.7587, -73.9677), (40.7823, -73.9515),
        (40.8098, -73.9270), (40.8347, -73.9089),
    ],
    # Brooklyn
    "Flatbush Avenue": [
        (40.6935, -73.9800), (40.6710, -73.9626), (40.6501, -73.9496),
        (40.6180, -73.9316), (40.5936, -73.9083),
    ],
    "Atlantic Avenue": [
        (40.6907, -73.9959), (40.6836, -73.9700), (40.6789, -73.9354),
        (40.6763, -73.8956),
    ],
    "Eastern Parkway": [
        (40.6720, -73.9587), (40.6698, -73.9308), (40.6636, -73.9014),
    ],
    "Ocean Parkway": [
        (40.6501, -73.9700), (40.6115, -73.9700), (40.5762, -73.9686),
    ],
    "Utica Avenue": [
        (40.6698, -73.9308), (40.6350, -73.9308), (40.6115, -73.9308),
    ],
    # Queens
    "Queens Boulevard": [
        (40.7470, -73.9376), (40.7395, -73.8803), (40.7218, -73.8448),
        (40.7048, -73.8079),
    ],
    "Northern Boulevard": [
        (40.7644, -73.9282), (40.7590, -73.8648), (40.7434, -73.7910),
    ],
    "Roosevelt Avenue": [
        (40.7470, -73.9105), (40.7469, -73.8783), (40.7527, -73.8370),
    ],
    "Jamaica Avenue": [
        (40.7028, -73.8067), (40.6934, -73.7717), (40.6970, -73.7369),
    ],
    # Bronx
    "Grand Concourse": [
        (40.8098, -73.9270), (40.8347, -73.9089), (40.8558, -73.8993),
        (40.8778, -73.8869),
    ],
    "Bruckner Boulevard": [
        (40.8098, -73.9107), (40.8180, -73.8730), (40.8347, -73.8367),
    ],
    # Staten Island
    "Hylan Boulevard": [
        (40.6260, -74.0776), (40.5735, -74.1046), (40.5192, -74.1447),
        (40.5013, -74.2140),
    ],
    "Richmond Avenue": [
        (40.6072, -74.1478), (40.5735, -74.1663), (40.5449, -74.1727),
    ],
}


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Local reimplementation of transit_fetcher._haversine_miles()'s
    formula — that function is file-private there, so it's re-derived
    here rather than imported across modules (same convention already
    used elsewhere in this codebase, e.g. deal_scorer's tenure helper)."""
    r_miles = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r_miles * math.asin(min(1.0, math.sqrt(a)))


def list_available_avenues() -> list[str]:
    """The sorted set of avenue/boulevard names this module has waypoint
    data for. Never raises (pure static data, no fetch)."""
    return sorted(MAJOR_AVENUES.keys())


def is_near_avenue(lat: float, lon: float, avenue: str, buffer_miles: float = 0.5) -> bool:
    """
    True if (lat, lon) is within `buffer_miles` of ANY waypoint on
    `avenue` (a buffer around each hand-plotted waypoint — not a
    continuous corridor polygon, mirroring is_near_line()'s exact
    approximation for subway lines, for the same reason: no NYC avenue
    geometry dataset is available).

    Never raises; returns False on missing coordinates, an unknown
    avenue name, or any other error.
    """
    try:
        if lat is None or lon is None:
            return False
        waypoints = MAJOR_AVENUES.get(avenue)
        if not waypoints:
            return False
        lat, lon = float(lat), float(lon)
        return any(
            _haversine_miles(lat, lon, wp_lat, wp_lon) <= buffer_miles
            for wp_lat, wp_lon in waypoints
        )
    except Exception:
        return False

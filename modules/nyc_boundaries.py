"""
NYC Borough & ZIP Code Boundary Fetcher — Site Finder map "search extent"
outline.

Two free, keyless NYC Open Data (Socrata) GeoJSON sources:
  1. Borough Boundaries — dataset gthc-hcne. Dataset ID corroborated via
     its canonical NYC Open Data page URL
     (data.cityofnewyork.us/City-Government/Borough-Boundaries/gthc-hcne).
  2. Zip Code Boundaries — dataset i8iw-xf4u.

Neither dataset's exact `properties` field names (the borough-name /
ZIP-code column on each GeoJSON feature) could be confirmed against a
live request in this sandbox (network egress to data.cityofnewyork.us is
blocked here, consistent with every other NYC Open Data fetch built in
this codebase). Both datasets are small (5 boroughs, ~250 ZIPs), so
rather than guess a SoQL `$where` column name, this fetches the whole
dataset and filters client-side by trying several plausible `properties`
key candidates per feature (mirrors modules/property_search.py's
existing f_any() defensive-multi-candidate pattern). If the real schema
uses a different key than all candidates tried, the boundary simply
won't match and the caller degrades gracefully (no boundary drawn, no
broken map) rather than raising or silently guessing wrong.

Fixed (geojson_or_None, ok) contract throughout — never raises.
"""

from __future__ import annotations

import requests

from modules.app_logging import get_logger, record_source_status

log = get_logger(__name__)

_TIMEOUT = 15
_BOROUGH_URL = "https://data.cityofnewyork.us/resource/gthc-hcne.geojson"
_ZIP_URL = "https://data.cityofnewyork.us/resource/i8iw-xf4u.geojson"

_BOROUGH_NAME_KEYS = ["boro_name", "BoroName", "borough", "Borough", "boroname"]
_ZIP_CODE_KEYS = ["modzcta", "zipcode", "ZIPCODE", "zcta", "zip_code", "postalCode"]


def _get_geojson(url: str, params: dict | None = None) -> tuple[dict | None, bool]:
    """Fetch a GeoJSON FeatureCollection. Returns (data, ok) — ok=False
    means the request itself failed, not that there were zero features."""
    try:
        r = requests.get(url, params=params or {}, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
            return None, False
        return data, True
    except Exception as exc:
        log.warning("nyc_boundaries request to %s failed: %s", url, exc)
        return None, False


def _feature_value(feature: dict, candidate_keys: list[str]) -> str | None:
    props = feature.get("properties") or {}
    for key in candidate_keys:
        val = props.get(key)
        if val:
            return str(val).strip()
    return None


def fetch_borough_boundaries(borough_names: list[str]) -> tuple[dict | None, bool]:
    """
    Fetch boundary polygons for the given borough display names (e.g.
    ["Manhattan", "Brooklyn"] — the same names property_search.BOROUGH_CODES
    uses).

    Returns (geojson, ok):
        geojson — a FeatureCollection dict containing only the matched
                  boroughs' features, ready for folium.GeoJson(); None if
                  the fetch failed OR none of the requested names matched
                  any feature (caller should treat None as "nothing to
                  draw" either way — check `ok` only for status reporting).
        ok      — False only if the HTTP request itself failed.
    """
    wanted = {b.strip().lower() for b in (borough_names or []) if b and b.strip()}
    if not wanted:
        return None, True

    data, ok = _get_geojson(_BOROUGH_URL, {"$limit": "10"})
    record_source_status("NYC Borough Boundaries", ok=ok, detail="" if ok else "Borough Boundaries request failed")
    if not ok or not data:
        return None, ok

    matched = [
        f for f in data.get("features", [])
        if (_feature_value(f, _BOROUGH_NAME_KEYS) or "").lower() in wanted
    ]
    if not matched:
        return None, True
    return {"type": "FeatureCollection", "features": matched}, True


def fetch_zip_boundaries(zip_codes: list[str]) -> tuple[dict | None, bool]:
    """
    Fetch boundary polygons for the given ZIP codes (5-digit strings).

    Returns (geojson, ok) — same contract as fetch_borough_boundaries().
    """
    wanted = {_normalize_zip(z) for z in (zip_codes or []) if z}
    wanted.discard(None)
    if not wanted:
        return None, True

    data, ok = _get_geojson(_ZIP_URL, {"$limit": "300"})
    record_source_status("NYC Zip Code Boundaries", ok=ok, detail="" if ok else "Zip Code Boundaries request failed")
    if not ok or not data:
        return None, ok

    matched = [
        f for f in data.get("features", [])
        if _normalize_zip(_feature_value(f, _ZIP_CODE_KEYS) or "") in wanted
    ]
    if not matched:
        return None, True
    return {"type": "FeatureCollection", "features": matched}, True


def _normalize_zip(raw: str) -> str | None:
    """'10001' -> '10001'; '10001.0' -> '10001'; '10001-1234' -> '10001'."""
    s = str(raw).strip()
    if not s:
        return None
    s = s.split("-")[0].split(".")[0]
    return s if s else None

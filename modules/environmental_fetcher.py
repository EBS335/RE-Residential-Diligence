"""
Environmental & Flood Zone Fetcher — FEMA NFHL + NYS DEC Spill Incidents.

Two free, keyless public data sources:
  1. FEMA National Flood Hazard Layer (NFHL) — ArcGIS REST point-in-polygon
     query against the effective Flood Insurance Rate Map (FIRM) data.
     https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28
     (layer 28 = Flood Hazard Zones; confirmed via FEMA's own NFHL API docs)
  2. NYS DEC Spill Incidents — Socrata dataset u44d-k5fk on data.ny.gov,
     petroleum/hazardous-material spill records dating back to 1978.
     https://data.ny.gov/Energy-Environment/Spill-Incidents/u44d-k5fk

The FEMA point-in-polygon query is a standard, well-established GIS
operation independent of the dataset's internal field naming, so it's
fetched with reasonable confidence. The DEC spill dataset's exact spatial
filter field names could not be verified against a live request in this
sandbox (network egress to data.ny.gov is blocked here) — it attempts a
county-based filter defensively and always surfaces the official DEC
search tool link so a user can self-serve accurate results regardless of
whether the query field-name guess is correct.
"""

from __future__ import annotations

import requests

from modules.app_logging import get_logger, record_source_status

log = get_logger(__name__)

_NFHL_URL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"
_DEC_SPILLS_URL = "https://data.ny.gov/resource/u44d-k5fk.json"
_DEC_SEARCH_TOOL_URL = "https://appfactory.dec.ny.gov/DERExternalSearch/SpillsSearch"
_TIMEOUT = 15

# FEMA flood zone code -> (human label, is_special_flood_hazard_area)
_FLOOD_ZONE_LABELS = {
    "X":    ("Minimal flood risk — outside the 500-year floodplain", False),
    "X500": ("Moderate flood risk — 500-year floodplain (0.2% annual chance)", False),
    "A":    ("High risk — 100-year floodplain (1% annual chance), no base flood elevation determined", True),
    "AE":   ("High risk — 100-year floodplain (1% annual chance), base flood elevation determined", True),
    "AO":   ("High risk — 100-year floodplain, shallow flooding/sheet flow", True),
    "AH":   ("High risk — 100-year floodplain, shallow ponding", True),
    "A99":  ("High risk — 100-year floodplain, protected by a federal flood-control system under construction", True),
    "V":    ("High risk — coastal high-hazard area (wave action), no base flood elevation determined", True),
    "VE":   ("High risk — coastal high-hazard area (wave action), base flood elevation determined", True),
    "D":    ("Undetermined — flood hazard not yet studied", None),
}

_BOROUGH_TO_COUNTY = {
    "Manhattan": "New York", "Brooklyn": "Kings", "Queens": "Queens",
    "Bronx": "Bronx", "Staten Island": "Richmond",
}


def _get_json(url: str, params: dict) -> tuple[dict | list | None, bool]:
    """Fetch and parse JSON from a REST/Socrata endpoint.
    Returns (data, ok) — ok=False means the request itself failed."""
    try:
        r = requests.get(url, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json(), True
    except Exception as exc:
        log.warning("environmental_fetcher request to %s failed: %s", url, exc)
        return None, False


def fetch_flood_zone(lat: float, lon: float) -> dict:
    """
    Look up the FEMA flood zone for a point via the NFHL's point-in-polygon
    ArcGIS REST query.

    Returns (always this shape, never raises):
        {
          "flood_zone": str | None,               # e.g. "AE", "X", "VE"
          "zone_description": str,
          "in_special_flood_hazard_area": bool | None,
          "source": "FEMA National Flood Hazard Layer",
          "verified": True,
          "error": str | None,
        }
    """
    base = {
        "flood_zone": None,
        "zone_description": "Not available",
        "in_special_flood_hazard_area": None,
        "source": "FEMA National Flood Hazard Layer",
        "verified": True,
        "error": None,
    }
    try:
        if lat is None or lon is None:
            return {**base, "error": "missing lat/lon"}
        params = {
            "geometry": f"{lon},{lat}",
            "geometryType": "esriGeometryPoint",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "FLD_ZONE,ZONE_SUBTY,SFHA_TF",
            "returnGeometry": "false",
            "f": "json",
        }
        data, ok = _get_json(_NFHL_URL, params)
        record_source_status("FEMA Flood Zone", ok=ok, detail="" if ok else "NFHL request failed")
        if not ok:
            return {**base, "error": "FEMA NFHL request failed or timed out"}
        if not isinstance(data, dict):
            return {**base, "error": "unexpected NFHL response shape"}

        features = data.get("features", [])
        if not features:
            return {**base, "zone_description": "No mapped flood zone found at this location (likely Zone X / minimal risk, or outside mapped area)"}

        attrs = features[0].get("attributes", {})
        zone = str(attrs.get("FLD_ZONE") or "").strip().upper()
        if not zone:
            return {**base, "error": "no FLD_ZONE attribute in response"}

        label, is_sfha = _FLOOD_ZONE_LABELS.get(zone, (f"Zone {zone} (see FEMA flood zone glossary)", None))
        return {
            **base,
            "flood_zone": zone,
            "zone_description": label,
            "in_special_flood_hazard_area": is_sfha,
        }
    except Exception as exc:
        log.warning("fetch_flood_zone failed: %s", exc)
        record_source_status("FEMA Flood Zone", ok=False, detail=str(exc))
        return {**base, "error": str(exc)}


def fetch_dec_spill_incidents(borough: str = "", limit: int = 25) -> dict:
    """
    Best-effort lookup of NYS DEC spill incident records for the property's
    county (derived from borough — NYC's 5 boroughs are coextensive with 5
    counties). This is a coarse, county-wide filter, NOT a precise-radius
    match around the property (the dataset's exact spatial/address field
    names could not be verified against a live request in this sandbox) —
    always confirm via the official DEC search tool link in the response.

    Returns (always this shape, never raises):
        {
          "incidents": list[dict],
          "count": int,
          "county": str,
          "search_tool_url": str,
          "verified": False,
          "source": "NYS DEC Spill Incidents (data.ny.gov)",
          "error": str | None,
        }
    """
    base = {
        "incidents": [],
        "count": 0,
        "county": "",
        "search_tool_url": _DEC_SEARCH_TOOL_URL,
        "verified": False,
        "source": "NYS DEC Spill Incidents (data.ny.gov)",
        "error": None,
    }
    try:
        county = _BOROUGH_TO_COUNTY.get(borough, "")
        if not county:
            return {**base, "error": "borough not recognized — cannot map to a county"}

        params = {"county": county, "$limit": str(limit), "$order": "spill_date DESC"}
        data, ok = _get_json(_DEC_SPILLS_URL, params)
        record_source_status("NYS DEC Spill Incidents", ok=ok, detail="" if ok else "DEC spills request failed")
        if not ok:
            return {**base, "county": county, "error": "DEC spill incidents request failed or timed out"}
        if not isinstance(data, list):
            return {**base, "county": county, "error": "unexpected response shape"}

        incidents = [{
            "spill_number": r.get("spill_number", ""),
            "date": (r.get("spill_date") or "")[:10],
            "material": r.get("material_name", r.get("material", "")),
            "source": r.get("spill_source", r.get("source", "")),
            "status": r.get("case_status", r.get("status", "")),
            "address": r.get("street_address", r.get("address", "")),
        } for r in data]

        return {**base, "incidents": incidents, "count": len(incidents), "county": county}
    except Exception as exc:
        log.warning("fetch_dec_spill_incidents failed: %s", exc)
        record_source_status("NYS DEC Spill Incidents", ok=False, detail=str(exc))
        return {**base, "error": str(exc)}

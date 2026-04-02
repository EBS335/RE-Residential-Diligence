"""
NYC Zoning & Lot Information — ZOLA / PLUTO integration.

Uses two free, keyless public APIs:
  1. NYC GeoSearch  — converts an address to a BBL (Borough-Block-Lot)
     https://geosearch.planninglabs.nyc/v2/search
  2. NYC Open Data PLUTO — returns 80+ lot/zoning attributes for a BBL
     https://data.cityofnewyork.us/resource/64uk-42ks.json

No API keys required. Both APIs are maintained by NYC Planning Labs.
"""

import re
import requests

# ── API endpoints ─────────────────────────────────────────────────────────────
_GEOSEARCH_URL = "https://geosearch.planninglabs.nyc/v2/search"
_PLUTO_URL     = "https://data.cityofnewyork.us/resource/64uk-42ks.json"
_ZOLA_MAP_BASE = "https://zola.planning.nyc.gov/map/lot"

# ── Land Use category labels ──────────────────────────────────────────────────
LAND_USE_LABELS = {
    "01": "One & Two Family Buildings",
    "02": "Multi-Family Walk-Up",
    "03": "Multi-Family Elevator",
    "04": "Mixed Residential & Commercial",
    "05": "Commercial & Office Buildings",
    "06": "Industrial & Manufacturing",
    "07": "Transportation & Utility",
    "08": "Public Facilities & Institutions",
    "09": "Open Space & Outdoor Recreation",
    "10": "Parking Facilities",
    "11": "Vacant Land",
}

# ── Building class broad descriptions ─────────────────────────────────────────
BLDG_CLASS_LABELS = {
    "A": "Single-Family Residential",
    "B": "Two-Family Residential",
    "C": "Walk-Up Apartment",
    "D": "Elevator Apartment",
    "E": "Warehouse / Factory / Industrial",
    "F": "Factory / Industrial",
    "G": "Garage",
    "H": "Hotel",
    "I": "Hospital / Health",
    "J": "Theatre",
    "K": "Store / Office",
    "L": "Loft",
    "M": "Religious / Church",
    "N": "Asylum / Home",
    "O": "Office Building",
    "P": "Indoor Public Assembly",
    "Q": "Outdoor Recreation",
    "R": "Condo",
    "S": "Mixed Residential & Commercial",
    "T": "Transportation",
    "U": "Utility",
    "V": "Vacant Land",
    "W": "Educational",
    "Y": "Government",
    "Z": "Miscellaneous",
}


def _bldg_class_label(code: str) -> str:
    if not code:
        return "—"
    prefix = code[0].upper()
    label  = BLDG_CLASS_LABELS.get(prefix, "")
    return f"{code} — {label}" if label else code


def geosearch_bbl(address: str, lat: float = None, lon: float = None) -> dict | None:
    """
    Convert an address string to a BBL using NYC GeoSearch.

    Returns a dict with keys {bbl, label, lat, lon} or None if not found.
    Passing lat/lon as focus point prioritises nearby results when the address
    string is ambiguous (e.g. "350 West 42nd" without a borough).
    """
    params: dict = {"text": address.strip(), "size": 1}
    if lat is not None and lon is not None:
        params["focus.point.lat"] = round(lat, 6)
        params["focus.point.lon"] = round(lon, 6)

    try:
        r = requests.get(_GEOSEARCH_URL, params=params, timeout=10)
        r.raise_for_status()
        features = r.json().get("features", [])
    except Exception:
        return None

    if not features:
        return None

    feat  = features[0]
    props = feat.get("properties", {})

    # BBL lives in pad_bbl, or nested under addendum.pad.bbl
    bbl = (
        props.get("pad_bbl")
        or props.get("addendum", {}).get("pad", {}).get("bbl")
    )
    if not bbl:
        return None

    coords = feat.get("geometry", {}).get("coordinates", [None, None])
    return {
        "bbl":   str(bbl).replace(" ", ""),
        "label": props.get("label", ""),
        "lat":   coords[1],
        "lon":   coords[0],
    }


def fetch_pluto(bbl: str) -> dict | None:
    """
    Fetch the PLUTO row for a BBL from NYC Open Data.
    Returns the raw PLUTO row dict, or None if not found.

    The Socrata endpoint accepts a 10-digit BBL string (no spaces/dashes).
    """
    bbl_clean = re.sub(r"\D", "", str(bbl))
    if len(bbl_clean) != 10:
        return None

    try:
        r = requests.get(_PLUTO_URL, params={"bbl": bbl_clean}, timeout=10)
        r.raise_for_status()
        rows = r.json()
    except Exception:
        return None

    return rows[0] if rows else None


def bbl_to_zola_url(bbl: str) -> str:
    """
    Build a direct ZOLA map URL for the given 10-digit BBL.

    BBL format: BBBBBBBBBBB (10 digits)
      digit 1   = borough  (1=Manhattan, 2=Bronx, 3=Brooklyn, 4=Queens, 5=SI)
      digits 2-6 = block   (5 digits, zero-padded)
      digits 7-10= lot     (4 digits, zero-padded)

    ZOLA URL format: /map/lot/{borough}/{block}/{lot}
    """
    bbl_clean = re.sub(r"\D", "", str(bbl))
    if len(bbl_clean) != 10:
        return "https://zola.planning.nyc.gov/"
    borough = bbl_clean[0]
    block   = bbl_clean[1:6].lstrip("0") or "0"
    lot     = bbl_clean[6:10].lstrip("0") or "0"
    return f"{_ZOLA_MAP_BASE}/{borough}/{block}/{lot}"


def fetch_zoning_info(address: str, lat: float = None, lon: float = None) -> dict:
    """
    Full pipeline: address → BBL (GeoSearch) → lot/zoning data (PLUTO).

    Returns a structured dict:
      - On success: zoning, lot, building fields + zola_url
      - On failure: {"error": "..."} with a human-readable message
    """
    geo = geosearch_bbl(address, lat, lon)
    if not geo:
        return {"error": f"Address not found in NYC GeoSearch: {address!r}"}

    pluto = fetch_pluto(geo["bbl"])
    if not pluto:
        return {
            "error": f"No PLUTO data found for BBL {geo['bbl']} ({geo['label']})",
            "bbl":   geo["bbl"],
            "matched_label": geo["label"],
        }

    lu_code = str(pluto.get("landuse") or "").zfill(2)

    def _v(key: str, default: str = "—") -> str:
        val = pluto.get(key)
        if val is None or str(val).strip() in ("", "0", "0.0"):
            return default
        return str(val).strip()

    def _num(key: str, default: str = "—") -> str:
        val = pluto.get(key)
        try:
            n = float(val)
            if n == 0:
                return default
            return f"{n:,.0f}"
        except (TypeError, ValueError):
            return default

    return {
        # Identification
        "bbl":              geo["bbl"],
        "matched_label":    geo["label"],
        "zola_url":         bbl_to_zola_url(geo["bbl"]),
        # Zoning
        "zoning_dist":      _v("zonedist1"),
        "overlay":          _v("overlay1"),
        "special_dist":     _v("spdist1"),
        # Lot dimensions
        "lot_area_sqft":    _num("lotarea"),
        "lot_frontage_ft":  _num("lotfront"),
        "lot_depth_ft":     _num("lotdepth"),
        # Building
        "bldg_area_sqft":   _num("bldgarea"),
        "num_floors":       _v("numfloors"),
        "year_built":       _v("yearbuilt"),
        "bldg_class":       _bldg_class_label(_v("bldgclass", "")),
        "land_use":         LAND_USE_LABELS.get(lu_code, _v("landuse")),
        # Units
        "units_res":        _num("unitsres"),
        "units_total":      _num("unitstotal"),
        # FAR (existing development)
        "far_existing":     _v("far"),
        # Historic / landmark
        "historic_dist":    _v("histdist"),
        "landmark":         _v("landmark"),
        # Raw BBL parts for display
        "borough_code":     geo["bbl"][0],
        "block":            geo["bbl"][1:6].lstrip("0") or "0",
        "lot":              geo["bbl"][6:].lstrip("0") or "0",
    }

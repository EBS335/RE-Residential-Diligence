"""
NYC PLUTO Bulk Property Search Engine — Site Finder sourcing layer.

Queries the same NYC Open Data PLUTO dataset used by zola_fetcher.py
(https://data.cityofnewyork.us/resource/64uk-42ks.json) but in BULK —
filtering across an entire borough/ZIP/neighborhood instead of looking
up a single BBL — to power the Investment Criteria search.

No API key required. Uses Socrata SoQL $where clauses for server-side
filtering so we never have to pull the full ~850k-row PLUTO table.
"""

from __future__ import annotations
import re
import requests

from modules.zola_fetcher import LOT_TYPE_LABELS

_TIMEOUT   = 30
_PLUTO_URL = "https://data.cityofnewyork.us/resource/64uk-42ks.json"
_PAGE_SIZE = 1000
_MAX_ROWS  = 3000   # hard cap per search to keep the UI responsive

# Borough display name -> PLUTO 2-letter borough code
BOROUGH_CODES = {
    "Manhattan":     "MN",
    "Bronx":         "BX",
    "Brooklyn":      "BK",
    "Queens":        "QN",
    "Staten Island": "SI",
}

# PLUTO landuse code -> human label (mirrors zola_fetcher.LAND_USE_LABELS)
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

# Property-type filter option -> set of PLUTO landuse codes it maps to
PROPERTY_TYPE_LANDUSE = {
    "Vacant Lot":        {"11"},
    "Multifamily":       {"02", "03"},
    "Office":            {"05"},
    "Retail":            {"05"},
    "Mixed-Use":         {"04"},
    "Industrial":        {"06"},
    "Hotel":             {"05"},   # PLUTO has no distinct hotel landuse; refine w/ bldgclass "H" downstream
    "Institutional":     {"08"},
    "Any":                None,
}


def _num(val, default=0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _get_page(where_clause: str, offset: int, limit: int) -> list[dict]:
    params = {
        "$where":  where_clause,
        "$limit":  limit,
        "$offset": offset,
        "$order":  "bbl",
    }
    try:
        r = requests.get(_PLUTO_URL, params=params, timeout=_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def _build_where_clause(criteria: dict) -> str:
    """Translate investment-criteria dict into a Socrata SoQL $where clause."""
    clauses: list[str] = []

    # ── Geography ────────────────────────────────────────────────────────────
    boroughs = criteria.get("boroughs") or []
    if boroughs:
        codes = [BOROUGH_CODES[b] for b in boroughs if b in BOROUGH_CODES]
        if codes:
            in_list = ",".join(f"'{c}'" for c in codes)
            clauses.append(f"borough IN({in_list})")

    zips = criteria.get("zip_codes") or []
    if zips:
        clean = [re.sub(r"\D", "", z) for z in zips if re.sub(r"\D", "", z)]
        if clean:
            in_list = ",".join(f"'{z}'" for z in clean)
            clauses.append(f"zipcode IN({in_list})")

    cds = criteria.get("community_districts") or []
    if cds:
        in_list = ",".join(f"'{c}'" for c in cds)
        clauses.append(f"cd IN({in_list})")

    # ── Lot / building size ─────────────────────────────────────────────────
    if criteria.get("min_lot_sf"):
        clauses.append(f"lotarea >= {_num(criteria['min_lot_sf']):.0f}")
    if criteria.get("max_lot_sf"):
        clauses.append(f"lotarea <= {_num(criteria['max_lot_sf']):.0f}")

    # ── FAR (uses PLUTO's own max-permitted FAR fields) ─────────────────────
    if criteria.get("min_far"):
        clauses.append(
            f"(residfar >= {_num(criteria['min_far']):.2f} OR "
            f"commfar >= {_num(criteria['min_far']):.2f})"
        )
    if criteria.get("max_far"):
        clauses.append(
            f"(residfar <= {_num(criteria['max_far']):.2f} AND "
            f"commfar <= {_num(criteria['max_far']):.2f})"
        )

    # ── Residential units ────────────────────────────────────────────────────
    if criteria.get("min_units"):
        clauses.append(f"unitsres >= {_num(criteria['min_units']):.0f}")
    if criteria.get("max_units"):
        clauses.append(f"unitsres <= {_num(criteria['max_units']):.0f}")

    # ── Property type (landuse code) ────────────────────────────────────────
    prop_types = criteria.get("property_types") or []
    landuse_codes: set[str] = set()
    for pt in prop_types:
        codes = PROPERTY_TYPE_LANDUSE.get(pt)
        if codes is None:            # "Any" selected — no landuse filter
            landuse_codes = set()
            break
        landuse_codes |= codes
    if landuse_codes:
        in_list = ",".join(f"'{c}'" for c in sorted(landuse_codes))
        clauses.append(f"landuse IN({in_list})")

    # Exclude records with null/blank BBL (a handful of malformed PLUTO rows)
    clauses.append("bbl IS NOT NULL")

    return " AND ".join(clauses) if clauses else "bbl IS NOT NULL"


def search_properties(criteria: dict, max_rows: int = _MAX_ROWS) -> tuple[list[dict], dict]:
    """
    Bulk-search NYC PLUTO for properties matching investment criteria.

    Args:
        criteria: dict with any of: boroughs (list[str]), zip_codes (list[str]),
                  community_districts (list[str]), min_lot_sf, max_lot_sf,
                  min_far, max_far, min_units, max_units, property_types (list[str])
        max_rows: hard cap on rows returned (default 3000)

    Returns (rows, status) where:
        rows   — list of normalized property dicts
        status — {"total_fetched": int, "truncated": bool, "where_clause": str, "error": str|None}
    """
    where_clause = _build_where_clause(criteria)
    rows: list[dict] = []
    offset = 0
    truncated = False
    error = None

    try:
        while len(rows) < max_rows:
            page = _get_page(where_clause, offset, _PAGE_SIZE)
            if not page:
                break
            rows.extend(page)
            offset += _PAGE_SIZE
            if len(page) < _PAGE_SIZE:
                break   # last page
        if len(rows) >= max_rows:
            truncated = True
            rows = rows[:max_rows]
    except Exception as exc:
        error = str(exc)

    normalized = [_normalize_row(r) for r in rows]
    # Drop rows with no usable BBL or address after normalization
    normalized = [r for r in normalized if r["bbl"] and r["address"]]

    # Diagnostic for the "map shows no markers" failure mode: if we got
    # real results but NONE of them carry usable coordinates, that's a
    # systematic field-mapping problem (e.g. PLUTO's live schema no longer
    # matches the "latitude"/"longitude" field names _normalize_row()
    # assumes), not a data-quality gap in a handful of lots. Surface the
    # raw keys of one sample row so this is diagnosable from the app
    # itself rather than a silent empty map.
    coords_missing_pct = None
    raw_field_sample = None
    if normalized:
        with_coords = sum(1 for r in normalized if r.get("latitude") and r.get("longitude"))
        coords_missing_pct = round(100.0 * (1 - with_coords / len(normalized)), 1)
        if with_coords == 0 and rows:
            raw_field_sample = sorted(rows[0].keys())

    status = {
        "total_fetched": len(normalized),
        "truncated":     truncated,
        "where_clause":  where_clause,
        "error":         error,
        "coords_missing_pct": coords_missing_pct,
        "raw_field_sample_if_no_coords": raw_field_sample,
    }
    return normalized, status


def _normalize_row(r: dict) -> dict:
    """Convert a raw PLUTO row into the common Site Finder property schema."""
    def f(key, default=0.0):
        return _num(r.get(key), default)

    def f_any(keys, default=0.0):
        """Like f(), but tries each key in order and returns the first
        that parses to a nonzero value. Defensive against PLUTO schema
        drift between dataset revisions (NYC Planning periodically
        renames/adds fields) — cheap insurance, never a source of error
        since a missing key just falls through to the next candidate."""
        for key in keys:
            val = _num(r.get(key), None)
            if val:
                return val
        return default

    lot_area   = f("lotarea")
    bldg_area  = f("bldgarea")
    far_built  = f("builtfar") or f("far")
    far_res    = f("residfar")
    far_comm   = f("commfar")
    far_max    = max(far_res, far_comm)
    unused_far = max(0.0, far_max - far_built)
    lu_code    = str(r.get("landuse") or "").zfill(2)

    bbl = str(r.get("bbl") or "").strip()
    borough_code = bbl[0] if bbl else ""
    boro_name = {v: k for k, v in BOROUGH_CODES.items()}.get(
        str(r.get("borough") or "").strip().upper(), ""
    )

    # Mirrors zola_fetcher.py's own lot_type fallback convention exactly
    # (unrecognized code -> the raw code itself, not silently dropped).
    lot_type_code = str(r.get("lottype", "") or "").strip()
    lot_type = LOT_TYPE_LABELS.get(lot_type_code, lot_type_code) if lot_type_code else "—"

    return {
        "bbl":              bbl,
        "borough":          boro_name or r.get("borough", ""),
        "borough_code":     borough_code,
        "block":            str(r.get("block", "")),
        "lot":              str(r.get("lot", "")),
        "address":          (r.get("address") or "").strip().title(),
        "zip_code":         str(r.get("zipcode", "") or ""),
        "community_district": str(r.get("cd", "") or ""),
        "zoning_dist":      r.get("zonedist1", "") or "",
        "landuse_code":     lu_code,
        "landuse_label":    LAND_USE_LABELS.get(lu_code, "Unknown"),
        "bldg_class":       r.get("bldgclass", "") or "",
        "owner":            (r.get("ownername") or r.get("owner") or "").strip(),
        "owner_type":       r.get("ownertype", "") or "",
        "lot_sf":           lot_area,
        "bldg_sf":          bldg_area,
        "year_built":       str(r.get("yearbuilt", "") or ""),
        "num_floors":       f("numfloors"),
        "units_res":        f("unitsres"),
        "units_total":      f("unitstotal"),
        "far_built":        far_built,
        "far_residential":  far_res,
        "far_commercial":   far_comm,
        "far_max":          far_max,
        "unused_far":       unused_far,
        "unused_far_pct":   (unused_far / far_max * 100.0) if far_max > 0 else 0.0,
        "assess_land":      f("assessland"),
        "assess_total":     f("assesstot"),
        "exempt_land":      f("exemptland"),
        "exempt_total":     f("exempttot"),
        "is_vacant":        lu_code == "11" or bldg_area <= 0,
        "historic_dist":    r.get("histdist", "") or "",
        "landmark":         r.get("landmark", "") or "",
        "lot_type":         lot_type,
        "latitude":         f_any(["latitude", "lat"], None),
        "longitude":        f_any(["longitude", "lon", "lng"], None),
    }

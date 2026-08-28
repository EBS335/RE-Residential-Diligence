"""
NYC Sales & DOB Permits Fetcher — NYC Open Data.

Two free, keyless public APIs:
  1. NYC Rolling Sales  (usep-8jbt) — closed residential & commercial sale comps
  2. NYC DOB Permits    (ipu4-2q9a) — new building & major alteration pipeline

No API keys required. Both hosted on NYC Open Data (Socrata).
"""

from __future__ import annotations
import math
import re
import requests
from typing import Optional

from modules.app_logging import get_logger, record_source_status

log = get_logger(__name__)

_SALES_URL  = "https://data.cityofnewyork.us/resource/usep-8jbt.json"
_DOB_URL    = "https://data.cityofnewyork.us/resource/ipu4-2q9a.json"
_TIMEOUT    = 20

_SALES_SELECT_MINIMAL = (
    "address,sale_price,gross_sq_ft,sale_date,"
    "building_class_category,zip_code,borough,block,lot"
)
_SALES_SELECT_BASE = _SALES_SELECT_MINIMAL + ",residential_units,commercial_units,total_units"
# Augmented $select attempting geo columns for a real distance sort. This
# sandbox cannot verify the live usep-8jbt schema actually has these column
# names — _query_sales()'s HTTPError fallback below makes that safe either
# way: a wrong guess just degrades to the base (then minimal) fields, same
# as today.
_SALES_SELECT_GEO = _SALES_SELECT_BASE + ",latitude,longitude"


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r_miles = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r_miles * math.asin(min(1.0, math.sqrt(a)))


def _query_sales(where_clause: str, select_fields: str, limit: int = 100) -> list:
    params = {
        "$where": where_clause, "$select": select_fields,
        "$order": "sale_date DESC", "$limit": str(limit),
    }
    resp = requests.get(_SALES_URL, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()

# Building class category prefix → asset_type
_RESI_PREFIXES = {
    "01 ONE FAMILY", "02 TWO FAMILY", "03 THREE FAMILY",
    "04 TAX CLASS 1 CONDO", "07 RENTALS", "08 RENTALS",
    "09 COOPS", "10 COOPS", "13 CONDOS", "14 RENTALS",
    "15 CONDOS", "16 CONDOS", "17 CONDOS",
}


def _is_residential(bldg_class_cat: str) -> bool:
    cat = str(bldg_class_cat).upper()
    # Simple heuristics: single/multi-family, condos, co-ops, rentals
    residential_patterns = (
        "FAMILY", "CONDO", "CO-OP", "RENTAL", "RESIDENTIAL",
        "WALK-UP", "ELEVATOR APT",
    )
    return any(p in cat for p in residential_patterns)


def fetch_nyc_sales(
    lat: float,
    lon: float,
    radius_miles: float,
    zip_code: Optional[str] = None,
    neighborhood: Optional[str] = None,
) -> tuple[list, str]:
    """
    Fetch recent closed sales from NYC Rolling Sales dataset.

    Filters by zip_code (preferred) or neighborhood. Returns up to 100 records
    sorted by sale_date descending, with sale_price > $10,000.

    Returns (listings, status).
    Each listing uses unified schema with asset_type in:
      "Residential Sale" | "Commercial Sale"
    """
    if not zip_code and not neighborhood:
        return [], "no_filter"

    where_parts = ["sale_price > 10000"]
    if zip_code:
        where_parts.append(f"zip_code='{zip_code.strip()}'")
    elif neighborhood:
        where_parts.append(f"upper(neighborhood)='{neighborhood.strip().upper()}'")
    where_clause = " AND ".join(where_parts)

    has_geo = True
    try:
        rows = _query_sales(where_clause, _SALES_SELECT_GEO)
    except requests.HTTPError:
        # Geo columns likely don't exist on the live schema under this name
        # — degrade to the base fields rather than failing the whole fetch.
        has_geo = False
        try:
            rows = _query_sales(where_clause, _SALES_SELECT_BASE)
        except requests.HTTPError:
            # Unit-count columns likely don't exist either — degrade once
            # more to the original minimal field set.
            try:
                rows = _query_sales(where_clause, _SALES_SELECT_MINIMAL)
            except Exception as exc:
                log.warning("fetch_nyc_sales failed: %s", exc)
                record_source_status("NYC Rolling Sales", ok=False, detail=str(exc))
                return [], f"error: {exc}"
        except Exception as exc:
            log.warning("fetch_nyc_sales failed: %s", exc)
            record_source_status("NYC Rolling Sales", ok=False, detail=str(exc))
            return [], f"error: {exc}"
    except Exception as exc:
        log.warning("fetch_nyc_sales failed: %s", exc)
        record_source_status("NYC Rolling Sales", ok=False, detail=str(exc))
        return [], f"error: {exc}"

    if not isinstance(rows, list):
        record_source_status("NYC Rolling Sales", ok=False, detail="unexpected response shape")
        return [], "error"

    listings: list[dict] = []
    for r in rows:
        try:
            price_raw = r.get("sale_price") or "0"
            price = float(str(price_raw).replace(",", ""))
            if price <= 10_000:
                continue

            sqft_raw = r.get("gross_sq_ft") or "0"
            sqft = int(float(str(sqft_raw).replace(",", ""))) if sqft_raw else None
            if sqft and sqft <= 0:
                sqft = None

            price_psf = round(price / sqft, 2) if sqft and sqft > 0 else None

            units_raw = r.get("total_units") or "0"
            try:
                total_units = int(float(str(units_raw).replace(",", "")))
            except ValueError:
                total_units = 0
            price_per_unit = round(price / total_units, 2) if total_units and total_units > 0 else None

            bcc = str(r.get("building_class_category") or "")
            asset_type = "Residential Sale" if _is_residential(bcc) else "Commercial Sale"

            addr = str(r.get("address") or "—").strip()
            if r.get("borough"):
                addr = f"{addr}, {r['borough']}"

            distance = None
            item_lat, item_lon = lat, lon
            if has_geo:
                try:
                    item_lat = float(r.get("latitude"))
                    item_lon = float(r.get("longitude"))
                    distance = round(_haversine_miles(lat, lon, item_lat, item_lon), 2)
                except (TypeError, ValueError):
                    item_lat, item_lon = lat, lon

            listings.append({
                "address":        addr[:80],
                "price":          price,
                "rent":           None,
                "sqft":           sqft,
                "price_psf":      price_psf,
                "total_units":    total_units or None,
                "price_per_unit": price_per_unit,
                "asset_type":     asset_type,
                "unit_type":      asset_type,
                "bedrooms":       0,
                "building_name":  bcc[:50],
                "date":           (r.get("sale_date") or "")[:10],
                "source":         "NYC Rolling Sales",
                "url":            "",
                "lat":            item_lat,
                "lon":            item_lon,
                "distance_miles": distance,
                "days_on_market": None,
                "photos":         [],
            })
        except Exception:
            continue

    if has_geo:
        # Nearest-first when real distance is available; comps without a
        # resolvable distance sort last rather than being dropped.
        listings.sort(key=lambda item: (item["distance_miles"] is None, item["distance_miles"]))

    status = "live" if listings else "no_results"
    record_source_status("NYC Rolling Sales", ok=True, detail="" if listings else "no matching sales in window")
    return listings, status


def fetch_nyc_sales_counts_by_zips(zip_codes: list[str], since_date: str) -> tuple[dict[str, int], str]:
    """
    Batched, count-only sibling of fetch_nyc_sales(): counts closed sales
    (sale_price > $10,000) since `since_date` for MULTIPLE ZIP codes in a
    SINGLE Socrata aggregate request (zip_code IN(...), $group=zip_code),
    instead of one request per ZIP — meant for area-wide sales-velocity
    metrics where only a per-ZIP count is needed, not distance-sorted
    listing rows. Deliberately drops fetch_nyc_sales()'s anchor-point
    distance sort — not needed for a count metric — fetch_nyc_sales()
    itself is untouched and keeps that behavior for its own callers.

    Does NOT call record_source_status() — intentional: callers running
    this from a worker thread must record source status themselves, on
    the main thread, after collecting the result (record_source_status()
    writes to st.session_state, which is not thread-safe).

    Args:
        zip_codes:   ZIP code strings (any duplicates deduped internally).
        since_date:  a plain "YYYY-MM-DD" string; only sales strictly
                     after this date are counted.

    Returns (counts_by_zip, status):
        counts_by_zip: dict keyed by each ORIGINAL zip_code string passed
                        in, each value an int count (0 for a ZIP absent
                        from the grouped response — Socrata omits
                        zero-count groups — never a missing key).
        status:  "no_filter" if zip_codes is empty (no request made),
                 "live" if the request succeeded with >=1 sale counted,
                 "no_results" if it succeeded with zero sales counted,
                 "error: <detail>" on a request failure (never raises).
    """
    zip_codes = list(zip_codes or [])
    if not zip_codes:
        return {}, "no_filter"

    clean = sorted({z.strip() for z in zip_codes if z and z.strip()})
    if not clean:
        return {z: 0 for z in zip_codes}, "no_filter"

    in_list = ",".join(f"'{z}'" for z in clean)
    params = {
        "$select": "zip_code, count(*) as cnt",
        "$where": f"sale_price > 10000 AND zip_code IN({in_list}) AND sale_date > '{since_date}'",
        "$group": "zip_code",
    }
    try:
        resp = requests.get(_SALES_URL, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        rows = resp.json()
    except Exception as exc:
        log.warning("fetch_nyc_sales_counts_by_zips failed: %s", exc)
        return {z: 0 for z in zip_codes}, f"error: {exc}"

    if not isinstance(rows, list):
        return {z: 0 for z in zip_codes}, "error: unexpected response shape"

    counts_by_clean: dict[str, int] = {}
    for r in rows:
        z = str(r.get("zip_code", "")).strip()
        try:
            counts_by_clean[z] = int(r.get("cnt", 0))
        except (TypeError, ValueError):
            counts_by_clean[z] = 0

    counts_by_zip = {z: counts_by_clean.get(z.strip(), 0) for z in zip_codes}
    total = sum(counts_by_zip.values())
    return counts_by_zip, ("live" if total else "no_results")


def fetch_dob_permits(
    lat: float,
    lon: float,
    radius_miles: float,
) -> tuple[list, str]:
    """
    Fetch recent DOB new-building and major-alteration permits within the radius.

    Uses a lat/lon bounding-box query on the DOB permits dataset (ipu4-2q9a).
    Returns (listings, status).
    Each listing uses asset_type = "New Building" or "Major Alteration".
    """
    lat_d = radius_miles / 69.0
    lon_d = radius_miles / (69.0 * math.cos(math.radians(lat)))

    params = {
        "$where": (
            f"gis_latitude  > {lat - lat_d:.6f} AND gis_latitude  < {lat + lat_d:.6f} "
            f"AND gis_longitude > {lon - lon_d:.6f} AND gis_longitude < {lon + lon_d:.6f} "
            f"AND job_type in('NB','A1')"
        ),
        "$select": (
            "job__,job_type,job_desc,house__,street_name,"
            "initial_cost,stories_prop,block,lot,filing_date,job_status,"
            "gis_latitude,gis_longitude"
        ),
        "$order":  "filing_date DESC",
        "$limit":  "200",
    }

    try:
        resp = requests.get(_DOB_URL, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        rows = resp.json()
    except Exception as exc:
        log.warning("fetch_dob_permits failed: %s", exc)
        record_source_status("NYC DOB Permits", ok=False, detail=str(exc))
        return [], f"error: {exc}"

    if not isinstance(rows, list):
        record_source_status("NYC DOB Permits", ok=False, detail="unexpected response shape")
        return [], "error"

    listings: list[dict] = []
    for r in rows:
        try:
            item_lat = float(r.get("gis_latitude") or lat)
            item_lon = float(r.get("gis_longitude") or lon)

            house = str(r.get("house__") or "").strip()
            street = str(r.get("street_name") or "").strip()
            address = f"{house} {street}".strip() or "—"

            cost_raw = r.get("initial_cost") or "0"
            cost = float(str(cost_raw).replace(",", "").replace("$", "")) if cost_raw else None

            job_type = str(r.get("job_type") or "").upper()
            asset_type = "New Building" if job_type == "NB" else "Major Alteration"

            listings.append({
                "address":        address[:80],
                "price":          cost,
                "rent":           None,
                "sqft":           None,
                "price_psf":      None,
                "asset_type":     asset_type,
                "unit_type":      asset_type,
                "bedrooms":       0,
                "building_name":  str(r.get("job_desc") or "")[:60],
                "date":           (r.get("filing_date") or "")[:10],
                "source":         "NYC DOB Permits",
                "url":            "",
                "lat":            item_lat,
                "lon":            item_lon,
                "distance_miles": None,
                "days_on_market": None,
                "photos":         [],
                "stories":        r.get("stories_prop"),
                "job_status":     r.get("job_status", "—"),
                "job_number":     r.get("job__", "—"),
            })
        except Exception:
            continue

    record_source_status("NYC DOB Permits", ok=True, detail="" if listings else "no matching permits in window")
    return listings, ("live" if listings else "no_results")

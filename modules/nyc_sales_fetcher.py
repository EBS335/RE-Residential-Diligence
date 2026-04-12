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

_SALES_URL  = "https://data.cityofnewyork.us/resource/usep-8jbt.json"
_DOB_URL    = "https://data.cityofnewyork.us/resource/ipu4-2q9a.json"
_TIMEOUT    = 20

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

    where_parts = ["sale_price > '10000'"]
    if zip_code:
        where_parts.append(f"zip_code='{zip_code.strip()}'")
    elif neighborhood:
        where_parts.append(f"upper(neighborhood)='{neighborhood.strip().upper()}'")

    params = {
        "$where":  " AND ".join(where_parts),
        "$select": (
            "address,sale_price,gross_sq_ft,sale_date,"
            "building_class_category,zip_code,borough,block,lot"
        ),
        "$order":  "sale_date DESC",
        "$limit":  "100",
    }

    try:
        resp = requests.get(_SALES_URL, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        rows = resp.json()
    except Exception as exc:
        return [], f"error: {exc}"

    if not isinstance(rows, list):
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

            bcc = str(r.get("building_class_category") or "")
            asset_type = "Residential Sale" if _is_residential(bcc) else "Commercial Sale"

            addr = str(r.get("address") or "—").strip()
            if r.get("borough"):
                addr = f"{addr}, {r['borough']}"

            listings.append({
                "address":        addr[:80],
                "price":          price,
                "rent":           None,
                "sqft":           sqft,
                "price_psf":      price_psf,
                "asset_type":     asset_type,
                "unit_type":      asset_type,
                "bedrooms":       0,
                "building_name":  bcc[:50],
                "date":           (r.get("sale_date") or "")[:10],
                "source":         "NYC Rolling Sales",
                "url":            "",
                "lat":            lat,
                "lon":            lon,
                "distance_miles": None,
                "days_on_market": None,
                "photos":         [],
            })
        except Exception:
            continue

    return listings, ("live" if listings else "no_results")


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
        return [], f"error: {exc}"

    if not isinstance(rows, list):
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

    return listings, ("live" if listings else "no_results")

"""
Site Finder Market Enrichment — Phase 3.

Fetches comparable sales and nearby competitive development pipeline for
a SINGLE Site Finder property (called on-demand from the detail/drill-
down view, not in bulk across search results, to keep searches fast).

Reuses the same fast, keyless NYC Open Data fetchers already used
elsewhere in the app:
    modules/nyc_sales_fetcher.py       — NYC Rolling Sales (ZIP-filtered)
    modules/nearby_developments.py     — DOB permits + news RSS pipeline
"""

from __future__ import annotations

from modules.nyc_sales_fetcher import fetch_nyc_sales
from modules.nearby_developments import fetch_nearby_developments

_DEFAULT_PIPELINE_RADIUS_MI = 0.5


def _median(values: list[float]) -> float | None:
    vals = sorted(v for v in values if v)
    n = len(vals)
    if n == 0:
        return None
    mid = n // 2
    return vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2.0


def fetch_market_comps(prop: dict) -> dict:
    """
    Fetch recent NYC Rolling Sales comps near the property's ZIP code.

    Returns:
        {
          "comps": list[dict],          # raw sales records
          "median_price_psf": float|None,
          "avg_price_psf": float|None,
          "median_price": float|None,
          "count": int,
          "status": str,
        }
    """
    zip_code = prop.get("zip_code", "")
    lat = prop.get("latitude") or 0.0
    lon = prop.get("longitude") or 0.0

    if not zip_code:
        return {
            "comps": [], "median_price_psf": None, "avg_price_psf": None,
            "median_price": None, "count": 0, "status": "no_zip_code",
        }

    comps, status = fetch_nyc_sales(lat, lon, radius_miles=0.5, zip_code=zip_code)

    psf_vals = [c["price_psf"] for c in comps if c.get("price_psf")]
    price_vals = [c["price"] for c in comps if c.get("price")]

    return {
        "comps":             comps[:25],
        "median_price_psf":  _median(psf_vals),
        "avg_price_psf":     (sum(psf_vals) / len(psf_vals)) if psf_vals else None,
        "median_price":      _median(price_vals),
        "count":             len(comps),
        "status":            status,
    }


def fetch_pipeline(prop: dict, radius_miles: float = _DEFAULT_PIPELINE_RADIUS_MI) -> dict:
    """
    Fetch nearby competitive development pipeline (DOB permits + news)
    within `radius_miles` of the property.

    Returns:
        {
          "developments": list[dict],
          "count": int,
          "total_units": int,          # summed where known
          "status": dict,
        }
    """
    lat = prop.get("latitude")
    lon = prop.get("longitude")
    if not lat or not lon:
        return {"developments": [], "count": 0, "total_units": 0, "status": {"overall": "no_coordinates"}}

    devs, status = fetch_nearby_developments(
        lat, lon, radius_miles,
        address=prop.get("address", ""),
        neighborhood=prop.get("borough", ""),
    )

    total_units = 0
    for d in devs:
        try:
            total_units += int(d.get("units") or 0)
        except (TypeError, ValueError):
            pass

    return {
        "developments": devs[:20],
        "count":        len(devs),
        "total_units":  total_units,
        "status":       status,
    }


def enrich_market_data(prop: dict) -> dict:
    """
    Convenience wrapper combining comps + pipeline for a single property.
    Does not mutate input; returns a new dict with added keys:
        market_comps    — see fetch_market_comps()
        pipeline         — see fetch_pipeline()
    """
    out = dict(prop)
    out["market_comps"] = fetch_market_comps(prop)
    out["pipeline"]     = fetch_pipeline(prop)
    return out

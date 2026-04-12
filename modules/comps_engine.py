"""
Comps Engine — unified multi-source comps aggregator.

Aggregates residential, commercial, and sales comps with:
  - Source reliability tagging
  - Fuzzy deduplication
  - Stale listing removal (>120 days)
  - Price-per-SF normalization

Sources used:
  Residential:  StreetEasy, Apartments.com, Craigslist, Zumper, RentHop
                + Redfin (keyless scrape)
  Commercial:   LoopNet, Crexi (loopnet_scraper.py)
  Sales:        NYC Rolling Sales (nyc_sales_fetcher.py)
"""

from __future__ import annotations

import re
from typing import Optional

# ── Reliability tiers ────────────────────────────────────────────────────────

RELIABILITY: dict[str, str] = {
    "NYC Rolling Sales": "High",
    "ACRIS":             "High",
    "StreetEasy":        "Medium-High",
    "Redfin":            "Medium-High",
    "Apartments.com":    "Medium",
    "Zumper":            "Medium",
    "RentHop":           "Medium",
    "Zillow":            "Medium",
    "Craigslist":        "Low",
    "LoopNet":           "Asking / Unverified",
    "Crexi":             "Asking / Unverified",
}

_RELIABILITY_ORDER = ["High", "Medium-High", "Medium", "Low", "Asking / Unverified"]


def _reliability_rank(source: str) -> int:
    tier = RELIABILITY.get(source, "Low")
    try:
        return _RELIABILITY_ORDER.index(tier)
    except ValueError:
        return len(_RELIABILITY_ORDER)


# ── Deduplication ────────────────────────────────────────────────────────────

def _normalize_addr(addr: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(addr).lower())[:30]


def _fuzzy_dedup(listings: list) -> list:
    """
    Remove near-duplicates: same normalized address prefix AND rent within ±5% bucket.
    Keeps the entry with the highest-reliability source.
    """
    groups: dict = {}
    for l in listings:
        rent = l.get("rent") or l.get("price") or 0
        addr_key = _normalize_addr(l.get("address", ""))
        rent_bucket = round(rent / 50) * 50 if rent else 0
        beds = l.get("bedrooms", 0)
        key = (addr_key, rent_bucket, beds)
        if key not in groups or _reliability_rank(l.get("source","")) < _reliability_rank(groups[key].get("source","")):
            groups[key] = l
    return list(groups.values())


def _remove_stale(listings: list, max_days: int = 120) -> list:
    """Remove listings where days_on_market > max_days."""
    out = []
    for l in listings:
        dom = l.get("days_on_market")
        if dom is not None:
            try:
                if int(dom) > max_days:
                    continue
            except (TypeError, ValueError):
                pass
        out.append(l)
    return out


def _tag_reliability(listings: list) -> list:
    """Add 'reliability' field to each listing."""
    for l in listings:
        l["reliability"] = RELIABILITY.get(l.get("source", ""), "Unknown")
    return listings


# ── Residential comps ─────────────────────────────────────────────────────────

def build_residential_comps(
    lat: float,
    lon: float,
    radius_miles: float,
    listings: list,
    proxy_key: Optional[str] = None,
) -> tuple[list, dict]:
    """
    Combine already-fetched residential listings with optional Redfin fetch.
    Deduplicates, removes stale listings (>120 days), and tags reliability.

    Args:
        listings: pre-fetched listings from data_fetcher.fetch_all_listings()
        proxy_key: optional ScrapingBee key for Redfin fetch

    Returns (comps_list, status_dict)
    """
    status: dict = {
        "base_sources": "live" if listings else "no_results",
        "redfin":       "pending",
        "overall":      "no_results",
    }
    combined = list(listings)

    # Attempt Redfin (keyless)
    try:
        from modules.redfin_scraper import scrape_redfin
        rf_listings, rf_status = scrape_redfin(lat, lon, radius_miles, proxy_key)
        status["redfin"] = rf_status
        combined.extend(rf_listings)
    except Exception:
        status["redfin"] = "error"

    # Process
    combined = _remove_stale(combined, max_days=120)
    combined = _fuzzy_dedup(combined)
    combined = _tag_reliability(combined)
    combined.sort(key=lambda x: x.get("distance_miles") or 99)

    status["overall"] = "live" if combined else "no_results"
    return combined, status


# ── Commercial comps ─────────────────────────────────────────────────────────

def build_commercial_comps(
    lat: float,
    lon: float,
    radius_miles: float,
    existing_comm: Optional[list] = None,
    proxy_key: Optional[str] = None,
) -> tuple[list, dict]:
    """
    Fetch/aggregate commercial comps from LoopNet + Crexi + Craigslist commercial.
    Optionally takes already-fetched listings to avoid re-fetching.

    Returns (comps_list, status_dict)
    """
    if existing_comm is not None:
        comps = list(existing_comm)
        comps = _tag_reliability(comps)
        status = {"overall": "live" if comps else "no_results"}
        return comps, status

    status: dict = {"loopnet": "pending", "crexi": "pending",
                    "craigslist_comm": "pending", "overall": "no_results"}
    combined: list = []

    try:
        from modules.loopnet_scraper import fetch_commercial_listings as _fetch_ln
        ln_lst, ln_st = _fetch_ln(lat, lon, radius_miles, proxy_key)
        status["loopnet"] = ln_st.get("loopnet", "—") if isinstance(ln_st, dict) else str(ln_st)
        status["crexi"]   = ln_st.get("crexi",   "—") if isinstance(ln_st, dict) else "—"
        combined.extend(ln_lst)
    except Exception:
        status["loopnet"] = "error"

    try:
        from modules.commercial_scraper import fetch_commercial_comps
        cl_lst, cl_st = fetch_commercial_comps(lat, lon, radius_miles, proxy_key)
        status["craigslist_comm"] = cl_st.get("overall", "—") if isinstance(cl_st, dict) else str(cl_st)
        combined.extend(cl_lst)
    except Exception:
        status["craigslist_comm"] = "error"

    combined = _tag_reliability(combined)
    status["overall"] = "live" if combined else "no_results"
    return combined, status


# ── Retail comps ──────────────────────────────────────────────────────────────

def build_retail_comps(commercial_comps: list) -> list:
    """
    Filter commercial comps to retail listings.
    Uses asset_type / use_type field.
    """
    retail = [
        l for l in commercial_comps
        if "retail" in str(l.get("use_type") or l.get("asset_type") or "").lower()
    ]
    return retail


# ── Sales comps ───────────────────────────────────────────────────────────────

def build_sales_comps(
    lat: float,
    lon: float,
    radius_miles: float,
    existing_sales: Optional[list] = None,
    zip_code: Optional[str] = None,
    neighborhood: Optional[str] = None,
) -> tuple[list, dict]:
    """
    Fetch/aggregate property sales comps from NYC Rolling Sales.
    Optionally takes already-fetched listings to avoid re-fetching.

    Returns (comps_list, status_dict)
    """
    if existing_sales is not None:
        comps = _tag_reliability(list(existing_sales))
        return comps, {"overall": "live" if comps else "no_results"}

    try:
        from modules.nyc_sales_fetcher import fetch_nyc_sales
        sales, s_status = fetch_nyc_sales(
            lat, lon, radius_miles,
            zip_code=zip_code,
            neighborhood=neighborhood,
        )
        sales = _tag_reliability(sales)
        return sales, {"overall": s_status}
    except Exception as exc:
        return [], {"overall": f"error: {exc}"}


# ── Summary helpers ───────────────────────────────────────────────────────────

def residential_summary(comps: list) -> dict:
    """
    Return summary stats grouped by unit_type.
    Keys per group: count, avg_rent, median_rent, min_rent, max_rent, avg_psf
    """
    from modules.data_fetcher import UNIT_ORDER
    groups: dict = {}
    for l in comps:
        ut = l.get("unit_type") or "Unknown"
        groups.setdefault(ut, []).append(l)
    result = {}
    for ut, lsts in groups.items():
        rents = [l.get("rent") or 0 for l in lsts if l.get("rent")]
        psfs  = [l["rent"] / l["sqft"] for l in lsts
                 if l.get("sqft") and l["sqft"] > 0 and l.get("rent")]
        if not rents:
            continue
        rents_sorted = sorted(rents)
        n = len(rents_sorted)
        median = rents_sorted[n // 2]
        result[ut] = {
            "count":       len(rents),
            "avg_rent":    int(sum(rents) / n),
            "median_rent": int(median),
            "min_rent":    int(min(rents)),
            "max_rent":    int(max(rents)),
            "avg_psf":     round(sum(psfs) / len(psfs), 2) if psfs else None,
        }
    # Sort by UNIT_ORDER
    ordered = {k: result[k] for k in UNIT_ORDER if k in result}
    for k in result:
        if k not in ordered:
            ordered[k] = result[k]
    return ordered


def commercial_summary(comps: list) -> dict:
    """Return summary stats for commercial comps."""
    rents = [l.get("rent") or l.get("price") or 0 for l in comps if l.get("rent") or l.get("price")]
    psfs  = [l.get("psf_yr") or l.get("price_psf") or 0 for l in comps if l.get("psf_yr") or l.get("price_psf")]
    sqfts = [l.get("sqft") or 0 for l in comps if l.get("sqft")]
    return {
        "count":    len(comps),
        "avg_rent": int(sum(rents) / len(rents)) if rents else None,
        "avg_psf":  round(sum(psfs) / len(psfs), 2) if psfs else None,
        "avg_sqft": int(sum(sqfts) / len(sqfts)) if sqfts else None,
    }


def sales_summary(comps: list) -> dict:
    """Return summary stats for sales comps."""
    prices = [l.get("price") or 0 for l in comps if l.get("price")]
    psfs   = [l.get("price_psf") or 0 for l in comps if l.get("price_psf")]
    return {
        "count":     len(comps),
        "avg_price": int(sum(prices) / len(prices)) if prices else None,
        "avg_psf":   round(sum(psfs) / len(psfs), 2) if psfs else None,
        "total_volume": int(sum(prices)) if prices else None,
    }

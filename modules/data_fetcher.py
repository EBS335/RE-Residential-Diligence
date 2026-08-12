"""
Data fetching module — NYC rental listings.

Primary (no key needed):
  StreetEasy    — scraped via modules/scraper.py
  Apartments.com — scraped via modules/scraper.py

Supplemental (API keys required):
  Rentcast API  (rentcast.io)
  Zillow via RapidAPI  (zillow-com1.p.rapidapi.com)

Each function returns a list of normalised listing dicts:
  address, rent, bedrooms, unit_type, building_name,
  lat, lon, url, photos, source, sqft, days_on_market
"""

import math
import time
from typing import Optional
import requests
import pandas as pd

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

UNIT_ORDER = ["Studio", "1 Bed", "2 Bed", "3 Bed", "4+ Bed"]

_BED_LABEL = {0: "Studio", 1: "1 Bed", 2: "2 Bed", 3: "3 Bed"}


def bed_label(beds) -> str:
    try:
        b = int(beds)
        if b >= 4:
            return "4+ Bed"
        return _BED_LABEL.get(b, f"{b} Bed")
    except (TypeError, ValueError):
        return "Unknown"


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------------------------
# Rentcast API
# ---------------------------------------------------------------------------

def fetch_rentcast(
    lat: float,
    lon: float,
    radius_miles: float,
    api_key: str,
    bed_filter: Optional[list] = None,
) -> tuple[list, str]:
    """
    Fetch active long-term rental listings from Rentcast.
    Docs: https://developers.rentcast.io/reference/rental-listings

    Returns (listings, status) where status in {'live','partial','error','no_key'}
    """
    url = "https://api.rentcast.io/v1/listings/rental/long-term"
    headers = {"X-Api-Key": api_key, "accept": "application/json"}
    all_listings: list = []
    offset = 0
    limit = 500
    status = "live"

    while True:
        params = {
            "latitude": lat,
            "longitude": lon,
            "radius": radius_miles,
            "limit": limit,
            "offset": offset,
            "status": "Active",
        }
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=20)
            if resp.status_code == 429:
                time.sleep(2)
                resp = requests.get(url, headers=headers, params=params, timeout=20)
            if resp.status_code == 401:
                return [], "invalid_key"
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.Timeout:
            status = "partial"
            break
        except Exception:
            status = "partial"
            break

        if not data:
            break

        for item in data:
            beds = item.get("bedrooms") or 0
            rent = item.get("price") or item.get("rentPrice") or 0
            if not rent:
                continue

            utype = bed_label(beds)
            if bed_filter and utype not in bed_filter:
                continue

            item_lat = item.get("latitude") or lat
            item_lon = item.get("longitude") or lon

            all_listings.append({
                "address":       item.get("formattedAddress") or item.get("addressLine1", ""),
                "rent":          float(rent),
                "bedrooms":      int(beds),
                "unit_type":     utype,
                "building_name": item.get("propertyName") or "",
                "lat":           item_lat,
                "lon":           item_lon,
                "url":           item.get("listingUrl") or "",
                "photos":        item.get("photos") or [],
                "sqft":          item.get("squareFootage") or None,
                "days_on_market": item.get("daysOnMarket") or None,
                "source":        "Rentcast",
                "distance_miles": haversine_miles(lat, lon, item_lat, item_lon),
            })

        if len(data) < limit:
            break
        offset += limit

    return all_listings, status


# ---------------------------------------------------------------------------
# Zillow via RapidAPI
# ---------------------------------------------------------------------------

def fetch_zillow(
    lat: float,
    lon: float,
    radius_miles: float,
    api_key: str,
    bed_filter: Optional[list] = None,
) -> tuple[list, str]:
    """
    Fetch rental listings via Zillow Com1 on RapidAPI.
    Host: zillow-com1.p.rapidapi.com
    """
    url = "https://zillow-com1.p.rapidapi.com/propertyExtendedSearch"
    headers = {
        "X-RapidAPI-Key":  api_key,
        "X-RapidAPI-Host": "zillow-com1.p.rapidapi.com",
    }
    params = {
        "location":    f"{lat},{lon}",
        "status_type": "ForRent",
        "home_type":   "Apartments,Condos,Townhomes,Multi-family",
        "sort":        "Newest",
        "page":        "1",
    }
    listings: list = []
    status = "live"

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=20)
        if resp.status_code == 429:
            time.sleep(2)
            resp = requests.get(url, headers=headers, params=params, timeout=20)
        if resp.status_code in (401, 403):
            return [], "invalid_key"
        resp.raise_for_status()
        props = resp.json().get("props") or []
    except requests.exceptions.Timeout:
        return [], "partial"
    except Exception:
        return [], "error"

    for item in props:
        item_lat = item.get("latitude") or 0
        item_lon = item.get("longitude") or 0
        if not item_lat:
            continue

        dist = haversine_miles(lat, lon, item_lat, item_lon)
        if dist > radius_miles:
            continue

        beds_raw = item.get("bedrooms") or 0
        utype = bed_label(beds_raw)
        if bed_filter and utype not in bed_filter:
            continue

        rent = item.get("price") or 0
        if not rent:
            continue

        detail_path = item.get("detailUrl", "")
        listing_url = f"https://www.zillow.com{detail_path}" if detail_path else ""

        photos = [item["imgSrc"]] if item.get("imgSrc") else []

        listings.append({
            "address":        item.get("address") or "",
            "rent":           float(rent),
            "bedrooms":       int(beds_raw),
            "unit_type":      utype,
            "building_name":  item.get("buildingName") or "",
            "lat":            item_lat,
            "lon":            item_lon,
            "url":            listing_url,
            "photos":         photos,
            "sqft":           item.get("livingArea") or None,
            "days_on_market": item.get("daysOnMarket") or None,
            "source":         "Zillow",
            "distance_miles": dist,
        })

    return listings, status


# ---------------------------------------------------------------------------
# Deduplication & cleaning
# ---------------------------------------------------------------------------

def _dedup(listings: list) -> list:
    """Remove near-duplicate listings (same address + ±$50 rent bucket)."""
    seen: set = set()
    out: list = []
    for l in listings:
        key = (
            l["address"].lower().strip()[:45],
            round(l["rent"] / 50) * 50,
            l["bedrooms"],
        )
        if key not in seen:
            seen.add(key)
            out.append(l)
    return out


def _remove_outliers(listings: list) -> list:
    """
    IQR-based outlier removal per unit_type.
    Hard floor: $500/mo.  Hard ceiling: $60,000/mo (ultra-luxury).
    """
    if not listings:
        return listings
    df = pd.DataFrame(listings)
    df = df[(df["rent"] >= 500) & (df["rent"] <= 60_000)]
    cleaned: list = []
    for utype, grp in df.groupby("unit_type"):
        q1 = grp["rent"].quantile(0.05)
        q3 = grp["rent"].quantile(0.95)
        iqr = q3 - q1
        low  = max(q1 - 3 * iqr, 500)
        high = q3 + 3 * iqr
        filtered = grp[(grp["rent"] >= low) & (grp["rent"] <= high)]
        cleaned.extend(filtered.to_dict("records"))
    return cleaned


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def fetch_all_listings(
    lat: float,
    lon: float,
    radius_miles: float,
    proxy_key: Optional[str] = None,
) -> tuple[list, dict]:
    """
    Pull from all residential rental sources, merge, deduplicate, and clean.
    Sources: StreetEasy, Apartments.com, Craigslist, Zumper, RentHop,
             Redfin, Realtor.com, LeaseBreak

    Returns (listings, status_dict).
    status values: 'live' | 'partial' | 'blocked' | 'error' | 'no_results'
    """
    from modules.scraper import (
        scrape_streeteasy,
        scrape_apartments_com,
        scrape_craigslist,
        scrape_zumper,
        scrape_renthop,
    )
    from modules.redfin_scraper import scrape_redfin
    from modules.extended_scrapers import scrape_realtor_com, scrape_leasebreak

    raw: list = []
    status: dict = {
        "streeteasy":    "pending",
        "apartments":    "pending",
        "craigslist":    "pending",
        "zumper":        "pending",
        "renthop":       "pending",
        "redfin":        "pending",
        "realtor":       "pending",
        "leasebreak":    "pending",
        "overall":       "no_data",
        "_counts": {
            "streeteasy": 0,
            "apartments": 0,
            "craigslist": 0,
            "zumper":     0,
            "renthop":    0,
            "redfin":     0,
            "realtor":    0,
            "leasebreak": 0,
        },
    }

    # ── StreetEasy ──────────────────────────────────────────────────────────────
    se_listings, se_status = scrape_streeteasy(lat, lon, radius_miles, None, proxy_key=proxy_key)
    status["streeteasy"] = se_status if se_listings else (
        se_status if se_status != "live" else "no_results"
    )
    raw.extend(se_listings)
    status["_counts"]["streeteasy"] = len(se_listings)

    # ── Apartments.com ─────────────────────────────────────────────────────────
    ap_listings, ap_status = scrape_apartments_com(lat, lon, radius_miles, None, proxy_key=proxy_key)
    status["apartments"] = ap_status if ap_listings else (
        ap_status if ap_status != "live" else "no_results"
    )
    raw.extend(ap_listings)
    status["_counts"]["apartments"] = len(ap_listings)

    # ── Craigslist ─────────────────────────────────────────────────────────────
    cl_listings, cl_status = scrape_craigslist(lat, lon, radius_miles, None, proxy_key=proxy_key)
    status["craigslist"] = cl_status if cl_listings else (
        cl_status if cl_status != "live" else "no_results"
    )
    raw.extend(cl_listings)
    status["_counts"]["craigslist"] = len(cl_listings)

    # ── Zumper ─────────────────────────────────────────────────────────────────
    zu_listings, zu_status = scrape_zumper(lat, lon, radius_miles, None, proxy_key=proxy_key)
    status["zumper"] = zu_status if zu_listings else (
        zu_status if zu_status != "live" else "no_results"
    )
    raw.extend(zu_listings)
    status["_counts"]["zumper"] = len(zu_listings)

    # ── RentHop ────────────────────────────────────────────────────────────────
    rh_listings, rh_status = scrape_renthop(lat, lon, radius_miles, None, proxy_key=proxy_key)
    status["renthop"] = rh_status if rh_listings else (
        rh_status if rh_status != "live" else "no_results"
    )
    raw.extend(rh_listings)
    status["_counts"]["renthop"] = len(rh_listings)

    # ── Redfin ─────────────────────────────────────────────────────────────────
    try:
        rf_listings, rf_status = scrape_redfin(lat, lon, radius_miles, proxy_key=proxy_key)
        status["redfin"] = rf_status if rf_listings else (
            rf_status if rf_status != "live" else "no_results"
        )
        raw.extend(rf_listings)
        status["_counts"]["redfin"] = len(rf_listings)
    except Exception:
        status["redfin"] = "error"

    # ── Realtor.com ────────────────────────────────────────────────────────────
    try:
        rc_listings, rc_status = scrape_realtor_com(lat, lon, radius_miles, proxy_key=proxy_key)
        status["realtor"] = rc_status if rc_listings else (
            rc_status if rc_status != "live" else "no_results"
        )
        raw.extend(rc_listings)
        status["_counts"]["realtor"] = len(rc_listings)
    except Exception:
        status["realtor"] = "error"

    # ── LeaseBreak ─────────────────────────────────────────────────────────────
    try:
        lb_listings, lb_status = scrape_leasebreak(lat, lon, radius_miles, proxy_key=proxy_key)
        status["leasebreak"] = lb_status if lb_listings else (
            lb_status if lb_status != "live" else "no_results"
        )
        raw.extend(lb_listings)
        status["_counts"]["leasebreak"] = len(lb_listings)
    except Exception:
        status["leasebreak"] = "error"

    if not raw:
        status["overall"] = "no_data"
        return [], status

    cleaned = _dedup(raw)
    cleaned = _remove_outliers(cleaned)
    cleaned.sort(key=lambda x: x.get("distance_miles") or 0)

    # Normalize unified schema fields
    for l in cleaned:
        l.setdefault("asset_type", "Residential Rental")
        l.setdefault("price", l.get("rent"))
        l.setdefault("price_psf", None)
        l.setdefault("date", None)

    primary_sources = ("streeteasy", "apartments", "craigslist", "zumper", "renthop",
                       "redfin", "realtor", "leasebreak")
    all_active = [status[k] for k in primary_sources]
    if any(s == "live" for s in all_active):
        status["overall"] = "live"
    elif any(s == "partial" for s in all_active):
        status["overall"] = "partial"
    else:
        status["overall"] = "no_data"

    return cleaned, status


# ---------------------------------------------------------------------------
# Commercial comps (LoopNet + Crexi + Craigslist commercial)
# ---------------------------------------------------------------------------

def fetch_commercial_listings(
    lat: float,
    lon: float,
    radius_miles: float,
    proxy_key: Optional[str] = None,
) -> tuple[list, dict]:
    """
    Fetch commercial lease comps from LoopNet, Crexi, CommercialEdge,
    and Craigslist commercial.
    Returns (listings, status_dict).
    """
    from modules.loopnet_scraper import fetch_commercial_listings as _loopnet_fetch
    from modules.commercial_scraper import fetch_commercial_comps
    from modules.extended_scrapers import scrape_commercial_edge

    all_listings: list[dict] = []
    status: dict = {
        "loopnet":         "pending",
        "crexi":           "pending",
        "craigslist_comm": "pending",
        "commercial_edge": "pending",
        "overall":         "no_data",
    }

    ln_listings, ln_status = _loopnet_fetch(lat, lon, radius_miles, proxy_key)
    status["loopnet"] = ln_status.get("loopnet", ln_status) if isinstance(ln_status, dict) else ln_status
    status["crexi"]   = ln_status.get("crexi",   "pending") if isinstance(ln_status, dict) else "pending"
    all_listings.extend(ln_listings)

    cl_comm, cl_comm_status = fetch_commercial_comps(lat, lon, radius_miles, proxy_key)
    status["craigslist_comm"] = cl_comm_status.get("overall", "no_data")
    for item in cl_comm:
        item.setdefault("asset_type", item.get("use_type", "Commercial"))
        item.setdefault("price", item.get("rent"))
        item.setdefault("price_psf", item.get("psf_yr"))
        item.setdefault("date", None)
        item.setdefault("bedrooms", 0)
        item.setdefault("building_name", "")
        item.setdefault("photos", [])
        item.setdefault("days_on_market", None)
    all_listings.extend(cl_comm)

    # CommercialEdge
    try:
        ce_listings, ce_status = scrape_commercial_edge(lat, lon, radius_miles, proxy_key)
        status["commercial_edge"] = ce_status
        for item in ce_listings:
            item.setdefault("date", None)
            item.setdefault("bedrooms", 0)
            item.setdefault("building_name", item.get("building_name", ""))
            item.setdefault("photos", [])
        all_listings.extend(ce_listings)
    except Exception:
        status["commercial_edge"] = "error"

    if all_listings:
        status["overall"] = "live"
    elif any(v in ("blocked",) for v in status.values()):
        status["overall"] = "blocked"
    else:
        status["overall"] = "no_results"

    return all_listings, status


# ---------------------------------------------------------------------------
# Sales comps (NYC Rolling Sales)
# ---------------------------------------------------------------------------

def fetch_sales_comps(
    lat: float,
    lon: float,
    radius_miles: float,
    zip_code: Optional[str] = None,
    neighborhood: Optional[str] = None,
) -> tuple[list, str]:
    """
    Fetch closed sale comps from NYC Rolling Sales dataset.
    Returns (listings, status).
    """
    from modules.nyc_sales_fetcher import fetch_nyc_sales
    return fetch_nyc_sales(lat, lon, radius_miles, zip_code=zip_code, neighborhood=neighborhood)


# ---------------------------------------------------------------------------
# DOB development pipeline
# ---------------------------------------------------------------------------

def fetch_dob_pipeline(
    lat: float,
    lon: float,
    radius_miles: float,
) -> tuple[list, str]:
    """
    Fetch NYC DOB new-building and major-alteration permits within the radius.
    Returns (listings, status).
    """
    from modules.nyc_sales_fetcher import fetch_dob_permits
    return fetch_dob_permits(lat, lon, radius_miles)


# ---------------------------------------------------------------------------
# Tax abatement / rent stabilization / transit / demographics signals
# ---------------------------------------------------------------------------

def fetch_tax_abatement_signal(prop: dict) -> dict:
    """Rules-based tax abatement (485-x/J-51/ICAP) signal for a property.
    Pure calculation, no network call — see modules/abatement_estimator.py."""
    from modules.abatement_estimator import estimate_tax_abatement
    return estimate_tax_abatement(prop)


def fetch_rent_stabilization_signal(prop: dict) -> dict:
    """Rules-based rent-stabilization signal for a property.
    Pure calculation, no network call — see modules/rent_stab_estimator.py."""
    from modules.rent_stab_estimator import estimate_rent_stabilization
    return estimate_rent_stabilization(prop)


def fetch_transit_proximity(lat: float, lon: float) -> dict:
    """Nearest-subway-station distance for a lat/lon point.
    See modules/transit_fetcher.py."""
    from modules.transit_fetcher import fetch_transit_proximity as _f
    return _f(lat, lon)


def fetch_demographics(zip_code: str) -> dict:
    """ZCTA-level population & median household income.
    See modules/demographics_fetcher.py."""
    from modules.demographics_fetcher import fetch_demographics as _f
    return _f(zip_code)

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
    rentcast_key: Optional[str] = None,
    rapidapi_key: Optional[str] = None,
    bed_filter: Optional[list] = None,
) -> tuple[list, dict]:
    """
    Pull from all sources, merge, deduplicate, and clean.

    Scraping (StreetEasy, Apartments.com, Craigslist, Zumper, RentHop) runs
    automatically — no keys needed.
    Rentcast and Zillow/RapidAPI are optional supplements when keys are provided.

    Returns (listings, status_dict).
    status values: 'live' | 'partial' | 'blocked' | 'error' | 'no_key' | 'no_results'
    """
    from modules.scraper import (
        scrape_streeteasy,
        scrape_apartments_com,
        scrape_craigslist,
        scrape_zumper,
        scrape_renthop,
    )

    raw: list = []
    status: dict = {
        "streeteasy":    "pending",
        "apartments":    "pending",
        "craigslist":    "pending",
        "zumper":        "pending",
        "renthop":       "pending",
        "rentcast":      "no_key",
        "zillow":        "no_key",
        "overall":       "no_data",
    }

    # ── Primary: scrape StreetEasy ─────────────────────────────────────────────
    se_listings, se_status = scrape_streeteasy(lat, lon, radius_miles, bed_filter)
    status["streeteasy"] = se_status if se_listings else (
        se_status if se_status != "live" else "no_results"
    )
    raw.extend(se_listings)

    # ── Primary: scrape Apartments.com ────────────────────────────────────────
    ap_listings, ap_status = scrape_apartments_com(lat, lon, radius_miles, bed_filter)
    status["apartments"] = ap_status if ap_listings else (
        ap_status if ap_status != "live" else "no_results"
    )
    raw.extend(ap_listings)

    # ── Primary: scrape Craigslist ────────────────────────────────────────────
    cl_listings, cl_status = scrape_craigslist(lat, lon, radius_miles, bed_filter)
    status["craigslist"] = cl_status if cl_listings else (
        cl_status if cl_status != "live" else "no_results"
    )
    raw.extend(cl_listings)

    # ── Primary: scrape Zumper ────────────────────────────────────────────────
    zu_listings, zu_status = scrape_zumper(lat, lon, radius_miles, bed_filter)
    status["zumper"] = zu_status if zu_listings else (
        zu_status if zu_status != "live" else "no_results"
    )
    raw.extend(zu_listings)

    # ── Primary: scrape RentHop ───────────────────────────────────────────────
    rh_listings, rh_status = scrape_renthop(lat, lon, radius_miles, bed_filter)
    status["renthop"] = rh_status if rh_listings else (
        rh_status if rh_status != "live" else "no_results"
    )
    raw.extend(rh_listings)

    # ── Supplemental: Rentcast API (if key provided) ──────────────────────────
    if rentcast_key:
        rc_listings, rc_status = fetch_rentcast(lat, lon, radius_miles, rentcast_key, bed_filter)
        status["rentcast"] = rc_status if rc_listings else (
            rc_status if rc_status != "live" else "no_results"
        )
        raw.extend(rc_listings)

    # ── Supplemental: Zillow/RapidAPI (if key provided) ───────────────────────
    if rapidapi_key:
        zl_listings, zl_status = fetch_zillow(lat, lon, radius_miles, rapidapi_key, bed_filter)
        status["zillow"] = zl_status if zl_listings else (
            zl_status if zl_status != "live" else "no_results"
        )
        raw.extend(zl_listings)

    if not raw:
        status["overall"] = "no_data"
        return [], status

    cleaned = _dedup(raw)
    cleaned = _remove_outliers(cleaned)
    cleaned.sort(key=lambda x: x["distance_miles"])

    scraper_statuses = [status[k] for k in ("streeteasy", "apartments", "craigslist", "zumper", "renthop")]
    api_statuses = [status[k] for k in ("rentcast", "zillow") if status[k] != "no_key"]
    all_active = scraper_statuses + api_statuses
    if any(s == "live" for s in all_active):
        status["overall"] = "live"
    elif any(s == "partial" for s in all_active):
        status["overall"] = "partial"
    else:
        status["overall"] = "no_data"

    return cleaned, status

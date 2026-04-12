"""
LoopNet + Crexi Commercial Scrapers — NYC commercial listings.

Scrapes LoopNet HTML search results and hits Crexi's public JSON API
to surface commercial/retail/office lease comps. No API key required.

Returns listings in the unified schema with asset_type (Office, Retail, Industrial).

Status codes returned:
  'live'       — listings retrieved successfully
  'blocked'    — bot-detection / access denied
  'no_results' — request succeeded but zero listings found
  'error'      — unexpected exception
"""

from __future__ import annotations
import math
import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

try:
    from modules.scraper import _bbox, _make_session, _proxy_get, _is_blocked, _haversine
except ImportError:
    def _bbox(lat, lon, radius_miles):
        lat_d = radius_miles / 69.0
        lon_d = radius_miles / (69.0 * math.cos(math.radians(lat)))
        return (round(lat+lat_d,6), round(lon+lon_d,6),
                round(lat-lat_d,6), round(lon-lon_d,6))
    def _haversine(lat1, lon1, lat2, lon2):
        R = 3958.8
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp = math.radians(lat2-lat1); dl = math.radians(lon2-lon1)
        a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
        return R*2*math.atan2(math.sqrt(a), math.sqrt(1-a))
    def _is_blocked(resp):
        return resp.status_code in (403, 429, 503)
    def _make_session():
        return requests.Session()
    def _proxy_get(url, session, **kw):
        return session.get(url, timeout=kw.get("timeout", 20))

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

_BLDG_TYPE_MAP = {
    "office":         "Office",
    "retail":         "Retail",
    "industrial":     "Industrial",
    "flex":           "Flex / Industrial",
    "mixed":          "Mixed Use",
    "multifamily":    "Multi-Family",
    "land":           "Land",
    "hospitality":    "Hospitality",
    "healthcare":     "Healthcare",
    "specialty":      "Specialty",
}


def _classify_type(text: str) -> str:
    t = text.lower()
    for k, v in _BLDG_TYPE_MAP.items():
        if k in t:
            return v
    return "Commercial"


def _parse_psf(text: str) -> Optional[float]:
    """Extract $/SF/yr from text like '$42.00/SF/YR' or '42 psf'."""
    m = re.search(r"\$\s*([\d,.]+)\s*(?:/\s*sf|psf|per\s*sf)", text, re.I)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            pass
    return None


def _parse_sqft(text: str) -> Optional[int]:
    m = re.search(r"([\d,]+)\s*(?:sq\.?\s*ft|sqft|SF|square\s*feet)", text, re.I)
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            pass
    return None


def _parse_rent(text: str) -> Optional[float]:
    m = re.search(r"\$\s*([\d,]+)", text.replace(",", ""))
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            pass
    return None


# ── LoopNet ───────────────────────────────────────────────────────────────────

def scrape_loopnet(
    lat: float,
    lon: float,
    radius_miles: float,
    proxy_key: Optional[str] = None,
) -> tuple[list, str]:
    """
    Scrape LoopNet NYC commercial lease listings.
    Returns (listings, status).
    """
    session = _make_session()
    listings: list[dict] = []

    # LoopNet search URL for NYC commercial leases
    search_url = "https://www.loopnet.com/search/commercial-real-estate/new-york-ny/for-lease/"
    params = {
        "c": "3",
        "siteid": "0",
        "searchtype": "for-lease",
        "mradius": f"{radius_miles:.1f}",
        "lat": f"{lat:.6f}",
        "lng": f"{lon:.6f}",
    }

    try:
        resp = _proxy_get(search_url, session, proxy_key=proxy_key, timeout=25,
                          params=params)
    except Exception:
        return [], "error"

    if _is_blocked(resp):
        return [], "blocked"

    try:
        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.select(
            "article.placard, li.placard, div[data-testid='placard'], "
            "div.PropertyCard, article[data-listing-id]"
        )

        for card in cards[:40]:
            try:
                title_el = card.select_one(
                    ".placard-title, .PropertyCard-title, h3, h4, [data-testid='address']"
                )
                price_el = card.select_one(
                    ".placard-price, .PropertyCard-price, .price, [data-testid='price']"
                )
                meta_el  = card.select_one(
                    ".placard-meta, .PropertyCard-details, .property-details"
                )
                type_el  = card.select_one(
                    ".property-type, .placard-type, [data-testid='property-type']"
                )
                link_el  = card.select_one("a[href]")

                title     = title_el.get_text(strip=True) if title_el else ""
                price_txt = price_el.get_text(strip=True)  if price_el else ""
                meta_txt  = meta_el.get_text(" ", strip=True) if meta_el else ""
                type_txt  = type_el.get_text(strip=True) if type_el else ""
                link      = link_el["href"] if link_el else ""
                if link and not link.startswith("http"):
                    link = "https://www.loopnet.com" + link

                psf  = _parse_psf(price_txt) or _parse_psf(meta_txt)
                sqft = _parse_sqft(meta_txt) or _parse_sqft(title)
                rent_mo = _parse_rent(price_txt)
                if not psf and not sqft and not rent_mo:
                    continue

                asset_type = _classify_type(type_txt or title)

                listings.append({
                    "address":        title[:80] if title else "—",
                    "rent":           rent_mo,
                    "price":          rent_mo,
                    "price_psf":      psf,
                    "sqft":           sqft,
                    "asset_type":     asset_type,
                    "unit_type":      asset_type,
                    "bedrooms":       0,
                    "building_name":  "",
                    "source":         "LoopNet",
                    "url":            link,
                    "lat":            lat,
                    "lon":            lon,
                    "distance_miles": None,
                    "days_on_market": None,
                    "photos":         [],
                    "date":           None,
                })
            except Exception:
                continue
    except Exception:
        return [], "error"

    return listings, ("live" if listings else "no_results")


# ── Crexi ─────────────────────────────────────────────────────────────────────

def scrape_crexi(
    lat: float,
    lon: float,
    radius_miles: float,
    proxy_key: Optional[str] = None,
) -> tuple[list, str]:
    """
    Query Crexi's public search API for commercial lease listings.
    Returns (listings, status).
    """
    ne_lat, ne_lng, sw_lat, sw_lng = _bbox(lat, lon, radius_miles)

    headers = {
        **_HEADERS,
        "Content-Type": "application/json",
        "Origin":        "https://www.crexi.com",
        "Referer":       "https://www.crexi.com/",
    }
    payload = {
        "transactionType": "lease",
        "bounds": {
            "northEastLat":  ne_lat,
            "northEastLong": ne_lng,
            "southWestLat":  sw_lat,
            "southWestLong": sw_lng,
        },
        "take":    50,
        "skip":    0,
        "markets": ["New York"],
    }

    try:
        resp = requests.post(
            "https://api.crexi.com/assets/search",
            json=payload,
            headers=headers,
            timeout=20,
        )
        if _is_blocked(resp):
            return [], "blocked"
        data = resp.json()
    except Exception:
        # Try alternate endpoint
        try:
            resp2 = requests.get(
                "https://api.crexi.com/assets",
                params={
                    "transactionType": "lease",
                    "lat": lat, "lng": lon, "radius": radius_miles,
                    "take": 50,
                },
                headers=headers,
                timeout=20,
            )
            if _is_blocked(resp2):
                return [], "blocked"
            data = resp2.json()
        except Exception:
            return [], "error"

    assets = (
        data.get("assets")
        or data.get("results")
        or data.get("data", {}).get("assets")
        or []
    )

    listings: list[dict] = []
    for a in assets:
        try:
            item_lat = float(a.get("latitude") or a.get("lat") or lat)
            item_lon = float(a.get("longitude") or a.get("lng") or lon)
            dist = _haversine(lat, lon, item_lat, item_lon)
            if dist > radius_miles:
                continue

            price_raw = a.get("askingPrice") or a.get("listPrice") or a.get("price")
            psf_raw   = a.get("pricePerSqFt") or a.get("psfRate")
            sqft_raw  = a.get("totalSqFt") or a.get("sqFt") or a.get("size")

            rent_mo = float(price_raw) if price_raw else None
            psf     = float(psf_raw)   if psf_raw   else None
            sqft    = int(float(sqft_raw)) if sqft_raw else None

            if not rent_mo and not psf and not sqft:
                continue

            type_raw   = (a.get("propertyType") or a.get("assetType") or "Commercial")
            asset_type = _classify_type(str(type_raw))
            address    = (
                a.get("address", {}).get("address1")
                or a.get("streetAddress")
                or a.get("name")
                or "—"
            )
            url_slug   = a.get("url") or a.get("slug") or ""
            url = f"https://www.crexi.com/properties/{url_slug}" if url_slug else ""

            listings.append({
                "address":        str(address)[:80],
                "rent":           rent_mo,
                "price":          rent_mo,
                "price_psf":      psf,
                "sqft":           sqft,
                "asset_type":     asset_type,
                "unit_type":      asset_type,
                "bedrooms":       0,
                "building_name":  a.get("name", ""),
                "source":         "Crexi",
                "url":            url,
                "lat":            item_lat,
                "lon":            item_lon,
                "distance_miles": round(dist, 3),
                "days_on_market": a.get("daysOnMarket"),
                "photos":         [],
                "date":           None,
            })
        except Exception:
            continue

    return listings, ("live" if listings else "no_results")


# ── Orchestrator ──────────────────────────────────────────────────────────────

def fetch_commercial_listings(
    lat: float,
    lon: float,
    radius_miles: float,
    proxy_key: Optional[str] = None,
) -> tuple[list, dict]:
    """
    Fetch commercial lease comps from LoopNet + Crexi.
    Returns (listings, status_dict).
    """
    status: dict = {
        "loopnet":  "pending",
        "crexi":    "pending",
        "overall":  "no_data",
    }
    all_listings: list[dict] = []

    ln_listings, ln_status = scrape_loopnet(lat, lon, radius_miles, proxy_key)
    status["loopnet"] = ln_status
    all_listings.extend(ln_listings)

    time.sleep(0.4)

    cx_listings, cx_status = scrape_crexi(lat, lon, radius_miles, proxy_key)
    status["crexi"] = cx_status
    all_listings.extend(cx_listings)

    if all_listings:
        status["overall"] = "live"
    elif any(s == "blocked" for s in (ln_status, cx_status)):
        status["overall"] = "blocked"
    else:
        status["overall"] = "no_results"

    return all_listings, status

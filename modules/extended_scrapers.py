"""
Extended Scrapers — additional residential and commercial listing sources.

Residential:
  - Realtor.com    (public JSON search API)
  - LeaseBreak.com (HTML scraper)

Commercial:
  - CommercialEdge (public search API)
  - PropertyShark  (HTML scraper, limited)

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
    from modules.scraper import _bbox, _make_session, _proxy_get, _is_blocked, _haversine, _bed_label
except ImportError:
    def _bbox(lat, lon, radius_miles):
        lat_d = radius_miles / 69.0
        lon_d = radius_miles / (69.0 * math.cos(math.radians(lat)))
        return (round(lat + lat_d, 6), round(lon + lon_d, 6),
                round(lat - lat_d, 6), round(lon - lon_d, 6))
    def _haversine(lat1, lon1, lat2, lon2):
        R = 3958.8
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp = math.radians(lat2 - lat1); dl = math.radians(lon2 - lon1)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    def _is_blocked(resp):
        return resp.status_code in (403, 429, 503)
    def _make_session():
        return requests.Session()
    def _proxy_get(url, session, **kw):
        return session.get(url, timeout=kw.get("timeout", 20))
    def _bed_label(beds):
        m = {0: "Studio", 1: "1 Bed", 2: "2 Bed", 3: "3 Bed"}
        return "4+ Bed" if beds >= 4 else m.get(beds, f"{beds} Bed")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "application/json, text/html, */*",
}


# ─────────────────────────────────────────────────────────────────────────────
# Realtor.com
# ─────────────────────────────────────────────────────────────────────────────

_REALTOR_API = "https://www.realtor.com/api/v1/rdc_search_srp"


def scrape_realtor_com(
    lat: float,
    lon: float,
    radius_miles: float,
    proxy_key: Optional[str] = None,
) -> tuple[list, str]:
    """
    Fetch rental listings from Realtor.com via their internal SRP API.
    Returns (listings, status).
    """
    ne_lat, ne_lng, sw_lat, sw_lng = _bbox(lat, lon, radius_miles)

    payload = {
        "query": {
            "type": "for_rent",
            "search_location": {
                "location": f"{lat},{lon}",
            },
            "coordinates": {
                "lat_max": ne_lat,
                "lat_min": sw_lat,
                "lon_max": ne_lng,
                "lon_min": sw_lng,
            },
            "radius": str(radius_miles),
        },
        "client_data": {"device_data": {"device_type": "web"}},
        "limit": 200,
        "offset": 0,
        "sort": [{"field": "list_date", "direction": "desc"}],
        "schema": "v2",
    }
    headers = {
        **_HEADERS,
        "Content-Type": "application/json",
        "Origin": "https://www.realtor.com",
        "Referer": "https://www.realtor.com/apartments/",
    }

    listings: list[dict] = []
    try:
        resp = requests.post(_REALTOR_API, json=payload, headers=headers, timeout=20)
        if _is_blocked(resp):
            return [], "blocked"
        data = resp.json()
    except Exception:
        # Fallback: try the search endpoint via GET with lat/lng bbox
        try:
            alt_url = "https://www.realtor.com/api/v1/hulk"
            params = {
                "client_id": "rdc-x",
                "limit": "42",
                "offset": "0",
                "status": "for_rent",
                "coordinates": f"{sw_lat},{sw_lng},{ne_lat},{ne_lng}",
                "schema": "v2",
            }
            resp2 = requests.get(alt_url, headers=headers, params=params, timeout=20)
            if _is_blocked(resp2):
                return [], "blocked"
            data = resp2.json()
        except Exception:
            return [], "error"

    # Navigate to results list — structure varies by API version
    results = (
        data.get("data", {}).get("results")
        or data.get("results")
        or data.get("properties")
        or []
    )

    for item in results:
        try:
            loc = item.get("location", {}) or {}
            addr = loc.get("address", {}) or {}
            item_lat = float(
                item.get("location", {}).get("coordinate", {}).get("lat")
                or item.get("lat") or lat
            )
            item_lon = float(
                item.get("location", {}).get("coordinate", {}).get("lon")
                or item.get("lon") or lon
            )

            dist = _haversine(lat, lon, item_lat, item_lon)
            if dist > radius_miles:
                continue

            price_raw = (
                item.get("list_price")
                or item.get("price")
                or (item.get("price_reduced_amount") or 0)
            )
            rent = float(price_raw) if price_raw else 0.0
            if not rent:
                continue

            beds_raw = item.get("description", {}).get("beds") or 0
            baths    = item.get("description", {}).get("baths") or 0
            sqft     = item.get("description", {}).get("sqft") or None

            street   = addr.get("line", "") or ""
            city     = addr.get("city", "") or ""
            state    = addr.get("state_code", "") or ""
            address  = f"{street}, {city}, {state}".strip(", ")

            detail_path = item.get("permalink") or item.get("property_id", "")
            url = f"https://www.realtor.com/apartments/{detail_path}" if detail_path else ""

            photos = []
            for ph in (item.get("photos") or [])[:3]:
                src = ph.get("href") or ph.get("url") or ""
                if src:
                    photos.append(src)

            beds = int(beds_raw) if beds_raw else 0
            listings.append({
                "address":        address[:80],
                "rent":           rent,
                "price":          rent,
                "bedrooms":       beds,
                "unit_type":      _bed_label(beds),
                "building_name":  item.get("community", {}).get("name", "") or "",
                "sqft":           float(sqft) if sqft else None,
                "price_psf":      round(rent / float(sqft), 2) if sqft and float(sqft) > 0 else None,
                "days_on_market": item.get("list_date_delta"),
                "lat":            item_lat,
                "lon":            item_lon,
                "url":            url,
                "photos":         photos,
                "source":         "Realtor.com",
                "asset_type":     "Residential Rental",
                "distance_miles": round(dist, 3),
                "date":           None,
            })
        except Exception:
            continue

    return listings, ("live" if listings else "no_results")


# ─────────────────────────────────────────────────────────────────────────────
# LeaseBreak.com
# ─────────────────────────────────────────────────────────────────────────────

_LEASEBREAK_URL = "https://www.leasebreak.com/listings"


def scrape_leasebreak(
    lat: float,
    lon: float,
    radius_miles: float,
    proxy_key: Optional[str] = None,
) -> tuple[list, str]:
    """
    Scrape LeaseBreak.com NYC listings (lease takeovers / sublets).
    Returns (listings, status).
    """
    session = _make_session()
    listings: list[dict] = []

    params = {
        "city":    "New York",
        "state":   "NY",
        "lat":     f"{lat:.6f}",
        "lng":     f"{lon:.6f}",
        "radius":  f"{radius_miles:.1f}",
        "sort":    "newest",
        "type":    "lease-transfer",
    }
    try:
        resp = _proxy_get(_LEASEBREAK_URL, session,
                          proxy_key=proxy_key, timeout=20, params=params)
    except Exception:
        return [], "error"

    if _is_blocked(resp):
        return [], "blocked"

    try:
        soup = BeautifulSoup(resp.text, "html.parser")
        # LeaseBreak listing cards
        cards = soup.select(
            "div.listing-card, article.listing, div[class*='listing'], "
            "div[data-listing], .property-card"
        )

        if not cards:
            # Try JSON embedded in page
            nd_match = re.search(r'"listings"\s*:\s*(\[.*?\])', resp.text, re.S)
            if nd_match:
                import json
                try:
                    raw_listings = json.loads(nd_match.group(1))
                    for item in raw_listings[:50]:
                        rent = float(item.get("price") or item.get("rent") or 0)
                        if not rent:
                            continue
                        beds = int(item.get("bedrooms") or item.get("beds") or 0)
                        item_lat = float(item.get("lat") or lat)
                        item_lon = float(item.get("lon") or item.get("lng") or lon)
                        dist = _haversine(lat, lon, item_lat, item_lon)
                        if dist > radius_miles:
                            continue
                        listings.append({
                            "address":        str(item.get("address") or "")[:80],
                            "rent":           rent,
                            "price":          rent,
                            "bedrooms":       beds,
                            "unit_type":      _bed_label(beds),
                            "building_name":  "",
                            "sqft":           None,
                            "price_psf":      None,
                            "days_on_market": None,
                            "lat":            item_lat,
                            "lon":            item_lon,
                            "url":            item.get("url") or "",
                            "photos":         [],
                            "source":         "LeaseBreak",
                            "asset_type":     "Residential Rental",
                            "distance_miles": round(dist, 3),
                            "date":           None,
                        })
                except Exception:
                    pass

        for card in cards[:60]:
            try:
                price_el  = card.select_one(".price, .rent, [class*='price'], [class*='rent']")
                addr_el   = card.select_one(".address, [class*='address'], [class*='street']")
                bed_el    = card.select_one("[class*='bed'], [class*='room']")
                link_el   = card.select_one("a[href]")

                rent_txt  = price_el.get_text(strip=True) if price_el else ""
                addr_txt  = addr_el.get_text(strip=True)  if addr_el  else ""
                bed_txt   = bed_el.get_text(strip=True)   if bed_el   else ""
                url       = link_el["href"] if link_el else ""
                if url and not url.startswith("http"):
                    url = "https://www.leasebreak.com" + url

                rent = 0.0
                m = re.search(r"\$\s*([\d,]+)", rent_txt.replace(",", ""))
                if m:
                    try:
                        rent = float(m.group(1).replace(",", ""))
                    except ValueError:
                        pass
                if not rent:
                    continue

                beds = 0
                bm = re.search(r"(\d+)\s*(?:bed|br)", bed_txt, re.I)
                if bm:
                    beds = int(bm.group(1))

                listings.append({
                    "address":        addr_txt[:80] or "—",
                    "rent":           rent,
                    "price":          rent,
                    "bedrooms":       beds,
                    "unit_type":      _bed_label(beds),
                    "building_name":  "",
                    "sqft":           None,
                    "price_psf":      None,
                    "days_on_market": None,
                    "lat":            lat,
                    "lon":            lon,
                    "url":            url,
                    "photos":         [],
                    "source":         "LeaseBreak",
                    "asset_type":     "Residential Rental",
                    "distance_miles": 0.0,
                    "date":           None,
                })
            except Exception:
                continue
    except Exception:
        return [], "error"

    return listings, ("live" if listings else "no_results")


# ─────────────────────────────────────────────────────────────────────────────
# CommercialEdge
# ─────────────────────────────────────────────────────────────────────────────

_CE_API = "https://www.commercialedge.com/api/search/listings"


def scrape_commercial_edge(
    lat: float,
    lon: float,
    radius_miles: float,
    proxy_key: Optional[str] = None,
) -> tuple[list, str]:
    """
    Fetch commercial lease listings from CommercialEdge public API.
    Returns (listings, status).
    """
    ne_lat, ne_lng, sw_lat, sw_lng = _bbox(lat, lon, radius_miles)

    headers = {
        **_HEADERS,
        "Content-Type": "application/json",
        "Origin":  "https://www.commercialedge.com",
        "Referer": "https://www.commercialedge.com/",
    }
    payload = {
        "transactionType": "lease",
        "propertyTypes":   ["office", "retail", "industrial", "flex"],
        "bounds": {
            "north": ne_lat, "south": sw_lat,
            "east":  ne_lng, "west":  sw_lng,
        },
        "market":  "New York, NY",
        "page":    1,
        "perPage": 50,
    }

    listings: list[dict] = []
    try:
        resp = requests.post(_CE_API, json=payload, headers=headers, timeout=20)
        if _is_blocked(resp):
            return [], "blocked"
        data = resp.json()
    except Exception:
        # Fallback: GET with query params
        try:
            resp2 = requests.get(
                "https://www.commercialedge.com/api/listings",
                headers=headers,
                params={
                    "lat": lat, "lng": lon,
                    "radius": radius_miles,
                    "transactionType": "lease",
                    "page": 1,
                },
                timeout=20,
            )
            if _is_blocked(resp2):
                return [], "blocked"
            data = resp2.json()
        except Exception:
            return [], "error"

    assets = (
        data.get("listings")
        or data.get("results")
        or data.get("data", [])
        or []
    )

    _type_map = {
        "office":     "Office",
        "retail":     "Retail",
        "industrial": "Industrial",
        "flex":       "Flex / Industrial",
        "mixed":      "Mixed Use",
        "multifamily":"Multi-Family",
    }

    for a in assets:
        try:
            item_lat = float(a.get("latitude") or a.get("lat") or lat)
            item_lon = float(a.get("longitude") or a.get("lng") or lon)
            dist = _haversine(lat, lon, item_lat, item_lon)
            if dist > radius_miles:
                continue

            psf_raw  = a.get("askingRentPerSqFt") or a.get("pricePerSqFt") or a.get("psf")
            sqft_raw = a.get("availableSpace") or a.get("sqFt") or a.get("size")
            rent_raw = a.get("askingRent") or a.get("price")

            psf  = float(psf_raw)   if psf_raw   else None
            sqft = int(float(sqft_raw)) if sqft_raw else None
            rent = float(rent_raw)  if rent_raw  else None

            if not psf and not sqft and not rent:
                continue

            ptype = str(a.get("propertyType") or a.get("type") or "").lower()
            asset_type = _type_map.get(ptype, "Commercial")

            address = (
                a.get("address") or a.get("streetAddress") or a.get("name") or "—"
            )
            url = a.get("url") or a.get("link") or ""
            if url and not url.startswith("http"):
                url = "https://www.commercialedge.com" + url

            listings.append({
                "address":        str(address)[:80],
                "rent":           rent,
                "price":          rent,
                "price_psf":      psf,
                "sqft":           sqft,
                "asset_type":     asset_type,
                "unit_type":      asset_type,
                "bedrooms":       0,
                "building_name":  a.get("buildingName") or "",
                "source":         "CommercialEdge",
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

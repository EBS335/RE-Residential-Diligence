"""
Redfin Scraper — NYC rental listings.

Uses Redfin's internal stingray GIS JSON API (no auth required).
Returns listings in the unified schema compatible with data_fetcher.py.

Status codes returned:
  'live'       — listings retrieved successfully
  'blocked'    — bot-detection / access denied
  'no_results' — request succeeded but zero listings found
  'error'      — unexpected exception
"""

from __future__ import annotations
import json
import re
import time
from typing import Optional

from modules.scraper import _bbox, _make_session, _proxy_get, _is_blocked, _haversine

_REDFIN_GIS_URL = "https://www.redfin.com/stingray/api/gis"
_REDFIN_SEARCH_URL = "https://www.redfin.com/stingray/api/gis-csv"


def _strip_jsonp(text: str) -> str:
    """Redfin prefixes responses with '{}&&' — strip it."""
    if text.startswith("{}&&"):
        return text[4:]
    return text


def scrape_redfin(
    lat: float,
    lon: float,
    radius_miles: float,
    proxy_key: Optional[str] = None,
) -> tuple[list, str]:
    """
    Fetch rental listings from Redfin's stingray GIS API.

    Returns (listings, status).
    Each listing has the unified schema:
      address, asset_type, price (rent/mo), beds, sqft, price_psf,
      source, url, lat, lon, distance_miles, days_on_market
    """
    ne_lat, ne_lng, sw_lat, sw_lng = _bbox(lat, lon, radius_miles)

    session = _make_session()
    session.headers.update({
        "Referer": "https://www.redfin.com/",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
    })

    params = {
        "al":          "1",
        "for_rent":    "true",
        "for_sale":    "false",
        "market":      "newyork",
        "num_homes":   "350",
        "ord":         "redfin-recommended-asc",
        "page_number": "1",
        "sf":          "1,2,3,5,6,7",
        "uipt":        "1,2,3,4,5,6",
        "v":           "8",
        "bounds":      f"{ne_lat},{ne_lng},{sw_lat},{sw_lng}",
    }

    try:
        resp = _proxy_get(_REDFIN_GIS_URL, session, proxy_key=proxy_key, timeout=20,
                          params=params)
    except Exception as exc:
        return [], "error"

    if _is_blocked(resp):
        return [], "blocked"

    try:
        raw = _strip_jsonp(resp.text.strip())
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return [], "error"

    # Navigate to homes list — varies by API version
    homes = (
        data.get("payload", {}).get("homes")
        or data.get("payload", {}).get("exactMatch", {}).get("homes")
        or data.get("homes")
        or []
    )

    if not homes:
        return [], "no_results"

    listings: list[dict] = []
    for h in homes:
        try:
            price_raw = (
                h.get("priceInfo", {}).get("amount")
                or h.get("price", {}).get("value")
                or 0
            )
            rent = float(price_raw) if price_raw else 0.0
            if not rent:
                continue

            beds_raw = (
                h.get("beds")
                or h.get("beds", {})
                or 0
            )
            beds = int(beds_raw) if isinstance(beds_raw, (int, float)) else 0

            sqft_raw = h.get("sqFt", {}).get("value") or h.get("sqFt") or None
            sqft = float(sqft_raw) if sqft_raw else None

            item_lat = float(h.get("latLong", {}).get("latitude") or h.get("lat") or lat)
            item_lon = float(h.get("latLong", {}).get("longitude") or h.get("lon") or lon)

            dist = _haversine(lat, lon, item_lat, item_lon)
            if dist > radius_miles:
                continue

            url_path = h.get("url") or ""
            url = f"https://www.redfin.com{url_path}" if url_path else ""

            price_psf = round(rent / sqft, 2) if sqft and sqft > 0 else None

            address = (
                h.get("streetLine", {}).get("value")
                or h.get("address", {}).get("streetAddress")
                or ""
            )

            listings.append({
                "address":        address,
                "rent":           rent,
                "price":          rent,
                "bedrooms":       beds,
                "asset_type":     "Residential Rental",
                "unit_type":      _bed_label(beds),
                "building_name":  "",
                "sqft":           sqft,
                "price_psf":      price_psf,
                "days_on_market": h.get("dom", {}).get("value"),
                "lat":            item_lat,
                "lon":            item_lon,
                "url":            url,
                "photos":         [h.get("primaryPhotoDisplayUrl")] if h.get("primaryPhotoDisplayUrl") else [],
                "source":         "Redfin",
                "distance_miles": round(dist, 3),
                "date":           None,
            })
        except Exception:
            continue

    return listings, ("live" if listings else "no_results")


def _bed_label(beds: int) -> str:
    _map = {0: "Studio", 1: "1 Bed", 2: "2 Bed", 3: "3 Bed"}
    if beds >= 4:
        return "4+ Bed"
    return _map.get(beds, f"{beds} Bed")

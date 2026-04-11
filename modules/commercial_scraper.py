"""
Commercial & Retail Comps Scraper — NYC Craigslist.

Scrapes Craigslist NYC commercial sections (office and retail/commercial)
to provide commercial and retail lease comparables. No API key required.

Returns listings in a normalized format compatible with the residential
comps schema, with an added 'use_type' field.
"""

from __future__ import annotations
import math
import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
_TIMEOUT = 12


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in miles between two lat/lon points."""
    R = 3958.8
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def _parse_rent(text: str) -> Optional[int]:
    """Extract a dollar amount from a string."""
    m = re.search(r"\$\s*([\d,]+)", text.replace(",", ""))
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            pass
    return None


def _parse_sqft(text: str) -> Optional[int]:
    """Extract square footage from listing text."""
    m = re.search(r"([\d,]+)\s*(?:sq\.?\s*ft|sqft|SF|square\s*feet)", text, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            pass
    return None


def _scrape_section(
    section: str,
    use_type: str,
    lat: float,
    lon: float,
    radius_miles: float,
    proxy_key: Optional[str] = None,
) -> list[dict]:
    """
    Scrape a single Craigslist commercial section.

    Args:
        section:      CL section code, e.g. 'off' (office) or 'com' (commercial/retail)
        use_type:     Display label, e.g. 'Office' or 'Retail/Commercial'
        lat, lon:     Subject property coordinates
        radius_miles: Search radius
        proxy_key:    Optional ScrapingBee key for proxy routing
    """
    results = []
    radius_km = radius_miles * 1.60934
    url = f"https://newyork.craigslist.org/search/{section}"
    params = {
        "search_distance": f"{radius_miles:.2f}",
        "postal": "10001",        # Manhattan ZIP as anchor (CL uses ZIP for proximity)
        "availabilityMode": "0",
        "sale_date": "all+dates",
    }

    try:
        if proxy_key:
            resp = requests.get(
                "https://app.scrapingbee.com/api/v1/",
                params={"api_key": proxy_key, "url": url + "?" + "&".join(f"{k}={v}" for k, v in params.items()), "render_js": "false"},
                timeout=_TIMEOUT + 10,
                headers=_HEADERS,
            )
        else:
            resp = requests.get(url, params=params, timeout=_TIMEOUT, headers=_HEADERS)

        if not resp.ok:
            return results

        soup = BeautifulSoup(resp.text, "html.parser")
        items = soup.select("li.cl-search-result, li.result-row")
        if not items:
            # Try alternate structure
            items = soup.select(".result-info")

        for item in items[:40]:
            try:
                title_el = item.select_one(".posting-title .label, .result-title, a.result-title")
                price_el = item.select_one(".priceinfo, .result-price")
                meta_el  = item.select_one(".meta, .result-meta")
                link_el  = item.select_one("a[href]")

                title = title_el.get_text(strip=True) if title_el else ""
                price_text = price_el.get_text(strip=True) if price_el else ""
                meta_text  = meta_el.get_text(" ", strip=True) if meta_el else ""
                link  = link_el["href"] if link_el else ""
                if link and not link.startswith("http"):
                    link = "https://newyork.craigslist.org" + link

                rent = _parse_rent(price_text) or _parse_rent(title)
                sqft = _parse_sqft(title) or _parse_sqft(meta_text)

                # Skip if no meaningful data
                if not rent and not sqft:
                    continue

                # Compute $/SF/yr if possible
                psf_yr = round(rent * 12 / sqft, 2) if rent and sqft and sqft > 0 else None

                results.append({
                    "address":        title[:80] if title else "—",
                    "rent":           rent,
                    "sqft":           sqft,
                    "psf_yr":         psf_yr,
                    "use_type":       use_type,
                    "source":         "Craigslist (Commercial)",
                    "url":            link,
                    "distance_miles": None,   # unknown without geocoding each listing
                    "beds":           "—",
                    "unit_type":      use_type,
                })
            except Exception:
                continue

    except Exception:
        pass

    return results


def fetch_commercial_comps(
    lat: float,
    lon: float,
    radius_miles: float,
    proxy_key: Optional[str] = None,
) -> tuple[list[dict], dict]:
    """
    Fetch commercial and retail comps from Craigslist NYC commercial sections.

    Returns (listings, status_dict).
    """
    status: dict = {"office": "pending", "retail": "pending", "overall": "no_data"}
    all_listings: list[dict] = []

    # Office section
    office = _scrape_section("off", "Office", lat, lon, radius_miles, proxy_key)
    status["office"] = "live" if office else "no_results"
    all_listings.extend(office)

    time.sleep(0.5)   # polite delay between requests

    # Commercial / Retail section
    retail = _scrape_section("com", "Retail / Commercial", lat, lon, radius_miles, proxy_key)
    status["retail"] = "live" if retail else "no_results"
    all_listings.extend(retail)

    if all_listings:
        status["overall"] = "live"
    else:
        status["overall"] = "no_results"

    return all_listings, status

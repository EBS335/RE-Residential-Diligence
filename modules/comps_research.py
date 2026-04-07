"""
Competing / Comparable Development Research.

Uses DuckDuckGo HTML search (free, no API key) + NYC GeoSearch to discover
recent or under-construction competing rental developments in the same
neighborhood, geocode them, and surface them in the app.

All results are cached in Streamlit session_state; only one search per
session per neighborhood to avoid rate-limiting.
"""

from __future__ import annotations

import re
import time
import html as _html
import requests
from bs4 import BeautifulSoup

# Reuse existing geocoder from the project
try:
    from modules.zola_fetcher import geosearch_bbl
except ImportError:
    geosearch_bbl = None  # type: ignore[assignment]

# ── Constants ──────────────────────────────────────────────────────────────────
_DDG_URL  = "https://html.duckduckgo.com/html/"
_TIMEOUT  = 12
_MAX_DEVS = 8
_SLEEP    = 1.5   # seconds between queries

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://duckduckgo.com/",
}

# NYC boroughs → neighbourhood centroids (lat, lon) for fallback geocoding
_BOROUGH_CENTROIDS = {
    "Manhattan":     (40.7831, -73.9712),
    "Brooklyn":      (40.6782, -73.9442),
    "Queens":        (40.7282, -73.7949),
    "Bronx":         (40.8448, -73.8648),
    "Staten Island": (40.5795, -74.1502),
}


# ── DuckDuckGo search ─────────────────────────────────────────────────────────

def _ddg_search(query: str) -> list[dict]:
    """
    Run a single DuckDuckGo HTML search and return list of
    {title, snippet, url} result dicts (up to 10 results).
    """
    try:
        resp = requests.post(
            _DDG_URL,
            data={"q": query, "b": "", "kl": "us-en"},
            headers=_HEADERS,
            timeout=_TIMEOUT,
            allow_redirects=True,
        )
        resp.raise_for_status()
    except Exception:
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    results = []

    for div in soup.select(".result"):
        title_el   = div.select_one(".result__title")
        snippet_el = div.select_one(".result__snippet")
        url_el     = div.select_one(".result__url")

        title   = title_el.get_text(" ", strip=True)   if title_el   else ""
        snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
        url_raw = url_el.get_text(" ", strip=True)     if url_el     else ""

        # DDG wraps the real URL in a redirect — extract from href
        a = div.select_one(".result__title a")
        url = ""
        if a and a.get("href"):
            href = a["href"]
            # "/l/?uddg=https%3A%2F%2F..." pattern
            m = re.search(r"uddg=([^&]+)", href)
            if m:
                import urllib.parse
                url = urllib.parse.unquote(m.group(1))
            else:
                url = href if href.startswith("http") else url_raw

        if title or snippet:
            results.append({
                "title":   _html.unescape(title),
                "snippet": _html.unescape(snippet),
                "url":     url,
            })

    return results


# ── Address / development parsing ─────────────────────────────────────────────

# Patterns that suggest a building/development name
_NAME_RE = re.compile(
    r'\b(?:The\s+\w[\w\s]{1,30}?|'           # "The Monarch at..."
    r'\d+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}|'  # "100 West 42nd..."
    r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\s+Towers?|'  # "Hudson Towers"
    r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\s+Residences?|'
    r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\s+Apartments?)\b'
)

# NYC street address patterns
_ADDR_RE = re.compile(
    r'\b(\d{1,5})\s+'                        # house number
    r'((?:West|East|North|South|W\.|E\.|N\.|S\.)\s+)?'
    r'(\d{1,3}(?:st|nd|rd|th)|\w+)\s+'      # street name
    r'(Street|St\.?|Avenue|Ave\.?|Boulevard|Blvd\.?|'
    r'Place|Pl\.?|Drive|Dr\.?|Road|Rd\.?|Lane|Ln\.?|'
    r'Broadway|Park|Way|Court|Ct\.?)\b',
    re.IGNORECASE,
)

_UNITS_RE  = re.compile(r'(\d{2,4})\s*(?:unit|apartment|home|residence)s?', re.IGNORECASE)
_RENT_RE   = re.compile(r'\$\s*(\d{1,3}(?:,\d{3})*|\d{3,4})\s*(?:/mo|per month)?', re.IGNORECASE)


def _parse_dev(title: str, snippet: str, url: str) -> dict | None:
    """
    Extract structured development info from a search result.
    Returns None if we can't extract a meaningful address.
    """
    combined = f"{title} {snippet}"

    # Building name
    name_m = _NAME_RE.search(combined)
    name   = name_m.group(0).strip() if name_m else title[:60].split(" - ")[0].strip()

    # Address
    addr_m = _ADDR_RE.search(combined)
    if not addr_m:
        return None
    address = addr_m.group(0).strip()

    # Unit count
    units_m = _UNITS_RE.search(combined)
    units   = int(units_m.group(1)) if units_m else None

    # Rent estimates
    rents = [int(r.replace(",", "")) for r in _RENT_RE.findall(combined)]
    rent_min = min(rents) if rents else None
    rent_max = max(rents) if rents else None

    return {
        "name":         name,
        "address":      address,
        "lat":          None,
        "lon":          None,
        "units":        units,
        "est_rent_min": rent_min,
        "est_rent_max": rent_max,
        "source_url":   url,
        "snippet":      snippet[:200],
    }


def _geocode_dev(dev: dict, neighborhood: str, borough: str) -> dict:
    """
    Add lat/lon to a development dict.
    Tries GeoSearch first; falls back to borough centroid.
    """
    if geosearch_bbl is None:
        clat, clon = _BOROUGH_CENTROIDS.get(borough, (40.7128, -74.0060))
        dev["lat"] = clat
        dev["lon"] = clon
        dev["geocoded"] = "centroid"
        return dev

    addr = f"{dev['address']}, {neighborhood}, {borough}, NY"
    try:
        geo = geosearch_bbl(addr)
        if geo and geo.get("lat") and geo.get("lon"):
            dev["lat"] = geo["lat"]
            dev["lon"] = geo["lon"]
            dev["geocoded"] = "geosearch"
            return dev
    except Exception:
        pass

    clat, clon = _BOROUGH_CENTROIDS.get(borough, (40.7128, -74.0060))
    dev["lat"] = clat
    dev["lon"] = clon
    dev["geocoded"] = "centroid"
    return dev


def _dedupe(devs: list[dict]) -> list[dict]:
    """Remove near-duplicate entries by address similarity."""
    seen: list[str] = []
    out:  list[dict] = []
    for dev in devs:
        addr_key = re.sub(r'\W+', '', dev["address"].lower())[:20]
        if any(addr_key in s or s in addr_key for s in seen):
            continue
        seen.append(addr_key)
        out.append(dev)
    return out


# ── Public API ────────────────────────────────────────────────────────────────

def search_competing_devs(
    neighborhood: str,
    borough: str,
    lat: float,
    lon: float,
    zip_code: str = "",
) -> list[dict]:
    """
    Discover competing/comparable rental developments near the subject property.

    Uses DuckDuckGo HTML search (no API key required) to find news articles,
    real estate filings, and developer websites, then extracts structured
    development data and geocodes each address.

    Returns up to 8 development dicts:
        {name, address, lat, lon, units, est_rent_min, est_rent_max, source_url, snippet, geocoded}

    Results should be cached by the caller (e.g. in st.session_state) to
    avoid repeated network calls.
    """
    queries = [
        f'"{neighborhood}" NYC new apartment development rental 2024 2025',
        f'"{neighborhood}" {borough} residential building construction "units" "stories"',
        (
            f'"{neighborhood}" NYC "new development" OR "under construction" OR "delivered" '
            f'site:therealdeal.com OR site:yimbynewyork.com OR site:commercialobserver.com '
            f'OR site:curbed.com OR site:6sqft.com OR site:nypost.com'
        ),
        f'"{neighborhood}" {borough} rental development 2023 2024 2025 apartments "new building"',
    ]
    if zip_code:
        queries.append(f'{zip_code} "new construction" apartment rental NYC site:streeteasy.com OR site:zillow.com')

    raw_results: list[dict] = []
    for q in queries[:4]:
        raw_results.extend(_ddg_search(q))
        time.sleep(_SLEEP)

    # Parse each result
    devs: list[dict] = []
    for r in raw_results:
        dev = _parse_dev(r["title"], r["snippet"], r["url"])
        if dev:
            devs.append(dev)

    # Deduplicate
    devs = _dedupe(devs)

    # Geocode (in order, up to _MAX_DEVS)
    geocoded: list[dict] = []
    for dev in devs[:_MAX_DEVS]:
        geocoded.append(_geocode_dev(dev, neighborhood, borough))

    return geocoded


def generate_pipeline_summary(devs: list[dict], neighborhood: str) -> str:
    """
    Generate a 2–3 sentence development pipeline summary from a list of devs.

    Args:
        devs: list returned by search_competing_devs()
        neighborhood: neighborhood name for context

    Returns a markdown-formatted summary string.
    """
    if not devs:
        return f"No competing developments identified in {neighborhood}."

    total = len(devs)
    geocoded = sum(1 for d in devs if d.get("geocoded"))
    total_units = sum(d.get("units", 0) or 0 for d in devs)

    # Categorize by snippet keywords
    _delivered, _pipeline, _planned = 0, 0, 0
    for d in devs:
        snip = (d.get("snippet", "") or "").lower()
        if any(kw in snip for kw in ("delivered", "complete", "opened", "leasing")):
            _delivered += 1
        elif any(kw in snip for kw in ("under construction", "construction", "breaking ground")):
            _pipeline += 1
        elif any(kw in snip for kw in ("planned", "proposed", "approved", "permit")):
            _planned += 1

    parts = [
        f"**{total} competing development{'s' if total != 1 else ''}** identified in {neighborhood}."
    ]
    if _delivered or _pipeline or _planned:
        status_parts = []
        if _delivered:
            status_parts.append(f"**{_delivered} recently delivered**")
        if _pipeline:
            status_parts.append(f"**{_pipeline} under construction**")
        if _planned:
            status_parts.append(f"**{_planned} planned/proposed**")
        parts.append(", ".join(status_parts) + ".")
    if total_units > 0:
        parts.append(f"Estimated **{total_units:,} total units** across identified projects.")

    return " ".join(parts)

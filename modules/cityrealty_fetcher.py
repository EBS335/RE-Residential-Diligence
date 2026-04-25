"""
CityRealty Comparable Building Fetcher.

Searches CityRealty.com for comparable buildings and recent transactions near
a given address/neighborhood using DuckDuckGo site-search (no API key needed).
Also attempts to query CityRealty's autocomplete endpoint for direct building
matches.

Returns up to 12 building results, each with:
    building_name   — building address or name
    address         — full street address
    neighborhood    — CityRealty neighborhood label
    link            — direct link to CityRealty building page
    history_link    — direct link to building's sales/rental history
    thumbnail       — thumbnail URL (if found)
    last_sale       — most recent sale price string (if found)
    listing_type    — "rental" | "condo" | "co-op" | "mixed" | "unknown"
    source          — always "CityRealty"
"""

from __future__ import annotations
import re
import time
import random
import urllib.parse
import requests
from bs4 import BeautifulSoup

_TIMEOUT   = 14
_CR_BASE   = "https://www.cityrealty.com"
_DDG_URL   = "https://html.duckduckgo.com/html/"
_AUTOCOMPLETE = "https://www.cityrealty.com/api/v1/autocomplete"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.cityrealty.com/",
}

# Neighbourhood slug overrides — maps common neighbourhood names to CityRealty slugs
_HOOD_SLUG: dict[str, str] = {
    "upper west side":        "upper-west-side",
    "upper east side":        "upper-east-side",
    "lower east side":        "lower-east-side",
    "east village":           "east-village",
    "west village":           "west-village",
    "greenwich village":      "greenwich-village",
    "hell's kitchen":         "hells-kitchen",
    "hells kitchen":          "hells-kitchen",
    "clinton hill":           "clinton-hill",
    "crown heights":          "crown-heights",
    "prospect heights":       "prospect-heights",
    "bedford stuyvesant":     "bed-stuy",
    "bed-stuy":               "bed-stuy",
    "east new york":          "east-new-york",
    "park slope":             "park-slope",
    "bay ridge":              "bay-ridge",
    "borough park":           "borough-park",
    "flatbush":               "flatbush",
    "flatlands":              "flatlands",
    "sunset park":            "sunset-park",
    "red hook":               "red-hook",
    "brownsville":            "brownsville",
    "williamsburg":           "williamsburg",
    "bushwick":               "bushwick",
    "astoria":                "astoria",
    "long island city":       "long-island-city",
    "lic":                    "long-island-city",
    "jackson heights":        "jackson-heights",
    "flushing":               "flushing",
    "forest hills":           "forest-hills",
    "jamaica":                "jamaica",
    "riverdale":              "riverdale",
    "fordham":                "fordham",
    "mott haven":             "mott-haven",
    "financial district":     "financial-district",
    "tribeca":                "tribeca",
    "soho":                   "soho",
    "nolita":                 "nolita",
    "little italy":           "little-italy",
    "chinatown":              "chinatown",
    "battery park city":      "battery-park-city",
    "midtown":                "midtown",
    "midtown west":           "midtown-west",
    "midtown east":           "midtown-east",
    "murray hill":            "murray-hill",
    "kips bay":               "kips-bay",
    "gramercy park":          "gramercy-park",
    "chelsea":                "chelsea",
    "flatiron":               "flatiron",
    "noho":                   "noho",
    "harlem":                 "harlem",
    "east harlem":            "east-harlem",
    "inwood":                 "inwood",
    "washington heights":     "washington-heights",
    "morningside heights":    "morningside-heights",
    "hamilton heights":       "hamilton-heights",
    "lenox hill":             "lenox-hill",
    "carnegie hill":          "carnegie-hill",
    "yorkville":              "yorkville",
}


def _hood_slug(neighborhood: str) -> str:
    """Convert a neighbourhood name to a CityRealty URL slug."""
    key = neighborhood.strip().lower()
    if key in _HOOD_SLUG:
        return _HOOD_SLUG[key]
    return re.sub(r"[^a-z0-9]+", "-", key).strip("-")


def _cr_neighborhood_urls(neighborhood: str) -> list[str]:
    """Build CityRealty search URLs for a neighbourhood."""
    slug = _hood_slug(neighborhood)
    return [
        f"{_CR_BASE}/nyc/{slug}/apt-for-rent/",
        f"{_CR_BASE}/nyc/{slug}/condo-for-sale/",
        f"{_CR_BASE}/nyc/{slug}/",
    ]


def _ddg_search(query: str, num: int = 10) -> list[dict]:
    """Search DuckDuckGo HTML for site:cityrealty.com results."""
    try:
        resp = requests.post(
            _DDG_URL,
            data={"q": f"site:cityrealty.com {query}", "b": "", "kl": "us-en"},
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        html = resp.text
    except Exception:
        return []

    results = []
    title_pat   = re.compile(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
    snippet_pat = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL)

    titles   = title_pat.findall(html)
    snippets = [re.sub(r"<[^>]+>", "", s).strip() for s in snippet_pat.findall(html)]

    for i, (url, title) in enumerate(titles[:num]):
        clean_title = re.sub(r"<[^>]+>", "", title).strip()
        snippet     = snippets[i] if i < len(snippets) else ""
        # Only keep building-level pages (not search pages)
        if "/building/" in url or ("/nyc/" in url and url.count("/") >= 5):
            results.append({"url": url, "title": clean_title, "snippet": snippet})

    return results


def _parse_cr_building_url(url: str) -> dict:
    """
    Parse a CityRealty building URL into components.
    Pattern: /nyc/{borough}/{street-slug}/building/{id}
    """
    m = re.search(
        r"/nyc/([^/]+)/([^/]+)/building(?:/(\d+))?",
        url,
    )
    if not m:
        return {"url": url, "neighborhood": "", "street_slug": "", "building_id": ""}

    neighborhood_slug = m.group(1)
    street_slug       = m.group(2)
    building_id       = m.group(3) or ""

    # Convert slugs to display text
    neighborhood = neighborhood_slug.replace("-", " ").title()
    address      = street_slug.replace("-", " ").title()

    history_link = f"{url}/sales" if building_id else url

    return {
        "url":           url,
        "history_link":  history_link,
        "neighborhood":  neighborhood,
        "address":       address,
        "building_id":   building_id,
        "street_slug":   street_slug,
    }


def _autocomplete(query: str) -> list[dict]:
    """Try CityRealty autocomplete API for building matches."""
    try:
        resp = requests.get(
            _AUTOCOMPLETE,
            params={"q": query, "type": "building"},
            headers=_HEADERS,
            timeout=8,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        results = []
        for item in (data.get("results") or data.get("buildings") or [])[:8]:
            addr  = item.get("address") or item.get("title") or ""
            bld_id = item.get("id") or item.get("building_id") or ""
            hood  = item.get("neighborhood") or ""
            slug  = item.get("slug") or re.sub(r"[^a-z0-9]+", "-", addr.lower())
            hood_slug_v = _hood_slug(hood) if hood else "nyc"
            link  = (
                item.get("url")
                or f"{_CR_BASE}/nyc/{hood_slug_v}/{slug}/building/{bld_id}"
            )
            results.append({
                "building_name": addr,
                "address":       addr,
                "neighborhood":  hood,
                "link":          link,
                "history_link":  f"{link}/sales",
                "listing_type":  item.get("type", "unknown"),
                "last_sale":     item.get("last_sale_price", ""),
                "thumbnail":     item.get("image_url") or item.get("thumbnail") or "",
                "source":        "CityRealty",
            })
        return results
    except Exception:
        return []


def fetch_cityrealty_comps(
    address: str,
    neighborhood: str,
    borough: str = "Manhattan",
    lat: float = 0.0,
    lon: float = 0.0,
) -> tuple[list[dict], dict]:
    """
    Fetch CityRealty comparable buildings for the given address/neighbourhood.

    Returns (comps_list, status_dict).
    Each comp dict has keys listed in module docstring.
    status_dict has key "status": "live" | "partial" | "no_results" | "error"
    """
    comps: list[dict] = []
    seen_links: set[str] = set()

    def _add(item: dict) -> None:
        link = item.get("link") or item.get("url") or ""
        canonical = link.rstrip("/").split("?")[0]
        if canonical and canonical not in seen_links:
            seen_links.add(canonical)
            # Ensure required keys
            item.setdefault("building_name", item.get("address", ""))
            item.setdefault("source", "CityRealty")
            item.setdefault("listing_type", "unknown")
            item.setdefault("history_link", link)
            item.setdefault("thumbnail", "")
            item.setdefault("last_sale", "")
            comps.append(item)

    # ── Step 1: Autocomplete by address ─────────────────────────────────────
    short_addr = re.sub(r",\s*(New York|NY|Brooklyn|Queens|Bronx|Staten Island).*", "", address)
    for ac in _autocomplete(short_addr):
        _add(ac)

    time.sleep(random.uniform(0.3, 0.6))

    # ── Step 2: DuckDuckGo site:cityrealty.com search ────────────────────────
    hood_slug_v = _hood_slug(neighborhood)
    queries = [
        f'"{neighborhood}" "{short_addr}" building',
        f"{neighborhood} {borough} buildings rentals",
        f"{neighborhood} condos for sale buildings",
    ]

    for q in queries:
        if len(comps) >= 12:
            break
        for hit in _ddg_search(q, num=6):
            url = hit.get("url", "")
            if not url or "cityrealty.com" not in url:
                continue
            info = _parse_cr_building_url(url)
            title   = hit.get("title", "")
            snippet = hit.get("snippet", "")
            # Extract last-sale price from snippet if present
            sale_match = re.search(r"\$[\d,]+(?:\s*M)?", snippet)
            last_sale  = sale_match.group(0) if sale_match else ""
            _add({
                "building_name": title or info.get("address", ""),
                "address":       info.get("address", "") or title,
                "neighborhood":  info.get("neighborhood", "") or neighborhood,
                "link":          url,
                "history_link":  info.get("history_link", url),
                "last_sale":     last_sale,
                "snippet":       snippet,
                "listing_type":  "condo" if "condo" in url.lower() or "sale" in url.lower() else "rental",
                "source":        "CityRealty",
            })
        time.sleep(random.uniform(0.4, 0.8))

    # ── Step 3: Neighbourhood browse URLs ────────────────────────────────────
    cr_hood_url_rent = f"{_CR_BASE}/nyc/{hood_slug_v}/apt-for-rent/"
    cr_hood_url_sale = f"{_CR_BASE}/nyc/{hood_slug_v}/condo-for-sale/"

    if not comps:
        status = "no_results"
    elif len(comps) < 4:
        status = "partial"
    else:
        status = "live"

    return comps, {
        "status":          status,
        "hood_rent_url":   cr_hood_url_rent,
        "hood_sale_url":   cr_hood_url_sale,
        "cr_search_url":   f"{_CR_BASE}/nyc/search?q={urllib.parse.quote(short_addr)}",
        "total":           len(comps),
    }

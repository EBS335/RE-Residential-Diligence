"""
Web scraper for NYC rental listings.

Targets StreetEasy and Apartments.com — the two dominant NYC rental platforms.
Neither has a public API; this module scrapes their search results with
proper rate-limiting and graceful fallback when bot-detection blocks the request.

Status codes returned:
  'live'       — listings retrieved successfully
  'partial'    — some pages fetched before being blocked/timed out
  'blocked'    — Cloudflare / CAPTCHA challenge detected
  'no_results' — request succeeded but zero matching listings found
  'timeout'    — network timeout
  'error'      — unexpected exception
"""

import json
import math
import random
import re
import time
from typing import Optional

# curl_cffi gives us Chrome-accurate TLS fingerprinting (JA3/JA3S), which
# bypasses bot-detection systems that flag the default requests TLS handshake.
try:
    from curl_cffi import requests as _cf_requests  # type: ignore
    _USE_CURL = True
except ImportError:
    import requests as _cf_requests  # type: ignore
    _USE_CURL = False

import requests as _plain_requests  # used for ScrapingBee proxy calls
from bs4 import BeautifulSoup

# ── Rotating User-Agent pool ──────────────────────────────────────────────────
_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
]

# ── Base browser headers (User-Agent injected per-session) ───────────────────
_HEADERS = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
}

_BED_MAP = {0: "Studio", 1: "1 Bed", 2: "2 Bed", 3: "3 Bed"}


# ═════════════════════════════════════════════════════════════════════════════
# Shared helpers
# ═════════════════════════════════════════════════════════════════════════════

def _bed_label(beds) -> str:
    try:
        b = int(beds)
        return "4+ Bed" if b >= 4 else _BED_MAP.get(b, f"{b} Bed")
    except (TypeError, ValueError):
        return "Unknown"


def _bbox(lat: float, lon: float, radius_miles: float) -> tuple:
    """Return (ne_lat, ne_lng, sw_lat, sw_lng) bounding box."""
    lat_d = radius_miles / 69.0
    lon_d = radius_miles / (69.0 * math.cos(math.radians(lat)))
    return (
        round(lat + lat_d, 6), round(lon + lon_d, 6),
        round(lat - lat_d, 6), round(lon - lon_d, 6),
    )


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _make_session():
    """
    Create a curl_cffi session impersonating Chrome 124 (best TLS fingerprint),
    or fall back to a plain requests.Session if curl_cffi is unavailable.
    A random User-Agent is chosen per session.
    """
    if _USE_CURL:
        sess = _cf_requests.Session()
        sess.impersonate = "chrome124"
    else:
        sess = _plain_requests.Session()
    sess.headers.update({**_HEADERS, "User-Agent": random.choice(_USER_AGENTS)})
    return sess


def _proxy_get(url: str, session, proxy_key: Optional[str] = None,
               render_js: bool = False, timeout: int = 20, **kwargs):
    """
    Make a GET request.
    - If proxy_key is provided: route through ScrapingBee (bypasses IP blocks).
    - Otherwise: use the curl_cffi / requests session directly.
    """
    if proxy_key:
        params = {
            "api_key": proxy_key,
            "url": url,
            "render_js": "true" if render_js else "false",
            "block_resources": "false",
        }
        return _plain_requests.get(
            "https://app.scrapingbee.com/api/v1/",
            params=params,
            timeout=60,
        )
    return session.get(url, timeout=timeout, **kwargs)


def _is_blocked(resp) -> bool:
    """Detect Cloudflare / bot-protection challenge pages."""
    if resp.status_code in (403, 429, 503):
        return True
    snip = resp.text[:4000].lower()
    return any(kw in snip for kw in (
        "cf-browser-verification", "just a moment", "enable javascript",
        "captcha", "ddos-guard", "access denied", "verifying you are human",
        "checking your browser", "ray id",
    ))


def _extract_price(text: str) -> int:
    """Parse '$2,500/mo' → 2500.  Returns 0 on failure."""
    digits = re.sub(r"[^\d]", "", text.split("/")[0] if "/" in text else text)
    return int(digits) if digits else 0


def _first_photo(tag) -> str:
    """Return first non-placeholder <img> src found inside a BS4 tag."""
    for img in tag.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
        if src.startswith("http") and "placeholder" not in src.lower():
            return src
    return ""


# ═════════════════════════════════════════════════════════════════════════════
# StreetEasy
# ═════════════════════════════════════════════════════════════════════════════

def _se_from_next_data(data: dict, clat: float, clon: float,
                        bed_filter: Optional[list]) -> list:
    """
    Parse listings out of StreetEasy's __NEXT_DATA__ JSON blob.
    The schema has changed over time so we try several known paths.
    """
    listings: list = []
    try:
        pp = data.get("props", {}).get("pageProps", {})
        raw = (
            pp.get("listings")
            or pp.get("searchResults", {}).get("listings")
            or pp.get("initialData", {}).get("listings")
            or pp.get("data", {}).get("listings")
            or []
        )
        for item in raw:
            beds  = item.get("bedrooms") or item.get("beds") or 0
            utype = _bed_label(beds)
            if bed_filter and utype not in bed_filter:
                continue
            rent = (
                item.get("price")
                or item.get("rental_price")
                or item.get("rentPrice")
                or 0
            )
            if not rent or float(rent) < 500:
                continue

            ilat = float(item.get("latitude") or item.get("lat") or clat)
            ilon = float(item.get("longitude") or item.get("lng") or clon)

            addr = (
                item.get("full_street_address")
                or item.get("address")
                or item.get("streetAddress")
                or ""
            )
            lid  = item.get("id") or item.get("listing_id") or ""
            url  = f"https://streeteasy.com/rental/{lid}" if lid else ""

            raw_photos = item.get("photos") or item.get("images") or []
            photos = []
            for p in raw_photos:
                src = p.get("src") or p.get("url") if isinstance(p, dict) else p
                if isinstance(src, str) and src.startswith("http"):
                    photos.append(src)

            listings.append({
                "address":        addr,
                "rent":           float(rent),
                "bedrooms":       int(beds),
                "unit_type":      utype,
                "building_name":  item.get("building_name") or item.get("buildingName") or "",
                "lat":            ilat,
                "lon":            ilon,
                "url":            url,
                "photos":         photos[:5],
                "sqft":           item.get("square_footage") or item.get("sqft") or None,
                "days_on_market": item.get("days_on_market") or item.get("daysOnMarket") or None,
                "source":         "StreetEasy",
                "distance_miles": _haversine(clat, clon, ilat, ilon),
            })
    except Exception:
        pass
    return listings


def _se_from_card(card, clat: float, clon: float,
                   bed_filter: Optional[list]) -> Optional[dict]:
    """Parse one StreetEasy HTML listing card."""
    try:
        # Data attributes (preferred — more reliable than text parsing)
        lid      = card.get("data-listing-id") or ""
        price_da = card.get("data-price") or ""
        beds_da  = card.get("data-bedrooms") or card.get("data-beds") or ""
        ilat     = float(card.get("data-lat") or clat)
        ilon     = float(card.get("data-lng") or clon)

        rent = _extract_price(price_da)
        if not rent:
            # Fallback: look for price text in the card
            pt = card.find(class_=re.compile(r"price|Price|rent|Rent", re.I))
            rent = _extract_price(pt.get_text()) if pt else 0
        if rent < 500:
            return None

        beds = int(re.sub(r"\D", "", beds_da) or "0") if beds_da else 0
        if not beds_da:
            bt = card.find(class_=re.compile(r"bed|Bed", re.I))
            m  = re.search(r"(\d+)", bt.get_text()) if bt else None
            beds = int(m.group(1)) if m else 0

        utype = _bed_label(beds)
        if bed_filter and utype not in bed_filter:
            return None

        at    = card.find(class_=re.compile(r"address|Address|street|Street", re.I))
        addr  = at.get_text(strip=True) if at else ""

        photo = _first_photo(card)
        url   = f"https://streeteasy.com/rental/{lid}" if lid else ""

        return {
            "address":        addr,
            "rent":           float(rent),
            "bedrooms":       beds,
            "unit_type":      utype,
            "building_name":  "",
            "lat":            ilat,
            "lon":            ilon,
            "url":            url,
            "photos":         [photo] if photo else [],
            "sqft":           None,
            "days_on_market": None,
            "source":         "StreetEasy",
            "distance_miles": _haversine(clat, clon, ilat, ilon),
        }
    except Exception:
        return None


def scrape_streeteasy(
    lat: float,
    lon: float,
    radius_miles: float,
    bed_filter: Optional[list] = None,
    proxy_key: Optional[str] = None,
) -> tuple[list, str]:
    """
    Scrape StreetEasy rental search results within the bounding box.
    Tries __NEXT_DATA__ JSON first, falls back to HTML card parsing.
    """
    ne_lat, ne_lng, sw_lat, sw_lng = _bbox(lat, lon, radius_miles)

    session = _make_session()
    session.headers.update({"Referer": "https://streeteasy.com/"})

    # Warm-up: visit homepage to get session cookies (reduces bot score)
    try:
        _proxy_get("https://streeteasy.com", session, proxy_key=proxy_key,
                   timeout=10, allow_redirects=True)
        time.sleep(1.0)
    except Exception:
        pass

    listings: list = []

    for page in range(1, 6):
        try:
            url = (
                "https://streeteasy.com/for-rent/nyc"
                f"?search%5Bstatus%5D=1"
                f"&search%5Bne_lat%5D={ne_lat}"
                f"&search%5Bne_lng%5D={ne_lng}"
                f"&search%5Bsw_lat%5D={sw_lat}"
                f"&search%5Bsw_lng%5D={sw_lng}"
                f"&page={page}"
            )
            resp = _proxy_get(url, session, proxy_key=proxy_key, timeout=20)

            if _is_blocked(resp):
                status = "blocked" if not listings else "partial"
                return listings, status

            soup = BeautifulSoup(resp.text, "lxml")

            # ── Strategy 1: __NEXT_DATA__ JSON ───────────────────────────────
            nd_tag = soup.find("script", id="__NEXT_DATA__")
            if nd_tag and nd_tag.string:
                parsed = _se_from_next_data(
                    json.loads(nd_tag.string), lat, lon, bed_filter
                )
                listings.extend(parsed)
                if not parsed:
                    break   # last page
                time.sleep(0.7)
                continue

            # ── Strategy 2: HTML listing cards ───────────────────────────────
            cards = (
                soup.find_all(attrs={"data-listing-id": True})
                or soup.find_all("article", class_=re.compile(r"listingCard", re.I))
                or soup.find_all("div",     class_=re.compile(r"listingCard", re.I))
            )
            if not cards:
                break

            for card in cards:
                item = _se_from_card(card, lat, lon, bed_filter)
                if item:
                    listings.append(item)

            time.sleep(0.7)

        except _plain_requests.exceptions.Timeout:
            return listings, "timeout" if not listings else "partial"
        except Exception:
            return listings, "error" if not listings else "partial"

    return listings, ("live" if listings else "no_results")


# ═════════════════════════════════════════════════════════════════════════════
# Apartments.com
# ═════════════════════════════════════════════════════════════════════════════

def _apts_from_json(data: dict, clat: float, clon: float,
                     bed_filter: Optional[list]) -> list:
    """Parse Apartments.com embedded JSON data."""
    listings: list = []
    items = (
        data.get("properties")
        or data.get("listings")
        or data.get("results")
        or []
    )
    for item in items:
        try:
            rent = (
                item.get("rentRange", {}).get("min")
                or item.get("price")
                or item.get("rentPrice")
                or 0
            )
            if not rent or float(rent) < 500:
                continue
            beds  = item.get("beds") or item.get("bedrooms") or 0
            utype = _bed_label(beds)
            if bed_filter and utype not in bed_filter:
                continue

            ilat = float(item.get("latitude") or clat)
            ilon = float(item.get("longitude") or clon)
            pid  = item.get("propertyId") or item.get("id") or ""
            url  = item.get("url") or (
                f"https://www.apartments.com/{pid}" if pid else ""
            )
            raw_photos = item.get("photos") or []
            photos = []
            for p in raw_photos:
                src = p.get("src") or p.get("url") if isinstance(p, dict) else p
                if isinstance(src, str) and src.startswith("http"):
                    photos.append(src)

            listings.append({
                "address":        item.get("streetAddress") or item.get("address") or "",
                "rent":           float(rent),
                "bedrooms":       int(beds),
                "unit_type":      utype,
                "building_name":  item.get("propertyName") or item.get("name") or "",
                "lat":            ilat,
                "lon":            ilon,
                "url":            url,
                "photos":         photos[:5],
                "sqft":           item.get("sqft") or item.get("squareFeet") or None,
                "days_on_market": item.get("daysOnMarket") or None,
                "source":         "Apartments.com",
                "distance_miles": _haversine(clat, clon, ilat, ilon),
            })
        except Exception:
            continue
    return listings


def _apts_from_card(card, clat: float, clon: float,
                     bed_filter: Optional[list]) -> Optional[dict]:
    """Parse an Apartments.com HTML property card."""
    try:
        lid  = card.get("data-listingid") or card.get("id") or ""
        ilat = float(card.get("data-latitude") or clat)
        ilon = float(card.get("data-longitude") or clon)

        # Price
        pt = (
            card.find("p", class_=re.compile(r"price|Price|rent|Rent", re.I))
            or card.find(class_=re.compile(r"price|Price|rent|Rent", re.I))
        )
        rent = _extract_price(pt.get_text()) if pt else 0
        if rent < 500:
            return None

        # Beds
        bt = card.find(class_=re.compile(r"bed|Bed", re.I))
        m  = re.search(r"(\d+)", bt.get_text()) if bt else None
        beds = int(m.group(1)) if m else 0
        utype = _bed_label(beds)
        if bed_filter and utype not in bed_filter:
            return None

        # Address / building name
        at   = card.find(class_=re.compile(r"property-title|title|address", re.I))
        addr = at.get_text(strip=True) if at else ""

        # Link
        a_tag = card.find("a", href=re.compile(r"apartments\.com", re.I))
        url   = a_tag["href"] if a_tag and a_tag.get("href") else ""
        if url and not url.startswith("http"):
            url = "https://www.apartments.com" + url

        photo = _first_photo(card)

        return {
            "address":        addr,
            "rent":           float(rent),
            "bedrooms":       beds,
            "unit_type":      utype,
            "building_name":  "",
            "lat":            ilat,
            "lon":            ilon,
            "url":            url,
            "photos":         [photo] if photo else [],
            "sqft":           None,
            "days_on_market": None,
            "source":         "Apartments.com",
            "distance_miles": _haversine(clat, clon, ilat, ilon),
        }
    except Exception:
        return None


def scrape_apartments_com(
    lat: float,
    lon: float,
    radius_miles: float,
    bed_filter: Optional[list] = None,
    proxy_key: Optional[str] = None,
) -> tuple[list, str]:
    """
    Scrape Apartments.com rental results.
    Uses their bounding-box search URL + HTML card parsing.
    """
    ne_lat, ne_lng, sw_lat, sw_lng = _bbox(lat, lon, radius_miles)

    session = _make_session()
    session.headers.update({"Referer": "https://www.apartments.com/"})

    listings: list = []

    for page in range(1, 5):
        try:
            # bbox format: sw_lat,sw_lng,ne_lat,ne_lng
            bbox = f"{sw_lat},{sw_lng},{ne_lat},{ne_lng}"
            url  = f"https://www.apartments.com/new-york-ny/{page}/?bb={bbox}"

            resp = _proxy_get(url, session, proxy_key=proxy_key, timeout=20)

            if _is_blocked(resp):
                return listings, "blocked" if not listings else "partial"

            soup = BeautifulSoup(resp.text, "lxml")

            # ── Strategy 1: embedded JSON ─────────────────────────────────────
            for script in soup.find_all("script"):
                raw = script.string or ""
                # Apartments.com sometimes embeds a window.data object
                for pattern in (
                    r"window\.__listing_results\s*=\s*({.+?});\s*(?:window|var|let|const|</)",
                    r"window\.data\s*=\s*({.+?});\s*(?:window|var|let|const|</)",
                    r'"rentRange":\s*\{.{0,300}?"latitude"',   # detect listing JSON
                ):
                    match = re.search(pattern, raw, re.DOTALL)
                    if match:
                        try:
                            blob = re.search(r"\{.+\}", match.group(0), re.DOTALL)
                            if blob:
                                data = json.loads(blob.group(0))
                                parsed = _apts_from_json(data, lat, lon, bed_filter)
                                listings.extend(parsed)
                        except Exception:
                            pass

            # ── Strategy 2: HTML property cards ───────────────────────────────
            if not listings:
                cards = (
                    soup.find_all("article", class_=re.compile(r"placard", re.I))
                    or soup.find_all("li",    class_=re.compile(r"placard", re.I))
                    or soup.find_all(attrs={"data-listingid": True})
                )
                for card in cards:
                    item = _apts_from_card(card, lat, lon, bed_filter)
                    if item:
                        listings.append(item)

            # If no new listings were found, last page reached
            page_new = len(listings)
            if page_new == 0 and page > 1:
                break

            time.sleep(0.9)

        except _plain_requests.exceptions.Timeout:
            return listings, "timeout" if not listings else "partial"
        except Exception:
            return listings, "error" if not listings else "partial"

    return listings, ("live" if listings else "no_results")


# ═════════════════════════════════════════════════════════════════════════════
# Craigslist NYC
# Most reliable free source — simple HTML, minimal bot protection.
# ═════════════════════════════════════════════════════════════════════════════

def scrape_craigslist(
    lat: float,
    lon: float,
    radius_miles: float,
    bed_filter=None,
    proxy_key: Optional[str] = None,
):
    session = _make_session()
    session.headers.update({"Referer": "https://newyork.craigslist.org/"})
    listings = []

    for page_offset in range(0, 600, 120):
        try:
            params = {
                "lat": lat, "lon": lon,
                "search_distance": round(radius_miles, 2),
                "availabilityMode": 0, "s": page_offset,
                "lang": "en", "cc": "us",
            }
            resp = _proxy_get("https://newyork.craigslist.org/search/apa",
                              session, proxy_key=proxy_key, timeout=20, params=params)
            if _is_blocked(resp):
                return listings, "blocked" if not listings else "partial"

            soup = BeautifulSoup(resp.text, "lxml")
            cards = (
                soup.find_all("li", class_=re.compile(r"cl-search-result|cl-static-search-result", re.I))
                or soup.find_all("li", class_="result-row")
                or soup.find_all("li", attrs={"data-pid": True})
            )
            if not cards:
                break

            for card in cards:
                item = _parse_cl_card(card, lat, lon, bed_filter)
                if item:
                    listings.append(item)

            if len(cards) < 119:
                break
            time.sleep(0.6)
        except _plain_requests.exceptions.Timeout:
            return listings, "timeout" if not listings else "partial"
        except Exception:
            return listings, "error" if not listings else "partial"

    return listings, ("live" if listings else "no_results")


def _parse_cl_card(card, clat, clon, bed_filter):
    try:
        price_tag = (
            card.find(class_=re.compile(r"priceinfo|result-price|price", re.I))
            or card.find("span", string=re.compile(r"\$\d"))
        )
        rent = _extract_price(price_tag.get_text(strip=True)) if price_tag else 0
        if rent < 400:
            return None

        link_tag = (
            card.find("a", class_=re.compile(r"cl-app-anchor|result-title|posting-title", re.I))
            or card.find("a", href=re.compile(r"craigslist\.org"))
        )
        if not link_tag:
            return None
        title = link_tag.get_text(strip=True)
        url   = link_tag.get("href", "")
        if url and not url.startswith("http"):
            url = "https://newyork.craigslist.org" + url

        beds  = _beds_from_title(title)
        utype = _bed_label(beds)
        if bed_filter and utype not in bed_filter:
            return None

        hood_tag = card.find(class_=re.compile(r"result-hood|hood|meta", re.I))
        address  = hood_tag.get_text(strip=True).strip("()/ ") if hood_tag else title[:60]

        sqft_m = re.search(r"(\d{3,4})\s*(?:sq\s*ft|sf|sqft)", title, re.I)
        sqft   = int(sqft_m.group(1)) if sqft_m else None
        photo  = _first_photo(card)

        return {
            "address": address, "rent": float(rent), "bedrooms": beds,
            "unit_type": utype, "building_name": "", "lat": clat, "lon": clon,
            "url": url, "photos": [photo] if photo else [], "sqft": sqft,
            "days_on_market": None, "source": "Craigslist", "distance_miles": 0.0,
        }
    except Exception:
        return None


def _beds_from_title(title):
    t = title.lower()
    if re.search(r"\bstudio\b|\b0\s*br\b|\b0br\b", t):
        return 0
    m = re.search(r"(\d)\s*(?:br|bd|bed(?:room)?s?)\b", t)
    return min(int(m.group(1)), 5) if m else 1


# ═════════════════════════════════════════════════════════════════════════════
# Zumper NYC
# JSON-backed search with broad NYC inventory.
# ═════════════════════════════════════════════════════════════════════════════

def scrape_zumper(lat, lon, radius_miles, bed_filter=None, proxy_key=None):
    ne_lat, ne_lng, sw_lat, sw_lng = _bbox(lat, lon, radius_miles)
    session = _make_session()
    session.headers.update({
        "Referer": "https://www.zumper.com/apartments-for-rent/new-york-city-ny",
        "Accept":  "application/json, text/plain, */*",
    })
    listings = []
    _zb = {"Studio": 0, "1 Bed": 1, "2 Bed": 2, "3 Bed": 3, "4+ Bed": 4}
    bed_codes = [_zb[u] for u in (bed_filter or []) if u in _zb]

    try:
        params = {
            "min_price": 500, "max_price": 30000, "page": 1,
            "ne_lat": ne_lat, "ne_lng": ne_lng,
            "sw_lat": sw_lat, "sw_lng": sw_lng,
        }
        if bed_codes:
            params["beds"] = ",".join(str(b) for b in bed_codes)

        resp = _proxy_get("https://www.zumper.com/api/t/1/listings",
                          session, proxy_key=proxy_key, timeout=20, params=params)
        if _is_blocked(resp):
            return [], "blocked"
        if not resp.ok:
            return _zumper_html_fallback(lat, lon, session, bed_filter, proxy_key=proxy_key)

        data = resp.json()
        raw  = data if isinstance(data, list) else (
            data.get("listings") or data.get("data") or []
        )
        for item in raw:
            beds  = item.get("bedrooms") or item.get("beds") or 0
            utype = _bed_label(beds)
            if bed_filter and utype not in bed_filter:
                continue
            rent = item.get("price") or item.get("rent") or 0
            if not rent or float(rent) < 400:
                continue
            ilat = float(item.get("latitude") or item.get("lat") or lat)
            ilon = float(item.get("longitude") or item.get("lng") or lon)
            raw_p = item.get("photos") or []
            photos = []
            for p in raw_p:
                src = p.get("src") or p.get("url") if isinstance(p, dict) else p
                if isinstance(src, str) and src.startswith("http"):
                    photos.append(src)
            lid = item.get("id") or ""
            listings.append({
                "address": item.get("address") or item.get("street") or "",
                "rent": float(rent), "bedrooms": int(beds), "unit_type": utype,
                "building_name": item.get("name") or "",
                "lat": ilat, "lon": ilon,
                "url": f"https://www.zumper.com/apartments-for-rent/a{lid}" if lid else "",
                "photos": photos[:5], "sqft": item.get("sqft") or None,
                "days_on_market": item.get("days_on_market") or None,
                "source": "Zumper",
                "distance_miles": _haversine(lat, lon, ilat, ilon),
            })
    except Exception as _e:
        if "timeout" in str(_e).lower() or "timed out" in str(_e).lower():
            return [], "timeout"
        return _zumper_html_fallback(lat, lon, session, bed_filter, proxy_key=proxy_key)

    return listings, ("live" if listings else "no_results")


def _zumper_html_fallback(clat, clon, session, bed_filter, proxy_key=None):
    listings = []
    try:
        resp = _proxy_get(
            "https://www.zumper.com/apartments-for-rent/new-york-city-ny",
            session, proxy_key=proxy_key, timeout=20,
        )
        if _is_blocked(resp) or not resp.ok:
            return [], "blocked"
        soup = BeautifulSoup(resp.text, "lxml")
        nd = soup.find("script", id="__NEXT_DATA__")
        if not nd or not nd.string:
            return [], "no_results"
        data  = json.loads(nd.string)
        pp    = data.get("props", {}).get("pageProps", {})
        raw   = pp.get("listings") or pp.get("initialState", {}).get("listings", {}).get("list") or []
        for item in raw:
            beds  = item.get("bedrooms") or 0
            utype = _bed_label(beds)
            if bed_filter and utype not in bed_filter:
                continue
            rent = item.get("price") or 0
            if not rent or float(rent) < 400:
                continue
            ilat = float(item.get("latitude") or clat)
            ilon = float(item.get("longitude") or clon)
            lid  = item.get("id") or ""
            listings.append({
                "address": item.get("address") or "", "rent": float(rent),
                "bedrooms": int(beds), "unit_type": utype, "building_name": item.get("name") or "",
                "lat": ilat, "lon": ilon,
                "url": f"https://www.zumper.com/apartments-for-rent/a{lid}" if lid else "",
                "photos": [], "sqft": item.get("sqft") or None, "days_on_market": None,
                "source": "Zumper", "distance_miles": _haversine(clat, clon, ilat, ilon),
            })
    except Exception:
        pass
    return listings, ("live" if listings else "no_results")


# ═════════════════════════════════════════════════════════════════════════════
# RentHop NYC
# NYC-dedicated aggregator with landlord-direct + brokerage listings.
# ═════════════════════════════════════════════════════════════════════════════

def scrape_renthop(lat, lon, radius_miles, bed_filter=None, proxy_key=None):
    session = _make_session()
    session.headers.update({"Referer": "https://www.renthop.com/"})
    listings = []
    _rb = {"Studio": 0, "1 Bed": 1, "2 Bed": 2, "3 Bed": 3, "4+ Bed": 4}
    bed_params = [_rb[u] for u in (bed_filter or []) if u in _rb]

    for page in range(1, 6):
        try:
            params = {
                "lat": lat, "lon": lon, "radius": radius_miles,
                "page": page, "sort": "hopscore",
            }
            if bed_params:
                params["bedrooms[]"] = bed_params

            resp = _proxy_get("https://www.renthop.com/search/the-big-apple",
                              session, proxy_key=proxy_key, timeout=20, params=params)
            if _is_blocked(resp):
                return listings, "blocked" if not listings else "partial"

            soup = BeautifulSoup(resp.text, "lxml")
            nd = soup.find("script", id="__NEXT_DATA__")
            if nd and nd.string:
                parsed = _parse_renthop_nd(json.loads(nd.string), lat, lon, bed_filter)
                listings.extend(parsed)
                if not parsed:
                    break
                time.sleep(0.7)
                continue

            cards = (
                soup.find_all("div", class_=re.compile(r"listing-card|apartment-card", re.I))
                or soup.find_all("article")
            )
            if not cards:
                break
            for card in cards:
                item = _parse_renthop_card(card, lat, lon, bed_filter)
                if item:
                    listings.append(item)
            time.sleep(0.8)
        except _plain_requests.exceptions.Timeout:
            return listings, "timeout" if not listings else "partial"
        except Exception:
            return listings, "error" if not listings else "partial"

    return listings, ("live" if listings else "no_results")


def _parse_renthop_nd(data, clat, clon, bed_filter):
    listings = []
    try:
        pp  = data.get("props", {}).get("pageProps", {})
        raw = pp.get("listings") or pp.get("apartments") or []
        for item in raw:
            beds  = item.get("bedrooms") or 0
            utype = _bed_label(beds)
            if bed_filter and utype not in bed_filter:
                continue
            rent = item.get("price") or item.get("rent") or 0
            if not rent or float(rent) < 400:
                continue
            ilat = float(item.get("latitude") or item.get("lat") or clat)
            ilon = float(item.get("longitude") or item.get("lon") or clon)
            raw_p = item.get("photos") or item.get("images") or []
            photos = []
            for p in raw_p:
                src = p.get("url") or p.get("src") if isinstance(p, dict) else p
                if isinstance(src, str) and src.startswith("http"):
                    photos.append(src)
            lid = item.get("id") or item.get("listing_id") or ""
            listings.append({
                "address": item.get("address") or item.get("street_address") or "",
                "rent": float(rent), "bedrooms": int(beds), "unit_type": utype,
                "building_name": item.get("building_name") or "",
                "lat": ilat, "lon": ilon,
                "url": f"https://www.renthop.com/apartments/{lid}" if lid else "",
                "photos": photos[:5], "sqft": item.get("sqft") or None,
                "days_on_market": item.get("days_on_market") or None,
                "source": "RentHop",
                "distance_miles": _haversine(clat, clon, ilat, ilon),
            })
    except Exception:
        pass
    return listings


def _parse_renthop_card(card, clat, clon, bed_filter):
    try:
        pt   = card.find(class_=re.compile(r"price|rent", re.I))
        rent = _extract_price(pt.get_text()) if pt else 0
        if rent < 400:
            return None
        bt   = card.find(class_=re.compile(r"bed|room", re.I))
        m    = re.search(r"(\d+)", bt.get_text()) if bt else None
        beds = int(m.group(1)) if m else 1
        utype = _bed_label(beds)
        if bed_filter and utype not in bed_filter:
            return None
        at   = card.find(class_=re.compile(r"address|location|street", re.I))
        addr = at.get_text(strip=True) if at else ""
        link = card.find("a", href=re.compile(r"renthop\.com", re.I))
        url  = link["href"] if link else ""
        photo = _first_photo(card)
        return {
            "address": addr, "rent": float(rent), "bedrooms": beds,
            "unit_type": utype, "building_name": "", "lat": clat, "lon": clon,
            "url": url, "photos": [photo] if photo else [], "sqft": None,
            "days_on_market": None, "source": "RentHop", "distance_miles": 0.0,
        }
    except Exception:
        return None

"""
Nearby Developments — multi-source real estate development pipeline fetcher.

Sources (no API keys required):
  1. NYC DOB Permits   (ipu4-2q9a) — NB, A1, DM filings within radius
  2. Google News RSS   (news.google.com/rss) — keyword search by address
  3. The Real Deal RSS (therealdeal.com/feed)
  4. Commercial Observer RSS (commercialobserver.com/feed)
  5. Bisnow RSS        (bisnow.com/feed)

Each development record uses unified schema:
  address, project_name, developer, asset_type, status,
  units, sqft, filing_date, source, url, lat, lon, distance_miles

Status codes returned in status_dict:
  'live'       — results found
  'no_results' — request succeeded, nothing found
  'error'      — exception during fetch
  'blocked'    — HTTP 403/429
"""

from __future__ import annotations

import math
import re
import time
from datetime import datetime, timedelta
from typing import Optional

import requests

from modules.app_logging import record_source_status

# ── NYC DOB Permits ─────────────────────────────────────────────────────────

_DOB_URL = "https://data.cityofnewyork.us/resource/ipu4-2q9a.json"
_TIMEOUT = 15

_JOB_STATUS_MAP = {
    "NB": "Under Construction / Approved",
    "A1": "Major Alteration",
    "DM": "Demolition",
}

_ASSET_KEYWORDS = {
    "residential": ["residential", "apartment", "dwelling", "condo", "co-op",
                    "multifamily", "housing", "affordable", "senior"],
    "commercial":  ["commercial", "office", "hotel", "retail", "warehouse",
                    "industrial", "medical", "community facility"],
    "mixed-use":   ["mixed use", "mixed-use"],
}


def _classify_asset(text: str) -> str:
    t = text.lower()
    if any(k in t for k in _ASSET_KEYWORDS["mixed-use"]):
        return "Mixed Use"
    if any(k in t for k in _ASSET_KEYWORDS["residential"]):
        return "Residential"
    if any(k in t for k in _ASSET_KEYWORDS["commercial"]):
        return "Commercial"
    return "Unknown"


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _cutoff_date(months: int = 36) -> str:
    """ISO date string N months ago."""
    return (datetime.utcnow() - timedelta(days=months * 30)).strftime("%Y-%m-%d")


def _fetch_dob(lat: float, lon: float, radius_miles: float) -> tuple[list, str]:
    """Fetch NYC DOB NB/A1/DM permits within radius, last 36 months."""
    lat_d = radius_miles / 69.0
    lon_d = radius_miles / (69.0 * math.cos(math.radians(lat)))
    cutoff = _cutoff_date(36)

    params = {
        "$where": (
            f"gis_latitude  > {lat - lat_d:.6f} AND gis_latitude  < {lat + lat_d:.6f} "
            f"AND gis_longitude > {lon - lon_d:.6f} AND gis_longitude < {lon + lon_d:.6f} "
            f"AND job_type in('NB','A1','DM') "
            f"AND filing_date >= '{cutoff}'"
        ),
        "$select": (
            "job__,job_type,job_desc,job_status,house__,street_name,"
            "initial_cost,stories_prop,filing_date,gis_latitude,gis_longitude"
        ),
        "$order":  "filing_date DESC",
        "$limit":  "300",
    }
    try:
        resp = requests.get(_DOB_URL, params=params, timeout=_TIMEOUT)
        if resp.status_code in (403, 429):
            return [], "blocked"
        resp.raise_for_status()
        rows = resp.json()
    except Exception as exc:
        return [], f"error: {exc}"

    out: list[dict] = []
    for r in rows:
        try:
            item_lat = float(r.get("gis_latitude") or lat)
            item_lon = float(r.get("gis_longitude") or lon)
            dist = _haversine(lat, lon, item_lat, item_lon)
            if dist > radius_miles:
                continue

            house  = str(r.get("house__") or "").strip()
            street = str(r.get("street_name") or "").strip()
            addr   = f"{house} {street}".strip() or "—"

            jtype = str(r.get("job_type") or "").upper()
            desc  = str(r.get("job_desc") or "")

            cost_raw = r.get("initial_cost") or "0"
            cost = None
            try:
                cost = float(str(cost_raw).replace(",", "").replace("$", ""))
            except Exception:
                pass

            out.append({
                "address":        addr[:80],
                "project_name":   desc[:80] if desc else addr[:80],
                "developer":      "—",
                "asset_type":     _classify_asset(desc),
                "status":         _JOB_STATUS_MAP.get(jtype, "Filed"),
                "units":          None,
                "sqft":           None,
                "cost":           cost,
                "filing_date":    (r.get("filing_date") or "")[:10],
                "source":         "NYC DOB Permits",
                "url":            "",
                "lat":            item_lat,
                "lon":            item_lon,
                "distance_miles": round(dist, 3),
                "job_status":     r.get("job_status", "—"),
            })
        except Exception:
            continue

    return out, ("live" if out else "no_results")


# ── Keyword extractors ────────────────────────────────────────────────────────

_UNIT_RE  = re.compile(r"(\d[\d,]*)\s*(?:unit|apartment|apt|dwelling|residential\s+unit)", re.I)
_SF_RE    = re.compile(r"(\d[\d,]*)\s*(?:sq\.?\s*ft|sqft|SF|square\s*feet)", re.I)
_DEV_RE   = re.compile(
    r"(?:developer|developed by|by|from)\s+([A-Z][a-zA-Z\s&,\.]+?)"
    r"(?:\s+(?:has|will|plans|is|broke|received|filed|announced)|,|\.|\Z)",
    re.I,
)
_STATUS_WORDS = {
    "completed":            "Completed",
    "delivered":            "Completed",
    "opened":               "Completed",
    "certificate of occupancy": "Completed",
    "under construction":   "Under Construction",
    "breaking ground":      "Under Construction",
    "broke ground":         "Under Construction",
    "topped out":           "Under Construction",
    "approved":             "Approved",
    "received approval":    "Approved",
    "rezoning approved":    "Approved",
    "land use approval":    "Approved",
    "planned":              "Planned",
    "proposed":             "Planned",
    "will build":           "Planned",
    "plans to":             "Planned",
    "seeking approval":     "Planned",
}


def _extract_from_text(text: str) -> dict:
    """Extract structured fields from unstructured news text."""
    units_m = _UNIT_RE.search(text)
    sf_m    = _SF_RE.search(text)
    dev_m   = _DEV_RE.search(text)
    units = int(units_m.group(1).replace(",", "")) if units_m else None
    sqft  = int(sf_m.group(1).replace(",", ""))    if sf_m    else None
    dev   = dev_m.group(1).strip()[:60]            if dev_m   else "—"

    status = "Unknown"
    tl = text.lower()
    for kw, sv in _STATUS_WORDS.items():
        if kw in tl:
            status = sv
            break

    asset_type = _classify_asset(text)
    return {"units": units, "sqft": sqft, "developer": dev,
            "status": status, "asset_type": asset_type}


# ── RSS feed parser (shared) ──────────────────────────────────────────────────

_PUB_FMT = ["%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"]


def _parse_pub_date(raw: str) -> str:
    for fmt in _PUB_FMT:
        try:
            return datetime.strptime(raw.strip(), fmt).strftime("%Y-%m-%d")
        except Exception:
            pass
    return raw[:10] if raw else ""


def _parse_rss(content: str, source_name: str,
               loc_filter: str, cutoff: str,
               lat: float, lon: float,
               dev_keywords: list) -> tuple[list, str]:
    """
    Generic RSS XML parser. Filters by loc_filter keyword and dev_keywords.
    Returns (items, status).
    """
    try:
        items_raw = re.findall(r"<item>(.*?)</item>", content, re.S)
    except Exception:
        return [], "error"

    out: list[dict] = []
    for raw in items_raw[:50]:
        try:
            title_m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S)
            link_m  = re.search(r"<link>(.*?)</link>",         raw, re.S)
            pub_m   = re.search(r"<pubDate>(.*?)</pubDate>",   raw, re.S)
            desc_m  = re.search(r"<description>(.*?)</description>", raw, re.S)

            title   = re.sub(r"<[^>]+>|&lt;[^&]+&gt;|&\w+;", "",
                             title_m.group(1) if title_m else "").strip()
            url     = link_m.group(1).strip() if link_m else ""
            pub_raw = pub_m.group(1).strip()  if pub_m  else ""
            desc    = re.sub(r"<[^>]+>|\[.*?\]|&\w+;", "",
                             desc_m.group(1) if desc_m else "").strip()

            pub_date = _parse_pub_date(pub_raw)
            if pub_date and pub_date < cutoff:
                continue

            combined = f"{title} {desc}"

            # Location filter — must mention the neighborhood/address
            if loc_filter and loc_filter.lower() not in combined.lower():
                # Also accept generic NYC development coverage
                if "new york" not in combined.lower() and "nyc" not in combined.lower():
                    continue

            # Must be development-related
            if dev_keywords and not any(k in combined.lower() for k in dev_keywords):
                continue

            extracted = _extract_from_text(combined)
            out.append({
                "address":        title[:80],
                "project_name":   title[:80],
                "developer":      extracted["developer"],
                "asset_type":     extracted["asset_type"],
                "status":         extracted["status"],
                "units":          extracted["units"],
                "sqft":           extracted["sqft"],
                "filing_date":    pub_date,
                "source":         source_name,
                "url":            url,
                "lat":            lat,
                "lon":            lon,
                "distance_miles": 0.0,
            })
        except Exception:
            continue

    return out, ("live" if out else "no_results")


_DEV_KW = [
    "development", "tower", "project", "construction", "permit", "approved",
    "units", "groundbreak", "rezoning", "mixed-use", "affordable housing",
    "luxury condo", "building", "stories", "floors", "sq ft", "square feet",
]


# ── Google News RSS ───────────────────────────────────────────────────────────

_GNEWS_URL = "https://news.google.com/rss/search"


def _fetch_google_news(
    lat: float, lon: float, radius_miles: float,
    address: str = "", neighborhood: str = "",
) -> tuple[list, str]:
    """Search Google News RSS for recent development articles near the address."""
    # Use street address first, then neighborhood, then a bare NYC query
    addr_part = address.split(",")[0].strip() if address else ""
    loc = addr_part or neighborhood
    if not loc:
        return [], "no_results"

    # Build two queries — one hyper-local, one neighborhood-level
    queries = []
    if addr_part:
        queries.append(f'"{addr_part}" NYC development construction')
    if neighborhood and neighborhood != addr_part:
        queries.append(f'"{neighborhood}" NYC real estate development')

    cutoff = _cutoff_date(36)
    out: list[dict] = []
    status = "no_results"

    for query in queries[:2]:
        params = {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
        try:
            resp = requests.get(_GNEWS_URL, params=params, timeout=_TIMEOUT,
                                headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code in (403, 429):
                status = "blocked"
                continue
            resp.raise_for_status()
            content = resp.content.decode("utf-8", errors="ignore")
        except Exception as exc:
            status = f"error: {exc}"
            continue

        items, s = _parse_rss(content, "Google News", loc, cutoff, lat, lon, _DEV_KW)
        out.extend(items)
        if items:
            status = "live"
        time.sleep(0.2)

    return out, status


# ── The Real Deal RSS ─────────────────────────────────────────────────────────

_TRD_RSS = "https://therealdeal.com/feed/"


def _fetch_trd(
    lat: float, lon: float, radius_miles: float,
    address: str = "", neighborhood: str = "",
) -> tuple[list, str]:
    """Fetch The Real Deal RSS and filter by location keyword."""
    loc = neighborhood or (address.split(",")[0].strip() if address else "")
    cutoff = _cutoff_date(36)

    try:
        resp = requests.get(_TRD_RSS, timeout=_TIMEOUT,
                            headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code in (403, 429):
            return [], "blocked"
        resp.raise_for_status()
        content = resp.content.decode("utf-8", errors="ignore")
    except Exception as exc:
        return [], f"error: {exc}"

    return _parse_rss(content, "The Real Deal", loc, cutoff, lat, lon, _DEV_KW)


# ── Commercial Observer RSS ───────────────────────────────────────────────────

_CO_RSS = "https://commercialobserver.com/feed/"


def _fetch_commercial_observer(
    lat: float, lon: float, radius_miles: float,
    address: str = "", neighborhood: str = "",
) -> tuple[list, str]:
    """Fetch Commercial Observer RSS and filter by location keyword."""
    loc = neighborhood or (address.split(",")[0].strip() if address else "")
    cutoff = _cutoff_date(36)

    try:
        resp = requests.get(_CO_RSS, timeout=_TIMEOUT,
                            headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code in (403, 429):
            return [], "blocked"
        resp.raise_for_status()
        content = resp.content.decode("utf-8", errors="ignore")
    except Exception as exc:
        return [], f"error: {exc}"

    return _parse_rss(content, "Commercial Observer", loc, cutoff, lat, lon, _DEV_KW)


# ── Bisnow RSS ────────────────────────────────────────────────────────────────

_BISNOW_RSS = "https://www.bisnow.com/new-york/rss.xml"


def _fetch_bisnow(
    lat: float, lon: float, radius_miles: float,
    address: str = "", neighborhood: str = "",
) -> tuple[list, str]:
    """Fetch Bisnow NYC RSS and filter by location keyword."""
    loc = neighborhood or (address.split(",")[0].strip() if address else "")
    cutoff = _cutoff_date(36)

    try:
        resp = requests.get(_BISNOW_RSS, timeout=_TIMEOUT,
                            headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code in (403, 429):
            return [], "blocked"
        resp.raise_for_status()
        content = resp.content.decode("utf-8", errors="ignore")
    except Exception as exc:
        return [], f"error: {exc}"

    return _parse_rss(content, "Bisnow", loc, cutoff, lat, lon, _DEV_KW)


# ── Fuzzy dedup ───────────────────────────────────────────────────────────────

def _completeness(d: dict) -> int:
    """Score completeness of a development record (higher = more fields filled)."""
    score = 0
    for k in ("developer", "asset_type", "units", "sqft", "filing_date", "url"):
        v = d.get(k)
        if v and v not in ("—", "Unknown", None, 0):
            score += 1
    return score


def _fuzzy_dedup(devs: list) -> list:
    """Remove near-duplicates by address prefix + filing year."""
    seen: dict = {}
    for d in devs:
        addr_key = d.get("address", "")[:30].lower().strip()
        year_key = d.get("filing_date", "")[:4]
        key = (addr_key, year_key)
        if key not in seen or _completeness(d) > _completeness(seen[key]):
            seen[key] = d
    return list(seen.values())


# ── Orchestrator ──────────────────────────────────────────────────────────────

def fetch_nearby_developments(
    lat: float,
    lon: float,
    radius_miles: float,
    address: str = "",
    neighborhood: str = "",
    proxy_key: Optional[str] = None,
) -> tuple[list, dict]:
    """
    Fetch recent real estate developments within radius from multiple sources.

    Sources:
      1. NYC DOB Permits (NB, A1, DM filings — last 36 months)
      2. Google News RSS (keyword search by address + neighborhood)
      3. The Real Deal RSS
      4. Commercial Observer RSS
      5. Bisnow NYC RSS

    Returns (developments, status_dict).
    status_dict keys: dob, google_news, the_real_deal,
                      commercial_observer, bisnow, overall
    """
    status: dict = {
        "dob":                "pending",
        "google_news":        "pending",
        "the_real_deal":      "pending",
        "commercial_observer":"pending",
        "bisnow":             "pending",
        "overall":            "no_results",
    }
    all_devs: list[dict] = []

    # Source 1 — NYC DOB Permits
    dob_devs, dob_status = _fetch_dob(lat, lon, radius_miles)
    status["dob"] = dob_status
    all_devs.extend(dob_devs)

    # Source 2 — Google News RSS
    gn_devs, gn_status = _fetch_google_news(lat, lon, radius_miles, address, neighborhood)
    status["google_news"] = gn_status
    all_devs.extend(gn_devs)
    time.sleep(0.2)

    # Source 3 — The Real Deal RSS
    trd_devs, trd_status = _fetch_trd(lat, lon, radius_miles, address, neighborhood)
    status["the_real_deal"] = trd_status
    all_devs.extend(trd_devs)
    time.sleep(0.2)

    # Source 4 — Commercial Observer RSS
    co_devs, co_status = _fetch_commercial_observer(lat, lon, radius_miles, address, neighborhood)
    status["commercial_observer"] = co_status
    all_devs.extend(co_devs)
    time.sleep(0.2)

    # Source 5 — Bisnow RSS
    bn_devs, bn_status = _fetch_bisnow(lat, lon, radius_miles, address, neighborhood)
    status["bisnow"] = bn_status
    all_devs.extend(bn_devs)

    # Dedup and sort by filing date (most recent first)
    all_devs = _fuzzy_dedup(all_devs)
    all_devs.sort(key=lambda x: x.get("filing_date") or "", reverse=True)

    if all_devs:
        status["overall"] = "live"
    elif any(v == "blocked" for v in status.values()):
        status["overall"] = "blocked"
    elif any(str(v).startswith("error") for v in status.values()):
        # All 5 sources failing outright (network error/timeout/exception,
        # as opposed to a literal HTTP 403/429 "blocked") must not be
        # reported as a clean "no_results" — that masks a total outage.
        status["overall"] = "error"
    else:
        status["overall"] = "no_results"

    record_source_status(
        "Nearby Development Pipeline",
        ok=(status["overall"] in ("live", "no_results")),
        detail="" if status["overall"] in ("live", "no_results") else f"overall status: {status['overall']}",
    )

    return all_devs, status

"""
Nearby Developments — multi-source real estate development pipeline fetcher.

Sources (no API keys required):
  1. NYC DOB Permits  (ipu4-2q9a) — NB, A1, DM filings within radius
  2. Google News RSS  (news.google.com/rss) — keyword search
  3. The Real Deal RSS (therealdeal.com/feed) — NYC RE news

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

# ── NYC DOB Permits ─────────────────────────────────────────────────────────

_DOB_URL = "https://data.cityofnewyork.us/resource/ipu4-2q9a.json"
_TIMEOUT = 15

_JOB_STATUS_MAP = {
    "NB": "Under Construction / Approved",
    "A1": "Major Alteration",
    "DM": "Demolition",
}

_ASSET_KEYWORDS = {
    "residential": ["residential", "apartment", "dwelling", "condo", "co-op", "multifamily", "housing"],
    "commercial":  ["commercial", "office", "hotel", "retail", "warehouse", "industrial"],
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
        "$limit":  "200",
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
    r"(?:developer|developed by|by)\s+([A-Z][a-zA-Z\s&,\.]+?)(?:\s+(?:has|will|plans|is|broke|received|filed)|,|\.|\Z)",
    re.I,
)
_STATUS_WORDS = {
    "completed":           "Completed",
    "delivered":           "Completed",
    "opened":              "Completed",
    "under construction":  "Under Construction",
    "breaking ground":     "Under Construction",
    "broke ground":        "Under Construction",
    "approved":            "Approved",
    "received approval":   "Approved",
    "planned":             "Planned",
    "proposed":            "Planned",
    "will":                "Planned",
    "plans to":            "Planned",
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


# ── Google News RSS ───────────────────────────────────────────────────────────

_GNEWS_URL = "https://news.google.com/rss/search"

_PUB_FMT = ["%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"]


def _parse_pub_date(raw: str) -> str:
    for fmt in _PUB_FMT:
        try:
            return datetime.strptime(raw.strip(), fmt).strftime("%Y-%m-%d")
        except Exception:
            pass
    return raw[:10] if raw else ""


def _fetch_google_news(
    lat: float, lon: float, radius_miles: float,
    address: str = "", neighborhood: str = "",
) -> tuple[list, str]:
    """Search Google News RSS for recent development articles."""
    # Build query — try neighborhood first, fall back to address fragment
    loc = neighborhood or (address.split(",")[0] if address else "")
    if not loc:
        return [], "no_results"

    query = f'"{loc}" real estate development NYC construction'
    params = {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}

    try:
        resp = requests.get(_GNEWS_URL, params=params, timeout=_TIMEOUT,
                            headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code in (403, 429):
            return [], "blocked"
        resp.raise_for_status()
        content = resp.content
    except Exception as exc:
        return [], f"error: {exc}"

    # Parse RSS XML manually (avoid feedparser dependency)
    try:
        items_raw = re.findall(r"<item>(.*?)</item>", content.decode("utf-8", errors="ignore"), re.S)
    except Exception:
        return [], "error"

    cutoff = _cutoff_date(36)
    out: list[dict] = []
    for raw in items_raw[:30]:
        try:
            title_m   = re.search(r"<title>(.*?)</title>", raw, re.S)
            link_m    = re.search(r"<link>(.*?)</link>", raw, re.S)
            pub_m     = re.search(r"<pubDate>(.*?)</pubDate>", raw, re.S)
            desc_m    = re.search(r"<description>(.*?)</description>", raw, re.S)

            title   = re.sub(r"<[^>]+>", "", title_m.group(1)).strip() if title_m else ""
            url     = link_m.group(1).strip() if link_m else ""
            pub_raw = pub_m.group(1).strip()  if pub_m  else ""
            desc    = re.sub(r"<[^>]+>", "", desc_m.group(1)).strip() if desc_m else ""

            pub_date = _parse_pub_date(pub_raw)
            if pub_date and pub_date < cutoff:
                continue

            combined = f"{title} {desc}"
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
                "source":         "Google News",
                "url":            url,
                "lat":            lat,
                "lon":            lon,
                "distance_miles": 0.0,
            })
        except Exception:
            continue

    return out, ("live" if out else "no_results")


# ── The Real Deal RSS ─────────────────────────────────────────────────────────

_TRD_RSS = "https://therealdeal.com/feed/"


def _fetch_trd(
    lat: float, lon: float, radius_miles: float,
    address: str = "", neighborhood: str = "",
) -> tuple[list, str]:
    """Fetch The Real Deal RSS and filter by neighborhood keyword."""
    loc = neighborhood or (address.split(",")[0] if address else "")

    try:
        resp = requests.get(_TRD_RSS, timeout=_TIMEOUT,
                            headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code in (403, 429):
            return [], "blocked"
        resp.raise_for_status()
        content = resp.content.decode("utf-8", errors="ignore")
    except Exception as exc:
        return [], f"error: {exc}"

    try:
        items_raw = re.findall(r"<item>(.*?)</item>", content, re.S)
    except Exception:
        return [], "error"

    cutoff = _cutoff_date(36)
    out: list[dict] = []
    for raw in items_raw[:40]:
        try:
            title_m = re.search(r"<title>(.*?)</title>", raw, re.S)
            link_m  = re.search(r"<link>(.*?)</link>",   raw, re.S)
            pub_m   = re.search(r"<pubDate>(.*?)</pubDate>", raw, re.S)
            desc_m  = re.search(r"<description>(.*?)</description>", raw, re.S)

            title   = re.sub(r"<[^>]+>", "", title_m.group(1)).strip() if title_m else ""
            url     = link_m.group(1).strip() if link_m else ""
            pub_raw = pub_m.group(1).strip()  if pub_m  else ""
            desc    = re.sub(r"<[^>]+>|\[.*?\]|&\w+;", "", desc_m.group(1) if desc_m else "").strip()

            pub_date = _parse_pub_date(pub_raw)
            if pub_date and pub_date < cutoff:
                continue

            combined = f"{title} {desc}"
            # Filter to articles mentioning the neighborhood/address
            if loc and loc.lower() not in combined.lower() and "nyc" not in combined.lower():
                continue
            # Must be development-related
            dev_keywords = ["development", "tower", "project", "construction",
                            "permit", "approved", "units", "ground-floor", "groundbreak"]
            if not any(k in combined.lower() for k in dev_keywords):
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
                "source":         "The Real Deal",
                "url":            url,
                "lat":            lat,
                "lon":            lon,
                "distance_miles": 0.0,
            })
        except Exception:
            continue

    return out, ("live" if out else "no_results")


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
        addr_key  = d.get("address", "")[:30].lower().strip()
        year_key  = d.get("filing_date", "")[:4]
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
      2. Google News RSS (keyword search)
      3. The Real Deal RSS

    Returns (developments, status_dict).
    status_dict keys: dob, google_news, the_real_deal, overall
    """
    status: dict = {
        "dob":          "pending",
        "google_news":  "pending",
        "the_real_deal":"pending",
        "overall":      "no_results",
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

    time.sleep(0.3)

    # Source 3 — The Real Deal RSS
    trd_devs, trd_status = _fetch_trd(lat, lon, radius_miles, address, neighborhood)
    status["the_real_deal"] = trd_status
    all_devs.extend(trd_devs)

    # Dedup and sort by filing date (most recent first)
    all_devs = _fuzzy_dedup(all_devs)
    all_devs.sort(key=lambda x: x.get("filing_date") or "", reverse=True)

    if all_devs:
        status["overall"] = "live"
    elif any(v == "blocked" for v in status.values()):
        status["overall"] = "blocked"
    else:
        status["overall"] = "no_results"

    return all_devs, status

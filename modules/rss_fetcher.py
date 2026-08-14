"""
Shared minimal RSS-feed fetch + parse primitives.

Every module that pulls from a public real-estate news RSS feed
(nearby_developments, articles_fetcher, comps_research) builds on these
instead of each hand-rolling its own copy of "fetch a feed, split <item>
blocks, strip HTML from title/description". No external XML parser
dependency — a small tolerant regex parser (the approach already proven
in modules/nearby_developments.py, extracted here so it has one home).

RSS is the deliberate choice over HTML search-engine scraping
(DuckDuckGo, etc.): a real estate trade outlet's own feed is a stable,
purpose-built contract that doesn't get CAPTCHA'd or silently return an
empty-but-technically-200 page the way scraping a search results page
can. Fixed (value, status) contracts throughout; nothing here raises.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

import requests

_TIMEOUT = 15
_DEFAULT_HEADERS = {"User-Agent": "Mozilla/5.0"}

_PUB_FMT = ["%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"]


def parse_pub_date(raw: str) -> str:
    """Best-effort RFC-822-ish <pubDate> -> 'YYYY-MM-DD'. Falls back to a
    naive prefix slice, and to '' if raw is empty. Never raises."""
    for fmt in _PUB_FMT:
        try:
            return datetime.strptime(raw.strip(), fmt).strftime("%Y-%m-%d")
        except Exception:
            pass
    return raw[:10] if raw else ""


def cutoff_date(months: int = 36) -> str:
    """ISO date string N months ago, for feed-item recency filtering."""
    return (datetime.utcnow() - timedelta(days=months * 30)).strftime("%Y-%m-%d")


def fetch_rss_content(url: str, params: dict | None = None, timeout: int = _TIMEOUT) -> tuple[str | None, str]:
    """
    Fetch a feed URL's raw text.

    Returns (content, status): status is "ok", "blocked" (HTTP 403/429),
    or "error: <message>" (network error, timeout, other non-2xx).
    content is None whenever status != "ok". Never raises — a dead or
    nonexistent feed URL (e.g. an outlet that doesn't actually publish
    RSS) degrades to a status string, not an exception.
    """
    try:
        resp = requests.get(url, params=params, timeout=timeout, headers=_DEFAULT_HEADERS)
        if resp.status_code in (403, 429):
            return None, "blocked"
        resp.raise_for_status()
        return resp.content.decode("utf-8", errors="ignore"), "ok"
    except Exception as exc:
        return None, f"error: {exc}"


def parse_rss_items(content: str) -> list[dict]:
    """
    Split raw RSS XML into <item> blocks and pull out the common
    title/link/pubDate/description fields, HTML-stripped.

    Returns a list of (at most 50) dicts, in feed order:
        {"title", "url", "pub_date" (YYYY-MM-DD or ""), "pub_date_raw",
         "description"}
    A malformed feed yields fewer/no items rather than raising.
    """
    try:
        raw_items = re.findall(r"<item>(.*?)</item>", content, re.S)
    except Exception:
        return []

    out: list[dict] = []
    for raw in raw_items[:50]:
        try:
            title_m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S)
            link_m  = re.search(r"<link>(.*?)</link>", raw, re.S)
            pub_m   = re.search(r"<pubDate>(.*?)</pubDate>", raw, re.S)
            desc_m  = re.search(r"<description>(.*?)</description>", raw, re.S)

            title = re.sub(r"<[^>]+>|&lt;[^&]+&gt;|&\w+;", "",
                            title_m.group(1) if title_m else "").strip()
            url = link_m.group(1).strip() if link_m else ""
            pub_raw = pub_m.group(1).strip() if pub_m else ""
            desc = re.sub(r"<[^>]+>|\[.*?\]|&\w+;", "",
                            desc_m.group(1) if desc_m else "").strip()

            out.append({
                "title": title,
                "url": url,
                "pub_date": parse_pub_date(pub_raw),
                "pub_date_raw": pub_raw,
                "description": desc,
            })
        except Exception:
            continue
    return out


def location_relevant(combined_text: str, loc_filter: str) -> bool:
    """
    True if `combined_text` (typically title + description) mentions the
    given location keyword (neighborhood or street address), OR at least
    generically mentions NYC — the same permissive rule
    modules/nearby_developments.py uses, shared here so every RSS-based
    fetcher applies location relevance consistently.
    """
    tl = combined_text.lower()
    if loc_filter and loc_filter.lower() in tl:
        return True
    return "new york" in tl or "nyc" in tl

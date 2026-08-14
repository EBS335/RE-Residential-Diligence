"""
Nearby address article fetcher — RSS-first, DDG as last-resort fallback.

Root cause of the previous "not currently working successfully" reports:
this module used to be DuckDuckGo-HTML-search-only, which is fragile —
DDG's HTML search endpoint can silently return a technically-200-OK page
with zero usable results when it decides to challenge/rate-limit a
scripted client, indistinguishable from a genuine "nothing found" search
without extra signal. modules/nearby_developments.py already proved a
more robust pattern for this exact problem (RSS feeds straight from the
real estate trade outlets), extracted into modules/rss_fetcher.py so
this module builds on the same primitives instead of re-implementing
feed parsing.

Sources (all free, no API key):
  - The Real Deal, Commercial Observer, Bisnow — confirmed working RSS
    feeds (proven in modules/nearby_developments.py).
  - Crain's New York Business — best-effort: no publicly documented RSS
    URL was confirmed for this feed in this environment. Attempts the
    conventional WordPress-style feed URL; if it's wrong or the outlet
    doesn't publish RSS, that source simply contributes zero results
    (never raises, never breaks the other sources).
  - PincusCo — best-effort, public-teaser-only per product decision:
    PincusCo's daily news feed is a paid subscription ($10/mo), which
    would break this app's free/keyless-only design. No public RSS feed
    could be confirmed either. This attempts the same conventional feed
    URL on the chance a public teaser feed exists; in practice it will
    likely contribute nothing, and that limitation is surfaced in the UI
    caption rather than silently presented as "checked, found nothing."
  - Google News RSS — generic keyword search by address/neighborhood,
    filtered for real-estate relevance (same pattern as nearby_developments).
  - DuckDuckGo HTML search — kept only as a last-resort supplement when
    the RSS sources collectively return nothing, to preserve coverage of
    outlets without a usable RSS feed (Yimby, 6sqft, Curbed, NY Post).
"""

from __future__ import annotations
import re
import time
import random
import requests

from modules.rss_fetcher import fetch_rss_content, parse_rss_items, cutoff_date, location_relevant

_DDG_URL = "https://html.duckduckgo.com/html/"
_TIMEOUT = 12
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Source badge colors by domain
_SOURCE_STYLES: dict[str, dict] = {
    "therealdeal.com": {"label": "The Real Deal", "bg": "#1E3A5F", "fg": "#FFFFFF"},
    "yimbynewyork.com": {"label": "Yimby NY",     "bg": "#166534", "fg": "#FFFFFF"},
    "commercialobserver.com": {"label": "Comm. Observer", "bg": "#1D4ED8", "fg": "#FFFFFF"},
    "6sqft.com":    {"label": "6sqft",     "bg": "#7C3AED", "fg": "#FFFFFF"},
    "curbed.com":   {"label": "Curbed",    "bg": "#DC2626", "fg": "#FFFFFF"},
    "nypost.com":   {"label": "NY Post",   "bg": "#C2410C", "fg": "#FFFFFF"},
    "bisnow.com":   {"label": "Bisnow",    "bg": "#0E7490", "fg": "#FFFFFF"},
    "crainsnewyork.com": {"label": "Crain's NY",  "bg": "#374151", "fg": "#FFFFFF"},
    "pincusco.com": {"label": "PincusCo",  "bg": "#9333EA", "fg": "#FFFFFF"},
    "news.google.com": {"label": "Google News", "bg": "#4B5563", "fg": "#FFFFFF"},
}

# RSS sources: (feed_url, source_name). Real Deal / Commercial Observer /
# Bisnow feed URLs are the same ones proven in nearby_developments.py.
# Crain's and PincusCo are best-effort guesses at the conventional feed
# URL — see module docstring.
_RSS_SOURCES = [
    ("https://therealdeal.com/feed/", "The Real Deal"),
    ("https://commercialobserver.com/feed/", "Commercial Observer"),
    ("https://www.bisnow.com/new-york/rss.xml", "Bisnow"),
    ("https://www.crainsnewyork.com/section/real-estate/feed", "Crain's NY"),
    ("https://www.pincusco.com/feed/", "PincusCo"),
]
_GNEWS_URL = "https://news.google.com/rss/search"

# Real-estate relevance keywords for the generic Google News source (the
# trade-press RSS feeds above are already real-estate-focused by nature,
# so they only need a location filter — Google News needs both).
_RE_KW = [
    "development", "tower", "project", "construction", "permit", "approved",
    "units", "groundbreak", "rezoning", "mixed-use", "affordable housing",
    "condo", "building", "sale", "acquisition", "lease", "real estate",
]


def _ddg_search(query: str) -> tuple[list[dict], bool]:
    """Search DuckDuckGo HTML. Returns (results, ok) — ok=False means the
    request itself failed, NOT that the search legitimately found nothing."""
    try:
        resp = requests.post(
            _DDG_URL,
            data={"q": query, "b": "", "kl": "us-en"},
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        html = resp.text
    except Exception:
        return [], False

    results = []
    title_pattern   = re.compile(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
    snippet_pattern = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL)

    titles   = title_pattern.findall(html)
    snippets = snippet_pattern.findall(html)

    for i, (url, title) in enumerate(titles[:8]):
        title_clean   = re.sub(r"<[^>]+>", "", title).strip()
        snippet_clean = re.sub(r"<[^>]+>", "", snippets[i] if i < len(snippets) else "").strip()
        if title_clean and url:
            real_url = url
            uddg_match = re.search(r"uddg=([^&]+)", url)
            if uddg_match:
                from urllib.parse import unquote
                real_url = unquote(uddg_match.group(1))
            results.append({"title": title_clean, "url": real_url, "snippet": snippet_clean})

    return results, True


def _source_info(url: str) -> dict:
    """Return badge label and colors for a URL's domain."""
    url_lower = url.lower()
    for domain, info in _SOURCE_STYLES.items():
        if domain in url_lower:
            return info
    # Fallback: extract domain
    m = re.search(r'https?://(?:www\.)?([^/]+)', url)
    domain_name = m.group(1).split(".")[0].title() if m else "Web"
    return {"label": domain_name, "bg": "#6B7280", "fg": "#FFFFFF"}


def _approx_date(snippet: str) -> str:
    """Try to extract an approximate date from a snippet (DDG-fallback path only —
    RSS items carry a real <pubDate>, so this is unused on the primary path)."""
    m = re.search(r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+20\d{2}\b', snippet, re.IGNORECASE)
    if m:
        return m.group(0)
    m = re.search(r'\b(20\d{2})\b', snippet)
    if m:
        return m.group(1)
    return ""


def _rss_articles_from_source(feed_url: str, source_name: str, loc: str, cutoff: str,
                               require_dev_keywords: bool = False) -> tuple[list[dict], str]:
    """Fetch one RSS feed and map its items into the article schema.
    Returns (articles, status) — status is "ok"/"blocked"/"error: ..."/"empty_feed"."""
    content, status = fetch_rss_content(feed_url)
    if status != "ok":
        return [], status

    items = parse_rss_items(content)
    if not items:
        return [], "empty_feed"

    # We already know which feed this item came from — use its badge style
    # (looked up once by feed domain) with the authoritative source_name as
    # the label, rather than re-sniffing each article's own URL domain.
    badge = {**_source_info(feed_url), "label": source_name}

    out: list[dict] = []
    for item in items:
        combined = f"{item['title']} {item['description']}"
        if not location_relevant(combined, loc):
            continue
        if require_dev_keywords and not any(k in combined.lower() for k in _RE_KW):
            continue
        out.append({
            "title":       item["title"],
            "url":         item["url"] or feed_url,
            "source":      badge,
            "snippet":     item["description"][:220],
            "date_approx": item["pub_date"] or _approx_date(item["description"]),
        })
    return out, "ok"


def fetch_nearby_articles(
    address: str,
    neighborhood: str,
    borough: str,
    max_results: int = 8,
) -> tuple[list[dict], str]:
    """
    Search for news articles mentioning the subject address or nearby area.

    RSS-first: pulls The Real Deal, Commercial Observer, Bisnow, Crain's
    NY (best-effort), PincusCo (best-effort, public teaser only), and
    Google News, filtered by location relevance. Falls back to a
    DuckDuckGo HTML search only if the RSS sources collectively return
    nothing, to preserve coverage of outlets without a usable feed.

    Returns (articles, status):
      articles — up to `max_results` dicts:
                 {title, url, source (dict with label/bg/fg), snippet, date_approx}
      status   — "live" | "no_results" | "error" (all searches failed,
                 distinct from "no_results" which means the searches
                 succeeded but found nothing)
    """
    if not address and not neighborhood:
        return [], "no_results"

    loc = neighborhood or (address.split(",")[0].strip() if address else "")
    cutoff = cutoff_date(18)  # news should be reasonably recent, unlike the 36mo permit window

    seen_urls: set[str] = set()
    articles: list[dict] = []
    any_ok = False

    for feed_url, source_name in _RSS_SOURCES:
        rows, status = _rss_articles_from_source(feed_url, source_name, loc, cutoff)
        if status == "ok":
            any_ok = True
        for r in rows:
            if r["url"] in seen_urls:
                continue
            seen_urls.add(r["url"])
            articles.append(r)
        if len(articles) >= max_results:
            break

    if len(articles) < max_results:
        addr_part = address.split(",")[0].strip() if address else ""
        gn_loc = addr_part or neighborhood
        if gn_loc:
            query = f'"{gn_loc}" NYC real estate'
            content, status = fetch_rss_content(_GNEWS_URL, params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
            if status == "ok":
                any_ok = True
                for item in parse_rss_items(content):
                    combined = f"{item['title']} {item['description']}"
                    if not location_relevant(combined, gn_loc):
                        continue
                    if not any(k in combined.lower() for k in _RE_KW):
                        continue
                    if item["url"] in seen_urls:
                        continue
                    seen_urls.add(item["url"])
                    # Google News RSS links out to the original outlet, so the
                    # article URL's own domain drives the badge (falls back
                    # to a generic "Google News" style if unrecognized).
                    articles.append({
                        "title":       item["title"],
                        "url":         item["url"],
                        "source":      _source_info(item["url"]) or {"label": "Google News", "bg": "#4B5563", "fg": "#FFFFFF"},
                        "snippet":     item["description"][:220],
                        "date_approx": item["pub_date"],
                    })
                    if len(articles) >= max_results:
                        break

    # Last-resort fallback: RSS sources collectively found nothing (not
    # merely fewer than max_results) — try DDG to preserve coverage of
    # outlets without a usable RSS feed (Yimby, 6sqft, Curbed, NY Post).
    if not articles:
        m = re.match(r'^(\d+)\s+(.+?)(?:,|$)', address.strip()) if address else None
        street_num  = m.group(1) if m else ""
        street_name = m.group(2).split(",")[0].strip() if m else ""

        queries = []
        if street_num and street_name:
            queries.append(
                f'"{street_num} {street_name}" NYC '
                f'site:therealdeal.com OR site:yimbynewyork.com OR site:commercialobserver.com'
            )
        queries.append(
            f'"{neighborhood}" {borough} development sale acquisition '
            f'site:therealdeal.com OR site:6sqft.com'
        )
        queries.append(
            f'"{neighborhood}" NYC real estate construction permit '
            f'site:yimbynewyork.com OR site:curbed.com OR site:bisnow.com'
        )

        for i, q in enumerate(queries):
            if i > 0:
                time.sleep(random.uniform(1.0, 2.0))
            results, ok = _ddg_search(q)
            any_ok = any_ok or ok
            for r in results:
                url = r.get("url", "")
                title = r.get("title", "")
                snippet = r.get("snippet", "")
                if not url or not title or url in seen_urls:
                    continue
                if re.search(r'(?:search|tag|category|author|page=)', url, re.IGNORECASE):
                    continue
                seen_urls.add(url)
                articles.append({
                    "title":       title,
                    "url":         url,
                    "source":      _source_info(url),
                    "snippet":     snippet[:220] if snippet else "",
                    "date_approx": _approx_date(snippet),
                })
                if len(articles) >= max_results:
                    break
            if len(articles) >= max_results:
                break

    if articles:
        status = "live"
    elif not any_ok:
        status = "error"
    else:
        status = "no_results"

    return articles[:max_results], status

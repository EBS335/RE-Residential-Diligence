"""
Nearby address article fetcher — DDG HTML search.

Searches Real Deal, Yimby, Commercial Observer, 6sqft, Curbed, and NY Post
Real Estate for articles mentioning the subject address or nearby area.

No API keys required. Uses DuckDuckGo HTML search scraping.
"""

from __future__ import annotations
import re
import time
import random
import requests

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
    "crain":        {"label": "Crain's",   "bg": "#374151", "fg": "#FFFFFF"},
}


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
    """Try to extract an approximate date from a snippet."""
    m = re.search(r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+20\d{2}\b', snippet, re.IGNORECASE)
    if m:
        return m.group(0)
    m = re.search(r'\b(20\d{2})\b', snippet)
    if m:
        return m.group(1)
    return ""


def fetch_nearby_articles(
    address: str,
    neighborhood: str,
    borough: str,
    max_results: int = 8,
) -> tuple[list[dict], str]:
    """
    Search for news articles mentioning the subject address or nearby area.

    Returns (articles, status):
      articles — up to `max_results` dicts:
                 {title, url, source (dict with label/bg/fg), snippet, date_approx}
      status   — "live" | "no_results" | "error" (all searches failed,
                 distinct from "no_results" which means the searches
                 succeeded but found nothing)
    """
    if not address and not neighborhood:
        return [], "no_results"

    # Extract street number + name from address
    m = re.match(r'^(\d+)\s+(.+?)(?:,|$)', address.strip())
    street_num  = m.group(1) if m else ""
    street_name = m.group(2).split(",")[0].strip() if m else ""

    queries = []
    if street_num and street_name:
        queries.append(
            f'"{street_num} {street_name}" NYC '
            f'site:therealdeal.com OR site:yimbynewyork.com OR site:commercialobserver.com'
        )
    queries.append(
        f'"{neighborhood}" {borough} development sale acquisition 2024 2025 '
        f'site:therealdeal.com OR site:6sqft.com'
    )
    queries.append(
        f'"{neighborhood}" NYC real estate construction permit 2024 2025 '
        f'site:yimbynewyork.com OR site:curbed.com OR site:bisnow.com'
    )

    seen_urls: set[str] = set()
    articles: list[dict] = []
    any_ok = False

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
            # Filter out non-article pages (homepages, search results)
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

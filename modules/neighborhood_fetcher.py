"""
Neighborhood market data fetcher — DDG HTML search.

Searches DuckDuckGo for neighborhood real estate reports from brokerages,
news outlets, and property sites, then extracts bullet-point insights.

No API keys required. Uses DuckDuckGo HTML search scraping.

Returns:
  {
    "bullets":     list[str],   # 6–10 bullet points (markdown-formatted)
    "sources":     list[dict],  # [{title, url}]
    "residential": str,         # residential market summary
    "commercial":  str,         # commercial / retail summary
    "error":       str | None,
  }
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

_EMPTY = {
    "bullets": [],
    "sources": [],
    "residential": "",
    "commercial": "",
    "error": None,
}


def _ddg_search(query: str) -> list[dict]:
    """
    Search DuckDuckGo HTML and return top results as list of {title, url, snippet}.
    """
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
        return []

    results = []
    # Parse result blocks: each result has a title link and snippet
    # DuckDuckGo HTML format: <a class="result__a" href="...">Title</a>
    #                          <a class="result__snippet">Snippet</a>
    title_pattern  = re.compile(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
    snippet_pattern = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL)

    titles  = title_pattern.findall(html)
    snippets = snippet_pattern.findall(html)

    for i, (url, title) in enumerate(titles[:8]):
        # Clean HTML tags from title/snippet
        title_clean = re.sub(r"<[^>]+>", "", title).strip()
        snippet_clean = re.sub(r"<[^>]+>", "", snippets[i] if i < len(snippets) else "").strip()
        if title_clean and url:
            # Decode DuckDuckGo redirect URLs
            real_url = url
            uddg_match = re.search(r"uddg=([^&]+)", url)
            if uddg_match:
                from urllib.parse import unquote
                real_url = unquote(uddg_match.group(1))
            results.append({
                "title":   title_clean,
                "url":     real_url,
                "snippet": snippet_clean,
            })

    return results


def _extract_bullets(snippets: list[str], neighborhood: str) -> list[str]:
    """
    Extract meaningful bullet points from search result snippets.
    Looks for mentions of rents, prices, trends, vacancy, development.
    """
    bullets = []
    seen = set()

    # Patterns that indicate useful data
    patterns = [
        # Rent / price figures
        (r"\$[\d,]+(?:\s*(?:per|/)\s*(?:month|mo|sq\.?\s*ft|SF|psf))?\b", "rent"),
        # Percentages (vacancy, growth)
        (r"\d+(?:\.\d+)?%\s+(?:vacancy|occupied|growth|increase|decrease|lower|higher|below|above)", "pct"),
        # Year-over-year trends
        (r"(?:year.over.year|YoY|y-o-y|annual|2024|2025)\b[^.]{0,80}(?:rent|price|growth|increase|decrease|change)", "trend"),
        # Development pipeline
        (r"(?:unit|apartment|development|building|project|pipeline|deliver|under construction)[^.]{0,80}(?:planned|proposed|complete|delivered|under)", "dev"),
    ]

    for snippet in snippets:
        if not snippet or len(snippet) < 30:
            continue
        # Split into sentences
        sentences = re.split(r"(?<=[.!?])\s+", snippet)
        for sent in sentences:
            sent = sent.strip()
            if len(sent) < 20 or len(sent) > 300:
                continue
            # Check if sentence contains useful data
            useful = False
            for pat, _ in patterns:
                if re.search(pat, sent, re.IGNORECASE):
                    useful = True
                    break
            if useful:
                # Deduplicate by first 60 chars
                key = sent[:60].lower()
                if key not in seen:
                    seen.add(key)
                    bullets.append(sent)
            if len(bullets) >= 10:
                break
        if len(bullets) >= 10:
            break

    return bullets[:10]


def _summarize_category(snippets: list[str], keywords: list[str]) -> str:
    """
    Build a 1–2 sentence summary from snippets mentioning given keywords.
    """
    relevant = []
    for snippet in snippets:
        if any(kw.lower() in snippet.lower() for kw in keywords):
            relevant.append(snippet)
    if not relevant:
        return ""
    # Take first 2 relevant sentences
    combined = " ".join(relevant[:2])
    sentences = re.split(r"(?<=[.!?])\s+", combined)
    return " ".join(sentences[:2]).strip()


def fetch_neighborhood_data(neighborhood: str, borough: str) -> dict:
    """
    Fetch neighborhood real estate market data via DuckDuckGo search.

    Args:
        neighborhood: Neighborhood name (e.g. "Williamsburg")
        borough: NYC borough (e.g. "Brooklyn")

    Returns dict with keys: bullets, sources, residential, commercial, error
    """
    if not neighborhood or not borough:
        return {**_EMPTY, "error": "Neighborhood and borough are required"}

    nb = neighborhood.strip()
    bo = borough.strip()

    queries = [
        f'"{nb}" {bo} NYC apartment rents market 2024 2025 residential',
        f'"{nb}" NYC real estate market report 2024 2025 site:therealdeal.com OR site:6sqft.com OR site:bisnow.com',
        f'"{nb}" {bo} retail commercial vacancy rents 2024 site:cbre.com OR site:jll.com OR site:commercialobserver.com',
    ]

    all_results = []
    all_snippets = []

    for i, q in enumerate(queries):
        if i > 0:
            time.sleep(random.uniform(1.0, 2.5))
        results = _ddg_search(q)
        all_results.extend(results)
        all_snippets.extend([r["snippet"] for r in results if r.get("snippet")])

    if not all_results:
        return {**_EMPTY, "error": f"No search results found for {nb}, {bo}"}

    bullets = _extract_bullets(all_snippets, nb)

    # If no structured bullets found, fall back to snippet summaries
    if not bullets:
        for r in all_results[:5]:
            snip = r.get("snippet", "").strip()
            if snip and len(snip) > 40:
                bullets.append(snip[:200])

    residential = _summarize_category(
        all_snippets,
        ["apartment", "rent", "residential", "unit", "tenant", "lease"],
    )
    commercial = _summarize_category(
        all_snippets,
        ["retail", "commercial", "office", "vacancy", "storefront", "ground floor"],
    )

    # Deduplicate sources by URL
    seen_urls: set[str] = set()
    sources = []
    for r in all_results:
        url = r.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            sources.append({"title": r.get("title", url), "url": url})

    return {
        "bullets":     bullets,
        "sources":     sources[:8],
        "residential": residential,
        "commercial":  commercial,
        "error":       None,
    }

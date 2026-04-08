"""
Neighborhood market data fetcher — DDG HTML search.

Searches DuckDuckGo for neighborhood real estate reports from brokerages,
news outlets, and property sites, then extracts bullet-point insights and
structured numeric market data.

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

_EMPTY = {
    "bullets": [],
    "sources": [],
    "residential": "",
    "commercial": "",
    "res_data": {
        "studio_rent": None, "one_bd_rent": None,
        "two_bd_rent": None, "three_bd_rent": None,
        "condo_psf": None, "summary": "",
    },
    "retail_data": {
        "asking_rent_psf": None, "tenant_types": [],
        "vacancy_pct": None, "summary": "",
    },
    "commercial_data": {
        "asking_rent_psf": None, "tenant_types": [],
        "vacancy_pct": None, "summary": "",
    },
    "error": None,
}


def _parse_dollar(text: str) -> int | None:
    """Extract first dollar amount (monthly rent or PSF) from text. Returns int or None."""
    m = re.search(r'\$\s*([\d,]+(?:\.\d+)?)\s*(?:per\s+(?:month|mo|sq\.?\s*ft|SF|psf)|\s*/\s*(?:mo|month|SF|psf|sqft))?', text, re.IGNORECASE)
    if m:
        try:
            val = float(m.group(1).replace(",", ""))
            return int(val) if val > 0 else None
        except ValueError:
            return None
    return None


def _parse_psf(text: str) -> int | None:
    """Extract a per-SF (PSF/year) figure from text."""
    m = re.search(r'\$\s*([\d,]+(?:\.\d+)?)\s*(?:per\s+(?:sq\.?\s*ft|SF|psf)|/\s*(?:SF|psf|sqft))', text, re.IGNORECASE)
    if m:
        try:
            val = float(m.group(1).replace(",", ""))
            return int(val) if val > 0 else None
        except ValueError:
            return None
    return None


def _parse_vacancy(text: str) -> float | None:
    """Extract vacancy percentage from text."""
    m = re.search(r'([\d.]+)\s*%\s*(?:vacancy|vacant|available)', text, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def _extract_tenant_types(text: str) -> list[str]:
    """Extract common tenant type categories mentioned in retail/commercial text."""
    types = []
    patterns = [
        ("F&B", r'\b(?:food|restaurant|cafe|caf[eé]|bar|eatery|dining)\b'),
        ("Services", r'\b(?:salon|spa|service|barber|dry clean|laundry|pharmacy|bank|finance)\b'),
        ("Retail", r'\b(?:fashion|clothing|apparel|boutique|shoes|jewelry|gift)\b'),
        ("Health", r'\b(?:gym|fitness|yoga|wellness|medical|dental|health)\b'),
        ("Office", r'\b(?:office|co-working|coworking|professional|tech|startup)\b'),
        ("Grocery", r'\b(?:grocery|supermarket|market|bodega|deli)\b'),
        ("Entertainment", r'\b(?:theater|cinema|arts|gallery|museum|entertainment)\b'),
    ]
    for label, pat in patterns:
        if re.search(pat, text, re.IGNORECASE):
            types.append(label)
    return types[:5]


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

    Returns dict with keys: bullets, sources, residential, commercial,
    res_data, retail_data, commercial_data, error
    """
    if not neighborhood or not borough:
        return {**_EMPTY, "error": "Neighborhood and borough are required"}

    nb = neighborhood.strip()
    bo = borough.strip()

    queries = [
        f'"{nb}" {bo} NYC apartment rents market 2024 2025 residential',
        f'"{nb}" NYC real estate market report 2024 2025 site:therealdeal.com OR site:6sqft.com OR site:bisnow.com',
        f'"{nb}" {bo} retail commercial vacancy rents 2024 site:cbre.com OR site:jll.com OR site:commercialobserver.com',
        f'"{nb}" {bo} apartment studio 1-bedroom average rent 2024 2025',
        f'"{nb}" NYC retail asking rent per square foot 2024 tenant vacancy',
    ]

    all_results = []
    all_snippets = []

    for i, q in enumerate(queries):
        if i > 0:
            time.sleep(random.uniform(1.0, 2.0))
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

    # ── Structured data extraction ──────────────────────────────────────────
    res_snippets  = [s for s in all_snippets if any(k in s.lower() for k in ["studio", "1-bed", "1 bed", "2-bed", "apartment", "rent", "condo"])]
    ret_snippets  = [s for s in all_snippets if any(k in s.lower() for k in ["retail", "psf", "per sq", "ground floor", "storefront", "tenant"])]
    comm_snippets = [s for s in all_snippets if any(k in s.lower() for k in ["office", "commercial", "co-working", "vacancy", "sublease"])]

    # Parse rents from residential snippets
    studio_rent = one_bd_rent = two_bd_rent = three_bd_rent = condo_psf = None
    for snip in res_snippets:
        sl = snip.lower()
        v = _parse_dollar(snip)
        if not v:
            continue
        if studio_rent is None and any(k in sl for k in ["studio", "studio rent"]) and 500 < v < 8000:
            studio_rent = v
        elif one_bd_rent is None and any(k in sl for k in ["1-bed", "1 bed", "one-bed", "one bed"]) and 800 < v < 12000:
            one_bd_rent = v
        elif two_bd_rent is None and any(k in sl for k in ["2-bed", "2 bed", "two-bed", "two bed"]) and 1000 < v < 18000:
            two_bd_rent = v
        elif three_bd_rent is None and any(k in sl for k in ["3-bed", "3 bed", "three-bed", "three bed"]) and 1200 < v < 25000:
            three_bd_rent = v
        if condo_psf is None and any(k in sl for k in ["per sq", "psf", "/sf", "condo"]) and 200 < v < 5000:
            condo_psf = v

    # Parse retail/commercial PSF
    retail_psf = retail_vacancy = None
    retail_tenant_types: list[str] = []
    for snip in ret_snippets:
        v = _parse_psf(snip)
        if v and retail_psf is None and 10 < v < 1000:
            retail_psf = v
        vac = _parse_vacancy(snip)
        if vac and retail_vacancy is None and 0 < vac < 100:
            retail_vacancy = vac
        retail_tenant_types.extend(_extract_tenant_types(snip))

    comm_psf = comm_vacancy = None
    comm_tenant_types: list[str] = []
    for snip in comm_snippets:
        v = _parse_psf(snip)
        if v and comm_psf is None and 10 < v < 500:
            comm_psf = v
        vac = _parse_vacancy(snip)
        if vac and comm_vacancy is None and 0 < vac < 100:
            comm_vacancy = vac
        comm_tenant_types.extend(_extract_tenant_types(snip))

    # Deduplicate tenant types
    retail_tenant_types = list(dict.fromkeys(retail_tenant_types))[:5]
    comm_tenant_types   = list(dict.fromkeys(comm_tenant_types))[:5]

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
        "res_data": {
            "studio_rent":   studio_rent,
            "one_bd_rent":   one_bd_rent,
            "two_bd_rent":   two_bd_rent,
            "three_bd_rent": three_bd_rent,
            "condo_psf":     condo_psf,
            "summary":       residential,
        },
        "retail_data": {
            "asking_rent_psf": retail_psf,
            "tenant_types":    retail_tenant_types,
            "vacancy_pct":     retail_vacancy,
            "summary":         commercial,
        },
        "commercial_data": {
            "asking_rent_psf": comm_psf,
            "tenant_types":    comm_tenant_types,
            "vacancy_pct":     comm_vacancy,
            "summary":         commercial,
        },
        "error": None,
    }

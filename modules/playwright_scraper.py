"""
Playwright-based stealth scraper — headless Chromium fallback.

Used automatically when curl_cffi requests are blocked by Cloudflare or
bot-detection systems. Renders JavaScript, mimics human browsing behavior
(random delays, gradual scrolling, realistic viewport/locale), and applies
playwright-stealth patches to remove automation signals.

No external services or API keys required — runs entirely on local Chromium.
Browser binaries are installed lazily on first use and cached in /tmp.
"""

import json
import os
import random
import re
import subprocess
import time
from typing import Optional

from bs4 import BeautifulSoup

# ── User-agents for Playwright sessions ──────────────────────────────────────
_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

_VIEWPORTS = [
    {"width": 1280, "height": 800},
    {"width": 1440, "height": 900},
    {"width": 1920, "height": 1080},
]

# ── Browser installation (lazy, cached) ──────────────────────────────────────
_PW_READY = False
_PW_FLAG  = "/tmp/.playwright_chromium_ready"


def _ensure_playwright() -> bool:
    """
    Install Chromium browser binaries on first use.
    Uses a /tmp flag file so installation only runs once per container lifecycle.
    """
    global _PW_READY
    if _PW_READY:
        return True
    if os.path.exists(_PW_FLAG):
        _PW_READY = True
        return True
    try:
        result = subprocess.run(
            ["playwright", "install", "chromium", "--with-deps"],
            capture_output=True, timeout=180,
        )
        if result.returncode == 0:
            open(_PW_FLAG, "w").close()
            _PW_READY = True
            return True
        return False
    except Exception:
        return False


# ── Human behaviour helpers ───────────────────────────────────────────────────

def _human_delay(min_s: float = 2.0, max_s: float = 6.0) -> None:
    """Pause for a random interval within [min_s, max_s] seconds."""
    time.sleep(random.uniform(min_s, max_s))


def _human_scroll(page, steps: int = 5) -> None:
    """
    Scroll down the page gradually in randomised increments with short
    pauses between each step — mimics a user reading through results.
    """
    try:
        total_height = page.evaluate("document.body.scrollHeight") or 3000
        step_size = max(200, total_height // steps)
        for _ in range(steps):
            delta = random.randint(step_size // 2, int(step_size * 1.5))
            page.evaluate(f"window.scrollBy(0, {delta})")
            time.sleep(random.uniform(0.3, 0.9))
    except Exception:
        pass


def _random_mouse_move(page) -> None:
    """Move the mouse to a random screen position (reduces automation signals)."""
    try:
        vp = page.viewport_size or {"width": 1280, "height": 800}
        x = random.randint(100, vp["width"] - 100)
        y = random.randint(100, vp["height"] - 100)
        page.mouse.move(x, y)
    except Exception:
        pass


# ── Stealth context factory ───────────────────────────────────────────────────

def _make_stealth_context(browser):
    """
    Create a browser context that looks like a real desktop Chrome session:
    - Randomised viewport and User-Agent
    - New York locale and timezone
    - playwright-stealth patches applied (removes navigator.webdriver etc.)
    """
    ctx = browser.new_context(
        user_agent=random.choice(_USER_AGENTS),
        viewport=random.choice(_VIEWPORTS),
        locale="en-US",
        timezone_id="America/New_York",
        java_script_enabled=True,
        bypass_csp=True,
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"macOS"',
        },
    )
    return ctx


def _apply_stealth(page) -> None:
    """Apply playwright-stealth patches plus manual JS overrides."""
    # playwright-stealth library (if installed)
    try:
        from playwright_stealth import stealth_sync  # type: ignore
        stealth_sync(page)
    except ImportError:
        pass

    # Manual JS overrides to remove common automation fingerprints
    try:
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5],
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en'],
            });
            window.chrome = { runtime: {} };
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications'
                    ? Promise.resolve({ state: Notification.permission })
                    : originalQuery(parameters)
            );
        """)
    except Exception:
        pass


# ── Core render function ──────────────────────────────────────────────────────

def render_page(url: str, wait_selector: Optional[str] = None,
                timeout_ms: int = 30000) -> tuple[str, str]:
    """
    Fetch a URL with headless Chromium + stealth patches.

    Returns (html_content, status) where status is one of:
      'live'    — page loaded and does not appear to be a bot challenge
      'blocked' — Cloudflare or similar challenge detected in the HTML
      'error'   — browser could not be launched or page failed to load
    """
    if not _ensure_playwright():
        return "", "error"

    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError:
        return "", "error"

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--window-size=1920,1080",
                ],
            )
            ctx  = _make_stealth_context(browser)
            page = ctx.new_page()
            _apply_stealth(page)

            # Navigate with a realistic wait strategy
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            _human_delay(1.5, 3.5)
            _random_mouse_move(page)
            _human_scroll(page)
            _human_delay(0.5, 1.5)

            # Wait for a specific element if requested
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=8000)
                    _human_delay(0.5, 1.0)
                except Exception:
                    pass

            html = page.content()
            browser.close()

        # Detect if Cloudflare or similar still challenged us
        snip = html[:5000].lower()
        if any(kw in snip for kw in (
            "just a moment", "cf-browser-verification",
            "verifying you are human", "checking your browser", "ray id",
            "enable javascript and cookies", "ddos-guard",
        )):
            return html, "blocked"
        return html, "live"

    except Exception:
        return "", "error"


# ── Site-specific Playwright scrapers ─────────────────────────────────────────

def pw_streeteasy(lat: float, lon: float, radius_miles: float,
                  bed_filter: Optional[list] = None) -> tuple[list, str]:
    """
    Playwright-based StreetEasy scraper.
    Called automatically by scrape_streeteasy() when curl_cffi is blocked.
    Limits to 3 pages to keep response time reasonable.
    """
    from modules.scraper import _bbox, _se_from_next_data, _se_from_card  # type: ignore

    ne_lat, ne_lng, sw_lat, sw_lng = _bbox(lat, lon, radius_miles)
    listings: list = []

    for page_n in range(1, 4):
        url = (
            "https://streeteasy.com/for-rent/nyc"
            f"?search%5Bstatus%5D=1"
            f"&search%5Bne_lat%5D={ne_lat}&search%5Bne_lng%5D={ne_lng}"
            f"&search%5Bsw_lat%5D={sw_lat}&search%5Bsw_lng%5D={sw_lng}"
            f"&page={page_n}"
        )
        html, status = render_page(
            url,
            wait_selector="[data-testid='listing-card'], article",
            timeout_ms=35000,
        )
        if status == "error":
            return listings, "error" if not listings else "partial"
        if status == "blocked":
            return listings, "blocked" if not listings else "partial"

        soup = BeautifulSoup(html, "lxml")

        # Strategy 1: __NEXT_DATA__ JSON
        nd = soup.find("script", id="__NEXT_DATA__")
        if nd and nd.string:
            try:
                parsed = _se_from_next_data(json.loads(nd.string), lat, lon, bed_filter)
                listings.extend(parsed)
                if not parsed:
                    break
                _human_delay(2.0, 5.0)
                continue
            except Exception:
                pass

        # Strategy 2: HTML listing cards
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
        _human_delay(2.0, 5.0)

    return listings, ("live" if listings else "no_results")


def pw_apartments_com(lat: float, lon: float, radius_miles: float,
                      bed_filter: Optional[list] = None) -> tuple[list, str]:
    """
    Playwright-based Apartments.com scraper.
    Called automatically by scrape_apartments_com() when curl_cffi is blocked.
    Limits to 3 pages to keep response time reasonable.
    """
    from modules.scraper import _bbox, _ap_parse_page  # type: ignore

    ne_lat, ne_lng, sw_lat, sw_lng = _bbox(lat, lon, radius_miles)
    listings: list = []

    for page_n in range(1, 4):
        bbox = f"{sw_lat},{sw_lng},{ne_lat},{ne_lng}"
        url  = f"https://www.apartments.com/new-york-ny/{page_n}/?bb={bbox}"

        html, status = render_page(
            url,
            wait_selector=".placard, article",
            timeout_ms=35000,
        )
        if status == "error":
            return listings, "error" if not listings else "partial"
        if status == "blocked":
            return listings, "blocked" if not listings else "partial"

        soup   = BeautifulSoup(html, "lxml")
        parsed = _ap_parse_page(soup, lat, lon, bed_filter)
        listings.extend(parsed)

        if not parsed and page_n > 1:
            break
        _human_delay(2.0, 5.0)

    return listings, ("live" if listings else "no_results")

"""
Neighborhood Demographics Fetcher — US Census ACS 5-Year Estimates.

Source: Census Bureau ACS 5-Year API, queried by ZCTA (ZIP Code Tabulation
Area — close enough to a NYC ZIP code for screening purposes; the property
dict already carries `zip_code`, so no extra geocoding is needed).
Variables:
  B01003_001E — total population
  B19013_001E — median household income (past 12 months, inflation-adjusted)

Works keyless at low request volume (the Census API's documented anonymous
rate limit is generous enough for interactive single-property lookups); if
a key is later required, thread it through the same sidebar API-key
pattern already used for Google Maps/ScrapingBee/Anthropic (app.py:930-957).

House fetcher-module contract: module-level URL/timeout constants, a
private `_get()` helper that swallows exceptions, and a public function
that always returns the same fixed dict shape, never raises.
"""

from __future__ import annotations

import requests

from modules.app_logging import get_logger

log = get_logger(__name__)

_ACS_URL = "https://api.census.gov/data/2022/acs/acs5"
_TIMEOUT = 15


def _get(params: dict) -> list | None:
    try:
        r = requests.get(_ACS_URL, params=params, timeout=_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, list) else None
    except Exception as exc:
        log.debug("demographics_fetcher: request failed: %s", exc)
    return None


def fetch_demographics(zip_code: str, census_api_key: str | None = None) -> dict:
    """
    Args:
        zip_code: 5-digit ZIP/ZCTA string.
        census_api_key: optional — improves reliability under load but not
            required for interactive single-lookup usage.

    Returns (always this shape, never raises):
        {
          "population": int | None,
          "median_household_income": int | None,
          "zcta": str,
          "verified": True,
          "source": "US Census ACS 5-Year",
          "error": str | None,
        }
    """
    base = {
        "population": None,
        "median_household_income": None,
        "zcta": zip_code or "",
        "verified": True,
        "source": "US Census ACS 5-Year",
        "error": None,
    }
    try:
        zip_clean = str(zip_code or "").strip()[:5]
        if not zip_clean or not zip_clean.isdigit():
            return {**base, "error": "missing/invalid zip code"}

        params = {
            "get": "B01003_001E,B19013_001E",
            "for": f"zip code tabulation area:{zip_clean}",
        }
        if census_api_key:
            params["key"] = census_api_key

        rows = _get(params)
        if not rows or len(rows) < 2:
            return {**base, "error": "no data returned for this ZCTA"}

        header, values = rows[0], rows[1]
        rec = dict(zip(header, values))

        def _int_or_none(v):
            try:
                iv = int(v)
                return iv if iv >= 0 else None  # Census uses negative sentinels for missing data
            except (TypeError, ValueError):
                return None

        return {
            **base,
            "population": _int_or_none(rec.get("B01003_001E")),
            "median_household_income": _int_or_none(rec.get("B19013_001E")),
        }
    except Exception as exc:
        log.warning("fetch_demographics failed: %s", exc)
        return {**base, "error": str(exc)}

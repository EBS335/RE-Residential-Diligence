"""
LL84 Energy & Water Data Disclosure Fetcher — feeds modules/carbon_compliance.py.

One free, keyless public data source: NYC's Local Law 84 annual energy/
water benchmarking disclosure (buildings ≥25,000 GSF must file). Where a
property has a filing, this gives modules.carbon_compliance a REAL
reported total GHG emissions figure to check against Local Law 97's
static per-occupancy-group limits — rather than fabricating an energy-use
estimate from scratch, which would be a far shakier heuristic than
anything else in this app's estimator family.

Same house pattern as modules/environmental_fetcher.py: a private
_get_json() wrapper, a fixed-shape dict return that never raises, and
record_source_status() wiring for the sidebar Data Health panel.

IMPORTANT — dataset-ID caveat (read before relying on this in production):
NYC publishes LL84 disclosure as a SEPARATE Socrata dataset per reporting
year (there is no single stable "current year" ID), and this sandbox's
egress to data.cityofnewyork.us is blocked, so the exact live dataset ID
and field names below could NOT be verified against a real request this
round — more uncertain than this app's other Batch B/C fetchers, which at
least had a stable single dataset ID to guess field names against.
_LL84_DATASET_ID is a single named constant specifically so confirming/
updating it against NYC Open Data's actual current-year LL84 dataset is a
one-line fix. Socrata returns an HTTP 400 for a bad dataset ID or a
$where clause referencing a column that doesn't exist, which the
fallback below catches the same way every other fetcher in this app
does — a wrong guess degrades to an explicit "couldn't confirm" (never a
false "not covered by LL84" negative).
"""

from __future__ import annotations

import requests

from modules.app_logging import get_logger, record_source_status

log = get_logger(__name__)

# NEEDS LIVE CONFIRMATION — see module docstring. Placeholder pointing at
# NYC Open Data's LL84 disclosure dataset family; update to the current
# reporting year's actual dataset ID before relying on this in production.
_LL84_DATASET_ID = "usc3-8zwd"
_LL84_URL = f"https://data.cityofnewyork.us/resource/{_LL84_DATASET_ID}.json"
_LL84_INFO_URL = "https://www.nyc.gov/site/sustainability/codes/benchmarking.page"
_TIMEOUT = 15


def _get_json(url: str, params: dict) -> tuple[list | None, bool]:
    try:
        r = requests.get(url, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json(), True
    except Exception as exc:
        log.warning("ll84_fetcher request to %s failed: %s", url, exc)
        return None, False


def fetch_ll84_emissions(bbl: str) -> dict:
    """
    Look up a property's most recent LL84 energy/water disclosure filing.

    Returns (always this shape, never raises):
        {
          "reported": bool | None,   # False = not found (may be under the
                                      # 25,000 GSF threshold, or just not
                                      # yet filed — NOT necessarily an error)
          "total_ghg_emissions_metric_tons": float | None,
          "ghg_intensity": float | None,   # kgCO2e/sf, if the dataset provides it
          "reporting_year": str | None,
          "info_url": str,
          "source": "NYC LL84 Energy & Water Data Disclosure",
          "verified": bool,   # True only when the query itself succeeded
          "error": str | None,
        }
    """
    base = {
        "reported": None,
        "total_ghg_emissions_metric_tons": None,
        "ghg_intensity": None,
        "reporting_year": None,
        "info_url": _LL84_INFO_URL,
        "source": "NYC LL84 Energy & Water Data Disclosure",
        "verified": False,
        "error": None,
    }
    try:
        if not bbl or len(str(bbl)) < 10:
            return {**base, "error": "missing or malformed BBL"}

        params = {
            "$where": f"nyc_borough_block_and_lot='{bbl}'",
            "$order": "reporting_year DESC",
            "$limit": "1",
        }
        data, ok = _get_json(_LL84_URL, params)
        record_source_status("LL84 Energy Disclosure", ok=ok, detail="" if ok else "LL84 request failed")
        if not ok:
            return {**base, "error": "LL84 request failed, timed out, or the dataset ID/field names have changed"}
        if not isinstance(data, list):
            return {**base, "error": "unexpected response shape"}

        if not data:
            return {**base, "verified": True, "reported": False}

        rec = data[0]

        def _to_float(v):
            try:
                return float(str(v).replace(",", ""))
            except (TypeError, ValueError):
                return None

        return {
            **base, "verified": True, "reported": True,
            "total_ghg_emissions_metric_tons": _to_float(
                rec.get("total_ghg_emissions_metric") or rec.get("total_ghg_emissions")
            ),
            "ghg_intensity": _to_float(
                rec.get("ghg_intensity_kgco2e_ft") or rec.get("ghg_intensity")
            ),
            "reporting_year": rec.get("reporting_year") or rec.get("report_year"),
        }
    except Exception as exc:
        log.warning("fetch_ll84_emissions failed: %s", exc)
        record_source_status("LL84 Energy Disclosure", ok=False, detail=str(exc))
        return {**base, "error": str(exc)}

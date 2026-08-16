"""
Tax Lien Sale List Fetcher — NYC DOF "Property Tax Lien List" (Socrata 9rrd-3h26).

One free, keyless public data source: the DOF list of properties with
unpaid property tax / water & sewer charges eligible for the city's
annual tax lien sale — a strong distress signal distinct from DOB/HPD
violations or ACRIS liens/foreclosures (feeds modules/distress_scorer.py
alongside those).

Same house pattern as modules/environmental_fetcher.py: a private
_get_json() wrapper, a fixed-shape dict return that never raises, and
record_source_status() wiring for the sidebar Data Health panel.

This sandbox cannot verify the live 9rrd-3h26 schema against a real
request (network egress to data.cityofnewyork.us is blocked here) — the
borough/block/lot field-name guesses below (boro, block, lot) match the
convention used by every other NYC DOF/DOB Socrata dataset already wired
into this app (e.g. modules/pip_fetcher.py, modules/nyc_boundaries.py).
Socrata returns an HTTP 400 for a $where clause referencing a column
that doesn't exist, which the fallback below catches the same way
environmental_fetcher.py's DEC-spills query does — a wrong guess
degrades to an explicit "couldn't confirm" rather than a false negative.
"""

from __future__ import annotations

import requests

from modules.app_logging import get_logger, record_source_status

log = get_logger(__name__)

_LIEN_LIST_URL = "https://data.cityofnewyork.us/resource/9rrd-3h26.json"
_LIEN_SALE_INFO_URL = "https://www.nyc.gov/site/finance/property/property-tax-lien-sale.page"
_TIMEOUT = 15


def _get_json(url: str, params: dict) -> tuple[list | None, bool]:
    try:
        r = requests.get(url, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json(), True
    except Exception as exc:
        log.warning("tax_lien_fetcher request to %s failed: %s", url, exc)
        return None, False


def fetch_tax_lien_status(borough_code: str, block: str, lot: str) -> dict:
    """
    Look up whether a parcel appears on the current DOF Tax Lien Sale
    List — properties with unpaid taxes/water charges eligible for lien
    sale, a distinct and typically more severe distress signal than a
    routine violation.

    Returns (always this shape, never raises):
        {
          "on_lien_list": bool | None,   # None = could not confirm either way
          "records": list[dict],
          "count": int,
          "info_url": str,
          "source": "NYC DOF Tax Lien Sale List",
          "verified": bool,              # True only when the query itself succeeded
          "error": str | None,
        }
    """
    base = {
        "on_lien_list": None,
        "records": [],
        "count": 0,
        "info_url": _LIEN_SALE_INFO_URL,
        "source": "NYC DOF Tax Lien Sale List",
        "verified": False,
        "error": None,
    }
    try:
        if not borough_code or not block or not lot:
            return {**base, "error": "missing borough/block/lot"}

        params = {
            "$where": f"boro='{borough_code}' AND block='{int(block)}' AND lot='{int(lot)}'",
            "$limit": "10",
        }
        data, ok = _get_json(_LIEN_LIST_URL, params)
        record_source_status("Tax Lien Sale List", ok=ok, detail="" if ok else "lien list request failed")
        if not ok:
            return {**base, "error": "tax lien list request failed, timed out, or field names have changed"}
        if not isinstance(data, list):
            return {**base, "error": "unexpected response shape"}

        records = [{
            "owner_name": r.get("owner_name", r.get("owner", "")),
            "total_due": r.get("total_amount_due", r.get("total_due", "")),
            "class": r.get("class", r.get("tax_class", "")),
        } for r in data]

        return {
            **base, "verified": True, "records": records, "count": len(records),
            "on_lien_list": len(records) > 0,
        }
    except Exception as exc:
        log.warning("fetch_tax_lien_status failed: %s", exc)
        record_source_status("Tax Lien Sale List", ok=False, detail=str(exc))
        return {**base, "error": str(exc)}

"""
Development Momentum Fetcher — NYC DOB Permit Issuance (Socrata ipu4-2q9a).

One free, keyless public data source: the same DOB Permit Issuance
dataset already used per-parcel in modules/pip_fetcher.py, queried here
in a NEW, AGGREGATE shape — a count of recent New-Building (NB) permit
filings in a community district, as a "how much ground-up development
activity is happening here right now" momentum signal for an AREA, not
one property. This is deliberately NOT a reuse of
modules/nearby_developments.py::fetch_nearby_developments() (that
function is single-property, issues several sequential RSS/DOB fetches
with sleeps between them, and is unsuitable to call once per bulk-search
result) — this module issues exactly ONE Socrata aggregate query per
community district, meant to be called once per DISTINCT community
district represented in a Site Finder search, not once per property.

Same house pattern as modules/tax_lien_fetcher.py / modules/ceqr_fetcher.py:
a private _get_json() wrapper, a fixed-shape dict return that never
raises, and record_source_status() wiring for the sidebar Data Health
panel.

This sandbox cannot verify the live ipu4-2q9a schema against a real
request (network egress to data.cityofnewyork.us is blocked here). The
`borough` field-name/format guess (full borough name, uppercased) is
confirmed by modules/pip_fetcher.py's own existing, already-working query
against this exact dataset. The community-district field name
(`community_board`) is an unverified guess, following the same
"Socrata 400s on an unknown $where column -> couldn't confirm, never a
false negative" resilience modules/tax_lien_fetcher.py and
modules/ceqr_fetcher.py already rely on for their own guessed field
names.
"""

from __future__ import annotations

import datetime
import requests

from modules.app_logging import get_logger, record_source_status

log = get_logger(__name__)

_DOB_PERMITS_URL = "https://data.cityofnewyork.us/resource/ipu4-2q9a.json"
_TIMEOUT = 15

# borough_code (single-digit BBL convention, matching every other fetcher
# in this app, e.g. modules/tax_lien_fetcher.py/modules/ceqr_fetcher.py)
# -> this dataset's own borough field format, confirmed via
# modules/pip_fetcher.py's existing working query against ipu4-2q9a.
_BOROUGH_NAME = {
    "1": "MANHATTAN", "2": "BRONX", "3": "BROOKLYN", "4": "QUEENS", "5": "STATEN ISLAND",
}


def _get_json(url: str, params: dict) -> tuple[list | None, bool]:
    try:
        r = requests.get(url, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json(), True
    except Exception as exc:
        log.warning("dev_momentum_fetcher request to %s failed: %s", url, exc)
        return None, False


def fetch_dev_momentum(borough_code: str, community_district: str, months_back: int = 12) -> dict:
    """
    Count recent DOB New-Building (NB) permit filings in a community
    district — a "how much ground-up development activity is happening
    here right now" momentum signal, meant to be called once per DISTINCT
    community district in a Site Finder search area (not once per
    property).

    Args:
        borough_code:        single-digit BBL borough code ("1"-"5"),
                              same convention as every other fetcher here.
        community_district:  3-digit code (borough + district, e.g. "105"
                              = Manhattan CD 5) — same format as
                              property_search.py's normalized
                              "community_district" field. Normalized to
                              just the district number internally, same
                              as modules/ceqr_fetcher.py does for this
                              same value shape.
        months_back:         how many months of filings to count (default 12).

    Returns (always this shape, never raises):
        {
          "nb_permit_count": int,
          "community_district": str,   # echoes the input, normalized
          "months_back": int,
          "source": "DOB Permit Issuance",
          "verified": bool,   # True only when the query itself succeeded
          "error": str | None,
        }
    """
    base = {
        "nb_permit_count": 0,
        "community_district": str(community_district or ""),
        "months_back": months_back,
        "source": "DOB Permit Issuance",
        "verified": False,
        "error": None,
    }
    try:
        if not borough_code or not community_district:
            return {**base, "error": "missing borough/community district"}
        boro = _BOROUGH_NAME.get(str(borough_code))
        if not boro:
            return {**base, "error": f"unrecognized borough code: {borough_code}"}

        cd_num = str(community_district).strip()[-2:].lstrip("0") or "0"
        cutoff = (datetime.date.today() - datetime.timedelta(days=30 * months_back)).isoformat()

        params = {
            "$where": (
                f"borough='{boro}' AND community_board='{cd_num}' "
                f"AND job_type='NB' AND filing_date > '{cutoff}'"
            ),
            "$select": "count(*) as cnt",
        }
        data, ok = _get_json(_DOB_PERMITS_URL, params)
        record_source_status("DOB Permit Issuance (momentum)", ok=ok, detail="" if ok else "permit momentum request failed")
        if not ok:
            return {**base, "error": "DOB permits request failed, timed out, or field names have changed"}
        if not isinstance(data, list):
            return {**base, "error": "unexpected response shape"}

        count = 0
        if data:
            try:
                count = int(data[0].get("cnt", 0))
            except (TypeError, ValueError):
                count = 0

        return {**base, "verified": True, "nb_permit_count": count}
    except Exception as exc:
        log.warning("fetch_dev_momentum failed: %s", exc)
        record_source_status("DOB Permit Issuance (momentum)", ok=False, detail=str(exc))
        return {**base, "error": str(exc)}

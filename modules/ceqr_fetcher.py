"""
CEQR/ULURP Fetcher — NYC Planning ULURP Applications (Socrata w7w3-xahh).

One free, keyless public data source: NYC Department of City Planning's
ULURP (Uniform Land Use Review Procedure) application records — real case
data, as opposed to modules/zoning_rules.py's estimate_entitlement_path(),
which only keyword-matches a massing scenario's description against a
static entitlement-path table. This module is a first step (fetch +
display nearby/recent applications by community district); using these
records to ground estimate_entitlement_path() in real case precedent is
left for a later round, per the plan.

ULURP applications are typically filed at the project level (often
spanning multiple lots or a whole rezoning area), not always tied to one
exact BBL — so this queries by borough + community district, a coarser
but meaningful "is there active/recent land-use review activity nearby"
signal, similar in spirit to modules/environmental_fetcher.py's
county-level DEC-spills fallback.

Same house pattern as modules/environmental_fetcher.py: a private
_get_json() wrapper, a fixed-shape dict return that never raises, and
record_source_status() wiring for the sidebar Data Health panel.

This sandbox cannot verify the live w7w3-xahh schema against a real
request (network egress to data.cityofnewyork.us is blocked here) — the
field-name guesses below (borough, community_district / cd) are drawn
from NYC Planning's publicly documented ULURP application column list. A
wrong guess is caught the same way environmental_fetcher.py's DEC-spills
fallback is: Socrata 400s on an unknown $where column, treated as
"couldn't confirm," never as a false "no applications" negative.
"""

from __future__ import annotations

import requests

from modules.app_logging import get_logger, record_source_status

log = get_logger(__name__)

_ULURP_URL = "https://data.cityofnewyork.us/resource/w7w3-xahh.json"
_ULURP_INFO_URL = "https://www.nyc.gov/site/planning/applicants/applicant-portal.page"
_TIMEOUT = 15

_BOROUGH_NAME = {
    "1": "MN", "2": "BX", "3": "BK", "4": "QN", "5": "SI",
}


def _get_json(url: str, params: dict) -> tuple[list | None, bool]:
    try:
        r = requests.get(url, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json(), True
    except Exception as exc:
        log.warning("ceqr_fetcher request to %s failed: %s", url, exc)
        return None, False


def fetch_ulurp_applications(borough_code: str, community_district: str, limit: int = 15) -> dict:
    """
    Look up recent/active ULURP applications filed in a parcel's community
    district — coarser than a per-parcel match, but a genuine signal of
    nearby rezoning/entitlement activity that could affect the subject
    site's near-term zoning context.

    Returns (always this shape, never raises):
        {
          "applications": list[dict],   # ulurp_no, project_name, certified_date, status
          "count": int,
          "info_url": str,
          "source": "NYC Planning ULURP Applications",
          "verified": bool,   # True only when the query itself succeeded
          "error": str | None,
        }
    """
    base = {
        "applications": [],
        "count": 0,
        "info_url": _ULURP_INFO_URL,
        "source": "NYC Planning ULURP Applications",
        "verified": False,
        "error": None,
    }
    try:
        if not borough_code or not community_district:
            return {**base, "error": "missing borough/community district"}
        boro = _BOROUGH_NAME.get(str(borough_code))
        if not boro:
            return {**base, "error": f"unrecognized borough code: {borough_code}"}

        # community_district is typically a 3-digit code (borough+district,
        # e.g. "302" = Brooklyn CD 3) elsewhere in this app — normalize to
        # just the district number for this dataset's likely field shape.
        cd_num = str(community_district).strip()[-2:].lstrip("0") or "0"

        params = {
            "$where": f"borough='{boro}' AND community_district='{cd_num}'",
            "$order": "certified_referred_date DESC",
            "$limit": str(limit),
        }
        data, ok = _get_json(_ULURP_URL, params)
        record_source_status("ULURP Applications", ok=ok, detail="" if ok else "ULURP request failed")
        if not ok:
            return {**base, "error": "ULURP request failed, timed out, or field names have changed"}
        if not isinstance(data, list):
            return {**base, "error": "unexpected response shape"}

        applications = [{
            "ulurp_no": r.get("ulurp_no", ""),
            "project_name": r.get("project_name", ""),
            "certified_date": (r.get("certified_referred_date", "") or "")[:10],
            "status": r.get("status", r.get("current_stage", "")),
        } for r in data]

        return {**base, "verified": True, "applications": applications, "count": len(applications)}
    except Exception as exc:
        log.warning("fetch_ulurp_applications failed: %s", exc)
        record_source_status("ULURP Applications", ok=False, detail=str(exc))
        return {**base, "error": str(exc)}


def _normalize_cd_num(community_district) -> str:
    """Same normalization rule fetch_ulurp_applications() applies inline —
    a 3-digit borough+district code (e.g. "302") down to just the district
    number ("2") this dataset's field is keyed on. Extracted so the batched
    function below can reuse it without duplicating the rule."""
    return str(community_district).strip()[-2:].lstrip("0") or "0"


def fetch_ulurp_applications_by_cds(
    borough_code: str, community_districts: list[str], limit: int = 15
) -> dict[str, dict]:
    """
    Batched sibling of fetch_ulurp_applications(): looks up ULURP
    applications for MULTIPLE community districts within one borough in a
    SINGLE Socrata request (community_district IN(...)), instead of one
    request per district — meant to be called once per borough present in
    a Site Finder search area, not once per district.

    Does NOT call record_source_status() (unlike fetch_ulurp_applications)
    — this is intentional: callers running this from a worker thread must
    record source status themselves, on the main thread, after collecting
    the result (record_source_status() writes to st.session_state, which
    is not thread-safe).

    Args:
        borough_code:          single-digit BBL borough code ("1"-"5").
        community_districts:   3-digit codes (e.g. "302"), any duplicates
                                are deduped internally.
        limit:                 max applications kept PER community district
                                (same semantics as fetch_ulurp_applications's
                                own `limit`, applied client-side after the
                                single batched fetch).

    Returns: dict keyed by each ORIGINAL (unnormalized) community_district
    string passed in, each value the exact same per-CD shape
    fetch_ulurp_applications() returns (never raises; a district with zero
    matching applications still gets `{"verified": True, "count": 0,
    "applications": []}`; on a request failure every requested district
    gets `{"verified": False, "error": "..."}`).
    """
    def _base_for(cd: str) -> dict:
        return {
            "applications": [], "count": 0, "info_url": _ULURP_INFO_URL,
            "source": "NYC Planning ULURP Applications", "verified": False, "error": None,
        }

    community_districts = list(community_districts or [])
    if not community_districts:
        return {}
    if not borough_code:
        return {cd: {**_base_for(cd), "error": "missing borough"} for cd in community_districts}
    boro = _BOROUGH_NAME.get(str(borough_code))
    if not boro:
        return {
            cd: {**_base_for(cd), "error": f"unrecognized borough code: {borough_code}"}
            for cd in community_districts
        }

    # Map normalized district number -> every original input string that
    # normalized to it (usually one-to-one; a collision is a harmless
    # degenerate case since callers pass the distinct CDs of one borough).
    norm_to_originals: dict[str, list[str]] = {}
    for cd in community_districts:
        norm_to_originals.setdefault(_normalize_cd_num(cd), []).append(cd)

    in_list = ",".join(f"'{n}'" for n in sorted(norm_to_originals))
    shared_limit = min(1000, limit * max(len(norm_to_originals), 1) * 5)

    try:
        params = {
            "$where": f"borough='{boro}' AND community_district IN({in_list})",
            "$order": "certified_referred_date DESC",
            "$limit": str(shared_limit),
        }
        data, ok = _get_json(_ULURP_URL, params)
        if not ok or not isinstance(data, list):
            return {
                cd: {**_base_for(cd), "error": "ULURP batched request failed, timed out, or field names have changed"}
                for cd in community_districts
            }

        by_norm: dict[str, list[dict]] = {}
        for r in data:
            norm = _normalize_cd_num(r.get("community_district", ""))
            by_norm.setdefault(norm, []).append({
                "ulurp_no": r.get("ulurp_no", ""),
                "project_name": r.get("project_name", ""),
                "certified_date": (r.get("certified_referred_date", "") or "")[:10],
                "status": r.get("status", r.get("current_stage", "")),
            })

        result: dict[str, dict] = {}
        for norm, originals in norm_to_originals.items():
            apps = by_norm.get(norm, [])[:limit]
            for cd in originals:
                result[cd] = {**_base_for(cd), "verified": True, "applications": apps, "count": len(apps)}
        return result
    except Exception as exc:
        log.warning("fetch_ulurp_applications_by_cds failed: %s", exc)
        return {cd: {**_base_for(cd), "error": str(exc)} for cd in community_districts}

"""
ECB Violations Fetcher — NYC Open Data.

Fetches Environmental Control Board (ECB) violations for a given BBL
from the NYC Open Data dataset (w9ak-ipjd). No API key required.

Returns violation records plus a distress score (Low / Medium / High).
"""

from __future__ import annotations
import re
import requests

_ECB_URL = "https://data.cityofnewyork.us/resource/w9ak-ipjd.json"
_TIMEOUT = 12

_EMPTY = {
    "violations": [],
    "count": 0,
    "open_count": 0,
    "distress_score": "Low",
    "distress_level": 0,
    "error": None,
}


def _clean_bbl(bbl: str) -> str:
    """Strip non-digits and zero-pad to 10 chars if needed."""
    digits = re.sub(r"\D", "", str(bbl))
    return digits.zfill(10) if digits else ""


def fetch_ecb_violations(bbl: str, lien_count: int = 0) -> dict:
    """
    Fetch open ECB violations for a BBL from NYC Open Data.

    Args:
        bbl: Property BBL string (10-digit or with dashes/spaces).
        lien_count: Number of ACRIS lien documents already found (UCC1, LIEN, etc.)
                    Used to augment the distress score.

    Returns dict:
        violations   : list of violation records (dicts)
        count        : total violations returned
        open_count   : violations with outstanding balance
        distress_score : "Low" | "Medium" | "High"
        distress_level : 0 | 1 | 2
        error        : str | None
    """
    clean = _clean_bbl(bbl)
    if not clean:
        return {**_EMPTY, "error": "Invalid BBL"}

    try:
        resp = requests.get(
            _ECB_URL,
            params={
                "boro_block_lot": clean,
                "$limit": "50",
                "$order": "issue_date DESC",
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        rows = resp.json()
    except Exception as exc:
        return {**_EMPTY, "error": str(exc)}

    if not isinstance(rows, list):
        return {**_EMPTY, "error": "Unexpected response format"}

    violations = []
    for r in rows:
        violations.append({
            "issue_date":      r.get("issue_date", "")[:10],
            "violation_type":  r.get("violation_type", "—"),
            "description":     r.get("description", r.get("infraction_codes", "—")),
            "respondent":      r.get("respondent_name", "—"),
            "penalty":         r.get("penalty_imposed", "—"),
            "balance_due":     r.get("balance_due", "0"),
            "status":          r.get("ecb_violation_status", "—"),
        })

    # Open = has outstanding balance
    open_count = sum(
        1 for v in violations
        if str(v.get("balance_due", "0")).strip() not in ("0", "0.00", "0.0", "")
    )

    total_signals = open_count + lien_count

    if total_signals >= 6:
        distress_score = "High"
        distress_level = 2
    elif total_signals >= 3:
        distress_score = "Medium"
        distress_level = 1
    else:
        distress_score = "Low"
        distress_level = 0

    return {
        "violations":     violations,
        "count":          len(violations),
        "open_count":     open_count,
        "distress_score": distress_score,
        "distress_level": distress_level,
        "error":          None,
    }

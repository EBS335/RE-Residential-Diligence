"""
HPD Open Violations Fetcher — NYC Open Data.

Fetches HPD (Housing Preservation & Development) violations for a given BBL
from the NYC Open Data dataset (wvxf-dwi5). No API key required.

Returns violation records plus a distress score (Low / Medium / High)
based on Class C (immediately hazardous) violations and ACRIS lien count.

Classes:
  A — Non-hazardous
  B — Hazardous
  C — Immediately hazardous
"""

from __future__ import annotations
import re
import requests

_HPD_URL = "https://data.cityofnewyork.us/resource/wvxf-dwi5.json"
_TIMEOUT = 12

_EMPTY = {
    "violations": [],
    "count": 0,
    "open_count": 0,
    "class_a": 0,
    "class_b": 0,
    "class_c": 0,
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
    Fetch HPD Open Violations for a BBL from NYC Open Data.

    Args:
        bbl:        Property BBL string (10-digit or with dashes/spaces).
        lien_count: Number of ACRIS lien documents already found (UCC1, LIEN, etc.)
                    Used to augment the distress score.

    Returns dict:
        violations    : list of violation records (dicts)
        count         : total violations returned
        open_count    : violations with status "Open"
        class_a       : count of Class A (non-hazardous)
        class_b       : count of Class B (hazardous)
        class_c       : count of Class C (immediately hazardous)
        distress_score: "Low" | "Medium" | "High"
        distress_level: 0 | 1 | 2
        error         : str | None
    """
    clean = _clean_bbl(bbl)
    if not clean:
        return {**_EMPTY, "error": "Invalid BBL"}

    try:
        resp = requests.get(
            _HPD_URL,
            params={"bbl": clean, "$limit": "100"},
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
        desc = r.get("novdescription") or r.get("novtype") or "—"
        violations.append({
            "issue_date":     (r.get("inspectiondate") or "")[:10],
            "violation_type": r.get("class", "—"),
            "description":    str(desc)[:100],
            "apartment":      r.get("apartment", "—"),
            "status":         r.get("violationstatus", "—"),
            "penalty":        "—",
            "balance_due":    "0",
        })

    class_a  = sum(1 for r in rows if str(r.get("class", "")).upper() == "A")
    class_b  = sum(1 for r in rows if str(r.get("class", "")).upper() == "B")
    class_c  = sum(1 for r in rows if str(r.get("class", "")).upper() == "C")
    open_ct  = sum(1 for r in rows if str(r.get("violationstatus", "")).lower() == "open")

    # Distress driven by Class C (immediately hazardous) + ACRIS liens
    total_signals = class_c + lien_count

    if total_signals >= 4:
        distress_score = "High"
        distress_level = 2
    elif total_signals >= 2:
        distress_score = "Medium"
        distress_level = 1
    else:
        distress_score = "Low"
        distress_level = 0

    return {
        "violations":     violations,
        "count":          len(violations),
        "open_count":     open_ct,
        "class_a":        class_a,
        "class_b":        class_b,
        "class_c":        class_c,
        "distress_score": distress_score,
        "distress_level": distress_level,
        "error":          None,
    }

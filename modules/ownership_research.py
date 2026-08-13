"""
Ownership & Distress Research — Site Finder Phase 2.

Batch-enriches Site Finder candidate properties with ownership, ACRIS
transaction history, and DOB/HPD violation counts, then classifies a
conservative distress signal. Reuses the SAME fetchers already used by
the Property Analysis tab (modules/acris_fetcher.py, modules/pip_fetcher.py)
so there is only one source of truth for how this data is retrieved.

IMPORTANT: This module never asserts that an owner IS financially
distressed. It only classifies observable public-record SIGNALS into
No / Weak / Moderate / Strong — see classify_distress() docstring.
"""

from __future__ import annotations
import re
import time

from modules.acris_fetcher import fetch_acris
from modules.pip_fetcher import fetch_property_history
from modules.app_logging import record_source_status

# Batch size cap — ACRIS + DOB/HPD are live network calls per property,
# so bulk-enriching is intentionally limited to a manageable top-N slice
# of already deal-score-ranked results, not the full result set.
DEFAULT_BATCH_SIZE = 25

# Gap between PROPERTIES (not documents) in enrich_ownership_batch()'s loop.
# Each property can trigger 10-15+ unauthenticated NYC Open Data requests
# (ACRIS's 4-tier fallback + party lookups, DOB/HPD's 5 endpoints) with no
# app token — a burst of these back-to-back across 25 properties is a
# plausible trigger for Socrata's anonymous-tier rate limiting. This pacing
# targets that burstiness directly rather than shrinking the batch size.
_BATCH_PACING_SECONDS = 0.4

_ENTITY_MARKERS = (
    "LLC", "L L C", "LP", "L P", "LLP", "INC", "CORP", "CO ", " CO",
    "CO.", "TRUST", "TRUS", "ASSOCIATES", "ASSOC", "PARTNERS", "REALTY",
    "HOLDINGS", "PROPERTIES", "MANAGEMENT", "GROUP", "ENTERPRISES",
)
_GOVERNMENT_MARKERS = (
    "CITY OF NEW YORK", "NYC HOUSING", "NYCHA", "HOUSING AUTHORITY",
    "DEPT OF", "DEPARTMENT OF", "BOARD OF EDUCATION", "PARKS DEPT",
    "HPD", "EDC", "SCA ", "STATE OF NEW YORK", "PORT AUTHORITY",
)
_NONPROFIT_MARKERS = (
    "FOUNDATION", "CHURCH", "TEMPLE", "SYNAGOGUE", "PARISH", "DIOCESE",
    "NOT FOR PROFIT", "NFP", "INC.", "MINISTRIES", "CATHEDRAL",
    "HOUSING DEVELOPMENT FUND", "HDFC",
)


def detect_owner_type(owner_name: str) -> str:
    """
    Classify a PLUTO/ACRIS owner-of-record string into a coarse type.
    Returns one of: "Individual", "Corporate Entity", "Nonprofit",
    "Government", "Unknown".
    """
    if not owner_name or not owner_name.strip():
        return "Unknown"
    name = owner_name.upper()

    if any(m in name for m in _GOVERNMENT_MARKERS):
        return "Government"
    if any(m in name for m in _NONPROFIT_MARKERS):
        return "Nonprofit"
    if any(m in name for m in _ENTITY_MARKERS):
        return "Corporate Entity"

    # Heuristic: individual names are typically 2-4 words, no entity markers
    words = name.split()
    if 1 <= len(words) <= 4 and not any(ch.isdigit() for ch in name):
        return "Individual"
    return "Unknown"


def classify_distress(
    acris_summary: dict,
    dob_hpd_summary: dict,
    year_built: str = "",
) -> dict:
    """
    Classify observable public-record distress SIGNALS (not a claim of
    actual financial distress) into No / Weak / Moderate / Strong, with
    the underlying evidence listed so a human can judge for themselves.

    Returns: {"level": str, "score": int, "evidence": list[str]}
    """
    evidence: list[str] = []
    score = 0

    open_liens   = acris_summary.get("open_liens", 0) or 0
    forecl_count = acris_summary.get("foreclosure_count", 0) or 0
    if forecl_count > 0:
        score += 4
        evidence.append(f"{forecl_count} foreclosure/lis pendens document(s) on ACRIS")
    if open_liens >= 2:
        score += 2
        evidence.append(f"{open_liens} open liens/UCC filings")
    elif open_liens == 1:
        score += 1
        evidence.append("1 open lien/UCC filing")

    open_dob = dob_hpd_summary.get("open_dob_viol", 0) or 0
    total_dob = dob_hpd_summary.get("total_dob_viol", 0) or 0
    open_complaints = dob_hpd_summary.get("open_complaints", 0) or 0
    if open_dob > 15:
        score += 2
        evidence.append(f"{open_dob} open DOB violations")
    elif open_dob > 5:
        score += 1
        evidence.append(f"{open_dob} open DOB violations")
    if total_dob > 30:
        score += 1
        evidence.append(f"{total_dob} total DOB violations on record")
    if open_complaints > 10:
        score += 1
        evidence.append(f"{open_complaints} open DOB complaints")

    try:
        yb = int(float(year_built))
        if 0 < yb < 1930:
            score += 1
            evidence.append(f"Pre-1930 construction (built {yb})")
    except (TypeError, ValueError):
        pass

    if score >= 6:
        level = "Strong Signal"
    elif score >= 3:
        level = "Moderate Signal"
    elif score >= 1:
        level = "Weak Signal"
    else:
        level = "No Signal"
        evidence = evidence or ["No violations, liens, or foreclosure filings found in public records checked"]

    return {"level": level, "score": score, "evidence": evidence}


def enrich_ownership(prop: dict, borough_name: str = "") -> dict:
    """
    Fetch ACRIS + DOB/HPD data for a SINGLE property and attach ownership
    research fields. Does not mutate the input; returns a new dict.

    Added keys:
        owner_type          — Individual / Corporate Entity / Nonprofit / Government / Unknown
        last_sale_price      — float | None
        last_sale_date       — str | None
        active_mortgage_amt — float | None
        active_lender        — str | None
        open_liens            — int
        foreclosure_count     — int
        dob_open_violations   — int
        hpd_dwelling_units    — str
        distress              — {"level", "score", "evidence"}
        acris_url             — str
        pip_url                — str
        acris_error            — str | None, set if the ACRIS fetch itself
                                  failed/timed out (distinct from a
                                  confirmed-clean "no records found" result)
        pip_error               — str | None, same for the DOB/HPD fetch
    """
    out = dict(prop)
    bbl = prop.get("bbl", "")
    boro = borough_name or prop.get("borough", "")

    acris = fetch_acris(bbl) if bbl else {}
    a_summ = acris.get("summary", {}) if acris else {}

    pip = fetch_property_history(bbl, borough_name=boro, address=prop.get("address", "")) if bbl else {}
    p_summ = pip.get("summary", {}) if pip else {}
    hpd_bld = pip.get("hpd_building", {}) if pip else {}

    owner_name = prop.get("owner") or a_summ.get("latest_buyer") or ""
    distress = classify_distress(a_summ, p_summ, prop.get("year_built", ""))

    out.update({
        "owner_type":           detect_owner_type(owner_name),
        "last_sale_price":      a_summ.get("latest_sale_price"),
        "last_sale_date":       a_summ.get("latest_sale_date"),
        "active_mortgage_amt":  a_summ.get("active_mortgage_amt"),
        "active_lender":        a_summ.get("active_lender"),
        "open_liens":           a_summ.get("open_liens", 0),
        "foreclosure_count":    a_summ.get("foreclosure_count", 0),
        "dob_open_violations":  p_summ.get("open_dob_viol", 0),
        "hpd_dwelling_units":   hpd_bld.get("dwelling_units", ""),
        "distress":             distress,
        "distress_signal":      distress["level"],   # overrides the PLUTO-only quick pass
        "acris_url":            acris.get("acris_url", ""),
        "pip_url":              pip.get("pip_url", ""),
        "acris_error":          acris.get("error"),
        "pip_error":            pip.get("error"),
    })
    return out


def enrich_ownership_batch(
    properties: list[dict],
    batch_size: int = DEFAULT_BATCH_SIZE,
    progress_callback=None,
) -> list[dict]:
    """
    Enrich the top `batch_size` properties (already assumed sorted by
    deal score) with ownership/ACRIS/distress data. Properties beyond
    the batch are returned unchanged (still carrying their PLUTO-only
    quick-pass distress_signal from site_sourcing.enrich_property()).

    progress_callback(i, n): optional callable invoked after each fetch,
    e.g. for a Streamlit progress bar.
    """
    to_enrich = properties[:batch_size]
    remainder = properties[batch_size:]

    enriched = []
    n = len(to_enrich)
    for i, prop in enumerate(to_enrich, start=1):
        try:
            enriched.append(enrich_ownership(prop, borough_name=prop.get("borough", "")))
        except Exception as exc:
            fallback = dict(prop)
            fallback["ownership_error"] = str(exc)
            enriched.append(fallback)
        if progress_callback:
            progress_callback(i, n)
        if i < n:
            time.sleep(_BATCH_PACING_SECONDS)

    fail_count = sum(
        1 for p in enriched
        if p.get("ownership_error") or p.get("acris_error") or p.get("pip_error")
    )
    if n:
        record_source_status(
            "Ownership Batch Enrichment (ACRIS/DOB-HPD)",
            ok=(fail_count == 0),
            detail=(
                "All properties enriched cleanly" if fail_count == 0
                else f"{fail_count} of {n} propert{'y' if n == 1 else 'ies'} had an ACRIS/DOB-HPD fetch issue"
            ),
        )

    return enriched + remainder

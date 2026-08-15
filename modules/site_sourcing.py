"""
Site Sourcing Heuristics — Site Finder opportunity classification.

Given a normalized PLUTO property row (from modules/property_search.py),
classify it into one or more development-strategy candidate buckets and
compute a preliminary Opportunity Score (0-100), independent of the
0-100 Deal Score computed later by modules/deal_scorer.py.

This module makes NO web requests — pure calculation over PLUTO fields.
All classifications are heuristic first-pass signals, not confirmed
findings; every property should still go through zoning/ownership/market
diligence before an acquisition decision.
"""

from __future__ import annotations
import re

# Strategy labels
STRATEGY_VACANT       = "Vacant / Underutilized"
STRATEGY_DEMOLITION   = "Demolition Candidate"
STRATEGY_CONVERSION   = "Conversion / Redevelopment"
STRATEGY_GROUND_UP    = "Ground-Up (Vacant)"

_OLD_BUILDING_YEAR = 1945          # pre/immediate-postwar construction
_LOW_FAR_UTIL_PCT  = 50.0          # existing FAR < 50% of max => underbuilt
_LARGE_FLOORPLATE_SF = 15000.0     # large-floorplate buildings suit conversion
_OBSOLETE_BLDG_CLASSES = {"G", "E", "F"}   # garage, warehouse, factory


def classify_strategies(prop: dict) -> list[str]:
    """
    Return the list of development-strategy buckets this property is a
    plausible candidate for, based on PLUTO characteristics alone.
    """
    strategies: list[str] = []

    lot_sf   = prop.get("lot_sf", 0.0)
    bldg_sf  = prop.get("bldg_sf", 0.0)
    far_max  = prop.get("far_max", 0.0)
    far_built = prop.get("far_built", 0.0)
    year_built = prop.get("year_built", "")
    bldg_class = (prop.get("bldg_class") or "")[:1].upper()
    num_floors = prop.get("num_floors", 0.0)
    is_vacant  = prop.get("is_vacant", False)

    # ── Vacant / severely underutilized land ────────────────────────────────
    if is_vacant or (lot_sf > 0 and bldg_sf / lot_sf < 0.15):
        strategies.append(STRATEGY_VACANT)
        strategies.append(STRATEGY_GROUND_UP)

    # ── Demolition candidate ────────────────────────────────────────────────
    is_old = False
    try:
        is_old = 0 < int(float(year_built)) <= _OLD_BUILDING_YEAR
    except (TypeError, ValueError):
        pass

    far_util_pct = (far_built / far_max * 100.0) if far_max > 0 else 0.0
    is_underbuilt = far_max > 0 and far_util_pct < _LOW_FAR_UTIL_PCT
    is_low_rise_on_large_lot = num_floors <= 2 and lot_sf >= 5000 and not is_vacant
    is_obsolete_class = bldg_class in _OBSOLETE_BLDG_CLASSES

    if not is_vacant and (is_old or is_underbuilt or is_low_rise_on_large_lot or is_obsolete_class):
        strategies.append(STRATEGY_DEMOLITION)

    # ── Conversion / redevelopment candidate ────────────────────────────────
    is_large_floorplate = num_floors > 0 and (bldg_sf / max(num_floors, 1)) >= _LARGE_FLOORPLATE_SF
    is_office_or_hotel   = bldg_class in {"O", "K", "H"}
    is_industrial        = bldg_class in {"E", "F", "L"}

    if not is_vacant and (is_large_floorplate or is_office_or_hotel or is_industrial):
        strategies.append(STRATEGY_CONVERSION)

    return strategies or ([STRATEGY_VACANT] if is_vacant else [])


def compute_opportunity_score(prop: dict) -> dict:
    """
    Compute a preliminary 0-100 Opportunity Score based purely on
    development potential relative to acquisition basis, using only
    PLUTO-derived fields (no web lookups).

    Returns dict: {score, tier, drivers: list[str]}
    """
    lot_sf     = prop.get("lot_sf", 0.0)
    far_max    = prop.get("far_max", 0.0)
    far_built  = prop.get("far_built", 0.0)
    unused_far_pct = prop.get("unused_far_pct", 0.0)
    assess_land = prop.get("assess_land", 0.0)
    is_vacant  = prop.get("is_vacant", False)

    drivers: list[str] = []

    # ── FAR upside (0-50 pts) ────────────────────────────────────────────────
    far_score = min(50.0, max(0.0, unused_far_pct * 0.5))
    if unused_far_pct >= 60:
        drivers.append(f"High unused FAR ({unused_far_pct:.0f}% of max)")
    elif unused_far_pct >= 30:
        drivers.append(f"Moderate unused FAR ({unused_far_pct:.0f}% of max)")

    # ── Vacancy / underutilization bonus (0-20 pts) ─────────────────────────
    vacancy_score = 20.0 if is_vacant else 0.0
    if is_vacant:
        drivers.append("Vacant or near-vacant lot")

    # ── Acquisition basis vs. assessed value (0-20 pts) ─────────────────────
    # Lower assessed $/SF land basis relative to lot size suggests cheaper
    # basis (assessed value is a rough, conservative proxy — not market value).
    basis_per_sf = (assess_land / lot_sf) if lot_sf > 0 else None
    if basis_per_sf is not None:
        if basis_per_sf < 50:
            basis_score = 20.0
            drivers.append(f"Low assessed land basis (${basis_per_sf:.0f}/SF)")
        elif basis_per_sf < 150:
            basis_score = 12.0
        else:
            basis_score = 5.0
    else:
        basis_score = 8.0   # unknown — neutral-low

    # ── Lot size scale bonus (0-10 pts) — bigger sites = more flexibility ───
    if lot_sf >= 10000:
        scale_score = 10.0
        drivers.append(f"Large lot ({lot_sf:,.0f} SF)")
    elif lot_sf >= 5000:
        scale_score = 6.0
    else:
        scale_score = 2.0

    total = far_score + vacancy_score + basis_score + scale_score
    total = int(round(max(0.0, min(100.0, total))))

    if total >= 75:
        tier = "Exceptional"
    elif total >= 60:
        tier = "Strong"
    elif total >= 40:
        tier = "Viable"
    elif total >= 25:
        tier = "Marginal"
    else:
        tier = "Reject"

    return {
        "score":   total,
        "tier":    tier,
        "drivers": drivers or ["Limited standout development signals from PLUTO alone"],
    }


def quick_distress_signal(prop: dict, dob_violation_count: int = 0, hpd_violation_count: int = 0) -> str:
    """
    Classify a QUICK-PASS distress signal using PLUTO + (optionally) violation
    counts already fetched elsewhere. This is intentionally conservative and
    does NOT claim an owner is financially distressed — see module docstring.

    Returns one of: "No Signal", "Weak Signal", "Moderate Signal", "Strong Signal"
    """
    score = 0
    if dob_violation_count > 15:
        score += 2
    elif dob_violation_count > 5:
        score += 1
    if hpd_violation_count > 15:
        score += 2
    elif hpd_violation_count > 5:
        score += 1

    year_built = prop.get("year_built", "")
    try:
        yb = int(float(year_built))
        if 0 < yb < 1930:
            score += 1
    except (TypeError, ValueError):
        pass

    if score >= 4:
        return "Strong Signal"
    if score >= 2:
        return "Moderate Signal"
    if score >= 1:
        return "Weak Signal"
    return "No Signal"


def enrich_property(prop: dict) -> dict:
    """
    Attach strategy classification + opportunity score to a normalized
    PLUTO property dict (from property_search.search_properties). Does not
    mutate the input; returns a new dict with added keys:
        strategies         — list[str]
        opportunity        — {score, tier, drivers}
        distress_signal    — str (quick pass, PLUTO-only — no violation counts)
        tax_abatement       — rules-based 485-x/J-51/ICAP estimate (PLUTO-only, cheap)
        rent_stab_signal    — rent-stabilization signal: a confirmed ground-truth
                               match against the bundled NYC Rent Guidelines Board
                               building list (modules/rent_stab_registry.py) when
                               available, else the PLUTO-only heuristic estimate
                               (modules/rent_stab_estimator.py) as a fallback. Same
                               dict shape either way (existing consumers keep
                               working unchanged) plus two always-present extra
                               keys: match_type ("bbl" | "address" | None) and
                               registry_notes (list[str], e.g. exemption codes).
    """
    from modules.abatement_estimator import estimate_tax_abatement
    from modules.rent_stab_estimator import estimate_rent_stabilization
    from modules.rent_stab_registry import check_rent_stabilized

    out = dict(prop)
    out["strategies"]      = classify_strategies(prop)
    out["opportunity"]     = compute_opportunity_score(prop)
    out["distress_signal"] = quick_distress_signal(prop)
    out["tax_abatement"]    = estimate_tax_abatement(prop)

    heuristic = estimate_rent_stabilization(prop)
    registry_hit = check_rent_stabilized(
        prop.get("borough_code", ""), prop.get("block"), prop.get("lot"), prop.get("address", ""),
    )
    if registry_hit.get("status") == "confirmed":
        out["rent_stab_signal"] = {
            **heuristic,
            "likely_stabilized": True,
            "confidence":        0.97,
            "verified":          True,
            "source":            "NYC Rent Guidelines Board building list (confirmed match)",
            "match_type":        registry_hit.get("match_type"),
            "registry_notes":    registry_hit.get("notes", []),
        }
    else:
        out["rent_stab_signal"] = {**heuristic, "match_type": None, "registry_notes": []}

    return out


def _lot_number(prop: dict) -> int | None:
    digits = re.sub(r"\D", "", str(prop.get("lot", "")))
    return int(digits) if digits else None


def flag_assemblage_candidates(properties: list[dict], max_lot_gap: int = 1) -> list[dict]:
    """
    Given a full Site Finder results list, flag properties that sit
    directly beside ANOTHER property in the SAME results set — i.e. two
    (or more) of a search's own qualifying results share a block and have
    near-neighboring lot numbers, suggesting an assemblage opportunity.

    Deliberately does NOT query PLUTO for every neighboring lot city-wide
    (that would mean one extra Socrata call per result — impractical at up
    to 3000 results, and most such neighbors wouldn't have matched the
    user's own search criteria anyway). It only cross-references lots
    already present in this result set — free, in-memory, O(n log n).

    Does not mutate the input; returns a new list with every dict gaining:
        assemblage_with: list[str]   — addresses of adjacent results in
                                        this same result set (empty if none)

    `max_lot_gap` controls how close two lot numbers must be to count as
    "adjacent." PLUTO lot numbers on a block are usually (not always)
    assigned in roughly physical sequence around the block, so a small
    gap is a reasonable, free approximation — it will occasionally over-
    or under-flag on irregular blocks; a genuine confirmation still
    requires a tax map/title check. Never raises.
    """
    out = [dict(p) for p in properties]
    for p in out:
        p["assemblage_with"] = []

    groups: dict[tuple[str, str], list[int]] = {}
    for i, p in enumerate(out):
        boro = str(p.get("borough_code") or "")
        block = str(p.get("block") or "")
        if not boro or not block:
            continue
        groups.setdefault((boro, block), []).append(i)

    for idxs in groups.values():
        if len(idxs) < 2:
            continue
        idxs_with_lots = [(i, _lot_number(out[i])) for i in idxs]
        idxs_with_lots = [(i, lot) for i, lot in idxs_with_lots if lot is not None]
        idxs_sorted = sorted(idxs_with_lots, key=lambda pair: pair[1])
        for pos, (i, lot_i) in enumerate(idxs_sorted):
            neighbors = []
            for other_pos in (pos - 1, pos + 1):
                if 0 <= other_pos < len(idxs_sorted):
                    j, lot_j = idxs_sorted[other_pos]
                    if abs(lot_j - lot_i) <= max_lot_gap:
                        addr = out[j].get("address", "")
                        if addr:
                            neighbors.append(addr)
            out[i]["assemblage_with"] = neighbors

    return out

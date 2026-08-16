"""
Structural Risk & System Recommendation — Estimator.

Two related but distinct signals, both pure heuristics (no free NYC Open
Data source publishes either), following the same explicit-labeling
convention as modules/abatement_estimator.py and modules/rent_stab_estimator.py:

  1. `compute_structural_vintage_risk()` — a 0-100 risk score derived from
     a building's era (year_built), reflecting the well-documented general
     relationship between NYC construction era and structural-system risk
     (pre-1901 unreinforced masonry/wood-joist construction, the 1968
     NYC Building Code's modernized seismic/structural provisions, etc.)
     — a coarse, honestly-labeled proxy, not an engineering assessment.
     Always recommends a structural/MEP survey before relying on it for
     underwriting.

  2. `recommend_structural_system()` — a frontage-width + height-driven
     rule-of-thumb for which structural system (wood-frame, light steel,
     steel-frame, concrete) is typically feasible/economical for a given
     scenario, mirroring the kind of guidance a developer's architect
     would give at a very early feasibility stage.

Pure function, no network call, fixed-shape dict return, never raises —
same house pattern as deal_scorer.py/abatement_estimator.py.
"""

from __future__ import annotations

# (min_year_inclusive, max_year_inclusive, score, era_label, typical_systems)
_VINTAGE_BANDS = [
    (0,    1900, 90, "Pre-1901 (pre-code)",
     "Unreinforced masonry bearing walls, wood joists — high risk of "
     "undocumented deterioration, no fireproofing, frequent asbestos/lead."),
    (1901, 1930, 72, "1901-1930 (early steel-frame era)",
     "Early steel-frame or masonry with wood joists — often the first "
     "generation of fireproofed steel, but original drawings rarely survive."),
    (1931, 1960, 50, "1931-1960 (transitional)",
     "Mixed masonry/steel/early reinforced concrete — generally documented, "
     "moderate risk, but pre-dates modern seismic/structural code provisions."),
    (1961, 1968, 35, "1961-1968 (pre-1968 NYC Building Code)",
     "Steel or reinforced concrete, pre-dates the 1968 NYC Building Code's "
     "modernized structural provisions — lower risk than earlier eras."),
    (1969, 2000, 22, "1969-2000 (post-1968 code)",
     "Steel or reinforced concrete under the modernized 1968 NYC Building "
     "Code — materially lower structural risk."),
    (2001, 9999, 10, "2001-present (modern code)",
     "Current-generation materials and code (2008/2014/2022 NYC Building "
     "Code cycles) — lowest baseline structural risk."),
]

_RISK_TIERS = [
    (70, "High"),
    (40, "Moderate"),
    (0,  "Low"),
]


def _tier_for(score: int) -> str:
    for threshold, label in _RISK_TIERS:
        if score >= threshold:
            return label
    return "Low"


def compute_structural_vintage_risk(year_built, num_floors: float = 0.0, bldg_class: str = "") -> dict:
    """
    Estimate a 0-100 structural risk score from a building's construction
    era, with a small upward adjustment for taller pre-1968 buildings
    (more structural system to have degraded/be non-conforming) and for
    building classes commonly associated with older, less-documented
    construction (e.g. walk-ups, lofts).

    Returns (always this shape, never raises):
        {
          "score": int (0-100),
          "tier": "Low" | "Moderate" | "High",
          "era_label": str,
          "notes": str,
          "year_built": int | None,
          "verified": False,   # always a heuristic, never a verified engineering assessment
        }
    """
    base = {
        "score": None, "tier": None, "era_label": None, "notes": None,
        "year_built": None, "verified": False,
    }
    try:
        yb = int(str(year_built).strip()[:4]) if year_built else None
        if not yb or yb < 1800 or yb > 2100:
            return {**base, "notes": "No usable year-built value — cannot estimate structural-vintage risk."}

        score, era_label, notes = 50, "Unknown era", ""
        for lo, hi, band_score, label, band_notes in _VINTAGE_BANDS:
            if lo <= yb <= hi:
                score, era_label, notes = band_score, label, band_notes
                break

        floors = float(num_floors or 0)
        if yb <= 1968 and floors >= 6:
            score = min(100, score + 8)
            notes += " Height (6+ floors) on a pre-1968 structural system adds risk."

        bc = str(bldg_class or "").upper()
        if bc.startswith("C") or bc.startswith("O") and yb <= 1930:
            score = min(100, score + 5)

        return {
            "score": score, "tier": _tier_for(score), "era_label": era_label,
            "notes": notes.strip(), "year_built": yb, "verified": False,
        }
    except Exception:
        return {**base, "notes": "Could not parse year_built — cannot estimate structural-vintage risk."}


# (min_frontage_ft, max_frontage_ft, max_floors_typical, system, rationale)
_SYSTEM_BANDS = [
    (0,  18,  4,  "Wood-frame or light-gauge steel",
     "Very narrow frontage (<18 ft) limits column-free spans; low-rise wood/light-steel framing is typically most economical."),
    (18, 25,  6,  "Light steel or masonry bearing wall",
     "Narrow rowhouse-scale frontage — light steel or masonry bearing-wall systems are typical for this scale."),
    (25, 50,  12, "Steel frame",
     "Mid-width frontage supports an efficient steel moment/braced frame for low- to mid-rise construction."),
    (50, 100, 25, "Steel frame or reinforced concrete",
     "Wide frontage allows either an efficient steel frame or reinforced-concrete flat-slab system, depending on height/use."),
    (100, 99999, 999, "Reinforced concrete or composite steel/concrete",
     "Very wide frontage (100+ ft) favors reinforced concrete or a composite system for larger floor plates and higher density."),
]


def recommend_structural_system(frontage_ft, target_floors: float = 0.0) -> dict:
    """
    Rule-of-thumb structural-system recommendation from lot frontage width
    (and, secondarily, target building height) — an early-feasibility-stage
    signal only, not a substitute for a structural engineer's input.

    Returns (always this shape, never raises):
        {
          "recommended_system": str | None,
          "rationale": str | None,
          "height_flag": str | None,   # non-None if target_floors exceeds the frontage-typical range
          "verified": False,
        }
    """
    base = {"recommended_system": None, "rationale": None, "height_flag": None, "verified": False}
    try:
        fw = float(frontage_ft or 0)
        if fw <= 0:
            return {**base, "rationale": "No usable lot frontage — cannot recommend a structural system."}

        floors = float(target_floors or 0)
        for lo, hi, max_floors_typical, system, rationale in _SYSTEM_BANDS:
            if lo <= fw < hi:
                height_flag = (
                    f"Target height ({floors:.0f} floors) exceeds what's typical for this frontage "
                    f"band (~{max_floors_typical} floors) — a taller building on this frontage will "
                    f"likely need a more robust (and costlier) structural system than the baseline "
                    f"recommendation."
                ) if floors and floors > max_floors_typical else None
                return {
                    **base, "recommended_system": system, "rationale": rationale,
                    "height_flag": height_flag,
                }
        return {**base, "rationale": "Frontage outside expected range — consult a structural engineer directly."}
    except Exception:
        return {**base, "rationale": "Could not parse frontage — cannot recommend a structural system."}

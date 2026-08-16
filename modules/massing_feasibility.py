"""
Massing Feasibility Score — 0-100 per massing scenario.

No existing function anywhere in the app combines frontage + lot area +
FAR headroom + zone type + landmark status + lot depth into one score
(deal_scorer.compute_deal_score() has no frontage/lot-depth/landmark
inputs at all — confirmed by direct read). This module fills that gap as
a new, standalone, read-only scorer: it never mutates the massing
scenario dicts it's given, and modules/massing_viz.py's 10 scenario
builders are untouched.

Deliberately reuses two existing scoring building blocks rather than
re-deriving them:
  - modules.structural_risk.recommend_structural_system() — frontage
    adequacy for the scenario's target height.
  - modules.deal_scorer._zoning_flexibility() — zone-type flexibility
    (same 0-15 scale already used by compute_deal_score()).

Pure function, no network call, fixed-shape dict return, never raises —
same house pattern as modules/structural_risk.py / modules/deal_scorer.py.
"""

from __future__ import annotations

from modules.structural_risk import recommend_structural_system
from modules.deal_scorer import _zoning_flexibility

_LANDMARK_PENALTY = 20
_HISTORIC_DISTRICT_PENALTY = 12


def compute_massing_feasibility_score(
    scenario: dict,
    lot_frontage_ft: float,
    lot_area_sqft: float,
    lot_depth_ft: float,
    zoning_dist: str,
    max_far: float = 0.0,
    is_landmark: bool = False,
    is_historic_district: bool = False,
) -> dict:
    """
    Score how feasible a single massing scenario is (0-100), combining
    FAR-headroom utilization, frontage adequacy for the scenario's target
    height, lot-depth adequacy, zone-type flexibility, and a landmark/
    historic-district penalty.

    Args:
        scenario: one of build_massing_options()'s returned scenario dicts
            (reads "total_sqft", "floors").
        lot_frontage_ft, lot_area_sqft, lot_depth_ft: subject lot dims.
        zoning_dist: primary zoning district string.
        max_far: the lot's max buildable FAR (0 -> FAR-utilization
            component is skipped, not penalized).
        is_landmark, is_historic_district: landmark/historic-district
            flags — either one triggers a penalty (LPC approval risk),
            not both stacked, since they overlap in practice.

    Returns (always this shape, never raises):
        {
          "score": int (0-100),
          "tier": "Strong" | "Viable" | "Constrained" | "Weak",
          "factors": list[str],
          "structural_system_note": dict,   # recommend_structural_system()'s result
          "verified": False,
        }
    """
    base = {"score": 0, "tier": "Weak", "factors": [], "structural_system_note": {}, "verified": False}
    try:
        factors: list[str] = []
        score = 0.0

        # ── FAR-headroom utilization (0-35 pts) ─────────────────────────
        lot_area = float(lot_area_sqft or 0)
        far = float(max_far or 0)
        total_sqft = float(scenario.get("total_sqft", 0) or 0)
        if lot_area > 0 and far > 0:
            max_buildable = lot_area * far
            utilization = min(1.0, total_sqft / max_buildable) if max_buildable > 0 else 0.0
            far_score = 35.0 * utilization
            score += far_score
            factors.append(f"Uses {utilization:.0%} of the lot's max buildable FAR")

        # ── Frontage adequacy for target height (0-25 pts) ──────────────
        struct = recommend_structural_system(lot_frontage_ft, target_floors=scenario.get("floors", 0))
        if struct.get("recommended_system"):
            if struct.get("height_flag"):
                score += 8.0
                factors.append(f"Frontage-vs-height concern: {struct['height_flag']}")
            else:
                score += 25.0
                factors.append(f"Frontage supports a {struct['recommended_system']} system at this height")

        # ── Lot-depth adequacy (0-15 pts) ───────────────────────────────
        depth = float(lot_depth_ft or 0)
        if depth >= 90:
            score += 15.0
        elif depth >= 60:
            score += 10.0
            factors.append(f"Moderate lot depth ({depth:.0f} ft) may constrain floor-plate efficiency")
        elif depth > 0:
            score += 4.0
            factors.append(f"Shallow lot depth ({depth:.0f} ft) significantly constrains floor-plate options")

        # ── Zone-type flexibility (0-15 pts, same scale as deal_scorer) ──
        flex = _zoning_flexibility(zoning_dist)
        score += flex
        factors.append(f"Zoning flexibility: {flex}/15 ({zoning_dist or 'unknown district'})")

        # ── Landmark / historic-district penalty ────────────────────────
        if is_landmark:
            score -= _LANDMARK_PENALTY
            factors.append(f"LPC individual landmark — approval risk (-{_LANDMARK_PENALTY} pts)")
        elif is_historic_district:
            score -= _HISTORIC_DISTRICT_PENALTY
            factors.append(f"Historic district — Certificate of Appropriateness risk (-{_HISTORIC_DISTRICT_PENALTY} pts)")

        score = max(0, min(100, int(round(score))))
        if score >= 70:
            tier = "Strong"
        elif score >= 45:
            tier = "Viable"
        elif score >= 20:
            tier = "Constrained"
        else:
            tier = "Weak"

        return {
            "score": score, "tier": tier, "factors": factors,
            "structural_system_note": struct, "verified": False,
        }
    except Exception:
        return base

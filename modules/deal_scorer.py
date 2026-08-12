"""
Deal Scoring Engine — 0–100 composite lead score for NYC development opportunities.

Combines unused FAR, distress signals, location demand, zoning flexibility,
and listing activity into a single numeric score with tier label.

No external API calls — all inputs are pre-computed values from PLUTO + other modules.
"""

from __future__ import annotations
import re


def _zoning_flexibility(zoning_dist: str) -> int:
    """
    Score zoning flexibility (0–15 pts).
    Mixed-use and commercial zones allow more development types.
    """
    if not zoning_dist:
        return 5
    z = zoning_dist.strip().upper()
    # M (manufacturing) zones allow widest conversion flexibility
    if z.startswith("M"):
        return 15
    # C (commercial) zones: mixed-use permitted
    if z.startswith("C"):
        return 13
    # Residential zones with commercial overlay (determined by caller via overlay flag)
    # or high-density R zones (R7+)
    if re.match(r"R[7-9]|R10", z):
        return 9
    if re.match(r"R[4-6]", z):
        return 7
    # Low-density R1/R2/R3
    return 5


def compute_deal_score(
    unused_far_pct: float = 0.0,
    distress_level: int = 0,
    neighborhood_rent_premium: float = 0.0,
    zoning_dist: str = "",
    listings_nearby: int = 0,
    assemblage_uplift_pct: float = 0.0,
    has_overlay: bool = False,
) -> dict:
    """
    Compute a 0–100 Deal Score for a NYC development opportunity.

    Args:
        unused_far_pct:           Unused FAR as percent of max FAR (0–100)
        distress_level:           0 = Low, 1 = Medium, 2 = High
        neighborhood_rent_premium: (neighborhood avg rent / borough median - 1) * 100
                                   e.g. +15 means 15% above borough median
        zoning_dist:              Primary zoning district (e.g. "R7A", "C6-2")
        listings_nearby:          Number of active comparable listings within 0.15 mi
        assemblage_uplift_pct:    % increase in buildable SF from assemblage (0–100+)
        has_overlay:              True if commercial overlay (C1/C2) applies

    Returns dict:
        score     : int 0–100
        tier      : "Strong Lead" | "Watch" | "Pass"
        breakdown : dict of component → {score, max, reasoning}
    """
    # ── Component 1: Unused FAR (30 pts) ──────────────────────────────────────
    unused_far_score = min(30, max(0.0, unused_far_pct * 0.30))

    # ── Component 2: Distress Signals (25 pts) ────────────────────────────────
    distress_map = {0: 8, 1: 17, 2: 25}
    distress_score = distress_map.get(distress_level, 8)

    # ── Component 3: Location Demand (20 pts) ─────────────────────────────────
    # 10 base pts + 0.5 pt per % premium above median (capped at 20)
    location_score = min(20, max(0.0, 10 + neighborhood_rent_premium * 0.5))

    # ── Component 4: Zoning Flexibility (15 pts) ──────────────────────────────
    flex_score = _zoning_flexibility(zoning_dist)
    if has_overlay and flex_score < 10:
        flex_score = 10  # overlay bumps R-zone score to at least 10

    # ── Component 5: Listing Activity (10 pts) ────────────────────────────────
    listings_score = min(10, listings_nearby * 2)

    total = int(round(
        unused_far_score + distress_score + location_score + flex_score + listings_score
    ))
    total = max(0, min(100, total))

    if total >= 70:
        tier = "Strong Lead"
    elif total >= 40:
        tier = "Watch"
    else:
        tier = "Pass"

    breakdown = {
        "Unused FAR": {
            "score":     int(round(unused_far_score)),
            "max":       30,
            "reasoning": f"{unused_far_pct:.1f}% unused FAR × 0.30",
        },
        "Distress Signals": {
            "score":     distress_score,
            "max":       25,
            "reasoning": ["Low distress (≤2 signals)", "Medium distress (3–5 signals)", "High distress (6+ signals)"][distress_level],
        },
        "Location Demand": {
            "score":     int(round(location_score)),
            "max":       20,
            "reasoning": f"{neighborhood_rent_premium:+.1f}% vs borough median",
        },
        "Zoning Flexibility": {
            "score":     flex_score,
            "max":       15,
            "reasoning": f"Zone: {zoning_dist or '—'}" + (" + overlay" if has_overlay else ""),
        },
        "Listing Activity": {
            "score":     listings_score,
            "max":       10,
            "reasoning": f"{listings_nearby} listings within 0.15 mi",
        },
    }

    return {
        "score":     total,
        "tier":      tier,
        "breakdown": breakdown,
    }


def compute_bulk_deal_scores(properties: list[dict]) -> list[dict]:
    """
    Score a list of Site Finder properties (as produced by
    modules.site_sourcing.enrich_property) using the SAME
    compute_deal_score() engine above, then return them sorted by
    score descending. Purely additive — does not alter single-property
    scoring behaviour.

    Each input dict should carry (all optional, defaults are neutral):
        unused_far_pct, distress_level (0/1/2), neighborhood_rent_premium,
        zoning_dist, listings_nearby, assemblage_uplift_pct, has_overlay

    Missing fields are inferred where possible from Site Finder's own
    `unused_far_pct` / `distress_signal` keys so callers don't have to
    pre-map everything by hand.

    Returns a NEW list of dicts (input dicts are not mutated), each with
    an added "deal_score" key holding the compute_deal_score() result.
    """
    _distress_map = {
        "No Signal":       0,
        "Weak Signal":     0,
        "Moderate Signal": 1,
        "Strong Signal":   2,
    }

    scored: list[dict] = []
    for prop in properties:
        distress_level = prop.get("distress_level")
        if distress_level is None:
            distress_level = _distress_map.get(prop.get("distress_signal", ""), 0)

        result = compute_deal_score(
            unused_far_pct=prop.get("unused_far_pct", 0.0),
            distress_level=distress_level,
            neighborhood_rent_premium=prop.get("neighborhood_rent_premium", 0.0),
            zoning_dist=prop.get("zoning_dist", ""),
            listings_nearby=prop.get("listings_nearby", 0),
            assemblage_uplift_pct=prop.get("assemblage_uplift_pct", 0.0),
            has_overlay=prop.get("has_overlay", False),
        )
        out = dict(prop)
        out["deal_score"] = result
        scored.append(out)

    scored.sort(key=lambda p: p["deal_score"]["score"], reverse=True)
    return scored

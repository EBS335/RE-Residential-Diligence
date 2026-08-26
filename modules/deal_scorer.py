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


def compute_seller_propensity(
    tenure_years: float | None = None,
    distress_level: int = 0,
    is_vacant: bool = False,
) -> dict:
    """
    Compute a 0–100 Seller Propensity Score — a SECONDARY, entirely separate
    score from Deal Score, estimating how likely an owner is to sell, not
    how good the site is as a deal. Never combined into compute_deal_score()
    or its output; callers keep both scores side by side.

    Weighting:
      - Tenure (0–40 pts): longer ownership tenure correlates with higher
        propensity to sell (built-up equity, "tired landlord" dynamics).
        `tenure_years is None` gets 20 pts — neutral PARTIAL credit, not
        zero — because tenure is only known for the ACRIS-enriched top-25
        subset (it comes from `last_sale_date`, which requires the ACRIS
        ownership-enrichment fetch to have run for this property). Treating
        "unknown" as 0 would unfairly penalize every un-enriched property
        relative to enriched ones, purely as an artifact of enrichment
        order rather than anything about the property itself. `is_vacant`,
        by contrast, is known for every property straight from PLUTO
        regardless of enrichment status, so its component below has no
        such "unknown" case to handle.
      - Distress (0–35 pts): mirrors compute_deal_score()'s distress_level
        0/1/2 -> points mapping style, but INVERTED in spirit — here higher
        distress means higher propensity-to-sell (a distressed owner is
        more likely to sell), not a lower score as it would be for deal
        quality elsewhere.
      - Vacancy (0–25 pts): flat bonus if the property is vacant (no
        tenants to relocate/buy out makes a sale simpler for the owner).

    Args:
        tenure_years:   Years of current ownership tenure, or None if unknown.
        distress_level: 0 = Low, 1 = Medium, 2 = High (same convention as
                         compute_deal_score()).
        is_vacant:      True if the property is currently vacant.

    Returns dict:
        score     : int 0–100
        tier      : "High" | "Moderate" | "Low"
        breakdown : dict of component → {score, max, reasoning}
    """
    # ── Component 1: Tenure (40 pts) ──────────────────────────────────────────
    if tenure_years is None:
        tenure_score = 20
        tenure_reasoning = "Tenure unknown (not yet ACRIS-enriched) — neutral partial credit"
    elif tenure_years > 10:
        tenure_score = 40
        tenure_reasoning = f"{tenure_years:.0f} yr tenure (>10 yr — long hold)"
    elif tenure_years >= 5:
        tenure_score = 25
        tenure_reasoning = f"{tenure_years:.0f} yr tenure (5–10 yr — moderate hold)"
    else:
        tenure_score = 10
        tenure_reasoning = f"{tenure_years:.0f} yr tenure (<5 yr — recent acquisition)"

    # ── Component 2: Distress (35 pts) — inverted vs. compute_deal_score(): ────
    # higher distress here means higher propensity-to-sell.
    propensity_distress_map = {0: 8, 1: 20, 2: 35}
    distress_score = propensity_distress_map.get(distress_level, 8)
    distress_reasoning = [
        "Low distress (≤2 signals) — little pressure to sell",
        "Medium distress (3–5 signals) — some pressure to sell",
        "High distress (6+ signals) — strong pressure to sell",
    ][distress_level] if distress_level in (0, 1, 2) else "Low distress (≤2 signals) — little pressure to sell"

    # ── Component 3: Vacancy (25 pts flat bonus) ────────────────────────────────
    vacancy_score = 25 if is_vacant else 0
    vacancy_reasoning = "Vacant — no tenants to relocate/buy out" if is_vacant else "Not flagged vacant"

    total = int(round(tenure_score + distress_score + vacancy_score))
    total = max(0, min(100, total))

    if total >= 70:
        tier = "High"
    elif total >= 40:
        tier = "Moderate"
    else:
        tier = "Low"

    breakdown = {
        "Tenure": {
            "score":     tenure_score,
            "max":       40,
            "reasoning": tenure_reasoning,
        },
        "Distress": {
            "score":     distress_score,
            "max":       35,
            "reasoning": distress_reasoning,
        },
        "Vacancy": {
            "score":     vacancy_score,
            "max":       25,
            "reasoning": vacancy_reasoning,
        },
    }

    return {
        "score":     total,
        "tier":      tier,
        "breakdown": breakdown,
    }


def _tenure_years_from_sale_date(sale_date) -> float | None:
    """
    Local reimplementation of site_finder_valuation._sale_age_years()'s
    simple year-parsing logic — that function is file-private (leading
    underscore) in its own module, so it's re-implemented here rather than
    imported across modules. Kept intentionally identical in behavior.
    """
    if not sale_date:
        return None
    try:
        sale_year = int(str(sale_date)[:4])
    except (TypeError, ValueError):
        return None
    import datetime
    return max(0.0, datetime.date.today().year - sale_year)


def compute_bulk_seller_propensity(properties: list[dict]) -> list[dict]:
    """
    Score a list of Site Finder properties with compute_seller_propensity(),
    mirroring compute_bulk_deal_scores()'s shape: returns a NEW list (input
    dicts are not mutated), each with an added "seller_propensity" key.
    Does NOT touch, reorder, or re-sort by "deal_score" — only adds the new
    key; the list order coming in is preserved coming out.

    Derivation per property:
      - tenure_years:   from prop["last_sale_date"] via a local reimplementation
                         of site_finder_valuation._sale_age_years()'s logic
                         (that helper is file-private there).
      - distress_level: same inference as compute_bulk_deal_scores() — prefers
                         an explicit prop["distress_level"], else maps
                         prop["distress_signal"] through the same string->int
                         table used there.
      - is_vacant:      prop.get("is_vacant", False).
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

        tenure_years = _tenure_years_from_sale_date(prop.get("last_sale_date"))

        result = compute_seller_propensity(
            tenure_years=tenure_years,
            distress_level=distress_level,
            is_vacant=prop.get("is_vacant", False),
        )
        out = dict(prop)
        out["seller_propensity"] = result
        scored.append(out)

    return scored


def recompute_display_score(
    breakdown: dict,
    weight_multipliers: dict[str, float] | None = None,
) -> dict:
    """
    Recombine an EXISTING compute_deal_score() breakdown's component
    (score, max) ratios with caller-supplied per-component multipliers,
    renormalized back to a 0-100 scale. Purely a DISPLAY-time re-ranking
    helper (Feature 13, "Adjustable Deal Score Weights") — never mutates
    `breakdown`, never writes anything back onto a property dict, and does
    not replace the canonical `deal_score` that export/portfolio/map/CSV
    keep reading unchanged.

    A component absent from `weight_multipliers` (or when
    `weight_multipliers` is None/empty) defaults to a multiplier of 1.0,
    which is a no-op for that component. When EVERY component's multiplier
    is 1.0, the returned score is IDENTICAL to the original
    compute_deal_score() score computed from this same breakdown — this is
    the load-bearing invariant a caller relies on for a "default weights =
    unchanged ranking" UI.

    Renormalization: for each component, its ORIGINAL fraction of full
    credit (score/max) is kept fixed, but its max-points "weight" in the
    combined total is scaled by the multiplier. That is, for component i:

        weighted_contribution_i = (score_i / max_i) * multiplier_i * max_i
        weighted_max_i          = multiplier_i * max_i

        total_score = round(100 * sum(weighted_contribution_i)
                                  / sum(weighted_max_i))

    Since weighted_contribution_i / weighted_max_i == score_i / max_i
    regardless of multiplier_i (the multiplier cancels — it only rescales
    how much that component's fraction counts toward the total, not the
    fraction itself), this is bounded to [0, 100] exactly like the
    original score (each component fraction is itself already in [0, 1]),
    and reduces to precisely `sum(score_i) / sum(max_i) * 100` — the
    original score — when every multiplier_i == 1.0.

    Args:
        breakdown:           A compute_deal_score() result's "breakdown" dict
                              (component -> {score, max, reasoning}). Not mutated.
        weight_multipliers:  Optional dict of component name -> multiplier
                              (e.g. 0.5–2.0). Missing components default to 1.0.

    Returns dict:
        score : int 0–100
        tier  : "Strong Lead" | "Watch" | "Pass" (same thresholds as
                compute_deal_score())
    """
    weight_multipliers = weight_multipliers or {}

    weighted_contribution_sum = 0.0
    weighted_max_sum = 0.0
    for component, detail in breakdown.items():
        score = detail.get("score", 0)
        maxv = detail.get("max", 0)
        multiplier = weight_multipliers.get(component, 1.0)
        weighted_contribution_sum += score * multiplier
        weighted_max_sum += maxv * multiplier

    if weighted_max_sum <= 0:
        total = 0
    else:
        total = int(round(100 * weighted_contribution_sum / weighted_max_sum))
    total = max(0, min(100, total))

    if total >= 70:
        tier = "Strong Lead"
    elif total >= 40:
        tier = "Watch"
    else:
        tier = "Pass"

    return {"score": total, "tier": tier}


def apply_custom_weights(breakdown: dict, custom_weights: dict[str, float]) -> dict:
    """
    Rebuild a FULL Deal Score dict (score, tier, AND a rebuilt breakdown)
    from an existing compute_deal_score() breakdown, using caller-supplied
    weights — point caps out of 100 (e.g. {"Unused FAR": 40, ...}), NOT
    the 0.5-2.0 multipliers recompute_display_score() takes for its
    display-only, post-search "this view only" adjuster.

    Meant to produce a full REPLACEMENT for a property's "deal_score" when
    a user opts into custom weights at SEARCH time (site_finder_ui.py's
    "Customize Deal Score Weights" panel) — unlike recompute_display_score()
    (deliberately display-only, returns no breakdown, never meant to
    become the canonical score), this function's result is designed to be
    assigned directly to prop["deal_score"], since every downstream
    consumer (results table, map marker color, CSV/Excel/PDF/PPTX export,
    Save to Portfolio, AI diligence context) reads that field
    unconditionally as THE score.

    For each component, its original earned FRACTION (score/max) is kept,
    but recombined against the new max: new_score = (score/max) * new_max.
    Using the engine's own default maxes (30/25/20/15/10) as
    `custom_weights` reproduces the exact original score — the load-
    bearing "no-op when using the standard weighting" invariant.

    Args:
        breakdown:       A compute_deal_score() result's "breakdown" dict
                          (component -> {score, max, reasoning}). Not mutated.
        custom_weights:  dict of component name -> new point cap. A
                          component's max defaults to its ORIGINAL max if
                          missing from this dict (never silently dropped).

    Returns dict:
        score     : int 0-100
        tier      : "Strong Lead" | "Watch" | "Pass" (same thresholds as
                    compute_deal_score())
        breakdown : dict of component -> {score, max, reasoning} rebuilt
                    against the new custom maxes
    """
    new_breakdown = {}
    total = 0
    for component, detail in breakdown.items():
        old_score, old_max = detail.get("score", 0), detail.get("max", 0) or 1
        new_max = custom_weights.get(component, old_max)
        new_score = int(round((old_score / old_max) * new_max))
        new_breakdown[component] = {
            "score": new_score, "max": new_max, "reasoning": detail.get("reasoning", ""),
        }
        total += new_score

    total = max(0, min(100, total))
    if total >= 70:
        tier = "Strong Lead"
    elif total >= 40:
        tier = "Watch"
    else:
        tier = "Pass"

    return {"score": total, "tier": tier, "breakdown": new_breakdown}

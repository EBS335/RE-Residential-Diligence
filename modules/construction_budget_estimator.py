"""
Trade-Level Construction Budget Estimator.

The only construction-cost logic elsewhere in the app is
modules/site_finder_valuation.py's two flat blended $/GSF rates
(_HARD_COST_PSF_GROUND_UP / _HARD_COST_PSF_CONVERSION) — a single-number
hard-cost figure with no trade breakdown, no budget tier, and no
prevailing-wage adjustment. This module ADDS a trade-level view on top of
those same anchor rates (imported, not duplicated) — it does not replace
or change them, and every existing caller of the flat rates is untouched.

Splits the same blended hard-cost anchor into illustrative NYC ground-up
trade categories (site work/foundation, structure, envelope, MEP, interior
finishes, general conditions/fee), then applies a budget-tier multiplier
(Economy/Standard/Luxury), an optional renovation-scope multiplier
(conversion scenarios only), and an optional prevailing-wage multiplier
(applied only to labor-heavy trades, a documented simplification).

Pure function, no network call, fixed-shape dict return, never raises —
same house pattern as modules/structural_risk.py / modules/deal_scorer.py.
Every rate/split here is an illustrative rule of thumb, not a GC estimate
or bid — always labeled "verified": False.
"""

from __future__ import annotations

from modules.site_finder_valuation import (
    _HARD_COST_PSF_GROUND_UP,
    _HARD_COST_PSF_CONVERSION,
)

# ── Trade split of blended hard cost (illustrative NYC ground-up rule of ───
# ── thumb — actual splits vary widely by building type/height/site) ────────
TRADE_SPLIT_PCT: dict[str, float] = {
    "Sitework & Foundation":       0.08,
    "Structure & Superstructure":  0.20,
    "Envelope & Facade":           0.15,
    "MEP (Mechanical/Electrical/Plumbing)": 0.25,
    "Interior Finishes":           0.20,
    "General Conditions & Fee":    0.12,
}
assert abs(sum(TRADE_SPLIT_PCT.values()) - 1.0) < 1e-9

# Labor-heavy trades a prevailing-wage requirement would primarily affect
# (vs. material-heavy trades like Sitework/Envelope, left at base rate —
# a documented simplification, not a certified wage determination).
_LABOR_HEAVY_TRADES = {
    "Structure & Superstructure",
    "MEP (Mechanical/Electrical/Plumbing)",
    "Interior Finishes",
}

BUDGET_TIER_MULTIPLIERS: dict[str, float] = {
    "Economy": 0.85,
    "Standard": 1.0,
    "Luxury": 1.35,
}

# Conversion/renovation scenarios only — ground-up scenarios ignore this.
RENOVATION_SCOPE_MULTIPLIERS: dict[str, float] = {
    "Light": 0.50,
    "Gut": 1.00,
    "Full Gut + Structural": 1.25,
}

DEFAULT_PREVAILING_WAGE_MULTIPLIER = 1.20


def estimate_trade_level_budget(
    gross_buildable_sf: float,
    development_type: str = "ground_up",
    budget_tier: str = "Standard",
    renovation_scope: str | None = None,
    prevailing_wage: bool = False,
    prevailing_wage_multiplier: float = DEFAULT_PREVAILING_WAGE_MULTIPLIER,
) -> dict:
    """
    Split a blended hard-cost anchor (same rates as
    site_finder_valuation.py) into trade-level line items.

    Args:
        gross_buildable_sf: total buildable SF the hard cost applies to.
        development_type: "ground_up" or "conversion" — selects which of
            the two existing blended anchor rates to use.
        budget_tier: "Economy" | "Standard" | "Luxury".
        renovation_scope: "Light" | "Gut" | "Full Gut + Structural", or
            None — only applied when development_type == "conversion".
        prevailing_wage: if True, applies prevailing_wage_multiplier to
            the labor-heavy trades only.
        prevailing_wage_multiplier: override for the default 1.20x.

    Returns (always this shape, never raises):
        {
          "trade_breakdown": {trade: {"psf": float, "total": float}},
          "total_hard_cost": float,
          "hard_cost_psf_base": float,     # the anchor rate before multipliers
          "development_type": str,
          "budget_tier": str,
          "renovation_scope": str | None,
          "prevailing_wage_applied": bool,
          "verified": False,
          "error": str | None,
        }
    """
    base = {
        "trade_breakdown": {}, "total_hard_cost": 0.0, "hard_cost_psf_base": 0.0,
        "development_type": development_type, "budget_tier": budget_tier,
        "renovation_scope": renovation_scope, "prevailing_wage_applied": bool(prevailing_wage),
        "verified": False, "error": None,
    }
    try:
        sf = float(gross_buildable_sf or 0)
        if sf <= 0:
            return {**base, "error": "gross_buildable_sf must be positive"}

        anchor_psf = (
            _HARD_COST_PSF_CONVERSION if development_type == "conversion"
            else _HARD_COST_PSF_GROUND_UP
        )
        tier_mult = BUDGET_TIER_MULTIPLIERS.get(budget_tier, 1.0)

        scope_mult = 1.0
        if development_type == "conversion" and renovation_scope:
            scope_mult = RENOVATION_SCOPE_MULTIPLIERS.get(renovation_scope, 1.0)

        wage_mult = prevailing_wage_multiplier if prevailing_wage else 1.0

        trade_breakdown: dict[str, dict] = {}
        total = 0.0
        for trade, pct in TRADE_SPLIT_PCT.items():
            trade_mult = tier_mult * scope_mult
            if trade in _LABOR_HEAVY_TRADES:
                trade_mult *= wage_mult
            trade_psf = anchor_psf * pct * trade_mult
            trade_total = trade_psf * sf
            trade_breakdown[trade] = {"psf": round(trade_psf, 2), "total": round(trade_total, 2)}
            total += trade_total

        return {
            **base,
            "trade_breakdown": trade_breakdown,
            "total_hard_cost": round(total, 2),
            "hard_cost_psf_base": anchor_psf,
        }
    except Exception as exc:
        return {**base, "error": str(exc)}

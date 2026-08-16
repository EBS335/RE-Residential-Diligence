from modules.construction_budget_estimator import (
    estimate_trade_level_budget, TRADE_SPLIT_PCT, BUDGET_TIER_MULTIPLIERS,
    RENOVATION_SCOPE_MULTIPLIERS, DEFAULT_PREVAILING_WAGE_MULTIPLIER,
)
from modules.site_finder_valuation import _HARD_COST_PSF_GROUND_UP, _HARD_COST_PSF_CONVERSION


def test_standard_ground_up_matches_blended_anchor_total():
    result = estimate_trade_level_budget(10_000, development_type="ground_up", budget_tier="Standard")
    assert result["error"] is None
    assert result["hard_cost_psf_base"] == _HARD_COST_PSF_GROUND_UP
    # Standard tier, no wage/scope multiplier -> total should reconcile to
    # the same blended anchor rate the rest of the app already uses.
    assert abs(result["total_hard_cost"] - _HARD_COST_PSF_GROUND_UP * 10_000) < 1.0


def test_conversion_uses_conversion_anchor():
    result = estimate_trade_level_budget(5_000, development_type="conversion", budget_tier="Standard")
    assert result["hard_cost_psf_base"] == _HARD_COST_PSF_CONVERSION


def test_trade_breakdown_has_all_categories_and_sums_to_total():
    result = estimate_trade_level_budget(8_000, budget_tier="Standard")
    assert set(result["trade_breakdown"].keys()) == set(TRADE_SPLIT_PCT.keys())
    summed = sum(t["total"] for t in result["trade_breakdown"].values())
    assert abs(summed - result["total_hard_cost"]) < 1.0


def test_economy_cheaper_than_luxury():
    econ = estimate_trade_level_budget(10_000, budget_tier="Economy")
    lux = estimate_trade_level_budget(10_000, budget_tier="Luxury")
    assert econ["total_hard_cost"] < lux["total_hard_cost"]
    assert BUDGET_TIER_MULTIPLIERS["Economy"] < BUDGET_TIER_MULTIPLIERS["Luxury"]


def test_renovation_scope_only_applies_to_conversion():
    ground_up_with_scope = estimate_trade_level_budget(
        10_000, development_type="ground_up", renovation_scope="Light",
    )
    ground_up_no_scope = estimate_trade_level_budget(10_000, development_type="ground_up")
    # Scope is ignored for ground_up — totals must match.
    assert ground_up_with_scope["total_hard_cost"] == ground_up_no_scope["total_hard_cost"]

    conv_light = estimate_trade_level_budget(10_000, development_type="conversion", renovation_scope="Light")
    conv_full = estimate_trade_level_budget(10_000, development_type="conversion", renovation_scope="Full Gut + Structural")
    assert conv_light["total_hard_cost"] < conv_full["total_hard_cost"]


def test_prevailing_wage_increases_labor_heavy_trades_only():
    base = estimate_trade_level_budget(10_000, prevailing_wage=False)
    waged = estimate_trade_level_budget(10_000, prevailing_wage=True)
    assert waged["total_hard_cost"] > base["total_hard_cost"]
    assert waged["prevailing_wage_applied"] is True

    # Material-heavy trades (not labor-heavy) must be unaffected.
    for trade in ("Sitework & Foundation", "Envelope & Facade", "General Conditions & Fee"):
        assert base["trade_breakdown"][trade]["total"] == waged["trade_breakdown"][trade]["total"]
    # Labor-heavy trades must increase by exactly the default multiplier.
    for trade in ("Structure & Superstructure", "MEP (Mechanical/Electrical/Plumbing)", "Interior Finishes"):
        ratio = waged["trade_breakdown"][trade]["total"] / base["trade_breakdown"][trade]["total"]
        assert abs(ratio - DEFAULT_PREVAILING_WAGE_MULTIPLIER) < 1e-6


def test_zero_or_negative_sf_returns_error_never_raises():
    result = estimate_trade_level_budget(0)
    assert result["error"] is not None
    assert result["total_hard_cost"] == 0.0

    result2 = estimate_trade_level_budget(-500)
    assert result2["error"] is not None


def test_never_claims_verified():
    result = estimate_trade_level_budget(5_000)
    assert result["verified"] is False


def test_unknown_tier_falls_back_to_standard_multiplier():
    result = estimate_trade_level_budget(10_000, budget_tier="NotATier")
    standard = estimate_trade_level_budget(10_000, budget_tier="Standard")
    assert result["total_hard_cost"] == standard["total_hard_cost"]


def test_garbage_input_never_raises():
    result = estimate_trade_level_budget("not a number")  # type: ignore
    assert result["error"] is not None
    assert "trade_breakdown" in result

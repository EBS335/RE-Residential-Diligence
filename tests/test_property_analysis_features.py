"""
Tests for the pure-function logic added to the Property Analysis tab
review pass: entitlement-path classification (modules/zoning_rules.py)
and comps reconciliation (modules/unit_mix.py).
"""

from modules.zoning_rules import estimate_entitlement_path
from modules.unit_mix import reconcile_comps, OPEX_RATIO


# ── estimate_entitlement_path ───────────────────────────────────────────────

def test_entitlement_path_low_risk_is_as_of_right():
    result = estimate_entitlement_path("LOW", "As-of-right conversion.")
    assert result["path_key"] == "as_of_right"


def test_entitlement_path_med_risk_default():
    result = estimate_entitlement_path("MED", "Mid-rise approach with open-space bonus.")
    assert result["path_key"] == "minor_modification"


def test_entitlement_path_high_risk_default_is_variance():
    result = estimate_entitlement_path("HIGH", "A high-density scenario with no specific keyword.")
    assert result["path_key"] == "bsa_variance"


def test_entitlement_path_keyword_variance_overrides():
    result = estimate_entitlement_path("HIGH", "Requires setback waivers or variance — higher entitlement risk.")
    assert result["path_key"] == "bsa_variance"


def test_entitlement_path_keyword_ulurp_overrides_even_at_med_risk():
    # Keyword match takes priority over the risk-level fallback.
    result = estimate_entitlement_path("MED", "Requires ULURP or MIH compliance.")
    assert result["path_key"] == "ulurp_rezoning"


def test_entitlement_path_unrecognized_risk_defaults_safely():
    result = estimate_entitlement_path("", "")
    assert result["path_key"] == "as_of_right"


def test_entitlement_path_never_raises_on_none():
    result = estimate_entitlement_path(None, None)
    assert result["path_key"] == "as_of_right"


def test_entitlement_path_shape():
    result = estimate_entitlement_path("HIGH", "")
    for key in ("label", "description", "timeline", "cost_range", "approval_probability", "path_key"):
        assert key in result


# ── reconcile_comps ──────────────────────────────────────────────────────────

def test_reconcile_comps_basic_math():
    result = reconcile_comps([60.0, 55.0, 65.0], [780.0, 820.0, 850.0])
    assert result["ann_rent_psf"] == 60.0
    assert result["sale_psf"] == 820.0
    # GRM = sale_psf / ann_rent_psf (NOT divided by 12 — regression test for
    # a real bug caught during manual review: dividing by monthly instead
    # of annual rent produced a GRM ~12x too high).
    assert abs(result["grm"] - (820.0 / 60.0)) < 1e-9
    assert result["grm"] < 20  # sanity bound -- realistic NYC GRMs are ~8-20x
    expected_noi_psf = 60.0 * (1 - OPEX_RATIO) * 0.93
    assert abs(result["noi_psf"] - expected_noi_psf) < 1e-9
    expected_cap_rate = expected_noi_psf / 820.0 * 100
    assert abs(result["cap_rate_pct"] - expected_cap_rate) < 1e-9
    assert 2.0 < result["cap_rate_pct"] < 8.0  # sanity bound for NYC cap rates


def test_reconcile_comps_empty_rent_returns_none():
    assert reconcile_comps([], [100.0]) is None


def test_reconcile_comps_empty_sale_returns_none():
    assert reconcile_comps([50.0], []) is None


def test_reconcile_comps_both_empty_returns_none():
    assert reconcile_comps([], []) is None


def test_reconcile_comps_counts():
    result = reconcile_comps([50.0, 55.0], [800.0, 810.0, 820.0])
    assert result["rent_comp_count"] == 2
    assert result["sale_comp_count"] == 3


def test_reconcile_comps_custom_occupancy():
    result_high_occ = reconcile_comps([50.0], [800.0], occupancy=0.98)
    result_low_occ = reconcile_comps([50.0], [800.0], occupancy=0.85)
    assert result_high_occ["noi_psf"] > result_low_occ["noi_psf"]

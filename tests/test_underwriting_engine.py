from modules.underwriting_engine import (
    solve_irr, equity_multiple, build_scenarios, build_cash_flows,
    size_financing, simple_sponsor_returns, lp_gp_waterfall, run_sensitivity,
    DEFAULT_SENSITIVITY_DELTAS_PCT, SENSITIVITY_LEVERS,
)


def _prop(**overrides):
    base = {
        "bbl": "3012345678", "borough": "Brooklyn", "zoning_dist": "R6A",
        "lot_sf": 5000.0, "bldg_sf": 0.0, "far_max": 3.0, "far_built": 0.0,
        "is_vacant": True, "strategies": ["Vacant / Underutilized"],
        "landuse_code": "11", "assess_total": 800_000,
    }
    base.update(overrides)
    return base


def _acq(estimate=3_000_000.0):
    return {"estimate": estimate, "basis": "test", "method": "prior_sale", "confidence": "High"}


# ── IRR / equity multiple solver ────────────────────────────────────────────

def test_solve_irr_known_two_year_example():
    assert abs(solve_irr([-100, 110]) - 0.10) < 1e-4


def test_solve_irr_multi_year_known_example():
    # -1000 upfront, +100/yr for 3 yrs, +1100 in yr 4: verify against a
    # hand-checked NPV-zero rate rather than a memorized constant.
    cf = [-1000, 100, 100, 100, 1100]
    r = solve_irr(cf)
    assert r is not None
    npv = sum(c / (1 + r) ** t for t, c in enumerate(cf))
    assert abs(npv) < 1e-3


def test_solve_irr_no_sign_change_returns_none():
    assert solve_irr([100, 100, 100]) is None
    assert solve_irr([-100, -50]) is None


def test_solve_irr_empty_returns_none():
    assert solve_irr([]) is None


def test_equity_multiple_basic():
    assert equity_multiple([-100, 40, 40, 60]) == 1.4


def test_equity_multiple_no_negative_flows_returns_none():
    assert equity_multiple([10, 20]) is None


# ── Scenario generator ──────────────────────────────────────────────────────

def test_build_scenarios_count_and_shape():
    scenarios = build_scenarios(_prop())
    assert 3 <= len(scenarios) <= 4
    required_keys = {
        "scenario_id", "label", "use_type", "development_type",
        "far_used", "far_basis", "gross_buildable_sf", "net_buildable_sf",
        "hard_cost_psf", "hard_cost_basis",
    }
    for s in scenarios:
        assert required_keys.issubset(s.keys())
        assert s["gross_buildable_sf"] > 0


def test_build_scenarios_includes_condo_and_rental():
    scenarios = build_scenarios(_prop())
    use_types = {s["use_type"] for s in scenarios}
    assert "rental" in use_types
    assert "condo" in use_types


def test_build_scenarios_conversion_variant_when_eligible():
    prop = _prop(strategies=["Conversion / Redevelopment"], far_built=1.5, is_vacant=False)
    scenarios = build_scenarios(prop)
    ids = {s["scenario_id"] for s in scenarios}
    assert "conversion_rental_hold" in ids
    assert "mixed_use_max_far" not in ids


def test_build_scenarios_mixed_use_when_not_conversion_eligible():
    scenarios = build_scenarios(_prop())  # default: vacant, no conversion strategy
    ids = {s["scenario_id"] for s in scenarios}
    assert "mixed_use_max_far" in ids


def test_build_scenarios_no_lot_sf_returns_empty():
    assert build_scenarios(_prop(lot_sf=0.0)) == []
    assert build_scenarios({}) == []


# ── Financing ────────────────────────────────────────────────────────────────

def test_size_financing_shape_and_bounds():
    result = size_financing(total_dev_cost=10_000_000, stabilized_value=9_000_000, year1_noi=500_000)
    assert result["construction_loan_amount"] <= 10_000_000
    assert result["perm_loan_amount"] <= result["perm_loan_ltv_amount"]
    assert result["perm_loan_amount"] <= result["perm_loan_dscr_amount"] + 1e-6
    assert result["binding_constraint"] in ("LTV", "DSCR")
    assert result["annual_debt_service"] >= 0


def test_size_financing_zero_inputs_degrades_gracefully():
    result = size_financing(total_dev_cost=0, stabilized_value=0, year1_noi=0)
    assert result["construction_loan_amount"] == 0.0
    assert result["perm_loan_amount"] == 0.0


# ── Cash flow builder ────────────────────────────────────────────────────────

def test_build_cash_flows_shape_rental_scenario():
    scenarios = build_scenarios(_prop())
    rental = next(s for s in scenarios if s["use_type"] == "rental")
    result = build_cash_flows(rental, _acq(), borough="Brooklyn", hold_years=7)
    assert len(result["annual_cash_flows"]) == 8  # year 0 + 7 hold years
    assert result["annual_cash_flows"][0]["phase"] == "construction"
    assert result["annual_cash_flows"][0]["equity_cf"] < 0  # equity outlay
    assert result["annual_cash_flows"][-1]["phase"] == "exit"
    assert result["total_dev_cost"] > 0
    assert result["year1_noi"] > 0


def test_build_cash_flows_condo_scenario_two_periods():
    scenarios = build_scenarios(_prop())
    condo = next(s for s in scenarios if s["use_type"] == "condo")
    result = build_cash_flows(condo, _acq(), market_comps={"median_price_psf": 900, "count": 10})
    assert len(result["annual_cash_flows"]) == 2
    assert result["annual_cash_flows"][0]["equity_cf"] < 0
    assert result["exit_cap_rate"] is None  # condo scenarios don't use a cap-rate exit


def test_build_cash_flows_never_raises_on_thin_inputs():
    scenarios = build_scenarios(_prop())
    for s in scenarios:
        result = build_cash_flows(s, {"estimate": None})
        assert "annual_cash_flows" in result


# ── Simple sponsor returns ──────────────────────────────────────────────────

def test_simple_sponsor_returns_shape():
    scenarios = build_scenarios(_prop())
    rental = next(s for s in scenarios if s["scenario_id"] == "rental_hold_max_far")
    cf = build_cash_flows(rental, _acq(), market_comps={"median_price_psf": 900, "count": 10}, borough="Brooklyn")
    result = simple_sponsor_returns(cf["annual_cash_flows"])
    for key in ("irr", "equity_multiple", "total_equity_in", "total_distributions", "cash_flow_series"):
        assert key in result
    assert result["total_equity_in"] > 0


# ── LP/GP Waterfall — reconciliation is the required consistency test ──────

def _profitable_cash_flows(hold_years=10):
    prop = _prop(borough="Manhattan", zoning_dist="R8", lot_sf=8000.0, far_max=7.2)
    scenarios = build_scenarios(prop, {"median_price_psf": 1400, "count": 20})
    rental = next(s for s in scenarios if s["scenario_id"] == "rental_hold_max_far")
    acq = _acq(estimate=3_000_000.0)
    return build_cash_flows(
        rental, acq, market_comps={"median_price_psf": 1400, "count": 20},
        borough="Manhattan", hold_years=hold_years,
    )["annual_cash_flows"]


def test_waterfall_lp_gp_reconcile_to_simple_model():
    annual_cash_flows = _profitable_cash_flows()
    simple = simple_sponsor_returns(annual_cash_flows)
    wf = lp_gp_waterfall(annual_cash_flows)

    total_simple = sum(simple["cash_flow_series"])
    total_lp_gp = sum(wf["lp_cash_flow_series"]) + sum(wf["gp_cash_flow_series"])
    assert abs(total_simple - total_lp_gp) < 1.0

    # Per-year reconciliation, not just the aggregate.
    for t, cf in enumerate(annual_cash_flows):
        assert abs(wf["lp_cash_flow_series"][t] + wf["gp_cash_flow_series"][t] - cf["equity_cf"]) < 1.0

    assert abs(wf["reconciliation_check"]) < 1.0


def test_waterfall_no_promote_when_deal_barely_clears_pref():
    # A thin deal (low simple IRR, at/below the 8% pref hurdle) should
    # show ~$0 GP promote -- GP shouldn't earn upside it didn't create.
    prop = _prop(borough="Brooklyn")
    scenarios = build_scenarios(prop, {"median_price_psf": 750, "count": 5})
    rental = next(s for s in scenarios if s["scenario_id"] == "rental_hold_as_of_right")
    acq = _acq(estimate=8_000_000.0)
    cf = build_cash_flows(
        rental, acq, market_comps={"median_price_psf": 750, "count": 5},
        borough="Brooklyn", hold_years=7,
    )
    simple = simple_sponsor_returns(cf["annual_cash_flows"])
    wf = lp_gp_waterfall(cf["annual_cash_flows"])
    assert simple["irr"] is None or simple["irr"] < 0.08
    assert wf["total_gp_promote"] < 1.0


def test_waterfall_meaningful_promote_on_strong_deal():
    annual_cash_flows = _profitable_cash_flows()
    simple = simple_sponsor_returns(annual_cash_flows)
    wf = lp_gp_waterfall(annual_cash_flows)
    assert simple["irr"] is not None and simple["irr"] > 0.10
    assert wf["total_gp_promote"] > 0
    # GP's promote should push its multiple above its pure pro-rata (10%)
    # capital share would otherwise deliver on a no-promote basis.
    assert wf["gp_equity_multiple"] > wf["lp_equity_multiple"]


def test_waterfall_preserves_capital_split_on_pure_contribution_years():
    annual_cash_flows = _profitable_cash_flows()
    wf = lp_gp_waterfall(annual_cash_flows, gp_co_invest_pct=0.10)
    year0 = annual_cash_flows[0]["equity_cf"]
    assert abs(wf["lp_cash_flow_series"][0] - year0 * 0.90) < 1.0
    assert abs(wf["gp_cash_flow_series"][0] - year0 * 0.10) < 1.0


# ── Sensitivity ──────────────────────────────────────────────────────────────

def test_sensitivity_grid_shape():
    scenarios = build_scenarios(_prop())
    rental = next(s for s in scenarios if s["scenario_id"] == "rental_hold_max_far")
    acq = _acq()
    result = run_sensitivity(rental, acq, base_kwargs={"market_comps": {"median_price_psf": 900, "count": 10}, "borough": "Brooklyn"})
    assert set(result["grid"].keys()) == set(SENSITIVITY_LEVERS)
    for lever in SENSITIVITY_LEVERS:
        assert len(result["grid"][lever]) == len(DEFAULT_SENSITIVITY_DELTAS_PCT)
    assert len(result["tornado_ranking"]) == len(SENSITIVITY_LEVERS)


def test_sensitivity_exit_cap_rate_produces_realistic_bounded_swings():
    # Regression test for a units bug where the exit-cap-rate lever was
    # scaled by 10,000 instead of applied as a relative multiplier,
    # producing an out-of-domain (negative) cap rate and None IRRs.
    scenarios = build_scenarios(_prop())
    rental = next(s for s in scenarios if s["scenario_id"] == "rental_hold_max_far")
    acq = _acq()
    result = run_sensitivity(rental, acq, base_kwargs={"market_comps": {"median_price_psf": 900, "count": 10}, "borough": "Brooklyn"})
    exit_cap_rows = result["grid"]["exit_cap_rate"]
    irr_values = [r["irr"] for r in exit_cap_rows]
    assert all(v is not None for v in irr_values)
    assert max(irr_values) - min(irr_values) < 1.0  # sane bound, not thousands-of-bps blowup

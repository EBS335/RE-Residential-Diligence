"""
Underwriting Engine — Multi-Year Pro Forma, Financing, IRR & Sensitivity.

Deterministic, free-data-only screening math (same design philosophy as
modules/site_finder_valuation.py — no paid APIs, no LLM call). Extends
that module's single-year snapshot into a real construction -> stabilized
operation -> exit-sale cash flow, with a financing/debt tranche and two
selectable equity structures (simple sponsor IRR, or an LP/GP waterfall).

Reuses rather than duplicates:
  - modules.site_finder_valuation.estimate_acquisition_cost() for the
    acquisition basis (shared across every scenario for one property).
  - Its cost-stack constants (_HARD_COST_PSF_*, _SOFT_COST_PCT,
    _CONTINGENCY_PCT, _CLOSING_COST_PCT, _EFFICIENCY_FACTOR) for the
    construction-period cost build-up.
  - modules.unit_mix.optimize_unit_mix() / compute_revenue() for the
    Year-1 rental NOI baseline (rental & mixed-use scenarios).
  - modules.zoning_rules.get_zoning_rules() for as-of-right vs.
    max-FAR-with-bonus scenario sizing.

No numpy-financial / scipy dependency: IRR is solved with a hand-rolled
Newton's-method routine (analytic derivative) with a bisection fallback.

Every output is explicitly labeled a preliminary screening estimate, not
a lender-grade or GP-facing underwriting package. The LP/GP waterfall is
a simplified EUROPEAN (whole-deal-at-exit) waterfall — not a deal-by-deal
American waterfall with clawback.
"""

from __future__ import annotations

from modules.site_sourcing import STRATEGY_DEMOLITION, STRATEGY_CONVERSION
from modules.site_finder_valuation import (
    estimate_acquisition_cost,
    _HARD_COST_PSF_GROUND_UP,
    _HARD_COST_PSF_CONVERSION,
    _SOFT_COST_PCT,
    _CONTINGENCY_PCT,
    _CLOSING_COST_PCT,
    _EFFICIENCY_FACTOR,
)
from modules.unit_mix import optimize_unit_mix, compute_revenue, CAP_RATES, RISK_PARAMS
from modules.zoning_rules import get_zoning_rules

# ── Hold / exit assumptions (NYC-typical rules of thumb, all overridable) ──
DEFAULT_CONSTRUCTION_MONTHS    = 24
DEFAULT_HOLD_YEARS_POST_STAB   = 7
DEFAULT_RENT_GROWTH_PCT        = 0.03
DEFAULT_EXPENSE_GROWTH_PCT     = 0.025
DEFAULT_EXIT_CAP_SPREAD_BPS    = 50          # exit cap = going-in cap + this spread
DEFAULT_SELLING_COST_PCT       = 0.03
DEFAULT_CONDO_SELLOUT_MONTHS   = 18
DEFAULT_CONDO_PRICE_GROWTH_PCT = 0.02

# ── Financing assumptions ───────────────────────────────────────────────────
DEFAULT_CONSTRUCTION_LTC  = 0.65
DEFAULT_CONSTRUCTION_RATE = 0.0850
DEFAULT_PERM_LTV          = 0.65
DEFAULT_PERM_DSCR_MIN     = 1.25
DEFAULT_PERM_RATE         = 0.0625
DEFAULT_PERM_AMORT_YEARS  = 30
DEFAULT_PERM_IO_YEARS     = 0

# ── Waterfall assumptions ───────────────────────────────────────────────────
DEFAULT_PREFERRED_RETURN_PCT = 0.08
DEFAULT_PROMOTE_TIERS = [
    # (irr_hurdle_lower_bound, irr_hurdle_upper_bound, gp_promote_pct_of_excess)
    (0.08, 0.14, 0.20),
    (0.14, 0.18, 0.30),
    (0.18, None, 0.40),
]
DEFAULT_GP_CO_INVEST_PCT = 0.10

# ── Mixed-use retail assumptions ────────────────────────────────────────────
DEFAULT_RETAIL_SHARE_OF_GROSS_SF = 0.15
DEFAULT_RETAIL_RENT_PSF_YR       = 75.0
DEFAULT_RETAIL_EFFICIENCY        = 0.95

# ── Sensitivity assumptions ─────────────────────────────────────────────────
DEFAULT_SENSITIVITY_DELTAS_PCT = [-0.15, -0.10, -0.05, 0.05, 0.10, 0.15]
SENSITIVITY_LEVERS = [
    "rent", "hard_cost", "exit_cap_rate", "interest_rate",
    "hold_period", "vacancy", "leverage", "price", "opex",
]


# ═════════════════════════════════════════════════════════════════════════
# 1. IRR / NPV solver — dependency-free
# ═════════════════════════════════════════════════════════════════════════

def _npv(rate: float, cash_flows: list[float]) -> float:
    return sum(cf / (1.0 + rate) ** t for t, cf in enumerate(cash_flows))


def _npv_derivative(rate: float, cash_flows: list[float]) -> float:
    return sum(-t * cf / (1.0 + rate) ** (t + 1) for t, cf in enumerate(cash_flows) if t > 0)


def _has_sign_change(cash_flows: list[float]) -> bool:
    signs = {1 if cf > 0 else (-1 if cf < 0 else 0) for cf in cash_flows}
    return 1 in signs and -1 in signs


def solve_irr(cash_flows: list[float], guess: float = 0.12, max_iter: int = 100, tol: float = 1e-6) -> float | None:
    """
    Solve for the internal rate of return of a cash-flow series (index 0 =
    t=0, typically a negative initial outlay). Never raises. Returns None
    if no valid IRR exists (e.g. no sign change) or no solution converges.

    Newton's method with an analytic derivative; falls back to bisection
    over [-0.99, 5.0] if Newton fails to converge or the derivative is
    near zero.
    """
    if not cash_flows or not _has_sign_change(cash_flows):
        return None

    rate = guess
    for _ in range(max_iter):
        npv = _npv(rate, cash_flows)
        if abs(npv) < tol:
            return rate
        deriv = _npv_derivative(rate, cash_flows)
        if abs(deriv) < 1e-10:
            break
        new_rate = rate - npv / deriv
        if new_rate <= -0.99:
            new_rate = (rate - 0.99) / 2.0  # clamp toward the valid domain
        rate = new_rate
    else:
        # Newton loop exhausted without early-return; still fall through to
        # bisection below for a robust answer rather than trusting the
        # possibly-unconverged `rate`.
        pass

    # ── Bisection fallback ──────────────────────────────────────────────
    lo, hi = -0.99, 5.0
    npv_lo, npv_hi = _npv(lo, cash_flows), _npv(hi, cash_flows)
    if npv_lo == 0:
        return lo
    if npv_hi == 0:
        return hi
    if (npv_lo > 0) == (npv_hi > 0):
        return None  # no sign change across the bracket -> no root found
    for _ in range(200):
        mid = (lo + hi) / 2.0
        npv_mid = _npv(mid, cash_flows)
        if abs(npv_mid) < tol:
            return mid
        if (npv_mid > 0) == (npv_lo > 0):
            lo, npv_lo = mid, npv_mid
        else:
            hi, npv_hi = mid, npv_mid
    return (lo + hi) / 2.0


def equity_multiple(cash_flows: list[float]) -> float | None:
    """sum(distributions) / abs(sum(contributions)). None if no negative flows."""
    positives = sum(cf for cf in cash_flows if cf > 0)
    negatives = sum(cf for cf in cash_flows if cf < 0)
    if negatives == 0:
        return None
    return positives / abs(negatives)


def _remaining_loan_balance(principal: float, annual_rate: float, amort_years: int, years_elapsed: float) -> float:
    """Standard amortization remaining-balance formula (monthly compounding)."""
    if principal <= 0 or amort_years <= 0:
        return 0.0
    if annual_rate <= 0:
        # Interest-free edge case: straight-line paydown.
        frac = min(1.0, max(0.0, years_elapsed / amort_years))
        return max(0.0, principal * (1 - frac))
    r = annual_rate / 12.0
    n = amort_years * 12
    k = min(n, max(0, round(years_elapsed * 12)))
    if k >= n:
        return 0.0
    return principal * ((1 + r) ** n - (1 + r) ** k) / ((1 + r) ** n - 1)


def _amortizing_payment(principal: float, annual_rate: float, amort_years: int) -> float:
    """Standard closed-form fixed-rate amortizing annual payment."""
    if principal <= 0 or amort_years <= 0:
        return 0.0
    if annual_rate <= 0:
        return principal / amort_years
    r = annual_rate / 12.0
    n = amort_years * 12
    monthly = principal * (r * (1 + r) ** n) / ((1 + r) ** n - 1)
    return monthly * 12.0


# ═════════════════════════════════════════════════════════════════════════
# 2. Scenario generator
# ═════════════════════════════════════════════════════════════════════════

def _far_options(prop: dict) -> tuple[float, float, str]:
    """Returns (as_of_right_far, max_far_with_bonus, source_note)."""
    zr = get_zoning_rules(prop.get("zoning_dist", ""))
    fallback = prop.get("far_max", 0.0) or 0.0
    if zr:
        as_of_right = zr.get("base_far") or fallback
        max_bonus = zr.get("max_far") or fallback
        return as_of_right, max_bonus, "NYC Zoning Resolution district table"
    return fallback, fallback, "PLUTO far_max (no static zoning-district rule match)"


def _hard_cost_for(development_type: str) -> tuple[float, str]:
    if development_type == "conversion":
        return _HARD_COST_PSF_CONVERSION, "conversion/renovation"
    return _HARD_COST_PSF_GROUND_UP, "ground-up new construction"


def _make_scenario(
    scenario_id: str, label: str, use_type: str, development_type: str,
    far_used: float, far_basis: str, lot_sf: float, far_source: str,
) -> dict:
    gross_buildable_sf = max(0.0, far_used * lot_sf)
    hard_cost_psf, hard_cost_basis = _hard_cost_for(development_type)

    assumptions_note = [f"FAR basis: {far_basis} ({far_source})"]

    retail_sf = 0.0
    residential_gross_sf = gross_buildable_sf
    if use_type == "mixed_use":
        retail_sf = gross_buildable_sf * DEFAULT_RETAIL_SHARE_OF_GROSS_SF
        residential_gross_sf = gross_buildable_sf - retail_sf
        assumptions_note.append(
            f"Ground-floor retail assumed at {DEFAULT_RETAIL_SHARE_OF_GROSS_SF:.0%} of gross SF"
        )

    net_buildable_sf = residential_gross_sf * _EFFICIENCY_FACTOR
    net_retail_sf = retail_sf * DEFAULT_RETAIL_EFFICIENCY

    return {
        "scenario_id": scenario_id,
        "label": label,
        "use_type": use_type,               # "rental" | "condo" | "mixed_use"
        "development_type": development_type,  # "ground_up" | "conversion"
        "far_used": far_used,
        "far_basis": far_basis,
        "lot_sf": lot_sf,
        "gross_buildable_sf": gross_buildable_sf,
        "residential_gross_sf": residential_gross_sf,
        "net_buildable_sf": net_buildable_sf,
        "retail_sf": retail_sf,
        "net_retail_sf": net_retail_sf,
        "hard_cost_psf": hard_cost_psf,
        "hard_cost_basis": hard_cost_basis,
        "assumptions_note": assumptions_note,
    }


def build_scenarios(prop: dict, market_comps: dict | None = None) -> list[dict]:
    """
    Generate 3-4 candidate development scenarios for a property, varying
    use type (rental hold / condo sell-out / mixed-use or conversion) and
    development intensity (as-of-right FAR vs. max FAR with bonus).

    Never raises. Returns [] only if the property has no usable lot_sf.
    """
    prop = prop or {}
    lot_sf = prop.get("lot_sf", 0.0) or 0.0
    if lot_sf <= 0:
        return []

    strategies = set(prop.get("strategies", []))
    as_of_right_far, max_far_bonus, far_source = _far_options(prop)

    scenarios = [
        _make_scenario(
            "rental_hold_as_of_right", "Rental Hold — As-of-Right FAR", "rental", "ground_up",
            as_of_right_far, "as_of_right", lot_sf, far_source,
        ),
        _make_scenario(
            "rental_hold_max_far", "Rental Hold — Max FAR (w/ bonus)", "rental", "ground_up",
            max_far_bonus, "max_far_with_bonus", lot_sf, far_source,
        ),
        _make_scenario(
            "condo_sellout_max_far", "Condo Sell-Out — Max FAR", "condo", "ground_up",
            max_far_bonus, "max_far_with_bonus", lot_sf, far_source,
        ),
    ]

    is_conversion_eligible = (
        STRATEGY_CONVERSION in strategies and STRATEGY_DEMOLITION not in strategies
        and (prop.get("far_built", 0.0) or 0.0) > 0
    )
    if is_conversion_eligible:
        scenarios.append(_make_scenario(
            "conversion_rental_hold", "Conversion to Rental — Existing Building", "rental", "conversion",
            prop.get("far_built", 0.0) or as_of_right_far, "existing_building", lot_sf, far_source,
        ))
    else:
        scenarios.append(_make_scenario(
            "mixed_use_max_far", "Mixed-Use (Retail + Rental) — Max FAR", "mixed_use", "ground_up",
            max_far_bonus, "max_far_with_bonus", lot_sf, far_source,
        ))

    return scenarios


# ═════════════════════════════════════════════════════════════════════════
# 3. Financing sizing
# ═════════════════════════════════════════════════════════════════════════

def size_financing(
    total_dev_cost: float,
    stabilized_value: float,
    year1_noi: float,
    construction_months: int = DEFAULT_CONSTRUCTION_MONTHS,
    construction_ltc: float = DEFAULT_CONSTRUCTION_LTC,
    construction_rate: float = DEFAULT_CONSTRUCTION_RATE,
    perm_ltv: float = DEFAULT_PERM_LTV,
    perm_dscr_min: float = DEFAULT_PERM_DSCR_MIN,
    perm_rate: float = DEFAULT_PERM_RATE,
    perm_amort_years: int = DEFAULT_PERM_AMORT_YEARS,
    perm_io_years: int = DEFAULT_PERM_IO_YEARS,
) -> dict:
    """
    Size a construction loan (LTC-constrained) and a permanent take-out
    loan (the lesser of an LTV-constrained and a DSCR-constrained amount).
    Never raises; degrades to zero-debt (all-equity) if inputs are <= 0.
    """
    total_dev_cost = max(0.0, total_dev_cost or 0.0)
    stabilized_value = max(0.0, stabilized_value or 0.0)
    year1_noi = max(0.0, year1_noi or 0.0)

    construction_loan_amount = min(construction_ltc, 1.0) * total_dev_cost if total_dev_cost else 0.0
    avg_balance = construction_loan_amount / 2.0
    construction_interest_accrued = avg_balance * construction_rate * (construction_months / 12.0)

    perm_ltv_amount = perm_ltv * stabilized_value

    if perm_dscr_min > 0 and year1_noi > 0:
        max_annual_debt_service = year1_noi / perm_dscr_min
        # Back-solve loan amount from the annual payment via the closed-form
        # amortization-payment formula, inverted.
        r = perm_rate / 12.0
        n = perm_amort_years * 12
        if perm_rate > 0 and n > 0:
            monthly_ads = max_annual_debt_service / 12.0
            perm_dscr_amount = monthly_ads * ((1 + r) ** n - 1) / (r * (1 + r) ** n)
        else:
            perm_dscr_amount = max_annual_debt_service * perm_amort_years
    else:
        perm_dscr_amount = perm_ltv_amount  # no DSCR constraint configured

    perm_loan_amount = min(perm_ltv_amount, perm_dscr_amount)
    binding_constraint = "DSCR" if perm_dscr_amount < perm_ltv_amount else "LTV"

    if perm_io_years > 0:
        annual_debt_service = perm_loan_amount * perm_rate
    else:
        annual_debt_service = _amortizing_payment(perm_loan_amount, perm_rate, perm_amort_years)

    construction_payoff = construction_loan_amount + construction_interest_accrued
    refinance_proceeds_net_of_construction_payoff = perm_loan_amount - construction_payoff

    return {
        "construction_loan_amount": construction_loan_amount,
        "construction_interest_accrued": construction_interest_accrued,
        "perm_loan_ltv_amount": perm_ltv_amount,
        "perm_loan_dscr_amount": perm_dscr_amount,
        "perm_loan_amount": perm_loan_amount,
        "binding_constraint": binding_constraint,
        "annual_debt_service": annual_debt_service,
        "perm_rate": perm_rate,
        "perm_amort_years": perm_amort_years,
        "perm_io_years": perm_io_years,
        "refinance_proceeds_net_of_construction_payoff": refinance_proceeds_net_of_construction_payoff,
        "note": "Construction interest accrued on a straight-line half-drawn-balance "
                "approximation, not a monthly draw schedule.",
    }


# ═════════════════════════════════════════════════════════════════════════
# 4. Multi-year cash flow builder (single scenario)
# ═════════════════════════════════════════════════════════════════════════

def _condo_revenue(scenario: dict, acquisition: dict, market_comps: dict | None) -> dict:
    mc = market_comps or {}
    psf = mc.get("median_price_psf")
    if not psf:
        acq_est = acquisition.get("estimate")
        lot_sf = scenario.get("lot_sf", 0.0) or 0.0
        psf = (acq_est / lot_sf * 3.0) if (acq_est and lot_sf) else 800.0  # very rough fallback
    net_sf = scenario.get("net_buildable_sf", 0.0)
    gross_sellout = psf * net_sf
    return {"sellout_price_psf": psf, "gross_sellout": gross_sellout}


def build_cash_flows(
    scenario: dict,
    acquisition: dict,
    market_comps: dict | None = None,
    avg_rents: dict | None = None,
    risk_level: str = "MED",
    borough: str = "Manhattan",
    construction_months: int = DEFAULT_CONSTRUCTION_MONTHS,
    hold_years: int = DEFAULT_HOLD_YEARS_POST_STAB,
    rent_growth_pct: float = DEFAULT_RENT_GROWTH_PCT,
    expense_growth_pct: float = DEFAULT_EXPENSE_GROWTH_PCT,
    exit_cap_spread_bps: int = DEFAULT_EXIT_CAP_SPREAD_BPS,
    selling_cost_pct: float = DEFAULT_SELLING_COST_PCT,
    cap_rate_multiplier: float = 1.0,
    financing_kwargs: dict | None = None,
    occupancy_override: float | None = None,
) -> dict:
    """
    Build a multi-year cash-flow-to-equity series for ONE scenario:
    construction (year 0) -> stabilization/hold (years 1..hold_years, with
    separately-grown rent & expenses) -> exit reversion sale in the final
    year. Rental/mixed-use scenarios use unit_mix.compute_revenue() for the
    Year-1 NOI baseline; condo scenarios use a sell-out price model instead.

    Never raises. Returns a fixed-shape dict; `annual_cash_flows[i]["equity_cf"]`
    is the series solve_irr()/equity_multiple() should be called on directly.
    Also returns `achieved_dscr_yr1`, `cash_on_cash_yr1`, and `yield_on_cost`
    — Year-1 acquisition-analysis output metrics computed from values this
    function already builds (None where not meaningful, e.g. condo sellout).
    `occupancy_override` (0-1) substitutes for risk_level's default
    occupancy, e.g. for a vacancy sensitivity lever in run_sensitivity().
    """
    financing_kwargs = financing_kwargs or {}
    acq_estimate = acquisition.get("estimate") or 0.0

    hard_cost = scenario["gross_buildable_sf"] * scenario["hard_cost_psf"]
    soft_cost = hard_cost * _SOFT_COST_PCT
    contingency = (hard_cost + soft_cost) * _CONTINGENCY_PCT
    closing_cost = acq_estimate * _CLOSING_COST_PCT
    total_dev_cost = acq_estimate + closing_cost + hard_cost + soft_cost + contingency
    cost_breakdown = {
        "acquisition_cost": acq_estimate, "closing_cost": closing_cost,
        "hard_cost": hard_cost, "soft_cost": soft_cost, "contingency": contingency,
        "total_dev_cost": total_dev_cost,
    }

    cap_rate = CAP_RATES.get(borough, CAP_RATES["Manhattan"]) * cap_rate_multiplier
    exit_cap_rate = cap_rate + (exit_cap_spread_bps / 10_000.0)

    annual_cash_flows: list[dict] = []
    is_condo = scenario["use_type"] == "condo"

    if is_condo:
        condo = _condo_revenue(scenario, acquisition, market_comps)
        gross_sellout = condo["gross_sellout"]
        net_sellout = gross_sellout * (1 - selling_cost_pct)
        financing = size_financing(total_dev_cost, stabilized_value=0.0, year1_noi=0.0, **financing_kwargs)
        equity_in = max(0.0, total_dev_cost - financing["construction_loan_amount"])

        annual_cash_flows.append({
            "year": 0, "phase": "construction", "noi": 0.0, "debt_service": 0.0,
            "capex": 0.0, "unlevered_cf": -total_dev_cost, "levered_cf": -equity_in,
            "reversion_proceeds": 0.0, "equity_cf": -equity_in,
        })
        # Sell-out modeled as a single lump distribution in "year 1" (post
        # the absorption window), net of the construction loan payoff.
        sellout_net_of_debt = net_sellout - (financing["construction_loan_amount"] + financing["construction_interest_accrued"])
        annual_cash_flows.append({
            "year": 1, "phase": "exit", "noi": 0.0, "debt_service": 0.0, "capex": 0.0,
            "unlevered_cf": net_sellout, "levered_cf": sellout_net_of_debt,
            "reversion_proceeds": sellout_net_of_debt, "equity_cf": sellout_net_of_debt,
        })

        return {
            "scenario_id": scenario["scenario_id"], "scenario_label": scenario["label"],
            "annual_cash_flows": annual_cash_flows,
            "total_dev_cost": total_dev_cost, "year1_noi": 0.0,
            "exit_value": gross_sellout, "exit_cap_rate": None,
            "unlevered_irr": solve_irr([cf["unlevered_cf"] for cf in annual_cash_flows]),
            "unlevered_equity_multiple": equity_multiple([cf["unlevered_cf"] for cf in annual_cash_flows]),
            "total_equity_in": equity_in,
            "financing": financing,
            "cost_breakdown": cost_breakdown,
            # Not meaningful for a lump-sum sellout (no stabilized Year-1 NOI
            # or amortizing debt service to divide by) — always None here.
            "achieved_dscr_yr1": None,
            "cash_on_cash_yr1": None,
            "yield_on_cost": None,
            "assumptions": {
                "hold_years": 1, "rent_growth_pct": None, "expense_growth_pct": None,
                "exit_cap_spread_bps": None, "selling_cost_pct": selling_cost_pct,
                "sellout_price_psf": condo["sellout_price_psf"],
            },
        }

    # ── Rental / mixed-use scenarios ────────────────────────────────────
    unit_mix = optimize_unit_mix(scenario["net_buildable_sf"], neighborhood=borough)
    year1 = compute_revenue(
        unit_mix, avg_rents or {}, risk_level=risk_level, borough=borough,
        occupancy_override=occupancy_override,
    )
    egi_1, opex_1, noi_1 = year1["egi"], year1["opex"], year1["noi"]

    retail_egi_1 = scenario.get("net_retail_sf", 0.0) * DEFAULT_RETAIL_RENT_PSF_YR
    egi_1 += retail_egi_1
    noi_1 = egi_1 - opex_1  # opex ratio already applied to residential EGI only; retail adds straight to NOI

    stabilized_value = noi_1 / cap_rate if cap_rate > 0 else 0.0
    financing = size_financing(total_dev_cost, stabilized_value, noi_1, **financing_kwargs)
    equity_in = max(0.0, total_dev_cost - financing["construction_loan_amount"])

    annual_cash_flows.append({
        "year": 0, "phase": "construction", "noi": 0.0, "debt_service": 0.0, "capex": 0.0,
        "unlevered_cf": -total_dev_cost, "levered_cf": -equity_in,
        "reversion_proceeds": 0.0, "equity_cf": -equity_in,
    })

    egi_t, opex_t = egi_1, opex_1
    final_noi = noi_1
    for yr in range(1, hold_years + 1):
        if yr > 1:
            egi_t = egi_t * (1 + rent_growth_pct)
            opex_t = opex_t * (1 + expense_growth_pct)
        noi_t = egi_t - opex_t + (retail_egi_1 if yr == 1 else retail_egi_1 * (1 + rent_growth_pct) ** (yr - 1))
        debt_service = financing["annual_debt_service"] if yr >= 1 else 0.0
        unlevered_cf = noi_t
        levered_cf = noi_t - debt_service

        reversion = 0.0
        if yr == hold_years:
            final_noi = noi_t
            exit_value = final_noi / exit_cap_rate if exit_cap_rate > 0 else 0.0
            selling_costs = exit_value * selling_cost_pct
            remaining_balance = _remaining_loan_balance(
                financing["perm_loan_amount"], financing["perm_rate"],
                financing["perm_amort_years"], years_elapsed=hold_years,
            )
            reversion = exit_value - selling_costs - remaining_balance

        equity_cf = levered_cf + reversion
        # First operating year also nets the refinance event (perm loan
        # proceeds vs. construction loan payoff).
        if yr == 1:
            equity_cf += financing["refinance_proceeds_net_of_construction_payoff"]

        annual_cash_flows.append({
            "year": yr, "phase": "exit" if yr == hold_years else "stabilized",
            "noi": noi_t, "debt_service": debt_service, "capex": 0.0,
            "unlevered_cf": unlevered_cf, "levered_cf": levered_cf,
            "reversion_proceeds": reversion, "equity_cf": equity_cf,
        })

    exit_value = final_noi / exit_cap_rate if exit_cap_rate > 0 else 0.0
    unlevered_series = [cf["unlevered_cf"] for cf in annual_cash_flows]
    unlevered_series[0] = -total_dev_cost
    unlevered_series[-1] += exit_value * (1 - selling_cost_pct)

    # Acquisition-analysis output metrics (Year-1, on-top-of the multi-year
    # IRR above) — pure arithmetic on values already computed in this
    # function; not a second financial model.
    year1_debt_service = financing["annual_debt_service"]
    achieved_dscr_yr1 = (noi_1 / year1_debt_service) if year1_debt_service > 0 else None
    cash_on_cash_yr1 = ((noi_1 - year1_debt_service) / equity_in) if equity_in > 0 else None
    yield_on_cost = (noi_1 / total_dev_cost) if total_dev_cost > 0 else None

    return {
        "scenario_id": scenario["scenario_id"], "scenario_label": scenario["label"],
        "annual_cash_flows": annual_cash_flows,
        "total_dev_cost": total_dev_cost, "year1_noi": noi_1,
        "exit_value": exit_value, "exit_cap_rate": exit_cap_rate,
        "unlevered_irr": solve_irr(unlevered_series),
        "unlevered_equity_multiple": equity_multiple(unlevered_series),
        "total_equity_in": equity_in,
        "financing": financing,
        "cost_breakdown": cost_breakdown,
        "achieved_dscr_yr1": achieved_dscr_yr1,
        "cash_on_cash_yr1": cash_on_cash_yr1,
        "yield_on_cost": yield_on_cost,
        "assumptions": {
            "hold_years": hold_years, "rent_growth_pct": rent_growth_pct,
            "expense_growth_pct": expense_growth_pct, "exit_cap_spread_bps": exit_cap_spread_bps,
            "selling_cost_pct": selling_cost_pct, "going_in_cap_rate": cap_rate,
        },
    }


# ═════════════════════════════════════════════════════════════════════════
# 4b. Land-residual solver
# ═════════════════════════════════════════════════════════════════════════

DEFAULT_LAND_RESIDUAL_TARGET_IRR = 0.15
DEFAULT_LAND_RESIDUAL_MAX_ITER = 60
DEFAULT_LAND_RESIDUAL_TOL_IRR = 0.0005


def solve_land_residual_value(
    scenario: dict,
    acquisition: dict,
    target_irr: float = DEFAULT_LAND_RESIDUAL_TARGET_IRR,
    price_bounds: tuple[float, float] | None = None,
    max_iter: int = DEFAULT_LAND_RESIDUAL_MAX_ITER,
    tol_irr: float = DEFAULT_LAND_RESIDUAL_TOL_IRR,
    **cash_flow_kwargs,
) -> dict:
    """
    Reverse-solve for the maximum acquisition/land price this scenario can
    pay and still hit `target_irr` — every other build_cash_flows()
    assumption held fixed. Bisects on acquisition price directly (never
    raises, no numpy/scipy) rather than reusing solve_irr()'s
    rate-bisection: IRR is monotonically non-increasing in acquisition
    price (a higher price only ever makes the deal's cash flows worse), so
    the same bisection strategy applies to a different variable. Reuses
    build_cash_flows()/simple_sponsor_returns() as black boxes — no
    parallel cash-flow model.

    `cash_flow_kwargs` are forwarded to build_cash_flows() exactly as in
    run_sensitivity() (market_comps, avg_rents, risk_level, borough, etc).

    Returns {"land_value", "achieved_irr", "note"} — never raises;
    degrades to a best-effort estimate (with an explanatory `note`) if the
    target IRR is unreachable within `price_bounds` or convergence stalls.
    """
    base_estimate = max(0.0, acquisition.get("estimate") or 0.0)
    lo, hi = price_bounds or (0.0, max(base_estimate * 3.0, 1_000_000.0))

    def _irr_at(price: float) -> float | None:
        acq = dict(acquisition)
        acq["estimate"] = max(0.0, price)
        result = build_cash_flows(scenario, acq, **cash_flow_kwargs)
        return simple_sponsor_returns(result["annual_cash_flows"])["irr"]

    irr_at_zero = _irr_at(lo)
    if irr_at_zero is None:
        return {"land_value": None, "achieved_irr": None,
                "note": "Could not solve — no valid IRR even at zero land cost."}
    if irr_at_zero < target_irr:
        return {"land_value": 0.0, "achieved_irr": irr_at_zero,
                "note": f"Target IRR ({target_irr:.1%}) unreachable even at zero land cost "
                        f"under these assumptions."}

    irr_at_hi = _irr_at(hi)
    if irr_at_hi is not None and irr_at_hi >= target_irr:
        return {"land_value": hi, "achieved_irr": irr_at_hi,
                "note": f"Target IRR still achievable at the upper price bound "
                        f"(${hi:,.0f}) — raise price_bounds to solve further."}

    mid = lo
    irr_mid = irr_at_zero
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        irr_mid = _irr_at(mid)
        if irr_mid is None:
            hi = mid
            continue
        if abs(irr_mid - target_irr) < tol_irr:
            return {"land_value": mid, "achieved_irr": irr_mid, "note": None}
        if irr_mid > target_irr:
            lo = mid
        else:
            hi = mid

    return {"land_value": mid, "achieved_irr": irr_mid,
            "note": "Max iterations reached — result is a close approximation, not exact."}


# ═════════════════════════════════════════════════════════════════════════
# 5. Equity structure calculators
# ═════════════════════════════════════════════════════════════════════════

def simple_sponsor_returns(annual_cash_flows: list[dict]) -> dict:
    """Single all-equity-in/all-cash-out perspective."""
    series = [cf["equity_cf"] for cf in annual_cash_flows]
    total_equity_in = -sum(cf for cf in series if cf < 0)
    total_distributions = sum(cf for cf in series if cf > 0)
    return {
        "irr": solve_irr(series),
        "equity_multiple": equity_multiple(series),
        "total_equity_in": total_equity_in,
        "total_distributions": total_distributions,
        "cash_flow_series": series,
    }


def _gp_pct_for_irr(achieved_irr: float, promote_tiers: list[tuple]) -> float:
    for lo, hi, gp_pct in promote_tiers:
        if achieved_irr >= lo and (hi is None or achieved_irr < hi):
            return gp_pct
    if promote_tiers and achieved_irr < promote_tiers[0][0]:
        return 0.0
    return promote_tiers[-1][2] if promote_tiers else 0.0


def lp_gp_waterfall(
    annual_cash_flows: list[dict],
    preferred_return_pct: float = DEFAULT_PREFERRED_RETURN_PCT,
    promote_tiers: list[tuple] | None = None,
    gp_co_invest_pct: float = DEFAULT_GP_CO_INVEST_PCT,
) -> dict:
    """
    Simplified European (whole-deal-at-exit) LP/GP waterfall:
      Tier 0 — Return of Capital, pro-rata by contribution %.
      Tier 1 — Preferred Return (compounded annually on unreturned
               capital), pro-rata by contribution %.
      Tier 2+ — Promote tiers: cash above the preferred return is split
               per `promote_tiers`, keyed to the deal's ACHIEVED IRR
               (recomputed each distribution year on the running cash-flow
               stream) rather than a fixed dollar hurdle.

    Guarantees, by construction, that lp_cash_flow_series[t] +
    gp_cash_flow_series[t] == annual_cash_flows[t]["equity_cf"] for every
    year — required for the reconciliation test against
    simple_sponsor_returns().
    """
    promote_tiers = promote_tiers if promote_tiers is not None else DEFAULT_PROMOTE_TIERS
    total_cf = [cf["equity_cf"] for cf in annual_cash_flows]

    lp_share = 1.0 - gp_co_invest_pct
    gp_share = gp_co_invest_pct

    lp_unreturned = gp_unreturned = 0.0
    lp_pref_accrued = gp_pref_accrued = 0.0
    lp_series: list[float] = []
    gp_series: list[float] = []
    tier_breakdown: list[dict] = []

    for t, cf_t in enumerate(total_cf):
        # Pref compounds on the OUTSTANDING balance (unreturned capital +
        # any already-accrued-but-unpaid pref) for EVERY elapsed year --
        # including years with an additional capital call or zero cash
        # flow, not only years with a distribution. Skipping accrual in
        # a contribution/zero year silently understates owed pref (and
        # the achieved-IRR hurdle checks below), since a single terminal
        # lump-sum payment of "capital + N years of simple, non-
        # compounding interest" yields an IRR BELOW the stated pref rate
        # (IRR values time) unless every elapsed period compounds.
        if t > 0:
            lp_pref_accrued += (lp_unreturned + lp_pref_accrued) * preferred_return_pct
            gp_pref_accrued += (gp_unreturned + gp_pref_accrued) * preferred_return_pct

        if cf_t <= 0:
            lp_cf = cf_t * lp_share
            gp_cf = cf_t * gp_share
            lp_unreturned += -lp_cf
            gp_unreturned += -gp_cf
            lp_series.append(lp_cf)
            gp_series.append(gp_cf)
            tier_breakdown.append({"year": t, "type": "contribution", "amount": cf_t})
            continue

        available = cf_t
        roc_needed = lp_unreturned + gp_unreturned
        roc_paid = min(available, roc_needed)
        lp_roc = roc_paid * (lp_unreturned / roc_needed) if roc_needed > 0 else 0.0
        gp_roc = roc_paid - lp_roc
        lp_unreturned -= lp_roc
        gp_unreturned -= gp_roc
        available -= roc_paid

        pref_paid = lp_pref = gp_pref = 0.0
        if available > 0:
            pref_needed = lp_pref_accrued + gp_pref_accrued
            pref_paid = min(available, pref_needed)
            lp_pref = pref_paid * (lp_pref_accrued / pref_needed) if pref_needed > 0 else 0.0
            gp_pref = pref_paid - lp_pref
            lp_pref_accrued -= lp_pref
            gp_pref_accrued -= gp_pref
            available -= pref_paid

        promote_lp = promote_gp = 0.0
        achieved_irr = None
        if available > 0:
            trial_cf = total_cf[:t] + [roc_paid + pref_paid]
            achieved_irr = solve_irr(trial_cf) or 0.0
            gp_pct = _gp_pct_for_irr(achieved_irr, promote_tiers)
            promote_gp = available * gp_pct
            promote_lp = available - promote_gp
            available = 0.0

        lp_cf = lp_roc + lp_pref + promote_lp
        gp_cf = gp_roc + gp_pref + promote_gp
        lp_series.append(lp_cf)
        gp_series.append(gp_cf)
        tier_breakdown.append({
            "year": t, "type": "distribution", "roc": roc_paid, "pref": pref_paid,
            "promote_pool": promote_lp + promote_gp, "promote_gp": promote_gp,
            "achieved_irr_at_promote": achieved_irr,
            "lp_amount": lp_cf, "gp_amount": gp_cf,
        })

    reconciliation_check = sum(lp_series) + sum(gp_series) - sum(total_cf)
    total_gp_promote = sum(tb.get("promote_gp", 0.0) for tb in tier_breakdown if tb.get("type") == "distribution")

    return {
        "lp_irr": solve_irr(lp_series),
        "lp_equity_multiple": equity_multiple(lp_series),
        "gp_irr": solve_irr(gp_series),
        "gp_equity_multiple": equity_multiple(gp_series),
        "lp_cash_flow_series": lp_series,
        "gp_cash_flow_series": gp_series,
        "total_gp_promote": total_gp_promote,
        "tier_breakdown": tier_breakdown,
        "reconciliation_check": reconciliation_check,
        "preferred_return_pct": preferred_return_pct,
        "gp_co_invest_pct": gp_co_invest_pct,
        "note": "Simplified European (whole-deal-at-exit) waterfall — not a "
                "deal-by-deal American waterfall with clawback.",
    }


# ═════════════════════════════════════════════════════════════════════════
# 6. Sensitivity / stress-test runner
# ═════════════════════════════════════════════════════════════════════════

def run_sensitivity(
    scenario: dict,
    acquisition: dict,
    base_kwargs: dict | None = None,
    deltas_pct: list[float] | None = None,
    levers: list[str] | None = None,
    equity_structure: str = "simple",
    waterfall_kwargs: dict | None = None,
) -> dict:
    """
    Re-run build_cash_flows() with one lever perturbed at a time, report
    the resulting IRR at each delta. Cheap (pure arithmetic, no I/O) —
    ~len(levers) x len(deltas) full re-runs.
    """
    deltas_pct = deltas_pct if deltas_pct is not None else DEFAULT_SENSITIVITY_DELTAS_PCT
    levers = levers if levers is not None else SENSITIVITY_LEVERS
    base_kwargs = dict(base_kwargs or {})
    waterfall_kwargs = waterfall_kwargs or {}

    def _irr_for(cf_result: dict) -> float | None:
        if equity_structure == "waterfall":
            return lp_gp_waterfall(cf_result["annual_cash_flows"], **waterfall_kwargs)["lp_irr"]
        return simple_sponsor_returns(cf_result["annual_cash_flows"])["irr"]

    base_result = build_cash_flows(scenario, acquisition, **base_kwargs)
    base_irr = _irr_for(base_result)

    grid: dict[str, list[dict]] = {}
    for lever in levers:
        rows = []
        for delta in deltas_pct:
            kwargs = dict(base_kwargs)
            scenario_for_run = scenario
            acquisition_for_run = acquisition

            if lever == "rent":
                kwargs["rent_growth_pct"] = base_kwargs.get("rent_growth_pct", DEFAULT_RENT_GROWTH_PCT) + delta
            elif lever == "hard_cost":
                scenario_for_run = dict(scenario)
                scenario_for_run["hard_cost_psf"] = scenario["hard_cost_psf"] * (1 + delta)
            elif lever == "exit_cap_rate":
                # Relative stress on the going-in cap rate itself (which the
                # exit cap is derived from), not the small fixed spread --
                # e.g. delta=+0.15 moves a 5.25% cap rate to ~6.04%, a
                # realistic ~80bp swing, rather than shifting the spread by
                # thousands of basis points.
                kwargs["cap_rate_multiplier"] = base_kwargs.get("cap_rate_multiplier", 1.0) * (1 + delta)
            elif lever == "interest_rate":
                fin_kwargs = dict(base_kwargs.get("financing_kwargs") or {})
                fin_kwargs["construction_rate"] = fin_kwargs.get("construction_rate", DEFAULT_CONSTRUCTION_RATE) + delta
                fin_kwargs["perm_rate"] = fin_kwargs.get("perm_rate", DEFAULT_PERM_RATE) + delta
                kwargs["financing_kwargs"] = fin_kwargs
            elif lever == "hold_period":
                base_hold = base_kwargs.get("hold_years", DEFAULT_HOLD_YEARS_POST_STAB)
                kwargs["hold_years"] = max(1, round(base_hold * (1 + delta)))
            elif lever == "vacancy":
                # Stress the VACANCY rate itself (not occupancy) so a
                # positive delta always means "more vacancy" — consistent
                # with hard_cost/interest_rate's positive-delta-is-adverse
                # convention, unlike rent's positive-delta-is-favorable one.
                base_occ = base_kwargs.get("occupancy_override")
                if base_occ is None:
                    base_occ = RISK_PARAMS.get(base_kwargs.get("risk_level", "MED"), RISK_PARAMS["MED"])["occupancy"]
                base_vacancy = 1.0 - base_occ
                stressed_vacancy = max(0.0, min(0.95, base_vacancy * (1 + delta)))
                kwargs["occupancy_override"] = 1.0 - stressed_vacancy
            elif lever == "leverage":
                fin_kwargs = dict(base_kwargs.get("financing_kwargs") or {})
                fin_kwargs["construction_ltc"] = max(0.0, min(0.95, fin_kwargs.get("construction_ltc", DEFAULT_CONSTRUCTION_LTC) * (1 + delta)))
                fin_kwargs["perm_ltv"] = max(0.0, min(0.95, fin_kwargs.get("perm_ltv", DEFAULT_PERM_LTV) * (1 + delta)))
                kwargs["financing_kwargs"] = fin_kwargs
            elif lever == "price":
                acquisition_for_run = dict(acquisition)
                acquisition_for_run["estimate"] = (acquisition.get("estimate") or 0.0) * (1 + delta)
            elif lever == "opex":
                kwargs["expense_growth_pct"] = base_kwargs.get("expense_growth_pct", DEFAULT_EXPENSE_GROWTH_PCT) + delta

            result = build_cash_flows(scenario_for_run, acquisition_for_run, **kwargs)
            irr = _irr_for(result)
            em = simple_sponsor_returns(result["annual_cash_flows"])["equity_multiple"]
            rows.append({"delta_pct": delta, "irr": irr, "equity_multiple": em})
        grid[lever] = rows

    tornado = []
    for lever, rows in grid.items():
        irrs = [r["irr"] for r in rows if r["irr"] is not None]
        swing = (max(irrs) - min(irrs)) if irrs else 0.0
        tornado.append({"lever": lever, "irr_range": swing})
    tornado.sort(key=lambda r: r["irr_range"], reverse=True)

    return {"base_irr": base_irr, "grid": grid, "tornado_ranking": tornado}

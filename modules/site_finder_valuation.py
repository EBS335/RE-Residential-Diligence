"""
Site Finder Valuation — Preliminary Acquisition Estimate & Business Plan.

Deterministic, free-data-only screening math. No paid APIs, no LLM call —
just arithmetic over data Site Finder has already collected (PLUTO,
ACRIS via ownership_research, NYC Rolling Sales via site_finder_market).

Every output is explicitly labeled as a preliminary screening estimate,
not an appraisal, broker opinion of value, or GC cost estimate.
"""

from __future__ import annotations

from modules.site_sourcing import STRATEGY_VACANT, STRATEGY_DEMOLITION, STRATEGY_CONVERSION

# ── Assumptions (static, free, illustrative — not sourced from any paid feed) ─

# NYC DOF target assessment ratios by approximate tax class, used only as a
# last-resort fallback when no sale price or comps are available. Class 1
# (1-3 family, owner-occupied) is assessed far below market (~6%); Class 2/4
# (multifamily, commercial) are assessed much closer to market (~45%).
_ASSESSMENT_RATIO_BY_LANDUSE = {
    "01": 0.06,   # One & Two Family (Class 1)
    "02": 0.45,   # Multi-Family Walk-Up (Class 2)
    "03": 0.45,   # Multi-Family Elevator (Class 2)
    "04": 0.45,   # Mixed Residential & Commercial
    "05": 0.45,   # Commercial & Office
    "06": 0.45,   # Industrial & Manufacturing
    "07": 0.45,   # Transportation & Utility
    "08": 0.45,   # Public Facilities & Institutions
    "09": 0.45,   # Open Space & Recreation
    "10": 0.45,   # Parking Facilities
    "11": 0.45,   # Vacant Land
}
_DEFAULT_ASSESSMENT_RATIO = 0.45

_STALE_SALE_YEARS_LOW  = 5   # sale older than this -> Low confidence
_STALE_SALE_YEARS_MED  = 2   # sale older than this (but <= LOW) -> Medium confidence

# Rule-of-thumb blended NYC hard costs ($/GSF). Wide ranges exist by height,
# quality, and site conditions — these are illustrative midpoints only.
_HARD_COST_PSF_GROUND_UP  = 380.0
_HARD_COST_PSF_CONVERSION = 240.0
_SOFT_COST_PCT      = 0.20   # of hard cost
_CONTINGENCY_PCT    = 0.10   # of (hard + soft)
_CLOSING_COST_PCT   = 0.03   # of acquisition price
_EFFICIENCY_FACTOR  = 0.85   # gross buildable SF -> net sellable/rentable SF


def _sale_age_years(sale_date: str) -> float | None:
    if not sale_date:
        return None
    try:
        sale_year = int(str(sale_date)[:4])
    except (TypeError, ValueError):
        return None
    # Site Finder has no wall-clock access in some contexts (e.g. workflow
    # scripts); the UI layer stamps "today" via Python's normal datetime,
    # which is fine here since this module is called directly by Streamlit,
    # not inside a Workflow script.
    import datetime
    return max(0.0, datetime.date.today().year - sale_year)


def estimate_acquisition_cost(prop: dict) -> dict:
    """
    Estimate a preliminary acquisition cost basis for a Site Finder property.

    Waterfall (cheapest/most-certain source first):
      1. Prior recorded sale price (from Phase 2 ACRIS ownership enrichment)
      2. Neighborhood/ZIP sales comps median $/SF (from Phase 3 market data)
         x relevant SF (lot SF for vacant land, building SF otherwise)
      3. Assessed-value fallback using NYC DOF target assessment ratios

    Returns:
        {
          "estimate": float | None,
          "basis": str,              # human-readable explanation
          "method": "prior_sale" | "neighborhood_comps" | "assessed_fallback" | "unavailable",
          "confidence": "High" | "Medium" | "Low",
        }
    """
    # ── 1. Prior sale ────────────────────────────────────────────────────────
    sale_price = prop.get("last_sale_price")
    sale_date  = prop.get("last_sale_date")
    if sale_price:
        age = _sale_age_years(sale_date)
        if age is None:
            confidence = "Medium"
            basis = f"Recorded prior sale of ${sale_price:,.0f} (date unknown)"
        elif age <= _STALE_SALE_YEARS_MED:
            confidence = "High"
            basis = f"Recorded prior sale of ${sale_price:,.0f} on {sale_date} ({age:.0f} yrs ago)"
        elif age <= _STALE_SALE_YEARS_LOW:
            confidence = "Medium"
            basis = f"Recorded prior sale of ${sale_price:,.0f} on {sale_date} ({age:.0f} yrs ago) — may not reflect current market"
        else:
            confidence = "Low"
            basis = f"Recorded prior sale of ${sale_price:,.0f} on {sale_date} ({age:.0f} yrs ago) — likely stale, treat as a floor only"
        return {"estimate": float(sale_price), "basis": basis, "method": "prior_sale", "confidence": confidence}

    # ── 2. Neighborhood/ZIP comps ───────────────────────────────────────────
    mc = prop.get("market_comps")
    psf = mc.get("median_price_psf") if mc else None
    if psf:
        relevant_sf = prop.get("lot_sf", 0) if prop.get("is_vacant") else (prop.get("bldg_sf") or prop.get("lot_sf", 0))
        if relevant_sf:
            estimate = psf * relevant_sf
            basis = (
                f"${psf:,.0f}/SF neighborhood median ({mc.get('count', 0)} comps) "
                f"x {relevant_sf:,.0f} SF"
            )
            return {"estimate": estimate, "basis": basis, "method": "neighborhood_comps", "confidence": "Medium"}

    # ── 3. Assessed-value fallback ──────────────────────────────────────────
    assess_total = prop.get("assess_total")
    if assess_total:
        ratio = _ASSESSMENT_RATIO_BY_LANDUSE.get(prop.get("landuse_code", ""), _DEFAULT_ASSESSMENT_RATIO)
        estimate = assess_total / ratio
        basis = (
            f"Assessed value ${assess_total:,.0f} / ~{ratio:.0%} target assessment ratio "
            f"(rough approximation — confirm with a broker opinion of value)"
        )
        return {"estimate": estimate, "basis": basis, "method": "assessed_fallback", "confidence": "Low"}

    return {"estimate": None, "basis": "No prior sale, comps, or assessed value available", "method": "unavailable", "confidence": "Low"}


def _select_hard_cost_psf(prop: dict) -> tuple[float, str]:
    strategies = set(prop.get("strategies", []))
    if STRATEGY_CONVERSION in strategies and STRATEGY_DEMOLITION not in strategies:
        return _HARD_COST_PSF_CONVERSION, "conversion/renovation"
    return _HARD_COST_PSF_GROUND_UP, "ground-up new construction"


def build_business_plan(prop: dict) -> dict:
    """
    Build a very concise preliminary business plan / investment analysis.
    Pure arithmetic over already-collected data — no network calls, no LLM.

    Returns:
        {
          "acquisition": {...},                 # see estimate_acquisition_cost()
          "net_buildable_sf": float,
          "hard_cost_psf": float, "hard_cost_basis": str,
          "hard_cost": float, "soft_cost": float, "contingency": float,
          "closing_cost": float,
          "total_dev_cost": float,
          "revenue_psf": float | None, "revenue": float | None,
          "profit": float | None, "margin_pct": float | None,
          "bullets": list[str],
        }
    """
    acq = estimate_acquisition_cost(prop)
    acq_estimate = acq["estimate"] or 0.0

    far_max = prop.get("far_max", 0) or 0.0
    lot_sf  = prop.get("lot_sf", 0) or 0.0
    gross_buildable_sf = far_max * lot_sf
    net_buildable_sf = gross_buildable_sf * _EFFICIENCY_FACTOR

    hard_psf, hard_label = _select_hard_cost_psf(prop)
    hard_cost   = gross_buildable_sf * hard_psf
    soft_cost   = hard_cost * _SOFT_COST_PCT
    contingency = (hard_cost + soft_cost) * _CONTINGENCY_PCT
    closing_cost = acq_estimate * _CLOSING_COST_PCT

    total_dev_cost = acq_estimate + closing_cost + hard_cost + soft_cost + contingency

    mc = prop.get("market_comps")
    revenue_psf = mc.get("median_price_psf") if mc else None
    revenue = (revenue_psf * net_buildable_sf) if (revenue_psf and net_buildable_sf) else None

    profit = (revenue - total_dev_cost) if revenue is not None else None
    margin_pct = (profit / total_dev_cost * 100.0) if (profit is not None and total_dev_cost) else None

    bullets: list[str] = []
    if acq["method"] == "prior_sale":
        bullets.append(f"Acquisition basis from recorded ACRIS sale ({acq['confidence']} confidence).")
    elif acq["method"] == "neighborhood_comps":
        bullets.append("Acquisition basis estimated from neighborhood sales comps — no confirmed offer/sale.")
    elif acq["method"] == "assessed_fallback":
        bullets.append("⚠️ No sale or comps found — acquisition basis is a rough assessed-value approximation only.")
    else:
        bullets.append("⚠️ Insufficient data to estimate an acquisition basis.")

    unused_pct = prop.get("unused_far_pct", 0) or 0
    if unused_pct >= 50:
        bullets.append(f"Significant unused FAR ({unused_pct:.0f}%) suggests meaningful development upside.")
    elif unused_pct > 0:
        bullets.append(f"Modest unused FAR ({unused_pct:.0f}%) — limited as-of-right upside without a variance/rezoning.")

    if revenue is None:
        bullets.append("No neighborhood sales comps found — revenue and profit figures are not shown; treat cost figures as illustrative only.")
    elif margin_pct is not None:
        if margin_pct >= 20:
            bullets.append(f"Estimated margin of {margin_pct:.0f}% is healthy for a preliminary screen — worth deeper underwriting.")
        elif margin_pct >= 0:
            bullets.append(f"Estimated margin of {margin_pct:.0f}% is thin — economics likely need a lower basis or cost efficiency to pencil.")
        else:
            bullets.append(f"Estimated economics are currently negative ({margin_pct:.0f}% margin) at this basis and rule-of-thumb cost.")

    bullets.append(f"Hard costs assume {hard_label} at ${hard_psf:,.0f}/GSF — a blended industry rule of thumb, not a GC estimate.")

    return {
        "acquisition":       acq,
        "gross_buildable_sf": gross_buildable_sf,
        "net_buildable_sf":  net_buildable_sf,
        "hard_cost_psf":     hard_psf,
        "hard_cost_basis":   hard_label,
        "hard_cost":         hard_cost,
        "soft_cost":         soft_cost,
        "contingency":       contingency,
        "closing_cost":      closing_cost,
        "total_dev_cost":    total_dev_cost,
        "revenue_psf":       revenue_psf,
        "revenue":           revenue,
        "profit":            profit,
        "margin_pct":        margin_pct,
        "bullets":           bullets,
    }

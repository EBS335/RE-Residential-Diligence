"""
Local Law 97 Carbon-Emissions Compliance Estimator.

Zero existing scaffolding elsewhere in the app (no energy/emissions field
anywhere — PLUTO, the only per-property data source wired up before this
module, has none). Rather than fabricating an energy-use estimate from
scratch, this module applies LL97's own published, static per-occupancy-
group emissions limits (Article 320) against a property's ACTUAL reported
emissions when available (from modules.ll84_fetcher — NYC's free LL84
energy-disclosure dataset), and clearly labels the result "unknown" (not
a fabricated guess) whenever no real filing is found.

IMPORTANT — coefficient-table caveat (read before relying on this in
production): LL97_EMISSIONS_LIMITS_KGCO2E_PER_SF below is populated from
this author's recollection of LL97's published Article 320 occupancy-
group limits; this sandbox cannot reach nyc.gov to verify the exact
published figures against a live source. Confirm against DOB's official
LL97 rules (https://www.nyc.gov/site/buildings/codes/local-law-97.page)
before using this for anything beyond a rough screening signal — same
verify-before-shipping caveat already documented on this batch's other
new fetchers/tables.

Pure function, no network call, fixed-shape dict return, never raises —
same house pattern as modules/structural_risk.py / modules/deal_scorer.py.
"""

from __future__ import annotations

# Metric tons CO2e penalty per ton over the limit, per year (LL97's
# published rate — verify against nyc.gov before production use).
PENALTY_PER_TON_OVER = 268.0

# kgCO2e per sf per year, by occupancy group, two compliance periods.
# Illustrative subset of LL97's Article 320 table — verify/extend before
# production use (see module docstring caveat).
LL97_EMISSIONS_LIMITS_KGCO2E_PER_SF: dict[str, dict[str, float]] = {
    "Multifamily Residential": {"2024-2029": 4.42, "2030-2034": 3.02},
    "Office":                  {"2024-2029": 8.46, "2030-2034": 4.53},
    "Retail":                  {"2024-2029": 9.60, "2030-2034": 3.98},
    "Hotel":                   {"2024-2029": 6.11, "2030-2034": 3.24},
    "Institutional":           {"2024-2029": 6.09, "2030-2034": 4.03},
    "Industrial/Warehouse":    {"2024-2029": 4.86, "2030-2034": 2.26},
}

# Coarse PLUTO land_use/bldg_class -> LL97 occupancy-group mapping.
_LANDUSE_TO_OCCUPANCY_GROUP = {
    "Multi-Family Walk-Up": "Multifamily Residential",
    "Multi-Family Elevator": "Multifamily Residential",
    "Mixed Residential & Commercial": "Multifamily Residential",
    "Commercial & Office": "Office",
    "Industrial & Manufacturing": "Industrial/Warehouse",
    "Public Facilities & Institutions": "Institutional",
}

DEFAULT_PERIOD = "2024-2029"


def map_landuse_to_occupancy_group(land_use_label: str) -> str | None:
    """Best-effort PLUTO land_use label -> LL97 occupancy-group name.
    Never raises; returns None if no confident mapping exists (the
    caller should then let the user pick an occupancy group directly)."""
    return _LANDUSE_TO_OCCUPANCY_GROUP.get((land_use_label or "").strip())


def compute_ll97_compliance(
    bldg_area_sqft: float,
    occupancy_group: str,
    annual_emissions_tons_co2e: float | None = None,
    period: str = DEFAULT_PERIOD,
) -> dict:
    """
    Compare a building's actual (if known) or unknown emissions against
    LL97's static per-occupancy-group limit.

    Args:
        bldg_area_sqft: total building GSF (e.g. PLUTO bldg_area_sqft).
        occupancy_group: one of LL97_EMISSIONS_LIMITS_KGCO2E_PER_SF's keys.
        annual_emissions_tons_co2e: the property's actual reported annual
            emissions in metric tons CO2e (e.g. from
            modules.ll84_fetcher.fetch_ll84_emissions()'s
            total_ghg_emissions_metric_tons) — if None, the function
            still returns the applicable limit but marks compliance
            status "unknown" rather than guessing.
        period: "2024-2029" or "2030-2034".

    Returns (always this shape, never raises):
        {
          "emissions_limit_tons": float | None,
          "annual_emissions_tons_co2e": float | None,   # echoed input
          "over_limit_tons": float | None,     # None if emissions unknown
          "estimated_annual_penalty": float | None,
          "compliance_status": "compliant" | "over_limit" | "unknown — no reported emissions data",
          "occupancy_group": str,
          "period": str,
          "verified": bool,     # True only when a real emissions figure was supplied
          "error": str | None,
        }
    """
    base = {
        "emissions_limit_tons": None, "annual_emissions_tons_co2e": annual_emissions_tons_co2e,
        "over_limit_tons": None, "estimated_annual_penalty": None,
        "compliance_status": "unknown — no reported emissions data",
        "occupancy_group": occupancy_group, "period": period,
        "verified": False, "error": None,
    }
    try:
        sf = float(bldg_area_sqft or 0)
        if sf <= 0:
            return {**base, "error": "bldg_area_sqft must be positive"}

        limits = LL97_EMISSIONS_LIMITS_KGCO2E_PER_SF.get(occupancy_group)
        if not limits:
            return {**base, "error": f"unrecognized occupancy_group: {occupancy_group!r}"}
        limit_kgco2e_per_sf = limits.get(period)
        if limit_kgco2e_per_sf is None:
            return {**base, "error": f"unrecognized period: {period!r}"}

        emissions_limit_tons = round(limit_kgco2e_per_sf * sf / 1000.0, 2)  # kg -> metric tons
        result = {**base, "emissions_limit_tons": emissions_limit_tons}

        if annual_emissions_tons_co2e is None:
            return result

        actual = float(annual_emissions_tons_co2e)
        over_limit = max(0.0, actual - emissions_limit_tons)
        return {
            **result,
            "over_limit_tons": round(over_limit, 2),
            "estimated_annual_penalty": round(over_limit * PENALTY_PER_TON_OVER, 2),
            "compliance_status": "over_limit" if over_limit > 0 else "compliant",
            "verified": True,
        }
    except Exception as exc:
        return {**base, "error": str(exc)}

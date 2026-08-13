"""
Unit Mix Optimization and Revenue Modeling.

Provides:
  - Neighborhood average unit size table (SF) for NYC markets
  - Loss-factor adjusted net rentable SF calculation
  - Optimized unit mix based on target unit-type ratios
  - Revenue projection model (gross rent, EGI, NOI, cap value)

Loss factors:
  New construction:        15%  (industry standard for NYC high-rise/mid-rise)
  Residential conversion:  25%  (higher due to structural constraints / irregular floorplates)

Unit mix ratios (typical NYC market-rate rental):
  Studio 30% | 1 Bed 40% | 2 Bed 20% | 3 Bed 8% | 4+ Bed 2%

Rent multipliers by risk tier:
  LOW:  0.95× (conservative underwriting)
  MED:  1.00× (base case)
  HIGH: 1.08× (aggressive / luxury premium)

Occupancy by risk tier:
  LOW: 94%  |  MED: 92%  |  HIGH: 88%

Operating expense ratio: 35% of EGI (NYC multifamily rule-of-thumb)

Cap rates (NYC 2025 estimates):
  Manhattan:        4.50%
  Brooklyn/Queens:  5.25%
  Bronx/SI:         6.00%
"""

from __future__ import annotations
import math

# ── Unit type ordering ────────────────────────────────────────────────────────
UNIT_ORDER = ["Studio", "1 Bed", "2 Bed", "3 Bed", "4+ Bed"]

# ── Typical rental unit mix ratios ────────────────────────────────────────────
TYPICAL_MIX: dict[str, float] = {
    "Studio": 0.30,
    "1 Bed":  0.40,
    "2 Bed":  0.20,
    "3 Bed":  0.08,
    "4+ Bed": 0.02,
}

# ── Neighborhood average unit sizes (SF net) ──────────────────────────────────
# Sources: StreetEasy market reports, CoStar, RentHop, NYC HPD filings (2023–2025)
NEIGHBORHOOD_AVG_SF: dict[str, dict[str, float]] = {
    # ── Manhattan ────────────────────────────────────────────────────────────
    "Upper East Side": {
        "Studio": 480, "1 Bed": 700, "2 Bed": 1_050, "3 Bed": 1_500, "4+ Bed": 2_200,
    },
    "Upper West Side": {
        "Studio": 470, "1 Bed": 710, "2 Bed": 1_100, "3 Bed": 1_600, "4+ Bed": 2_400,
    },
    "Midtown": {
        "Studio": 420, "1 Bed": 620, "2 Bed": 950,   "3 Bed": 1_400, "4+ Bed": 2_000,
    },
    "Midtown East": {
        "Studio": 440, "1 Bed": 640, "2 Bed": 980,   "3 Bed": 1_420, "4+ Bed": 2_050,
    },
    "Midtown West": {
        "Studio": 430, "1 Bed": 630, "2 Bed": 960,   "3 Bed": 1_380, "4+ Bed": 2_000,
    },
    "Chelsea": {
        "Studio": 460, "1 Bed": 680, "2 Bed": 1_000, "3 Bed": 1_450, "4+ Bed": 2_100,
    },
    "Hell's Kitchen": {
        "Studio": 440, "1 Bed": 650, "2 Bed": 950,   "3 Bed": 1_350, "4+ Bed": 2_000,
    },
    "Greenwich Village": {
        "Studio": 490, "1 Bed": 720, "2 Bed": 1_100, "3 Bed": 1_600, "4+ Bed": 2_400,
    },
    "West Village": {
        "Studio": 520, "1 Bed": 780, "2 Bed": 1_200, "3 Bed": 1_750, "4+ Bed": 2_600,
    },
    "East Village": {
        "Studio": 450, "1 Bed": 660, "2 Bed": 980,   "3 Bed": 1_400, "4+ Bed": 2_000,
    },
    "SoHo": {
        "Studio": 550, "1 Bed": 850, "2 Bed": 1_300, "3 Bed": 1_900, "4+ Bed": 2_800,
    },
    "Tribeca": {
        "Studio": 600, "1 Bed": 950, "2 Bed": 1_500, "3 Bed": 2_200, "4+ Bed": 3_200,
    },
    "Lower East Side": {
        "Studio": 430, "1 Bed": 630, "2 Bed": 920,   "3 Bed": 1_300, "4+ Bed": 1_900,
    },
    "Financial District": {
        "Studio": 500, "1 Bed": 750, "2 Bed": 1_150, "3 Bed": 1_700, "4+ Bed": 2_500,
    },
    "Harlem": {
        "Studio": 410, "1 Bed": 600, "2 Bed": 880,   "3 Bed": 1_250, "4+ Bed": 1_850,
    },
    "East Harlem": {
        "Studio": 390, "1 Bed": 570, "2 Bed": 840,   "3 Bed": 1_200, "4+ Bed": 1_750,
    },
    "Washington Heights": {
        "Studio": 390, "1 Bed": 575, "2 Bed": 840,   "3 Bed": 1_200, "4+ Bed": 1_750,
    },
    "Inwood": {
        "Studio": 380, "1 Bed": 560, "2 Bed": 820,   "3 Bed": 1_180, "4+ Bed": 1_700,
    },
    "Morningside Heights": {
        "Studio": 420, "1 Bed": 610, "2 Bed": 890,   "3 Bed": 1_280, "4+ Bed": 1_880,
    },
    "Murray Hill": {
        "Studio": 450, "1 Bed": 660, "2 Bed": 980,   "3 Bed": 1_400, "4+ Bed": 2_050,
    },
    "Gramercy": {
        "Studio": 470, "1 Bed": 690, "2 Bed": 1_020, "3 Bed": 1_480, "4+ Bed": 2_150,
    },
    "Flatiron": {
        "Studio": 480, "1 Bed": 710, "2 Bed": 1_060, "3 Bed": 1_550, "4+ Bed": 2_250,
    },
    "NoHo": {
        "Studio": 510, "1 Bed": 780, "2 Bed": 1_200, "3 Bed": 1_750, "4+ Bed": 2_550,
    },
    "Nolita": {
        "Studio": 500, "1 Bed": 760, "2 Bed": 1_150, "3 Bed": 1_700, "4+ Bed": 2_450,
    },
    "Two Bridges": {
        "Studio": 420, "1 Bed": 620, "2 Bed": 910,   "3 Bed": 1_300, "4+ Bed": 1_900,
    },
    "Hudson Heights": {
        "Studio": 385, "1 Bed": 565, "2 Bed": 830,   "3 Bed": 1_190, "4+ Bed": 1_720,
    },

    # ── Brooklyn ─────────────────────────────────────────────────────────────
    "Williamsburg": {
        "Studio": 490, "1 Bed": 730, "2 Bed": 1_100, "3 Bed": 1_550, "4+ Bed": 2_200,
    },
    "North Williamsburg": {
        "Studio": 500, "1 Bed": 740, "2 Bed": 1_120, "3 Bed": 1_580, "4+ Bed": 2_250,
    },
    "DUMBO": {
        "Studio": 600, "1 Bed": 900, "2 Bed": 1_400, "3 Bed": 2_000, "4+ Bed": 3_000,
    },
    "Brooklyn Heights": {
        "Studio": 510, "1 Bed": 760, "2 Bed": 1_180, "3 Bed": 1_700, "4+ Bed": 2_500,
    },
    "Park Slope": {
        "Studio": 480, "1 Bed": 700, "2 Bed": 1_100, "3 Bed": 1_600, "4+ Bed": 2_400,
    },
    "Bushwick": {
        "Studio": 430, "1 Bed": 640, "2 Bed": 930,   "3 Bed": 1_300, "4+ Bed": 1_900,
    },
    "Crown Heights": {
        "Studio": 420, "1 Bed": 610, "2 Bed": 900,   "3 Bed": 1_280, "4+ Bed": 1_850,
    },
    "Greenpoint": {
        "Studio": 470, "1 Bed": 690, "2 Bed": 1_050, "3 Bed": 1_500, "4+ Bed": 2_200,
    },
    "Bed-Stuy": {
        "Studio": 400, "1 Bed": 590, "2 Bed": 870,   "3 Bed": 1_240, "4+ Bed": 1_800,
    },
    "Fort Greene": {
        "Studio": 450, "1 Bed": 670, "2 Bed": 1_000, "3 Bed": 1_450, "4+ Bed": 2_100,
    },
    "Clinton Hill": {
        "Studio": 440, "1 Bed": 655, "2 Bed": 980,   "3 Bed": 1_400, "4+ Bed": 2_050,
    },
    "Prospect Heights": {
        "Studio": 455, "1 Bed": 675, "2 Bed": 1_010, "3 Bed": 1_460, "4+ Bed": 2_120,
    },
    "Cobble Hill": {
        "Studio": 470, "1 Bed": 695, "2 Bed": 1_060, "3 Bed": 1_540, "4+ Bed": 2_250,
    },
    "Boerum Hill": {
        "Studio": 465, "1 Bed": 685, "2 Bed": 1_040, "3 Bed": 1_510, "4+ Bed": 2_200,
    },
    "Carroll Gardens": {
        "Studio": 460, "1 Bed": 680, "2 Bed": 1_030, "3 Bed": 1_490, "4+ Bed": 2_180,
    },
    "Red Hook": {
        "Studio": 430, "1 Bed": 640, "2 Bed": 945,   "3 Bed": 1_350, "4+ Bed": 1_960,
    },
    "Gowanus": {
        "Studio": 445, "1 Bed": 660, "2 Bed": 975,   "3 Bed": 1_390, "4+ Bed": 2_020,
    },
    "Flatbush": {
        "Studio": 390, "1 Bed": 570, "2 Bed": 840,   "3 Bed": 1_200, "4+ Bed": 1_740,
    },
    "Sunset Park": {
        "Studio": 370, "1 Bed": 545, "2 Bed": 800,   "3 Bed": 1_150, "4+ Bed": 1_670,
    },

    # ── Queens ───────────────────────────────────────────────────────────────
    "Astoria": {
        "Studio": 440, "1 Bed": 640, "2 Bed": 940,   "3 Bed": 1_320, "4+ Bed": 1_900,
    },
    "Long Island City": {
        "Studio": 490, "1 Bed": 720, "2 Bed": 1_080, "3 Bed": 1_560, "4+ Bed": 2_250,
    },
    "Sunnyside": {
        "Studio": 420, "1 Bed": 615, "2 Bed": 905,   "3 Bed": 1_290, "4+ Bed": 1_870,
    },
    "Jackson Heights": {
        "Studio": 390, "1 Bed": 570, "2 Bed": 840,   "3 Bed": 1_200, "4+ Bed": 1_740,
    },
    "Flushing": {
        "Studio": 380, "1 Bed": 555, "2 Bed": 820,   "3 Bed": 1_180, "4+ Bed": 1_710,
    },
    "Forest Hills": {
        "Studio": 410, "1 Bed": 600, "2 Bed": 890,   "3 Bed": 1_280, "4+ Bed": 1_860,
    },
    "Jamaica": {
        "Studio": 360, "1 Bed": 530, "2 Bed": 780,   "3 Bed": 1_120, "4+ Bed": 1_620,
    },

    # ── Bronx ────────────────────────────────────────────────────────────────
    "South Bronx": {
        "Studio": 350, "1 Bed": 515, "2 Bed": 760,   "3 Bed": 1_090, "4+ Bed": 1_580,
    },
    "Mott Haven": {
        "Studio": 360, "1 Bed": 530, "2 Bed": 780,   "3 Bed": 1_120, "4+ Bed": 1_620,
    },
    "Fordham": {
        "Studio": 340, "1 Bed": 500, "2 Bed": 740,   "3 Bed": 1_060, "4+ Bed": 1_540,
    },
    "Riverdale": {
        "Studio": 400, "1 Bed": 590, "2 Bed": 870,   "3 Bed": 1_250, "4+ Bed": 1_810,
    },

    # ── Staten Island ─────────────────────────────────────────────────────────
    "St. George": {
        "Studio": 360, "1 Bed": 530, "2 Bed": 780,   "3 Bed": 1_120, "4+ Bed": 1_620,
    },

    # ── Default (Manhattan market-rate baseline) ──────────────────────────────
    "_default": {
        "Studio": 450, "1 Bed": 650, "2 Bed": 950,   "3 Bed": 1_350, "4+ Bed": 1_800,
    },
}

# ── Loss factors ──────────────────────────────────────────────────────────────
LOSS_FACTOR_NEW        = 0.15   # New construction
LOSS_FACTOR_CONVERSION = 0.25   # Residential conversion / adaptive reuse

# ── Risk parameters ───────────────────────────────────────────────────────────
RISK_PARAMS = {
    "LOW":  {"occupancy": 0.94, "rent_multiplier": 0.95},
    "MED":  {"occupancy": 0.92, "rent_multiplier": 1.00},
    "HIGH": {"occupancy": 0.88, "rent_multiplier": 1.08},
}

OPEX_RATIO = 0.35   # Operating expenses as % of EGI

CAP_RATES = {
    "Manhattan":     0.0450,
    "Brooklyn":      0.0525,
    "Queens":        0.0525,
    "Bronx":         0.0600,
    "Staten Island": 0.0600,
}

# ── Public API ────────────────────────────────────────────────────────────────

def get_avg_sf(neighborhood: str) -> dict[str, float]:
    """
    Return average unit sizes (SF) for the given neighborhood.
    Falls back to Manhattan default if neighborhood not in table.
    """
    # Exact match
    if neighborhood in NEIGHBORHOOD_AVG_SF:
        return NEIGHBORHOOD_AVG_SF[neighborhood]
    # Case-insensitive partial match
    nl = neighborhood.lower()
    for key in NEIGHBORHOOD_AVG_SF:
        if key == "_default":
            continue
        if nl in key.lower() or key.lower() in nl:
            return NEIGHBORHOOD_AVG_SF[key]
    return NEIGHBORHOOD_AVG_SF["_default"]


def net_rentable_sf(gross_sqft: float, is_conversion: bool = False) -> float:
    """Apply loss factor to gross floor area to get net rentable SF."""
    lf = LOSS_FACTOR_CONVERSION if is_conversion else LOSS_FACTOR_NEW
    return max(0.0, gross_sqft * (1 - lf))


def optimize_unit_mix(
    net_rentable_sqft: float,
    neighborhood: str,
    mix_ratios: dict[str, float] | None = None,
) -> dict[str, dict]:
    """
    Compute optimized unit mix for a given net rentable area.

    Parameters
    ----------
    net_rentable_sqft : float
        Net rentable square footage after loss factor
    neighborhood : str
        Neighborhood name for avg SF lookup
    mix_ratios : dict, optional
        Override unit-type percentage ratios; defaults to TYPICAL_MIX

    Returns
    -------
    dict mapping unit_type → {count, avg_sf, total_sf, pct_units}
    Also includes a "_totals" key with summary figures.
    """
    if mix_ratios is None:
        mix_ratios = TYPICAL_MIX

    avg_sf  = get_avg_sf(neighborhood)
    result  = {}
    total_units = 0
    total_sf    = 0.0

    for ut in UNIT_ORDER:
        if ut not in mix_ratios:
            continue
        pct     = mix_ratios[ut]
        alloc   = net_rentable_sqft * pct          # SF allocated to this type
        asf     = avg_sf.get(ut, NEIGHBORHOOD_AVG_SF["_default"][ut])
        count   = max(0, math.floor(alloc / asf))
        used_sf = count * asf
        total_units += count
        total_sf    += used_sf
        result[ut] = {
            "count":    count,
            "avg_sf":   asf,
            "total_sf": used_sf,
            "pct_units": pct,
        }

    result["_totals"] = {
        "total_units": total_units,
        "total_sf":    total_sf,
        "net_rentable_sqft": net_rentable_sqft,
    }
    return result


def compute_revenue(
    unit_mix: dict,
    avg_rents: dict[str, float],
    risk_level: str = "MED",
    borough: str = "Manhattan",
) -> dict:
    """
    Project annual revenue and estimated cap value for a given unit mix.

    Parameters
    ----------
    unit_mix : dict
        Output of optimize_unit_mix()
    avg_rents : dict
        {unit_type: avg_monthly_rent} derived from comparable listings data
        (e.g. {"Studio": 2800, "1 Bed": 3500, ...})
    risk_level : str
        "LOW", "MED", or "HIGH" — drives occupancy and rent multiplier
    borough : str
        Used to select applicable cap rate

    Returns
    -------
    dict with financial projection metrics
    """
    params      = RISK_PARAMS.get(risk_level, RISK_PARAMS["MED"])
    occupancy   = params["occupancy"]
    rent_mult   = params["rent_multiplier"]
    cap_rate    = CAP_RATES.get(borough, CAP_RATES["Manhattan"])

    # Default rents (Manhattan medians) if comps data is missing
    _default_rents: dict[str, float] = {
        "Studio": 2_800, "1 Bed": 3_500, "2 Bed": 5_000,
        "3 Bed": 7_500,  "4+ Bed": 11_000,
    }

    gross_annual = 0.0
    line_items   = []

    for ut in UNIT_ORDER:
        if ut not in unit_mix or ut == "_totals":
            continue
        info  = unit_mix[ut]
        count = info.get("count", 0)
        if count == 0:
            continue

        base_rent = avg_rents.get(ut) or _default_rents.get(ut, 3_000)
        adj_rent  = base_rent * rent_mult
        annual    = count * adj_rent * 12
        gross_annual += annual

        line_items.append({
            "unit_type":      ut,
            "units":          count,
            "avg_sf":         info["avg_sf"],
            "monthly_rent":   round(adj_rent),
            "annual_revenue": round(annual),
        })

    egi     = gross_annual * occupancy
    opex    = egi * OPEX_RATIO
    noi     = egi - opex
    cap_val = noi / cap_rate if cap_rate > 0 else 0.0

    return {
        "line_items":        line_items,
        "gross_annual_rent": round(gross_annual),
        "occupancy_used":    occupancy,
        "egi":               round(egi),
        "opex":              round(opex),
        "noi":               round(noi),
        "cap_rate_used":     cap_rate,
        "est_cap_value":     round(cap_val),
        "risk_level":        risk_level,
        "borough":           borough,
    }


def avg_rents_from_listings(listings: list[dict]) -> dict[str, float]:
    """
    Compute average monthly rent per unit type from the scraped listings list.
    Used to feed real market data into compute_revenue().
    """
    buckets: dict[str, list[float]] = {}
    for l in listings:
        ut   = l.get("unit_type", "")
        rent = l.get("rent", 0)
        if ut and rent and rent > 0:
            buckets.setdefault(ut, []).append(rent)
    return {ut: sum(rents) / len(rents) for ut, rents in buckets.items()}


def reconcile_comps(
    rent_psf_annual_values: list[float],
    sale_psf_values: list[float],
    occupancy: float = 0.93,
) -> dict | None:
    """
    Combine already-fetched rental and sales comps into an implied cap
    rate and gross rent multiplier (GRM) — a Property Analysis tab
    "Comps Reconciliation" panel otherwise has to compute by hand from two
    unconnected comp tabs.

    Uses MEDIAN $/SF from each side (not building-to-building matching,
    since rental and sales comps are typically different specific
    properties) and OPEX_RATIO for the NOI approximation, consistent with
    compute_revenue()'s assumptions elsewhere in this module.

    Args:
        rent_psf_annual_values: list of ANNUAL rent $/SF (e.g. monthly
            rent * 12 / sqft per rental comp).
        sale_psf_values: list of sale $/SF per sales comp.
        occupancy: stabilized occupancy assumption for the NOI approximation.

    Returns None if either list is empty (nothing to reconcile). Otherwise:
        {
          "ann_rent_psf": float,      # median annual rent $/SF
          "sale_psf": float,          # median sale $/SF
          "grm": float,               # sale_psf / ann_rent_psf
          "noi_psf": float,           # ann_rent_psf * (1-OPEX_RATIO) * occupancy
          "cap_rate_pct": float,      # noi_psf / sale_psf * 100
          "rent_comp_count": int,
          "sale_comp_count": int,
        }
    """
    if not rent_psf_annual_values or not sale_psf_values:
        return None

    def _median(vals: list[float]) -> float:
        s = sorted(vals)
        n = len(s)
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0

    ann_rent_psf = _median(rent_psf_annual_values)
    sale_psf = _median(sale_psf_values)
    grm = (sale_psf / ann_rent_psf) if ann_rent_psf > 0 else None
    noi_psf = ann_rent_psf * (1 - OPEX_RATIO) * occupancy
    cap_rate_pct = (noi_psf / sale_psf * 100.0) if sale_psf > 0 else None

    return {
        "ann_rent_psf": ann_rent_psf,
        "sale_psf": sale_psf,
        "grm": grm,
        "noi_psf": noi_psf,
        "cap_rate_pct": cap_rate_pct,
        "rent_comp_count": len(rent_psf_annual_values),
        "sale_comp_count": len(sale_psf_values),
    }

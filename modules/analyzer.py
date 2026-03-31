"""
Analysis module — per-unit-type rent statistics and market insights.
"""

import pandas as pd
import numpy as np

UNIT_ORDER = ["Studio", "1 Bed", "2 Bed", "3 Bed", "4+ Bed"]

HIGH_DEMAND_HOODS = {
    "SoHo", "Tribeca", "West Village", "Greenwich Village", "NoHo", "Nolita",
    "Lower East Side", "East Village", "Chelsea", "Flatiron", "Gramercy",
    "Murray Hill", "Kips Bay", "Midtown", "Midtown East", "Midtown West",
    "Upper East Side", "Upper West Side", "Financial District",
    "Battery Park City", "Williamsburg", "Greenpoint", "DUMBO",
    "Brooklyn Heights", "Park Slope", "Cobble Hill", "Boerum Hill",
    "Long Island City", "Astoria", "Hunters Point",
}


# ---------------------------------------------------------------------------
# Summary statistics
# ---------------------------------------------------------------------------

def compute_summary(listings: list) -> pd.DataFrame:
    """
    Return a DataFrame with one row per unit type found in listings.
    Columns (display + raw):
      Unit Type | # Listings | Avg Rent | Median Rent | Min Rent | Max Rent |
      Rent Range | Avg $/SF  |  _avg _median _min _max _count (floats for charts)
    """
    if not listings:
        return pd.DataFrame()

    df = pd.DataFrame(listings)
    rows = []

    for utype in UNIT_ORDER:
        grp = df[df["unit_type"] == utype]
        if grp.empty:
            continue

        rents = grp["rent"]
        avg   = rents.mean()
        med   = rents.median()
        lo    = rents.min()
        hi    = rents.max()
        cnt   = len(grp)

        # $/SF — only when ≥3 listings have sqft
        avg_psf = None
        sqft_grp = grp.dropna(subset=["sqft"])
        sqft_grp = sqft_grp[sqft_grp["sqft"] > 0]
        if len(sqft_grp) >= 3:
            avg_psf = (sqft_grp["rent"] / sqft_grp["sqft"]).mean()

        rows.append({
            "Unit Type":   utype,
            "# Listings":  cnt,
            "Avg Rent":    f"${avg:,.0f}",
            "Median Rent": f"${med:,.0f}",
            "Min Rent":    f"${lo:,.0f}",
            "Max Rent":    f"${hi:,.0f}",
            "Rent Range":  f"${lo:,.0f} – ${hi:,.0f}",
            "Avg $/SF":    f"${avg_psf:.2f}" if avg_psf else "N/A",
            # raw floats used by charts
            "_avg":    avg,
            "_median": med,
            "_min":    lo,
            "_max":    hi,
            "_count":  cnt,
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Market insight bullets
# ---------------------------------------------------------------------------

def compute_insights(listings: list, geo: dict, radius_miles: float) -> list[str]:
    """Return 3–5 insight bullet strings (may contain markdown bold)."""
    if not listings:
        return ["No listings found — try expanding the search radius or verify your API keys."]

    df          = pd.DataFrame(listings)
    hood        = geo.get("neighborhood") or geo.get("borough") or "this area"
    borough     = geo.get("borough") or "NYC"
    total       = len(df)
    sources     = ", ".join(sorted(df["source"].unique()))
    bullets: list[str] = []

    # 1. Coverage
    bullets.append(
        f"**Coverage:** {total} active listing{'s' if total != 1 else ''} found within "
        f"**{radius_miles:.2f} mi** of the subject address in **{hood}** ({borough}), "
        f"sourced from {sources}."
    )

    # 2. Supply mix
    counts  = df["unit_type"].value_counts()
    dom     = counts.idxmax()
    dom_pct = counts.max() / total * 100
    bullets.append(
        f"**Supply mix:** **{dom}** units dominate available inventory "
        f"({dom_pct:.0f}% of comps), indicating the most common product type "
        f"in this submarket."
    )

    # 3. Pricing level
    med_all = df["rent"].median()
    avg_all = df["rent"].mean()
    skew    = (avg_all - med_all) / med_all * 100
    skew_desc = (
        "upward-skewed — luxury outliers are pulling the average above the median"
        if skew > 10 else
        "downward-skewed — affordable units are pulling the average below the median"
        if skew < -10 else
        "well-balanced — average and median are closely aligned"
    )
    bullets.append(
        f"**Pricing level:** Area-wide median is **${med_all:,.0f}/mo** "
        f"(avg ${avg_all:,.0f}/mo). The distribution is {skew_desc}."
    )

    # 4. Price spread / market competition
    cv = df["rent"].std() / df["rent"].mean() * 100
    spread_desc = (
        "highly stratified — wide price tiers suggest both value and luxury product coexist"
        if cv > 30 else
        "moderately competitive"
        if cv > 15 else
        "tightly clustered — limited pricing differentiation; amenity/finish quality is the key differentiator"
    )
    rent_spread = df["rent"].max() - df["rent"].min()
    bullets.append(
        f"**Market spread:** ${rent_spread:,.0f} range across all listings "
        f"(CV {cv:.0f}%) — market is {spread_desc}."
    )

    # 5a. $/SF benchmark if available
    sqft_df = df.dropna(subset=["sqft"])
    sqft_df = sqft_df[sqft_df["sqft"] > 0]
    if len(sqft_df) >= 5:
        psf = (sqft_df["rent"] / sqft_df["sqft"]).median()
        bullets.append(
            f"**Rent/SF:** Median effective rent is **${psf:.2f}/SF/mo** "
            f"(based on {len(sqft_df)} listings with reported square footage) — "
            f"a key underwriting benchmark for this submarket."
        )
    else:
        # 5b. Fallback — high-demand signal
        is_hd = hood in HIGH_DEMAND_HOODS or borough == "Manhattan"
        bullets.append(
            f"**Location signal:** {hood} is {'a **high-demand** NYC submarket with strong rent fundamentals' if is_hd else 'a growing NYC submarket'}. "
            f"{'Expect landlord pricing power and limited concessions.' if is_hd else 'Monitor pipeline supply that could affect future rent growth.'}"
        )

    return bullets[:5]

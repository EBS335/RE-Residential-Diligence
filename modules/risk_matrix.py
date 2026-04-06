"""
NYC Real Estate Investment Risk Matrix.

Provides:
  - MACRO_RISKS: 6 city/market-level risk factors applicable to all NYC deals
  - MICRO_RISKS: neighborhood-specific risks keyed by neighborhood name
  - get_micro_risks(): lookup with borough-level fallback

Each risk entry:
    category    : str  — short category label
    description : str  — what the risk is
    probability : str  — "Low" | "Med" | "High"
    impact      : str  — "Low" | "Med" | "High"
    mitigation  : str  — actionable mitigation strategy
"""

from __future__ import annotations

# ── Macro Risks (city / market-wide) ─────────────────────────────────────────
MACRO_RISKS: list[dict] = [
    {
        "category":    "Interest Rates",
        "description": (
            "Elevated Fed Funds rate increases construction loan costs, permanent debt service, "
            "and cap rate expansion — compressing valuations and returns."
        ),
        "probability": "Med",
        "impact":      "High",
        "mitigation":  (
            "Lock in fixed-rate construction and take-out financing early; size the deal at 7%+ "
            "stabilized cap rate stress test; maintain a 12–18 month interest reserve."
        ),
    },
    {
        "category":    "Rent Regulation / Housing Policy",
        "description": (
            "NYC HSTPA (2019) eliminated most deregulation paths. Further Good Cause Eviction "
            "expansion or new preferential rent changes could cap rent growth on market-rate units."
        ),
        "probability": "Med",
        "impact":      "High",
        "mitigation":  (
            "Target free-market units in buildings below 6-unit threshold, or new construction "
            "exempt for 30+ years; include retail/commercial component for income diversification."
        ),
    },
    {
        "category":    "Construction Cost Inflation",
        "description": (
            "NYC hard costs average $350–$650+/SF; material and labor inflation has run 5–8%/yr. "
            "Cost overruns are the #1 reason NYC development deals fail."
        ),
        "probability": "High",
        "impact":      "High",
        "mitigation":  (
            "Execute a Guaranteed Maximum Price (GMP) contract; buy out major subcontracts early; "
            "carry 10–15% hard cost contingency; include a separate soft cost contingency of 8%."
        ),
    },
    {
        "category":    "ULURP / Discretionary Approval Delays",
        "description": (
            "Any discretionary approval (special permit, variance, rezoning) triggers a 7–18 month "
            "public review. Community Board opposition can add further delays or conditions."
        ),
        "probability": "Low-Med",
        "impact":      "High",
        "mitigation":  (
            "Design as-of-right wherever possible; engage the Community Board and local Council "
            "Member early if special approvals are needed; budget 24-month carry in pro forma."
        ),
    },
    {
        "category":    "Capital Markets / Lender Appetite",
        "description": (
            "Regional bank stress and CRE lending pullbacks since 2022 have reduced available "
            "construction financing. NYC multifamily remains favored but terms are tighter."
        ),
        "probability": "Med",
        "impact":      "High",
        "mitigation":  (
            "Secure a construction financing commitment (not just a term sheet) before closing on "
            "land; maintain 35–40% equity to qualify for multiple lenders; explore CDFI and "
            "public subsidy debt stacking (421-a/485-x successor programs)."
        ),
    },
    {
        "category":    "Absorption / Lease-Up Risk",
        "description": (
            "Pipeline of new luxury units in many NYC submarkets is elevated in 2024–2026, "
            "potentially extending stabilization timelines and increasing concession costs."
        ),
        "probability": "Med",
        "impact":      "Med",
        "mitigation":  (
            "Phase delivery to match absorption pace; budget 1–2 months free rent per unit in "
            "lease-up proforma; implement a pre-leasing program 6 months before TCO."
        ),
    },
]


# ── Micro Risks (neighborhood-specific) ──────────────────────────────────────
_MICRO: dict[str, list[dict]] = {

    # ── Manhattan ──────────────────────────────────────────────────────────
    "Midtown": [
        {"category": "Commercial Vacancy Adjacency", "probability": "High", "impact": "Med",
         "description": "Post-COVID office vacancy in surrounding blocks can suppress street activity and retail rents.",
         "mitigation": "Target residential over activated ground-floor uses (F&B, fitness, medical)."},
        {"category": "Transit Congestion Pricing", "probability": "High", "impact": "Low",
         "description": "Manhattan Congestion Pricing zone may deter car-dependent residents.",
         "mitigation": "Market to transit-oriented tenants; emphasize proximity to Penn/GCT."},
        {"category": "Flood Zone (Zone AE)", "probability": "Med", "impact": "High",
         "description": "Portions of Midtown West/Hell's Kitchen are in FEMA AE flood zone; insurance costs rising.",
         "mitigation": "Elevate MEP above BFE; obtain NFIP policy and private flood rider."},
        {"category": "Noise / Light Pollution", "probability": "High", "impact": "Low",
         "description": "Midtown density creates persistent noise (traffic, construction) that reduces residential desirability.",
         "mitigation": "Specify triple-pane windows; orient quiet bedrooms away from avenues."},
    ],
    "Upper East Side": [
        {"category": "Luxury Market Saturation", "probability": "Med", "impact": "Med",
         "description": "High-end UES market is competitive; new condo inventory competes with rentals.",
         "mitigation": "Differentiate with amenities and finishes; price at 95% of luxury comp."},
        {"category": "Aging Demographic", "probability": "Low", "impact": "Low",
         "description": "UES skews older; may limit pool of young professional renters.",
         "mitigation": "Include co-working, fitness, and pet amenities to attract younger tenants."},
        {"category": "Landmarked Block Restrictions", "probability": "Med", "impact": "High",
         "description": "Historic districts (Carnegie Hill, Metropolitan Museum) limit façade changes.",
         "mitigation": "File LPC application early; retain preservation architect; build compliance costs into budget."},
    ],
    "Upper West Side": [
        {"category": "Community Board Opposition", "probability": "Med", "impact": "Med",
         "description": "CB7 historically vocal on new development; may push for affordability conditions.",
         "mitigation": "Proactively offer CBP or MIH units; engage CB and local stakeholders early."},
        {"category": "Prewar Building Conversion Risk", "probability": "High", "impact": "High",
         "description": "Many UWS buildings are prewar with irregular floorplates, adding conversion cost.",
         "mitigation": "Budget 25% loss factor; detailed structural/MEP survey before land close."},
    ],
    "Chelsea": [
        {"category": "High Line Noise / Construction", "probability": "Med", "impact": "Low",
         "description": "Ongoing development along Hudson Yards / High Line corridor creates noise.",
         "mitigation": "Stage project around neighboring construction timelines."},
        {"category": "Gallery/Commercial Shift", "probability": "Med", "impact": "Med",
         "description": "Gallery district migration may reduce foot traffic on lower-block locations.",
         "mitigation": "Activate ground floor with food/beverage rather than art-dependent retail."},
    ],
    "Hell's Kitchen": [
        {"category": "Noise (Penn District / Javits)", "probability": "High", "impact": "Med",
         "description": "Events at MSG, Javits, and Hudson Yards create periodic traffic and noise surges.",
         "mitigation": "Enhanced soundproofing; highlight commuter convenience as marketing asset."},
        {"category": "Zoning / Special District", "probability": "Med", "impact": "Med",
         "description": "Clinton Special District and Theater Subdistrict have use and FAR restrictions.",
         "mitigation": "Confirm as-of-right compliance with DCP before land close."},
    ],
    "Harlem": [
        {"category": "Displacement Sensitivity", "probability": "High", "impact": "Med",
         "description": "Community groups actively monitor gentrification; may trigger protests or political action.",
         "mitigation": "Include 20–25% affordable units (MIH Option 1 or 2); engage LISC/ANHD."},
        {"category": "Rent-Stabilized Portfolio Risk", "probability": "High", "impact": "High",
         "description": "Existing RS buildings in portfolio cannot be deregulated; NOI growth is capped.",
         "mitigation": "Underwrite to flat rent growth (0–1%/yr) on RS units; explore 421-a/485-x eligibility."},
        {"category": "School Quality Concerns", "probability": "Med", "impact": "Med",
         "description": "Below-average school ratings may deter family-oriented renters.",
         "mitigation": "Market toward young professionals and empty nesters; emphasize transit access."},
    ],
    "Lower East Side": [
        {"category": "Nightlife Noise", "probability": "High", "impact": "Med",
         "description": "Dense bar/club district generates late-night noise complaints; high tenant turnover.",
         "mitigation": "High-STC windows and mechanical ventilation; set rents slightly below premium to maintain occupancy."},
        {"category": "Flood Zone (Zone AE)", "probability": "High", "impact": "High",
         "description": "LES was severely impacted by Superstorm Sandy; large portions in FEMA AE.",
         "mitigation": "Elevate MEP; NFIP + private flood policy; resilient ground floor design."},
    ],
    "Financial District": [
        {"category": "Weekend Quietness", "probability": "High", "impact": "Low",
         "description": "FiDi becomes quiet on weekends; amenities and retail are limited outside business hours.",
         "mitigation": "Emphasize proximity to Seaport, Battery Park; include resident amenities."},
        {"category": "Flood Zone (Zone AE / X)", "probability": "High", "impact": "High",
         "description": "Lower Manhattan coastline is in FEMA AE; future sea level rise adds long-term risk.",
         "mitigation": "Flood-resilient ground floor; elevate critical systems; review NYC FloodHelpNY maps."},
    ],
    "Washington Heights": [
        {"category": "Income Sensitivity", "probability": "Med", "impact": "Med",
         "description": "Median household income lower than midtown; rent growth may be constrained.",
         "mitigation": "Target affordable / moderate-income housing programs; 421-a/485-x eligible."},
        {"category": "Infrastructure / MTA Reliability", "probability": "Med", "impact": "Med",
         "description": "A/C train is the primary transit link; service disruptions affect desirability.",
         "mitigation": "Market proximity to express stop as asset; include parking if lot allows."},
    ],

    # ── Brooklyn ───────────────────────────────────────────────────────────
    "Williamsburg": [
        {"category": "Industrial Adjacency / Superfund", "probability": "Med", "impact": "High",
         "description": "Portions of South Williamsburg near former industrial sites; Newtown Creek Superfund site.",
         "mitigation": "Phase I/II ESA before land close; avoid Phase I sites without remediation plan."},
        {"category": "L Train Dependency", "probability": "Low", "impact": "Med",
         "description": "L train is primary transit; future closures or reduced service could impact rental demand.",
         "mitigation": "Highlight J/M/Z bus access as secondary transit; market to remote workers."},
        {"category": "Nightlife Oversaturation", "probability": "Med", "impact": "Low",
         "description": "North Williamsburg bar scene generates noise; may limit family-oriented demand.",
         "mitigation": "Target 25–40 demographic; set rents at market to attract desired tenant profile."},
        {"category": "Supply Pipeline", "probability": "High", "impact": "Med",
         "description": "Large pipeline of new luxury rental units in Williamsburg / LIC corridor.",
         "mitigation": "Differentiate on design or location; offer 1 month free for early signers."},
    ],
    "Bushwick": [
        {"category": "Gentrification Resistance", "probability": "High", "impact": "Med",
         "description": "Active tenant/community organizing; may trigger political opposition to large luxury projects.",
         "mitigation": "Include MIH affordable component; engage CB4 early in design process."},
        {"category": "Industrial Noise / Zoning Mix", "probability": "Med", "impact": "Med",
         "description": "M-zoned parcels adjacent to residential create noise and odor complaints.",
         "mitigation": "Sound buffer design; confirm M→R rezoning timeline; review DEP violation history."},
    ],
    "Crown Heights": [
        {"category": "Tenant Displacement Sensitivity", "probability": "High", "impact": "Med",
         "description": "Long-standing community with active tenant advocates monitoring new development.",
         "mitigation": "Include affordable component; engage CHNC and local stakeholders proactively."},
        {"category": "School Access", "probability": "Med", "impact": "Med",
         "description": "Variable school ratings may limit family demand in parts of Crown Heights.",
         "mitigation": "Target young-professional segment; consider proximity to Prospect Park as amenity."},
    ],
    "Park Slope": [
        {"category": "High Land Cost / Compressed Yields", "probability": "High", "impact": "High",
         "description": "Premium land pricing in Park Slope compresses development yield vs. outer areas.",
         "mitigation": "Underwrite to tight 4.75–5.25% yield; target condo-exit rather than long-term hold."},
        {"category": "Historic District Restrictions", "probability": "Med", "impact": "Med",
         "description": "Large portions of Park Slope are in LPC historic districts limiting new construction.",
         "mitigation": "Confirm site is outside HD boundary; if adjacent, engage preservation consultant."},
    ],
    "DUMBO": [
        {"category": "Market Depth / Liquidity", "probability": "Med", "impact": "High",
         "description": "DUMBO ultra-luxury market is thin; absorption can be slow for large unit counts.",
         "mitigation": "Limit unit count to ≤ 80; consider condo conversion to reduce lease-up risk."},
        {"category": "Flood Zone", "probability": "High", "impact": "High",
         "description": "DUMBO waterfront is in FEMA AE flood zone; insurance costs and mortgage constraints apply.",
         "mitigation": "Elevate base 2 ft above BFE; NFIP + private flood; buyer/tenant disclosure."},
    ],
    "Greenpoint": [
        {"category": "Greenpoint Landing Pipeline", "probability": "High", "impact": "Med",
         "description": "Greenpoint Landing megadevelopment (5,500+ units) will deliver 2024–2030.",
         "mitigation": "Underwrite 6–12 month extended lease-up; differentiate on boutique scale and design."},
        {"category": "Superfund Proximity", "probability": "Med", "impact": "High",
         "description": "Newtown Creek Superfund site borders Greenpoint; some parcels have soil contamination.",
         "mitigation": "Phase I/II ESA mandatory; avoid sites within 500 ft of creek without clean bill."},
    ],

    # ── Queens ─────────────────────────────────────────────────────────────
    "Astoria": [
        {"category": "Airport Noise", "probability": "Med", "impact": "Med",
         "description": "LaGuardia flight paths affect parts of Astoria; noise levels vary by block.",
         "mitigation": "Confirm flight path on FAA charts; specify STC-40+ windows on affected façades."},
        {"category": "Limited Luxury Pipeline", "probability": "Low", "impact": "Low",
         "description": "Astoria has limited luxury rental comp base; appraisals may lag actual rents.",
         "mitigation": "Document all comps with signed leases; engage appraiser with Queens market expertise."},
    ],
    "Long Island City": [
        {"category": "Large Supply Pipeline", "probability": "High", "impact": "High",
         "description": "LIC has one of NYC's largest new apartment pipelines (20,000+ units); rent growth is muted.",
         "mitigation": "Underwrite flat rent growth for 3 years; ensure project differentiates on amenities."},
        {"category": "Flood Zone", "probability": "High", "impact": "High",
         "description": "Portions of LIC waterfront are in FEMA AE; Superstorm Sandy caused major damage.",
         "mitigation": "Raise ground floor 3 ft above BFE; resilient MEP design; comprehensive flood insurance."},
    ],

    # ── Bronx ─────────────────────────────────────────────────────────────
    "Mott Haven": [
        {"category": "Infrastructure / Blight Adjacency", "probability": "Med", "impact": "Med",
         "description": "Rapid development adjacent to underinvested blocks creates uneven streetscape.",
         "mitigation": "Activate ground floor; participate in local BID improvement efforts."},
        {"category": "Asthma Alley Pollution", "probability": "High", "impact": "Med",
         "description": "South Bronx has among NYC's highest asthma rates due to truck traffic and industry.",
         "mitigation": "Enhanced HVAC filtration (MERV-13+); green rooftop; avoid ground-floor openings on major truck routes."},
    ],

    # ── Borough fallbacks ─────────────────────────────────────────────────
    "_manhattan_default": [
        {"category": "Regulatory / Zoning Risk", "probability": "Med", "impact": "Med",
         "description": "Manhattan zoning is complex; special districts and overlays may restrict as-of-right development.",
         "mitigation": "Confirm zoning compliance with DCP pre-application meeting before land close."},
        {"category": "High Land + Construction Costs", "probability": "High", "impact": "High",
         "description": "Manhattan hard costs ($500–$800/SF) and land leave thin margins; stressed scenarios can invert.",
         "mitigation": "Model downside at -15% rents and +10% costs; require 12%+ IRR hurdle in base case."},
    ],
    "_brooklyn_default": [
        {"category": "Rent Growth Moderation", "probability": "Med", "impact": "Med",
         "description": "Brooklyn rent growth has moderated from 2021 peaks; underwriting optimism requires scrutiny.",
         "mitigation": "Use current in-place rents from verified comps; flat growth for first 2 years."},
        {"category": "Infrastructure Gaps", "probability": "Med", "impact": "Low",
         "description": "Some Brooklyn submarkets lack transit connectivity or basic retail amenities.",
         "mitigation": "Confirm walk score and transit access before underwriting premium rents."},
    ],
    "_queens_default": [
        {"category": "Transit Access Variability", "probability": "Med", "impact": "Med",
         "description": "Queens transit access varies widely; poor-transit locations limit rent potential.",
         "mitigation": "Only underwrite high rents for locations within 0.25 mi of subway."},
    ],
    "_bronx_default": [
        {"category": "Income Constraints", "probability": "High", "impact": "Med",
         "description": "Bronx median income limits affordable rent achievable; market-rate projects may face lease-up issues.",
         "mitigation": "Structure as affordable or mixed-income with subsidy (HOME, LIHTC, 485-x)."},
    ],
    "_si_default": [
        {"category": "Car Dependency", "probability": "High", "impact": "Med",
         "description": "Staten Island is highly car-dependent; walkability and transit access are limited.",
         "mitigation": "Provide adequate parking; focus on waterfront / North Shore ferry-accessible locations."},
    ],
}

# ── Borough fallback key mapping ──────────────────────────────────────────────
_BOROUGH_FALLBACK = {
    "Manhattan":     "_manhattan_default",
    "Brooklyn":      "_brooklyn_default",
    "Queens":        "_queens_default",
    "Bronx":         "_bronx_default",
    "Staten Island": "_si_default",
}


# ── Public API ────────────────────────────────────────────────────────────────

def get_micro_risks(neighborhood: str, borough: str = "Manhattan") -> list[dict]:
    """
    Return neighborhood-specific micro risk factors.

    Tries exact match, then case-insensitive partial match,
    then falls back to borough-level risks.
    """
    # Exact match
    if neighborhood in _MICRO:
        return _MICRO[neighborhood]

    # Case-insensitive partial match
    nl = neighborhood.lower()
    for key in _MICRO:
        if key.startswith("_"):
            continue
        if nl in key.lower() or key.lower() in nl:
            return _MICRO[key]

    # Borough fallback
    fb_key = _BOROUGH_FALLBACK.get(borough)
    if fb_key and fb_key in _MICRO:
        return _MICRO[fb_key]

    # Ultimate fallback — generic Manhattan risks
    return _MICRO.get("_manhattan_default", [])

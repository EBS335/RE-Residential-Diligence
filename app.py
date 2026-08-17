"""
Real Estate Development & Investment Analytics
NYC development diligence platform: deal sourcing, rental comps, zoning, ACRIS, massing scenarios, risk analysis.
"""

import os
import re
import time
import requests
import streamlit as st
import folium
from folium.plugins import MiniMap
from streamlit_folium import st_folium
from dotenv import load_dotenv
import pandas as pd
import plotly.graph_objects as go

from modules.data_fetcher import (
    fetch_all_listings,
    fetch_tax_abatement_signal,
    fetch_rent_stabilization_signal,
    fetch_transit_proximity,
    fetch_demographics,
)
from modules.app_logging import init_logging, get_logger, record_source_status
from modules.analyzer import compute_summary, compute_insights
from modules.visualizer import build_map, build_bar_chart, build_range_chart, ESRI_SATELLITE_TILES, ESRI_SATELLITE_ATTR
from modules.zola_fetcher import fetch_zoning_info
from modules.zoning_rules import get_zoning_rules, get_zoning_citations, SPECIAL_DISTRICTS, COMMERCIAL_OVERLAYS, get_special_district_info, estimate_entitlement_path, classify_street_type
from modules.cityrealty_fetcher import fetch_cityrealty_comps
from modules.pip_fetcher import (
    fetch_property_history,
    _extract_sales_from_acris,
    _extract_mortgages_from_acris,
    _extract_liens_from_acris,
)
from modules.massing_viz import build_massing_options, floor_plate_fig, build_floor_stack, _calc_massing
from modules.massing_feasibility import compute_massing_feasibility_score
from modules.comps_research import search_competing_devs, generate_pipeline_summary
from modules.neighborhood_fetcher import fetch_neighborhood_data
from modules.acris_fetcher import fetch_acris
from modules.articles_fetcher import fetch_nearby_articles
from modules.ecb_fetcher import fetch_ecb_violations
from modules.deal_scorer import compute_deal_score
from modules.site_sourcing import compute_opportunity_score
from modules.rent_stab_registry import check_rent_stabilized
from modules.oath_fetcher import fetch_oath_hearings
from modules.tax_lien_fetcher import fetch_tax_lien_status
from modules.lpc_landmarks_fetcher import fetch_lpc_landmark_status, fetch_lpc_designation_status
from modules.ceqr_fetcher import fetch_ulurp_applications
from modules.distress_scorer import compute_composite_distress_score, DEFAULT_WEIGHTS
from modules.structural_risk import compute_structural_vintage_risk, recommend_structural_system
from modules.risk_scorecard import compute_composite_risk_scorecard
from modules.unit_mix import (
    get_avg_sf, optimize_unit_mix, compute_revenue,
    avg_rents_from_listings, NEIGHBORHOOD_AVG_SF, net_rentable_sf, OPEX_RATIO,
    reconcile_comps,
)
from modules.risk_matrix import MACRO_RISKS, get_micro_risks

load_dotenv()
init_logging()


# ── AI market summary helper ──────────────────────────────────────────────────

def _generate_ai_summary(
    comp_type: str,
    summary_data: dict,
    sample_listings: list,
    api_key: str,
) -> str:
    """Call Claude to generate a 3-5 sentence market summary for a comps section."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        prompt = (
            f"You are a NYC real estate investment analyst. Write a concise 3-5 sentence "
            f"market summary for {comp_type} comparables based on this data.\n\n"
            f"Summary statistics: {summary_data}\n\n"
            f"Sample listings (up to 5): {sample_listings[:5]}\n\n"
            f"Focus on: rent/price levels, market trends, supply-demand signals, "
            f"and key investment implications. Be specific about numbers."
        )
        msg = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text
    except ImportError:
        return "Install the `anthropic` package to enable AI summaries: `pip install anthropic`"
    except Exception as exc:
        return f"AI summary unavailable: {exc}"


# ── Section header helper ─────────────────────────────────────────────────────

def _section_header(icon: str, title: str, subtitle: str = "") -> None:
    """Render a consistent section divider + labeled header."""
    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    st.markdown(
        f'<div class="section-title">{icon} {title}</div>'
        + (f'<div class="section-subtitle">{subtitle}</div>' if subtitle else ""),
        unsafe_allow_html=True,
    )


def _status_chip(label: str, is_positive: bool) -> None:
    """A compact, deliberately-styled yes/no status indicator — used for
    binary checks (landmark status, historic district, rent stabilization)
    so a "No"/"Not found" result reads as a clear, calm status the same
    way a "Yes" result reads as a flag, instead of unstyled plain text."""
    cls = "opportunity-flag" if is_positive else "status-clear"
    st.markdown(f'<div class="{cls}">{label}</div>', unsafe_allow_html=True)


# ── Lot adjacency helper ──────────────────────────────────────────────────────

def _is_adjacent(bbl_a: str, bbl_b: str) -> bool:
    """Return True if two BBLs are on the same block (same borough + block digits)."""
    a = re.sub(r"\D", "", str(bbl_a))
    b = re.sub(r"\D", "", str(bbl_b))
    return len(a) == 10 and len(b) == 10 and a[:6] == b[:6]


# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Real Estate Development & Investment Analytics",
    page_icon="🏙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Styling ───────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:wght@600;700&family=Inter:wght@400;500;600;700;800&display=swap');

:root {
    --bg-page:      #F7F4EC;
    --bg-card:      #FFFFFF;
    --bg-card-alt:  #FCFAF3;
    --bg-raised:    #F1EDE0;
    --border:       #DCD5C2;
    --border-soft:  #E8E3D4;
    --text-primary: #1A1D2E;
    --text-body:    #3D4152;
    --text-muted:   #6B7280;
    --text-faint:   #9CA3AF;
    --accent:       #A6842C;
    --accent-strong:#8B6914;
    --accent-amber: #A6842C;
    --success-fg:   #1F6B3A;
    --success-bg:   #E6F0E5;
    --warn-fg:      #8B6914;
    --warn-bg:      #F5EBD3;
    --danger-fg:    #7A2E2E;
    --danger-bg:    #F3E1DE;
    --info-fg:      #2A3E63;
    --info-bg:      #E4E8F1;
    --chrome-dark:  #12131C;
    --chrome-dark2: #1A1D2E;
    --serif: 'Source Serif 4', Georgia, 'Times New Roman', serif;
}

/* ── Global ── */
html, body, [data-testid="stAppViewContainer"] {
    background-color: var(--bg-page);
    font-family: 'Inter', sans-serif;
}
[data-testid="stHeader"] { background-color: transparent; }
[data-testid="stMetricValue"] {
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.3px;
    color: var(--text-primary);
}
[data-testid="stMetricLabel"] {
    color: var(--text-muted) !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-size: 0.7rem !important;
}

/* ── Header banner ── */
.app-header {
    background: linear-gradient(135deg, var(--chrome-dark) 0%, var(--chrome-dark2) 55%, #232840 100%);
    border: 1px solid #2A2E42;
    border-bottom: 3px solid var(--accent);
    border-radius: 6px;
    padding: 32px 36px 28px;
    margin-bottom: 28px;
    color: #F5F1E6;
    box-shadow: 0 12px 28px rgba(26,29,46,0.16);
}
.app-header h1 {
    margin: 0 0 6px;
    font-size: 2.05rem;
    font-weight: 700;
    letter-spacing: -0.3px;
    font-family: var(--serif);
    color: #FAF8F2;
}
.app-header p {
    margin: 0;
    font-size: 0.92rem;
    color: #C9C2AE;
    max-width: 560px;
    line-height: 1.5;
}

/* ── Section headers ── */
.section-label {
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--text-muted);
    margin-bottom: 10px;
}

/* ── Info card (geocoding result) ── */
.geo-card {
    background: var(--bg-card);
    border-radius: 10px;
    border: 1px solid var(--border);
    padding: 20px 24px;
    margin-top: 20px;
    box-shadow: 0 1px 3px rgba(26,29,46,0.06), 0 1px 2px rgba(26,29,46,0.04);
}
.geo-card-title {
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--text-muted);
    margin-bottom: 14px;
}
.geo-row {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
}
.geo-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: rgba(166,132,44,0.09);
    color: var(--accent-strong);
    border: 1px solid rgba(166,132,44,0.24);
    border-radius: 20px;
    padding: 6px 14px;
    font-size: 0.83rem;
    font-weight: 600;
}
.geo-chip-label {
    color: var(--text-muted);
    font-weight: 400;
    font-size: 0.78rem;
}
.geo-address {
    font-size: 1.05rem;
    font-weight: 700;
    color: var(--text-primary);
    margin-bottom: 12px;
}
.geo-coords {
    font-size: 0.78rem;
    color: var(--text-faint);
    font-family: monospace;
    margin-top: 10px;
}
.geo-source {
    font-size: 0.72rem;
    color: var(--text-faint);
    margin-top: 6px;
}

/* ── Status badges ── */
.badge-live    { background:var(--success-bg); color:var(--success-fg); padding:3px 10px; border-radius:20px; font-size:0.75rem; font-weight:700; }
.badge-partial { background:var(--warn-bg); color:var(--warn-fg); padding:3px 10px; border-radius:20px; font-size:0.75rem; font-weight:700; }
.badge-error   { background:var(--danger-bg); color:var(--danger-fg); padding:3px 10px; border-radius:20px; font-size:0.75rem; font-weight:700; }

/* ── Filter tags ── */
.filter-summary {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 18px;
    margin-top: 16px;
    font-size: 0.84rem;
    color: var(--text-body);
    line-height: 1.7;
    box-shadow: 0 1px 3px rgba(26,29,46,0.05);
}
.filter-tag {
    display: inline-block;
    background: rgba(166,132,44,0.09);
    color: var(--accent-strong);
    border-radius: 6px;
    padding: 1px 8px;
    font-size: 0.78rem;
    font-weight: 600;
    margin: 0 2px;
}

/* ── Sidebar tweaks ── */
[data-testid="stSidebar"] > div:first-child {
    background: var(--chrome-dark);
    padding-top: 24px;
    border-right: 1px solid var(--accent);
}
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stMarkdown,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span {
    color: #C9C2AE !important;
}
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
    color: #FAF8F2 !important;
    font-family: var(--serif);
}

/* ── Next-step callout ── */
.next-step {
    background: var(--warn-bg);
    border: 1px solid rgba(139,105,20,0.25);
    border-radius: 10px;
    padding: 14px 18px;
    margin-top: 20px;
    font-size: 0.84rem;
    color: var(--warn-fg);
}

/* ── Data freshness pill ── */
.pill-live    { background:var(--success-bg); color:var(--success-fg); padding:4px 12px; border-radius:20px;
                font-size:0.74rem; font-weight:700; display:inline-block; }
.pill-partial { background:var(--warn-bg); color:var(--warn-fg); padding:4px 12px; border-radius:20px;
                font-size:0.74rem; font-weight:700; display:inline-block; }
.pill-cached  { background:var(--info-bg); color:var(--info-fg); padding:4px 12px; border-radius:20px;
                font-size:0.74rem; font-weight:700; display:inline-block; }
.pill-error   { background:var(--danger-bg); color:var(--danger-fg); padding:4px 12px; border-radius:20px;
                font-size:0.74rem; font-weight:700; display:inline-block; }

/* ── Photo gallery (legacy grid) ── */
.photo-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
    margin-bottom: 12px;
    box-shadow: 0 1px 3px rgba(26,29,46,0.05);
}
.photo-card img {
    width: 100%;
    height: 170px;
    object-fit: cover;
    display: block;
}
.photo-caption {
    padding: 8px 10px;
    font-size: 0.78rem;
    color: var(--text-body);
    line-height: 1.35;
}
.photo-caption b { color: var(--text-primary); }

/* ── Photo carousel (horizontal scroll) ── */
.gallery-scroll-row {
    display: flex;
    flex-direction: row;
    gap: 12px;
    overflow-x: auto;
    padding: 4px 0 12px 0;
    scroll-behavior: smooth;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: thin;
    scrollbar-color: var(--border) transparent;
}
.gallery-scroll-row::-webkit-scrollbar { height: 5px; }
.gallery-scroll-row::-webkit-scrollbar-track { background: transparent; }
.gallery-scroll-row::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
.gallery-card {
    flex: 0 0 190px;
    min-width: 190px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
    text-decoration: none;
    color: inherit;
    transition: box-shadow 0.15s, transform 0.15s, border-color 0.15s;
    display: block;
    box-shadow: 0 1px 3px rgba(26,29,46,0.05);
}
.gallery-card:hover {
    box-shadow: 0 6px 18px rgba(166,132,44,0.16);
    border-color: rgba(166,132,44,0.35);
    transform: translateY(-2px);
}
.gallery-card img {
    width: 100%;
    height: 130px;
    object-fit: cover;
    display: block;
}
.gallery-card .gc-caption {
    padding: 8px 10px 10px;
    font-size: 0.76rem;
    color: var(--text-body);
    line-height: 1.35;
}
.gallery-card .gc-caption b { color: var(--text-primary); font-size: 0.82rem; }
.gallery-card .gc-badge {
    display: inline-block;
    background: rgba(166,132,44,0.09);
    color: var(--accent-strong);
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 0.68rem;
    font-weight: 700;
    margin-top: 4px;
}

/* ── Risk badges ── */
.risk-low  { background:var(--success-bg); color:var(--success-fg); padding:2px 9px; border-radius:20px; font-size:0.72rem; font-weight:700; }
.risk-med  { background:var(--warn-bg); color:var(--warn-fg); padding:2px 9px; border-radius:20px; font-size:0.72rem; font-weight:700; }
.risk-high { background:var(--danger-bg); color:var(--danger-fg); padding:2px 9px; border-radius:20px; font-size:0.72rem; font-weight:700; }

/* ── Massing tile ── */
.massing-tile {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 12px;
    margin-bottom: 10px;
    box-shadow: 0 1px 3px rgba(26,29,46,0.05);
}

/* ── Risk matrix table ── */
.risk-table { width:100%; border-collapse:collapse; font-size:0.80rem; }
.risk-table th { background:var(--bg-raised); color:var(--text-muted); font-weight:700; padding:8px 10px;
                 text-align:left; border-bottom:2px solid var(--border); }
.risk-table td { padding:8px 10px; border-bottom:1px solid var(--border-soft); color:var(--text-body); vertical-align:top; }
.risk-table tr:last-child td { border-bottom:none; }
.prob-low  { color:var(--success-fg); font-weight:700; }
.prob-med  { color:var(--warn-fg); font-weight:700; }
.prob-high { color:var(--danger-fg); font-weight:700; }

/* ── Borough comparison table ── */
.bcomp-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.83rem;
}
.bcomp-table th {
    background: var(--bg-raised);
    color: var(--text-muted);
    font-weight: 700;
    padding: 8px 12px;
    text-align: left;
    border-bottom: 1px solid var(--border);
}
.bcomp-table td {
    padding: 8px 12px;
    border-bottom: 1px solid var(--border-soft);
    color: var(--text-body);
}
.bcomp-table tr:last-child td { border-bottom: none; }
.bcomp-above { color: var(--danger-fg); font-weight: 700; }
.bcomp-below { color: var(--success-fg); font-weight: 700; }
.bcomp-at    { color: var(--text-muted); font-weight: 600; }

/* ── Source card ── */
.source-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px 20px;
    margin-bottom: 10px;
    box-shadow: 0 1px 3px rgba(26,29,46,0.05);
}
.source-name { font-weight: 700; color: var(--text-primary); font-size: 0.9rem; }
.source-desc { color: var(--text-muted); font-size: 0.80rem; margin-top: 3px; line-height: 1.4; }
.source-link { font-size: 0.78rem; margin-top: 5px; }
.source-link a { color: var(--accent-strong); font-weight: 600; text-decoration: none; }

/* ── Neighborhood context banner ── */
.hood-banner {
    background: linear-gradient(90deg, rgba(166,132,44,0.08) 0%, rgba(31,107,58,0.05) 100%);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 18px;
    margin-bottom: 16px;
    display: flex;
    gap: 20px;
    flex-wrap: wrap;
    align-items: center;
}
.hood-stat { text-align: center; min-width: 80px; }
.hood-stat-val { font-size: 1.1rem; font-weight: 800; color: var(--accent-strong); }
.hood-stat-lbl { font-size: 0.70rem; color: var(--text-muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; }
/* ── Scraping status panel ────────────────────────────────────────────── */
.scrape-status-panel { background:var(--bg-card); border:1px solid var(--border); border-radius:10px;
    padding:14px 18px; margin-top:10px; margin-bottom:6px; box-shadow: 0 1px 3px rgba(26,29,46,0.05); }
.scrape-status-panel table { width:100%; border-collapse:collapse; font-size:0.82rem; }
.scrape-status-panel th { background:var(--bg-raised); color:var(--text-muted); font-weight:700;
    padding:6px 10px; text-align:left; border-bottom:1px solid var(--border);
    font-size:0.74rem; text-transform:uppercase; letter-spacing:0.06em; }
.scrape-status-panel td { padding:6px 10px; border-bottom:1px solid var(--border-soft);
    color:var(--text-body); vertical-align:middle; }
.scrape-status-panel tr:last-child td { border-bottom:none; }
.scrape-count-badge { background:var(--bg-raised); color:var(--text-body); border-radius:12px;
    padding:2px 9px; font-size:0.77rem; font-weight:700; font-family:monospace; }

/* ── Section dividers ── */
.section-divider {
    border: none;
    border-top: 1px solid var(--border);
    margin: 32px 0 24px;
}
.section-title {
    font-family: var(--serif);
    font-size: 1.2rem;
    font-weight: 700;
    color: var(--text-primary);
    letter-spacing: -0.2px;
    margin-bottom: 4px;
}
.section-subtitle {
    font-size: 0.86rem;
    color: var(--text-muted);
    margin-bottom: 18px;
}

/* ── Deal score gauge ── */
.deal-score-num {
    font-size: 3.2rem;
    font-weight: 900;
    line-height: 1;
    margin-bottom: 4px;
    font-variant-numeric: tabular-nums;
    color: var(--text-primary);
}
.deal-tier-badge {
    display: inline-block;
    border-radius: 20px;
    padding: 4px 16px;
    font-size: 0.85rem;
    font-weight: 700;
    margin-bottom: 12px;
}
.distress-low    { background:var(--success-bg); color:var(--success-fg); border-radius:20px; padding:3px 12px; font-size:0.82rem; font-weight:700; }
.distress-medium { background:var(--warn-bg); color:var(--warn-fg); border-radius:20px; padding:3px 12px; font-size:0.82rem; font-weight:700; }
.distress-high   { background:var(--danger-bg); color:var(--danger-fg); border-radius:20px; padding:3px 12px; font-size:0.82rem; font-weight:700; }
.opportunity-flag {
    background: var(--success-bg);
    border: 1px solid rgba(31,107,58,0.25);
    border-radius: 10px;
    padding: 12px 16px;
    color: var(--success-fg);
    font-weight: 600;
    font-size: 0.9rem;
    margin-bottom: 12px;
}
.status-clear {
    background: #F1F2F4;
    border: 1px solid rgba(107,114,128,0.25);
    border-radius: 10px;
    padding: 12px 16px;
    color: #6B7280;
    font-weight: 600;
    font-size: 0.9rem;
    margin-bottom: 12px;
}
</style>
""", unsafe_allow_html=True)

# ═════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═════════════════════════════════════════════════════════════════════════════

RADIUS_OPTIONS = {
    "5 blocks  (~0.25 mi)":  0.25,
    "10 blocks (~0.50 mi)":  0.50,
    "15 blocks (~0.75 mi)":  0.75,
    "20 blocks (~1.00 mi)":  1.00,
    "25 blocks (~1.25 mi)":  1.25,
    "30 blocks (~1.50 mi)":  1.50,
    "35 blocks (~1.75 mi)":  1.75,
    "40 blocks (~2.00 mi)":  2.00,
}

UNIT_TYPES = ["Studio", "1 Bed", "2 Bed", "3 Bed", "4+ Bed"]

RENTAL_TYPES = ["Market-rate", "Luxury / Premium", "All (no filter)"]

NYC_BOUNDS = dict(lat_min=40.4774, lat_max=40.9176, lon_min=-74.2591, lon_max=-73.7004)

# Canonical borough names used by Google Maps / OSM
BOROUGH_ALIASES = {
    "manhattan": "Manhattan",
    "new york":  "Manhattan",
    "brooklyn":  "Brooklyn",
    "kings":     "Brooklyn",
    "queens":    "Queens",
    "bronx":     "Bronx",
    "the bronx": "Bronx",
    "staten island": "Staten Island",
    "richmond":  "Staten Island",
}

HIGH_DEMAND = {
    "SoHo", "Tribeca", "West Village", "Greenwich Village", "NoHo", "Nolita",
    "Lower East Side", "East Village", "Chelsea", "Flatiron", "Gramercy",
    "Murray Hill", "Kips Bay", "Midtown", "Midtown East", "Midtown West",
    "Upper East Side", "Upper West Side", "Morningside Heights",
    "Financial District", "Battery Park City",
    "Williamsburg", "Greenpoint", "DUMBO", "Brooklyn Heights",
    "Park Slope", "Cobble Hill", "Boerum Hill", "Carroll Gardens",
    "Long Island City", "Astoria", "Hunters Point",
}

TRANSIT_HUBS = {
    "Midtown", "Times Square", "Grand Central", "Penn Station Area",
    "Herald Square", "Union Square", "Columbus Circle", "Fulton Street",
    "Atlantic Avenue", "Jay Street", "Long Island City", "Jackson Heights",
    "Jamaica", "Flushing",
}

# ── 2024/2025 NYC borough median rents (published market benchmarks) ──────────
# Source: StreetEasy / Zillow / NYC Rent Guidelines Board Q4 2024
BOROUGH_BENCHMARKS = {
    "Manhattan":   {"Studio": 2_950, "1 Bed": 4_100, "2 Bed": 5_500, "3 Bed": 7_200, "4+ Bed": 9_800},
    "Brooklyn":    {"Studio": 2_400, "1 Bed": 3_100, "2 Bed": 4_100, "3 Bed": 5_200, "4+ Bed": 6_900},
    "Queens":      {"Studio": 1_950, "1 Bed": 2_550, "2 Bed": 3_200, "3 Bed": 4_100, "4+ Bed": 5_200},
    "Bronx":       {"Studio": 1_600, "1 Bed": 2_000, "2 Bed": 2_600, "3 Bed": 3_200, "4+ Bed": 4_100},
    "Staten Island": {"Studio": 1_575, "1 Bed": 1_875, "2 Bed": 2_375, "3 Bed": 2_950, "4+ Bed": 3_700},
}


# ═════════════════════════════════════════════════════════════════════════════
# GEOCODING
# ═════════════════════════════════════════════════════════════════════════════

_NOM_HEADERS = {
    "User-Agent": "NYC-Rent-Comp-Analyzer/1.0 (real-estate-diligence-tool)",
    "Accept-Language": "en-US,en;q=0.9",
}
# Loose NYC bounds — includes a small buffer around all five boroughs
_NYC_BOUNDS = dict(lat_min=40.45, lat_max=40.95, lon_min=-74.30, lon_max=-73.65)

NYC_TERMS = ("new york", "nyc", "brooklyn", "manhattan",
             "queens", "bronx", "staten island", ", ny", " ny ")


def _normalize_borough(text: str) -> str | None:
    if not text:
        return None
    t = text.lower().strip()
    for key, val in BOROUGH_ALIASES.items():
        if key in t:
            return val
    return None


def _in_nyc(lat: float, lon: float) -> bool:
    b = _NYC_BOUNDS
    return b["lat_min"] <= lat <= b["lat_max"] and b["lon_min"] <= lon <= b["lon_max"]


_BBL_BOROUGH_NAMES = {
    "1": "Manhattan", "2": "Bronx", "3": "Brooklyn", "4": "Queens", "5": "Staten Island",
}


def _map_zinfo_to_portfolio_schema(zinfo: dict, address: str, lat: float, lon: float) -> dict:
    """
    Adapt zola_fetcher.fetch_zoning_info()'s dict (single-address flow,
    used by the Property Analysis tab) into the same normalized property
    shape modules/property_search.py._normalize_row() produces (bulk Site
    Finder flow), so a property saved from either tab renders identically
    in the Portfolio comparison view. The two source dicts use different
    field names and zinfo's numeric fields are pre-formatted display
    strings (e.g. "$500,000", "2.00"), not raw floats — parsed back out here.
    """
    def _num(v, default=0.0):
        try:
            if v is None:
                return default
            s = str(v).strip().replace("$", "").replace(",", "")
            if s in ("", "—", "-"):
                return default
            return float(s)
        except (TypeError, ValueError):
            return default

    zinfo = zinfo or {}
    far_res = _num(zinfo.get("far_residential"))
    far_comm = _num(zinfo.get("far_commercial"))
    far_built = _num(zinfo.get("far_built"))
    far_max = max(far_res, far_comm)
    unused_far = max(0.0, far_max - far_built)

    return {
        "bbl":              zinfo.get("bbl", ""),
        "address":          address or zinfo.get("matched_label", ""),
        "borough":          _BBL_BOROUGH_NAMES.get(zinfo.get("borough_code", ""), ""),
        "zip_code":         zinfo.get("zip_code", ""),
        "owner":            zinfo.get("owner", ""),
        "lot_sf":           _num(zinfo.get("lot_area_sqft")),
        "bldg_sf":          _num(zinfo.get("bldg_area_sqft")),
        "year_built":       zinfo.get("year_built", ""),
        "units_res":        _num(zinfo.get("units_res")),
        "far_built":        far_built,
        "far_residential":  far_res,
        "far_commercial":   far_comm,
        "far_max":          far_max,
        "unused_far":       unused_far,
        "unused_far_pct":   (unused_far / far_max * 100.0) if far_max > 0 else 0.0,
        "assess_land":      _num(zinfo.get("assess_land")),
        "assess_total":     _num(zinfo.get("assess_total")),
        "exempt_land":      _num(zinfo.get("exempt_land")),
        "exempt_total":     _num(zinfo.get("exempt_total")),
        "historic_dist":    zinfo.get("historic_dist", ""),
        "latitude":         lat,
        "longitude":        lon,
        "zoning_dist":      zinfo.get("zoning_dist", ""),
    }


def _parse_nom_result(result: dict) -> dict:
    addr          = result.get("address", {})
    city_district = addr.get("city_district") or addr.get("suburb") or ""
    borough = (
        _normalize_borough(addr.get("borough", ""))
        or _normalize_borough(city_district)
        or _normalize_borough(addr.get("city", ""))
        or _normalize_borough(addr.get("county", ""))
    )
    neighborhood = (
        addr.get("neighbourhood")
        or addr.get("quarter")
        or (city_district if city_district else None)
    )
    return {
        "lat":               float(result["lat"]),
        "lon":               float(result["lon"]),
        "formatted_address": result.get("display_name", ""),
        "borough":           borough,
        "neighborhood":      neighborhood,
        "zip_code":          addr.get("postcode", ""),
        "geocoder":          "OpenStreetMap / Nominatim",
    }


# ── Geocoding: Nominatim ──────────────────────────────────────────────────────

def _geocode_nominatim(address: str) -> dict | None:
    """
    Direct HTTP call to Nominatim.  No bounded= constraint — we rely
    on _in_nyc() to filter results so the query isn't artificially
    restricted and can resolve any valid NYC street address.
    """
    has_nyc = any(t in address.lower() for t in NYC_TERMS)

    queries = (
        [address, f"{address}, New York, NY"]
        if has_nyc else
        [
            f"{address}, New York City, NY",
            f"{address}, Manhattan, NY",
            f"{address}, Brooklyn, NY",
            f"{address}, Queens, NY",
            f"{address}, Bronx, NY",
            f"{address}, Staten Island, NY",
            f"{address}, New York, NY",
        ]
    )

    for query in queries:
        try:
            resp = requests.get(
                "https://nominatim.openstreetmap.org/search",
                headers=_NOM_HEADERS,
                params={
                    "q":              query,
                    "format":         "jsonv2",
                    "addressdetails": "1",
                    "limit":          "5",
                    "countrycodes":   "us",
                    # NOTE: no bounded/viewbox — rely on _in_nyc() instead
                },
                timeout=12,
            )
            if resp.status_code == 429:
                time.sleep(2)
                continue
            if not resp.ok:
                continue
            for r in resp.json():
                lat = float(r.get("lat", 0))
                lon = float(r.get("lon", 0))
                if _in_nyc(lat, lon):
                    return _parse_nom_result(r)
            time.sleep(0.4)
        except Exception:
            time.sleep(0.4)

    return None


# ── Geocoding: Photon (Komoot, OSM-based, no key) ────────────────────────────

def _geocode_photon(address: str) -> dict | None:
    """Photon geocoding API — fast, reliable, OSM-backed, no API key needed."""
    has_nyc = any(t in address.lower() for t in NYC_TERMS)
    query   = address if has_nyc else f"{address}, New York, NY"

    try:
        resp = requests.get(
            "https://photon.komoot.io/api/",
            headers={"User-Agent": "NYC-Rent-Comp-Analyzer/1.0"},
            params={"q": query, "limit": 5, "lang": "en"},
            timeout=10,
        )
        if not resp.ok:
            return None

        for f in resp.json().get("features", []):
            props  = f.get("properties", {})
            coords = f.get("geometry", {}).get("coordinates", [])
            if len(coords) < 2:
                continue
            lon, lat = float(coords[0]), float(coords[1])
            if not _in_nyc(lat, lon):
                continue
            # Verify it's actually in New York state
            if props.get("state") not in ("New York", "NY", None):
                continue

            city     = props.get("city", "")
            district = props.get("district", "") or props.get("suburb", "")
            borough  = (
                _normalize_borough(city)
                or _normalize_borough(district)
                or _normalize_borough(props.get("county", ""))
            )
            neighborhood = district or city or None

            parts = [p for p in [
                props.get("housenumber", ""),
                props.get("street", ""),
                district or city,
                props.get("postcode", ""),
            ] if p]
            formatted = ", ".join(parts) if parts else query

            return {
                "lat":               lat,
                "lon":               lon,
                "formatted_address": formatted,
                "borough":           borough,
                "neighborhood":      neighborhood,
                "zip_code":          props.get("postcode", ""),
                "geocoder":          "Photon / OSM",
            }
    except Exception:
        pass

    return None


# ── Geocoding: Google Maps ────────────────────────────────────────────────────

def _geocode_google(address: str, api_key: str) -> dict | None:
    try:
        r = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": address, "key": api_key, "components": "country:US"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("status") != "OK" or not data.get("results"):
            return None

        result   = data["results"][0]
        loc      = result["geometry"]["location"]
        lat, lon = loc["lat"], loc["lng"]
        if not _in_nyc(lat, lon):
            return None

        borough = neighborhood = zip_code = None
        for c in result.get("address_components", []):
            types = c["types"]
            name  = c["long_name"]
            if "neighborhood" in types and not neighborhood:
                neighborhood = name
            if ("sublocality_level_1" in types or "sublocality" in types) and not borough:
                borough = _normalize_borough(name)
            if "postal_code" in types:
                zip_code = name
        if not borough:
            for c in result.get("address_components", []):
                b = _normalize_borough(c["long_name"])
                if b:
                    borough = b
                    break

        return {
            "lat":               lat,
            "lon":               lon,
            "formatted_address": result.get("formatted_address", address),
            "borough":           borough,
            "neighborhood":      neighborhood,
            "zip_code":          zip_code,
            "geocoder":          "Google Maps",
        }
    except Exception:
        return None


# ── Orchestrator ──────────────────────────────────────────────────────────────

def geocode_address(address: str, google_key: str | None = None) -> tuple[dict | None, str]:
    """
    Try Google → Nominatim → Photon.
    Uses st.session_state as cache so failed results are NEVER cached
    (unlike @st.cache_data which would lock out an address on any transient error).
    """
    clean = address.strip()
    cache_key = f"_geo_{clean.lower()}"

    # Return cached success from this session
    if cache_key in st.session_state:
        return st.session_state[cache_key], "cached"

    # 1. Google Maps (most accurate, requires key)
    if google_key and google_key.strip():
        result = _geocode_google(clean, google_key.strip())
        if result:
            st.session_state[cache_key] = result
            return result, "live"

    # 2. Nominatim (free, no key)
    result = _geocode_nominatim(clean)
    if result:
        st.session_state[cache_key] = result
        return result, "live"

    # 3. Photon (free, no key — independent OSM-based service)
    result = _geocode_photon(clean)
    if result:
        st.session_state[cache_key] = result
        return result, "live"

    return None, "error"


# ═════════════════════════════════════════════════════════════════════════════
# MAP HELPER
# ═════════════════════════════════════════════════════════════════════════════

def build_subject_map(
    lat: float,
    lon: float,
    radius_miles: float,
    label: str,
    borough: str,
    neighborhood: str,
) -> folium.Map:
    """
    Build a zoomable Folium map centred on the subject property.
    Shows the address pin, search-radius ring, and a mini-map inset.
    Zoom level scales with radius so the full ring is always visible.
    """
    # Pick zoom level so the radius circle fits comfortably
    if radius_miles <= 0.10:
        zoom = 17
    elif radius_miles <= 0.15:
        zoom = 16
    elif radius_miles <= 0.25:
        zoom = 16
    elif radius_miles <= 0.50:
        zoom = 15
    elif radius_miles <= 1.0:
        zoom = 14
    else:
        zoom = 13

    m = folium.Map(
        location=[lat, lon],
        zoom_start=zoom,
        tiles="CartoDB positron",
        control_scale=True,
    )

    # ── Tile layer switcher ───────────────────────────────────────────────────
    folium.TileLayer(
        tiles="CartoDB dark_matter",
        name="Dark",
        attr="CartoDB",
    ).add_to(m)
    folium.TileLayer(
        tiles="OpenStreetMap",
        name="Street Map",
        attr="OpenStreetMap",
    ).add_to(m)
    folium.TileLayer(
        tiles=ESRI_SATELLITE_TILES,
        name="Satellite",
        attr=ESRI_SATELLITE_ATTR,
    ).add_to(m)
    folium.LayerControl(position="topright", collapsed=True).add_to(m)

    # ── Search radius ring ────────────────────────────────────────────────────
    folium.Circle(
        location=[lat, lon],
        radius=radius_miles * 1609.34,   # miles → metres
        color="#8B6914",
        weight=2,
        dash_array="6 4",
        fill=True,
        fill_color="#8B6914",
        fill_opacity=0.06,
        tooltip=f"Search radius: {radius_miles:.2f} mi",
    ).add_to(m)

    # Solid inner dot to mark the exact centre
    folium.CircleMarker(
        location=[lat, lon],
        radius=5,
        color="#8B6914",
        fill=True,
        fill_color="#8B6914",
        fill_opacity=0.9,
        weight=2,
    ).add_to(m)

    # ── Subject property pin ──────────────────────────────────────────────────
    hood_line = f"<br/><span style='color:#6B7280'>{neighborhood}</span>" if neighborhood and neighborhood != "—" else ""
    borough_line = f" · {borough}" if borough and borough != "—" else ""

    popup_html = f"""
    <div style="font-family:sans-serif;min-width:200px;padding:4px">
      <b style="font-size:1rem;color:#1A1D2E">📍 Subject Property</b>
      {hood_line}{borough_line}
      <hr style="margin:8px 0;border-color:#DCD5C2"/>
      <span style="font-size:0.82rem;color:#3D4152">{label}</span><br/>
      <span style="font-size:0.75rem;color:#9CA3AF;font-family:monospace">
        {lat:.6f}, {lon:.6f}
      </span><br/>
      <span style="font-size:0.75rem;color:#8B6914;font-weight:600">
        Radius: {radius_miles:.2f} mi
      </span>
    </div>
    """

    folium.Marker(
        location=[lat, lon],
        popup=folium.Popup(popup_html, max_width=260),
        tooltip="<b>Subject Property</b> — click for details",
        icon=folium.Icon(
            color="darkblue",
            icon="building",
            prefix="fa",
        ),
    ).add_to(m)

    # ── Mini-map inset ────────────────────────────────────────────────────────
    MiniMap(
        tile_layer="CartoDB positron",
        position="bottomright",
        width=140,
        height=100,
        collapsed_width=20,
        collapsed_height=20,
        zoom_level_offset=-6,
        toggle_display=True,
    ).add_to(m)

    return m


# ═════════════════════════════════════════════════════════════════════════════
# SIDEBAR  —  API keys + quick help
# ═════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("## 🔑 API Keys")
    st.caption("Keys are used only in this session — never stored.")

    google_key = st.text_input(
        "Google Maps API Key",
        value=os.getenv("GOOGLE_MAPS_API_KEY", ""),
        type="password",
        help="Enables the most accurate address geocoding. "
             "Falls back to OpenStreetMap if omitted.",
    )
    scraping_key = st.text_input(
        "ScrapingBee API Key  *(recommended)*",
        value=os.getenv("SCRAPINGBEE_KEY", ""),
        type="password",
        help=(
            "Routes scraping through residential proxies — the most reliable fix "
            "when StreetEasy / Apartments.com are blocked on cloud IPs. "
            "Free tier: 1,000 credits/month at scrapingbee.com."
        ),
    )

    anthropic_key = st.text_input(
        "Anthropic API Key *(AI Summaries)*",
        value=os.getenv("ANTHROPIC_API_KEY", ""),
        type="password",
        help="Optional. Enables AI-generated market summaries in each comps section. "
             "Get a key at console.anthropic.com.",
    )

    st.divider()
    st.markdown("### 📖 How to use")
    st.caption(
        "**No API keys needed** — the app scrapes 5 sources directly "
        "(StreetEasy, Apartments.com, Craigslist, Zumper, RentHop).\n\n"
        "Add a **ScrapingBee** key (free tier available) to route requests "
        "through residential proxies — this bypasses Cloudflare blocks that "
        "affect cloud-hosted apps."
    )
    st.divider()
    st.markdown("### 🔗 Get API keys")
    st.markdown(
        "- [ScrapingBee](https://scrapingbee.com) *(free tier — recommended)*\n"
        "- [Google Maps Platform](https://console.cloud.google.com) *(optional)*"
    )

    st.divider()
    with st.expander("🩺 Data Health", expanded=False):
        _health = st.session_state.get("_source_health", {})
        if not _health:
            st.caption("No data sources queried yet this session.")
        else:
            for _src_name, _info in _health.items():
                _icon = "🟢" if _info["ok"] else "🔴"
                st.markdown(
                    f"{_icon} **{_src_name}** — {_info['detail'] or 'OK'}  \n"
                    f"<span style='font-size:0.7rem;color:#9CA3AF'>{_info['ts']}</span>",
                    unsafe_allow_html=True,
                )
        from modules.app_logging import get_recent_logs
        _recent_logs = get_recent_logs()
        if _recent_logs:
            st.text_area("Recent log lines", value="\n".join(_recent_logs[-30:]), height=150, disabled=True)


# ═════════════════════════════════════════════════════════════════════════════
# HEADER
# ═════════════════════════════════════════════════════════════════════════════

st.markdown("""
<div class="app-header">
  <h1>🏗️ Real Estate Development &amp; Investment Analytics</h1>
  <p>
    Full-stack NYC development diligence
  </p>
</div>
""", unsafe_allow_html=True)

# ═════════════════════════════════════════════════════════════════════════════
# TOP-LEVEL TABS — Property Analysis (existing) vs. Site Finder (new)
# ═════════════════════════════════════════════════════════════════════════════

tab_sitefinder, tab_property, tab_portfolio = st.tabs(
    ["🔍 Site Finder", "🏢 Property Analysis", "📁 Portfolio"]
)

with tab_property:
    # ── Address autocomplete (additive — lives OUTSIDE the form below, since
    # a form's widgets only rerun on submit, but a live-typeahead suggestion
    # list needs a rerun on every keystroke). Purely assistive: it only ever
    # pre-fills the existing text field below; the existing type-and-submit
    # flow, and the Google→Nominatim→Photon geocode cascade it triggers, are
    # completely unchanged either way — this doesn't call fetch_zoning_info()
    # or set st.session_state["geo"] itself, so there's no new path around
    # the fetch/cache guard fixed earlier this session.
    _ac_query = st.text_input(
        "🔎 Address lookup (optional — start typing for suggestions)",
        key="_addr_autocomplete_query",
        placeholder="Start typing an NYC address…",
    )
    if _ac_query and len(_ac_query.strip()) >= 3:
        _ac_cache_key = f"_ac_suggest_{_ac_query.strip().lower()}"
        if _ac_cache_key not in st.session_state:
            from modules.zola_fetcher import geosearch_autocomplete
            st.session_state[_ac_cache_key] = geosearch_autocomplete(_ac_query.strip())
        _ac_suggestions = st.session_state.get(_ac_cache_key, [])
        if _ac_suggestions:
            _ac_cols = st.columns(min(3, len(_ac_suggestions)))
            for _ac_i, _ac_s in enumerate(_ac_suggestions):
                with _ac_cols[_ac_i % len(_ac_cols)]:
                    if st.button(_ac_s["label"][:45], key=f"_ac_btn_{_ac_cache_key}_{_ac_i}", use_container_width=True):
                        st.session_state["address_input_field"] = _ac_s["label"]
                        st.rerun()
        # If the call failed or found nothing, the suggestion row just
        # doesn't appear — the type-and-submit flow below is unaffected.

    # ═════════════════════════════════════════════════════════════════════════════
    # INPUT FORM
    # ═════════════════════════════════════════════════════════════════════════════

    with st.form("search_form", border=False):
        # ── Address ──────────────────────────────────────────────────────────────
        st.markdown('<div class="section-label">📍 Subject Property Address</div>',
                    unsafe_allow_html=True)
        address_input = st.text_input(
            label="address",
            label_visibility="collapsed",
            placeholder="e.g.  250 W 55th St, New York, NY  ·  123 Atlantic Ave, Brooklyn, NY 11201",
            help="Enter any valid NYC street address including borough or ZIP code.",
            key="address_input_field",
        )

        st.markdown("<br/>", unsafe_allow_html=True)

        # ── Radius ───────────────────────────────────────────────────────────────
        st.markdown('<div class="section-label">📏 Search Radius</div>',
                    unsafe_allow_html=True)
        radius_choice = st.selectbox(
            label="radius",
            label_visibility="collapsed",
            options=list(RADIUS_OPTIONS.keys()),
            index=0,   # default: 5 blocks
        )

        radius_miles = RADIUS_OPTIONS[radius_choice]

        st.markdown("<br/>", unsafe_allow_html=True)

        submitted = st.form_submit_button(
            "🔎  Geocode Address & Preview Search",
            type="primary",
            use_container_width=True,
        )


    # ═════════════════════════════════════════════════════════════════════════════
    # GEOCODING + RESULT DISPLAY
    # ═════════════════════════════════════════════════════════════════════════════

    if submitted:
        if not address_input.strip():
            st.warning("Please enter a NYC address before searching.")
            st.stop()

        with st.spinner("📍 Geocoding address…"):
            geo, geo_status = geocode_address(
                address_input.strip(),
                google_key=google_key.strip() or None,
            )

        # ── Error state ──────────────────────────────────────────────────────────
        if not geo:
            st.error(
                "Could not geocode this address within NYC. "
                "Check that you've included a NYC borough or ZIP code, then try again.\n\n"
                "**Tip:** Try adding *', New York, NY'* or a ZIP code to the end."
            )
            st.stop()

        # ── Persist result in session state ─────────────────────────────────────
        st.session_state["geo"]           = geo
        st.session_state["radius_miles"]  = radius_miles
        st.session_state["radius_choice"] = radius_choice
        st.session_state["address_raw"]   = address_input.strip()
        # Clear stale listing + ZOLA caches so each new search always refetches
        for _k in [k for k in list(st.session_state)
                   if k.startswith('_listings_') or k.startswith('_zola_')]:
            del st.session_state[_k]



    # ═══════════════════════════════════════════════════════════════════════
    # RESULTS — reads from session_state, persists across all reruns
    # ═══════════════════════════════════════════════════════════════════════

    if 'geo' in st.session_state:
        geo           = st.session_state['geo']
        radius_miles  = st.session_state['radius_miles']
        radius_choice = st.session_state.get('radius_choice', '5 blocks  (~0.25 mi)')
        underbuilt_threshold_pct = 20  # fixed default (previously a user-configurable 5-60 slider)

        # ── Derived fields ────────────────────────────────────────────────────────
        borough      = geo.get("borough")      or "—"
        neighborhood = geo.get("neighborhood") or "—"
        zip_code     = geo.get("zip_code")     or "—"
        lat          = geo["lat"]
        lon          = geo["lon"]
        geocoder     = geo.get("geocoder", "—")

        is_high_demand = neighborhood in HIGH_DEMAND or borough == "Manhattan"
        is_transit     = neighborhood in TRANSIT_HUBS

        # ── Geocoding result card ────────────────────────────────────────────────
        badge = '<span class="badge-live">✅ Geocoded</span>'

        demand_tag = ""
        if is_high_demand:
            demand_tag = ' &nbsp;<span style="background:#F3E1DE;color:#7A2E2E;border-radius:20px;padding:3px 10px;font-size:0.75rem;font-weight:700;">🔥 High-Demand</span>'
        transit_tag = ""
        if is_transit:
            transit_tag = ' &nbsp;<span style="background:#E4E8F1;color:#2A3E63;border-radius:20px;padding:3px 10px;font-size:0.75rem;font-weight:700;">🚇 Transit Hub</span>'

        # ── Info card ─────────────────────────────────────────────────────────────
        _hn = geo.get("house_number", "").strip()
        _sn = geo.get("street_name", "").strip().upper()
        _addr_std = f"{_hn} {_sn}".strip() + f", {borough}, NY {zip_code}" if (_hn or _sn) else geo.get("formatted_address", "")
        st.markdown(f"""
        <div class="geo-card">
          <div class="geo-card-title">📍 Geocoding Result &nbsp; {badge}{demand_tag}{transit_tag}</div>
          <div class="geo-address">{_addr_std}</div>
          <div style="font-size:0.82rem;color:#6B7280;margin:2px 0 8px">{neighborhood} &nbsp;·&nbsp; {borough}</div>
          <div class="geo-row">
            <div class="geo-chip">
              🏙️ &nbsp;<span class="geo-chip-label">Borough</span>&nbsp; {borough}
            </div>
            <div class="geo-chip">
              🗺️ &nbsp;<span class="geo-chip-label">Neighborhood</span>&nbsp; {neighborhood}
            </div>
            <div class="geo-chip">
              📮 &nbsp;<span class="geo-chip-label">ZIP</span>&nbsp; {zip_code}
            </div>
            <div class="geo-chip">
              📏 &nbsp;<span class="geo-chip-label">Radius</span>&nbsp; {radius_miles:.2f} mi
            </div>
          </div>
          <div class="geo-coords">lat {lat:.6f} &nbsp;·&nbsp; lon {lon:.6f}</div>
          <div class="geo-source">Geocoded via {geocoder}</div>
        </div>
        """, unsafe_allow_html=True)

        # ── Interactive map ───────────────────────────────────────────────────────
        st.markdown(
            "<div style='margin-top:20px;font-size:0.72rem;font-weight:700;"
            "letter-spacing:0.08em;text-transform:uppercase;color:#6B7280;"
            "margin-bottom:8px'>🗺️ Subject Property Map</div>",
            unsafe_allow_html=True,
        )
        st.caption(
            "Scroll to zoom · Click the pin for details · "
            "Use the layer icon (top-right) to switch map style · "
            "Mini-map toggle bottom-right"
        )

        subject_map = build_subject_map(
            lat=lat,
            lon=lon,
            radius_miles=radius_miles,
            label=geo["formatted_address"],
            borough=borough,
            neighborhood=neighborhood,
        )
        st_folium(
            subject_map,
            width="100%",
            height=460,
            returned_objects=[],   # no callbacks needed yet
            key="subject_map",
        )

        # ── Search filter summary ────────────────────────────────────────────────
        st.markdown(f"""
        <div class="filter-summary">
          <b>Search confirmed.</b> The dashed ring on the map shows the exact area
          from which rental comps will be pulled.<br/>
          &nbsp;&nbsp;• <b>Radius:</b> {radius_miles:.2f} miles ({radius_choice})
        </div>
        """, unsafe_allow_html=True)

        # ═════════════════════════════════════════════════════════════════════════════
        # STAGES 3–6: DATA COLLECTION, ANALYSIS, VISUALIZATIONS
        # ═════════════════════════════════════════════════════════════════════════════

        # ── Neighborhood context banner (always shown after geocoding) ────────────
        hood_flags = []
        if is_high_demand:
            hood_flags.append("🔥 High-Demand Submarket")
        if is_transit:
            hood_flags.append("🚇 Transit Hub")
        if not hood_flags:
            hood_flags.append("📍 NYC Submarket")

        bench = BOROUGH_BENCHMARKS.get(borough, {})
        bench_1bed = f"${bench.get('1 Bed', 0):,}" if bench.get("1 Bed") else "—"
        bench_studio = f"${bench.get('Studio', 0):,}" if bench.get("Studio") else "—"

        st.markdown(f"""
        <div class="hood-banner">
          <div class="hood-stat">
            <div class="hood-stat-val">{neighborhood}</div>
            <div class="hood-stat-lbl">Neighborhood</div>
          </div>
          <div class="hood-stat">
            <div class="hood-stat-val">{borough}</div>
            <div class="hood-stat-lbl">Borough</div>
          </div>
          <div class="hood-stat">
            <div class="hood-stat-val">{zip_code}</div>
            <div class="hood-stat-lbl">ZIP Code</div>
          </div>
          <div class="hood-stat">
            <div class="hood-stat-val">{bench_studio}</div>
            <div class="hood-stat-lbl">Borough Median Studio</div>
          </div>
          <div class="hood-stat">
            <div class="hood-stat-val">{bench_1bed}</div>
            <div class="hood-stat-lbl">Borough Median 1-Bed</div>
          </div>
          <div style="margin-left:auto;display:flex;gap:8px;flex-wrap:wrap;align-items:center">
            {"".join(f'<span style="background:#E4E8F1;color:#2A3E63;border-radius:20px;padding:4px 12px;font-size:0.74rem;font-weight:700">{f}</span>' for f in hood_flags)}
          </div>
        </div>
        """, unsafe_allow_html=True)

        # Scraping always runs — API keys are optional supplements

        st.divider()

        # ── Fetch with loading indicator ──────────────────────────────────────────
        has_proxy    = bool(scraping_key and scraping_key.strip())

        fetch_cache_key = f"_listings_{lat:.5f}_{lon:.5f}_{radius_miles}_pb{int(has_proxy)}"
        if fetch_cache_key in st.session_state:
            listings       = st.session_state[fetch_cache_key]["listings"]
            data_status    = st.session_state[fetch_cache_key]["status"]
            data_freshness = "Cached Data"
        else:
            with st.spinner(
                "🔍 Scraping 5 sources — Playwright stealth browser activates automatically if blocked…"
            ):
                listings, data_status = fetch_all_listings(
                    lat=lat,
                    lon=lon,
                    radius_miles=radius_miles,
                    proxy_key=scraping_key.strip() if has_proxy else None,
                )
            # Only cache successes — failures retry on next submit
            if listings:
                st.session_state[fetch_cache_key] = {"listings": listings, "status": data_status}
            data_freshness = (
                "Live Data"    if data_status.get("overall") == "live"    else
                "Partial Data" if data_status.get("overall") == "partial" else
                "No Data"
            )

        # ── Scraping status panel — compact pill row, rendered above Market Insights
        _counts = data_status.get("_counts", {})
        _status_emoji = {
            "live": "✅", "partial": "⚠️", "blocked": "🛡️",
            "no_results": "📭", "invalid_key": "🔑", "no_key": "➖",
            "timeout": "⏱️", "pending": "⭕", "no_data": "⭕",
        }
        _status_short = {
            "live": "live", "partial": "partial", "blocked": "blocked",
            "no_results": "0", "invalid_key": "key?", "no_key": "—",
            "timeout": "timeout", "pending": "pending", "no_data": "no data",
        }
        # Residential sources (available now)
        _scrape_chips_res = []
        for _sn, _sk in [("StreetEasy","streeteasy"),("Apartments","apartments"),
                         ("Craigslist","craigslist"),("Zumper","zumper"),("RentHop","renthop")]:
            _sv = data_status.get(_sk, "pending")
            _em = _status_emoji.get(_sv, "❌")
            _ct = _counts.get(_sk, 0)
            _ct_s = f" ({_ct})" if _ct > 0 else ""
            _scrape_chips_res.append(f"{_em} {_sn}: {_status_short.get(_sv,'err')}{_ct_s}")
        # Commercial sources (from last run, if available)
        _comm_st_last = st.session_state.get("_comm_status_last", {})
        _scrape_chips_comm = []
        for _sn, _sk in [("LoopNet","loopnet"),("Crexi","crexi"),("CL-Comm","craigslist_comm")]:
            _sv = _comm_st_last.get(_sk, "pending")
            _em = _status_emoji.get(_sv, "⭕")
            _scrape_chips_comm.append(f"{_em} {_sn}: {_status_short.get(_sv,'pending')}")

        def _build_scrape_status_html() -> str:
            _chip_style = (
                "display:inline-block;padding:2px 8px;margin:2px 3px;"
                "background:#E8E3D4;border:1px solid #DCD5C2;border-radius:12px;"
                "font-size:0.65rem;color:#3D4152;white-space:nowrap"
            )
            _res_chips = "".join(f'<span style="{_chip_style}">{c}</span>' for c in _scrape_chips_res)
            _comm_chips = "".join(f'<span style="{_chip_style}">{c}</span>' for c in _scrape_chips_comm)
            return (
                '<div style="background:#FCFAF3;border:1px solid #DCD5C2;border-radius:8px;'
                'padding:8px 12px;margin:8px 0">'
                '<span style="font-size:0.60rem;font-weight:700;text-transform:uppercase;'
                'color:#9CA3AF;letter-spacing:0.08em;margin-right:6px">🔍 Scraping Status</span>'
                f'<span style="{_chip_style};background:#E4E8F1;color:#2A3E63;border-color:#BFDBFE">'
                f'Residential</span>{_res_chips}'
                f'&nbsp;<span style="{_chip_style};background:#E6F0E5;color:#1F6B3A;border-color:#E6F0E5">'
                f'Commercial</span>{_comm_chips}'
                '</div>'
            )
        _scrape_status_html = _build_scrape_status_html()

        # ── No results / blocked state ─────────────────────────────────────────
        blocked_sources = [
            k for k in ("streeteasy", "apartments", "craigslist", "zumper", "renthop")
            if data_status.get(k) == "blocked"
        ]
        all_primary_blocked = len(blocked_sources) == 5

        if not listings:
            st.markdown(_scrape_status_html, unsafe_allow_html=True)
            if all_primary_blocked:
                st.warning(
                    "**All scraping sources were blocked** (bot/Cloudflare protection).\n\n"
                    "Try **expanding the radius** or run again — scraping success varies by time of day."
                )
            elif blocked_sources:
                blocked_names = ", ".join(blocked_sources)
                st.warning(
                    f"Some sources were blocked by bot protection ({blocked_names}). "
                    "Try **expanding the radius** for more results."
                )
            else:
                st.warning(
                    "No rental listings found in this area.\n\n"
                    "• Try **expanding the radius** (20–50 blocks captures more comps)\n"
                    "• Check your internet connection"
                )

        else:
            # ── Analysis ───────────────────────────────────────────────────────
            summary_df = compute_summary(listings)
            insights   = compute_insights(listings, geo, radius_miles)

            # ── Neighborhood context stats ─────────────────────────────────────
            total_listings = len(listings)
            sources_used   = sorted({l["source"] for l in listings})
            med_rent_all   = sorted(listings, key=lambda x: x["rent"])[len(listings)//2]["rent"]

            # ── Deal Sourcing & Opportunity Identification ─────────────────────
            _section_header(
                "🎯", "Deal Sourcing & Opportunity Identification",
                "Automated parcel intelligence · underbuilt detection · distress analysis · lead scoring",
            )

            # Pre-fetch subject PLUTO data (same session key reused later in Zoning section)
            _ds_addr = st.session_state.get("address_raw", geo.get("formatted_address", ""))
            _ds_zk   = f"_zola_subject_{lat:.5f}_{lon:.5f}"
            # Only treat a fetch as "done" if it actually succeeded — a stored
            # {"error": ...} result must not permanently block retries. Before
            # this fix, a single transient NYC Planning/Socrata failure locked
            # an address out of parcel data + the entire Zoning/Massing/
            # Underwriting section below for the rest of the session.
            _ds_zk_cached = st.session_state.get(_ds_zk)
            if (_ds_zk_cached is None or "error" in _ds_zk_cached) and _ds_addr:
                with st.spinner("Fetching parcel data from NYC Planning…"):
                    st.session_state[_ds_zk] = fetch_zoning_info(_ds_addr, lat=lat, lon=lon)
            _ds_zi  = st.session_state.get(_ds_zk) or {}
            _ds_bbl = _ds_zi.get("bbl", "")

            # Pre-initialize shared variables used across tabs
            _ub_max_far      = 0.0
            _ub_lot_area     = 0.0
            _ub_unused_pct   = 0.0
            _ub_uplift_pct   = 0.0
            _ub_max_sf       = 0
            _ds_dist_level   = 0
            _nearby_listings = []

            def _sf(v, d: float = 0.0) -> float:
                """Safe float: handles None, '—', and comma-formatted strings like '5,000'."""
                try:
                    return float(str(v or "").replace(",", "").strip())
                except (ValueError, TypeError):
                    return d

            # ── 3×2 Deal Sourcing Grid ───────────────────────────────────────────
            _ds_r1a, _ds_r1b = st.columns(2)

            # ─── CELL 1: Parcel Data ──────────────────────────────────────────────
            with _ds_r1a:
                st.markdown("**📋 Parcel Data**")
                if not _ds_zi or "error" in _ds_zi:
                    st.info("Parcel data unavailable — zoning lookup may have failed.")
                    if _ds_zi.get("error"):
                        st.caption(f"Detail: {_ds_zi['error']}")
                    if st.button("🔄 Retry zoning lookup", key="_ds_zi_retry_btn"):
                        st.session_state.pop(_ds_zk, None)
                        st.rerun()
                else:
                    _la_v  = int(_sf(_ds_zi.get("lot_area_sqft")))
                    _gfa_v = _ds_zi.get("bldg_area_sqft", "—")
                    _p_all = [
                        ("Owner",           _ds_zi.get("owner", "—")),
                        ("Address",         _ds_zi.get("address_pluto", "—")),
                        ("Borough",         borough),
                        ("Zoning",          _ds_zi.get("zoning_dist", "—")),
                        ("Bldg Class",      _ds_zi.get("bldg_class", "—")),
                        ("Land Use",        _ds_zi.get("land_use", "—")),
                        ("Year Built",      _ds_zi.get("year_built", "—")),
                        ("Floors",          _ds_zi.get("num_floors", "—")),
                        ("Res Units",       _ds_zi.get("units_res", "—")),
                        ("Lot Area",        f"{_la_v:,} SF" if _la_v else "—"),
                        ("Gross Floor Area",f"{_gfa_v} SF" if _gfa_v and _gfa_v != "—" else "—"),
                        ("FAR (Built)",     _ds_zi.get("far_built", "—")),
                        ("FAR (Res Max)",   _ds_zi.get("far_residential", "—")),
                        ("FAR (Comm Max)",  _ds_zi.get("far_commercial", "—")),
                        ("Assessed Total",  _ds_zi.get("assess_total", "—")),
                        ("BBL",             _ds_bbl or "—"),
                    ]
                    _p_html = "<table style='width:100%;font-size:0.80rem;border-collapse:collapse'>"
                    for _pk, _pv in _p_all:
                        _p_html += (
                            f"<tr><td style='color:#6B7280;padding:3px 8px 3px 0;white-space:nowrap'>{_pk}</td>"
                            f"<td style='font-weight:600;padding:3px 0;color:#1A1D2E'>{_pv}</td></tr>"
                        )
                    st.markdown(_p_html + "</table>", unsafe_allow_html=True)
                    st.caption("NYC PLUTO · NYC Planning GeoSearch")

                    # LPC Individual Landmarks + historic-district status, and
                    # Rent Stabilization, are automatic checks (no button) —
                    # each is check-cache-then-fetch, so a given BBL is only
                    # ever fetched once per session. ULURP stays its own
                    # smaller opt-in button below (a 3rd live NYC Open Data
                    # call — keeping it opt-in limits how many automatic
                    # fetches CELL 1 makes on every page load).
                    _cd = _ds_zi.get("community_board", "")
                    if _ds_bbl and len(str(_ds_bbl)) == 10:
                        _lpc_key = f"_lpc_{_ds_bbl}"
                        if _lpc_key not in st.session_state:
                            st.session_state[_lpc_key] = fetch_lpc_landmark_status(_ds_bbl)
                        _lpc_hist_key = f"_lpc_hist_{_ds_bbl}"
                        if _lpc_hist_key not in st.session_state:
                            st.session_state[_lpc_hist_key] = fetch_lpc_designation_status(_ds_bbl)

                        _lpc = st.session_state.get(_lpc_key, {})
                        if _lpc.get("is_individual_landmark"):
                            _status_chip(
                                "🏛️ LPC-designated individual landmark"
                                + (" — " + _lpc["landmark_name"] if _lpc.get("landmark_name") else "")
                                + (" (designated " + _lpc["designation_date"] + ")" if _lpc.get("designation_date") else ""),
                                is_positive=True,
                            )
                        elif _lpc.get("verified") and not _ds_zi.get("landmark"):
                            _status_chip("✅ Not on the LPC Individual Landmarks list (corroborates PLUTO)", is_positive=False)
                        elif _lpc and not _lpc.get("verified"):
                            st.caption("ℹ️ Could not confirm LPC individual-landmark status this time.")

                        # ── Historic district (LPC "Discover NYC Landmarks" dataset —
                        # a superset covering historic-district membership, which the
                        # px3f-pupb individual-landmarks dataset above does not) ──
                        _lpc_hist = st.session_state.get(_lpc_hist_key, {})
                        if _lpc_hist.get("is_in_historic_district"):
                            _status_chip(
                                "🏘️ In LPC historic district"
                                + (" — " + _lpc_hist["historic_district_name"] if _lpc_hist.get("historic_district_name") else ""),
                                is_positive=True,
                            )
                        elif _lpc_hist.get("verified") and not _lpc_hist.get("is_in_historic_district") and not _lpc_hist.get("is_individual_landmark"):
                            _status_chip("✅ Not in an LPC historic district (LPC Discover NYC Landmarks dataset)", is_positive=False)
                        elif _lpc_hist and not _lpc_hist.get("verified"):
                            st.caption("ℹ️ Could not confirm historic-district status this time.")

                        if _cd and st.button("📜 Check ULURP applications", key=f"_ulurp_btn_{_ds_bbl}"):
                            st.session_state[f"_ulurp_{_ds_zi.get('borough_code','')}_{_cd}"] = (
                                fetch_ulurp_applications(_ds_zi.get("borough_code", ""), _cd)
                            )
                        _ulurp = st.session_state.get(f"_ulurp_{_ds_zi.get('borough_code','')}_{_cd}", {})
                        if _ulurp.get("count"):
                            with st.expander(f"📜 ULURP Applications in this Community District ({_ulurp['count']})", expanded=False):
                                st.dataframe(pd.DataFrame(_ulurp["applications"]), use_container_width=True,
                                             height=min(_ulurp["count"] * 35 + 40, 220))
                        elif _ulurp.get("verified"):
                            st.caption("No recent ULURP applications found in this community district.")

                        # ── Rent Stabilization (compact pointer, same registry
                        # Site Finder uses via site_sourcing.enrich_property()) ──
                        _rentstab_reg_key = f"_rentstab_registry_{_ds_bbl}"
                        if _rentstab_reg_key not in st.session_state:
                            st.session_state[_rentstab_reg_key] = check_rent_stabilized(
                                _ds_zi.get("borough_code", ""), _ds_zi.get("block"), _ds_zi.get("lot"),
                                _ds_zi.get("address_pluto") or st.session_state.get("address_raw", ""),
                            )
                        _rentstab_registry_cell1 = st.session_state.get(_rentstab_reg_key, {})
                        if _rentstab_registry_cell1.get("status") == "confirmed":
                            _status_chip("🏠 Rent-Stabilized (confirmed — NYC RGB list)", is_positive=True)
                        elif _rentstab_registry_cell1.get("status") == "not_found":
                            _status_chip("Not found on NYC Rent Guidelines Board building list.", is_positive=False)
                        # "unavailable" status renders nothing here — the fuller
                        # Tax Abatement, Rent Stabilization & Transit section
                        # further down the page already surfaces the error text;
                        # this pointer stays silent-on-failure to stay compact.

            # ─── CELL 2: Underbuilt? ─────────────────────────────────────────────
            with _ds_r1b:
                st.markdown("**📈 Underbuilt? (Subject Property)**")
                _ub_lot_area   = _sf(_ds_zi.get("lot_area_sqft"))
                _ub_max_far    = max(
                    _sf(_ds_zi.get("far_residential")),
                    _sf(_ds_zi.get("far_commercial")),
                )
                _ub_built_far  = _sf(_ds_zi.get("far_built"))
                _ub_unused_far = max(0.0, _ub_max_far - _ub_built_far)
                _ub_unused_pct = (_ub_unused_far / _ub_max_far * 100) if _ub_max_far > 0 else 0.0
                _ub_add_sf     = int(_ub_unused_far * _ub_lot_area)
                _ub_max_sf     = int(_ub_max_far   * _ub_lot_area)
                _ub_built_sf   = int(_ub_built_far * _ub_lot_area)

                st.markdown(f"""
    <div style="display:flex;flex-wrap:wrap;gap:8px;margin:8px 0">
      <div style="flex:1;min-width:80px;background:#FCFAF3;border:1px solid #DCD5C2;border-radius:8px;padding:10px 8px">
        <div style="font-size:0.64rem;color:#6B7280;font-weight:700;text-transform:uppercase">Lot Size</div>
        <div style="font-size:1.15rem;font-weight:700;color:#1A1D2E">{int(_ub_lot_area):,}</div>
        <div style="font-size:0.68rem;color:#6B7280">SF</div>
      </div>
      <div style="flex:1;min-width:80px;background:#FCFAF3;border:1px solid #DCD5C2;border-radius:8px;padding:10px 8px">
        <div style="font-size:0.64rem;color:#6B7280;font-weight:700;text-transform:uppercase">Max FAR</div>
        <div style="font-size:1.15rem;font-weight:700;color:#1A1D2E">{_ub_max_far:.2f}</div>
        <div style="font-size:0.68rem;color:#6B7280">({_ub_max_sf:,} SF)</div>
      </div>
      <div style="flex:1;min-width:80px;background:#FCFAF3;border:1px solid #DCD5C2;border-radius:8px;padding:10px 8px">
        <div style="font-size:0.64rem;color:#6B7280;font-weight:700;text-transform:uppercase">Built FAR</div>
        <div style="font-size:1.15rem;font-weight:700;color:#1A1D2E">{_ub_built_far:.2f}</div>
        <div style="font-size:0.68rem;color:#6B7280">({_ub_built_sf:,} SF)</div>
      </div>
      <div style="flex:1;min-width:80px;background:#FCFAF3;border:1px solid #DCD5C2;border-radius:8px;padding:10px 8px">
        <div style="font-size:0.64rem;color:#6B7280;font-weight:700;text-transform:uppercase">Unused FAR %</div>
        <div style="font-size:1.15rem;font-weight:700;color:#{'15803D' if _ub_unused_pct > underbuilt_threshold_pct else '111827'}">{_ub_unused_pct:.0f}%</div>
        <div style="font-size:0.68rem;color:#6B7280">({_ub_add_sf:,} SF)</div>
      </div>
      <div style="flex:1;min-width:80px;background:#{'DCFCE7' if _ub_unused_pct > underbuilt_threshold_pct else 'F9FAFB'};border:1px solid #{'BBF7D0' if _ub_unused_pct > underbuilt_threshold_pct else 'E5E7EB'};border-radius:8px;padding:10px 8px">
        <div style="font-size:0.64rem;color:#6B7280;font-weight:700;text-transform:uppercase">Add&apos;l Buildable</div>
        <div style="font-size:1.15rem;font-weight:700;color:#1A1D2E">{_ub_add_sf:,}</div>
        <div style="font-size:0.68rem;color:#6B7280">SF</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

                if _ub_max_far > 0:
                    _ub_gauge = go.Figure(go.Indicator(
                        mode="gauge+number",
                        value=_ub_built_far,
                        number={"suffix": f" / {_ub_max_far:.2f} FAR"},
                        gauge={
                            "axis": {"range": [0, _ub_max_far]},
                            "bar": {"color": "#1A1D2E"},
                            "steps": [
                                {"range": [0, _ub_max_far * 0.5], "color": "#DCFCE7"},
                                {"range": [_ub_max_far * 0.5, _ub_max_far * 0.8], "color": "#F5EBD3"},
                                {"range": [_ub_max_far * 0.8, _ub_max_far], "color": "#F3E1DE"},
                            ],
                            "threshold": {
                                "line": {"color": "#1F6B3A", "width": 3},
                                "thickness": 0.85,
                                "value": _ub_max_far * (1 - underbuilt_threshold_pct / 100.0),
                            },
                        },
                    ))
                    _ub_gauge.update_layout(height=140, margin=dict(l=20, r=20, t=10, b=10))
                    st.plotly_chart(_ub_gauge, use_container_width=True)

                if _ub_unused_pct > underbuilt_threshold_pct:
                    st.markdown(
                        f'<div class="opportunity-flag">🏗️ Underbuilt — '
                        f'{_ub_unused_pct:.0f}% unused FAR · {_ub_add_sf:,} additional buildable SF</div>',
                        unsafe_allow_html=True,
                    )
                elif _ub_max_far > 0:
                    st.info(f"Near full buildout — {100 - _ub_unused_pct:.0f}% of max FAR utilized.")

                # Fetch nearby lots on same block (compact table only in grid view)
                _ub_block_key = f"_ub_block_{_ds_bbl}"
                if _ub_block_key not in st.session_state and _ds_bbl and len(str(_ds_bbl)) == 10:
                    _ub_bbl_s    = str(_ds_bbl)
                    _ub_boro_int = _ub_bbl_s[0]
                    _ub_blk_int  = str(int(_ub_bbl_s[1:6]))
                    try:
                        _ub_resp = requests.get(
                            "https://data.cityofnewyork.us/resource/64uk-42ks.json",
                            params={
                                "$where": f"block='{_ub_blk_int}' AND borough='{_ub_boro_int}'",
                                "$select": "lot,address,lotarea,builtfar,residfar,commfar,bldgclass,numfloors",
                                "$limit": "30",
                            },
                            timeout=12,
                        )
                        st.session_state[_ub_block_key] = _ub_resp.json() if _ub_resp.ok else []
                    except Exception:
                        st.session_state[_ub_block_key] = []
                _ub_lots = st.session_state.get(_ub_block_key, [])
                if _ub_lots:
                    _ub_rows = []
                    for _ul in _ub_lots:
                        try:
                            _ul_la    = float(_ul.get("lotarea") or 0)
                            _ul_built = float(_ul.get("builtfar") or 0)
                            _ul_max_f = max(float(_ul.get("residfar") or 0), float(_ul.get("commfar") or 0))
                            _ul_pct   = (max(0, _ul_max_f - _ul_built) / _ul_max_f * 100) if _ul_max_f > 0 else 0.0
                            _ub_rows.append({
                                "Address":    _ul.get("address", "—"),
                                "Built FAR":  round(_ul_built, 2),
                                "Max FAR":    round(_ul_max_f, 2),
                                "Unused %":   f"{_ul_pct:.0f}%",
                                "Add'l SF":   f"{int(max(0, _ul_max_f - _ul_built) * _ul_la):,}",
                                "Flag":       "🏗️" if _ul_pct > underbuilt_threshold_pct else "—",
                            })
                        except Exception:
                            continue
                    if _ub_rows:
                        st.markdown("**Lots — Same Block**")
                        st.dataframe(pd.DataFrame(_ub_rows), use_container_width=True,
                                     height=min(len(_ub_rows) * 35 + 40, 210))
                st.caption("Data: NYC PLUTO via Socrata")

            _ds_r2a, _ds_r2b = st.columns(2)

            # ─── CELL 3: Distress Signals ─────────────────────────────────────────
            with _ds_r2a:
                st.markdown("**🚨 Distress Signals**")
                _ecb_key = f"_ecb_{_ds_bbl}"
                if _ecb_key not in st.session_state and _ds_bbl:
                    with st.spinner("Checking HPD violations…"):
                        st.session_state[_ecb_key] = fetch_ecb_violations(_ds_bbl)
                _ecb_data = st.session_state.get(_ecb_key, {})

                _acris_ds   = st.session_state.get(f"_acris_{_ds_bbl}", {})
                _lien_count = sum(
                    1 for d in _acris_ds.get("documents", [])
                    if d.get("doc_type", "").upper() in ("UCC1", "LIEN", "LIEN2")
                )
                _dm1, _dm2, _dm3, _dm4 = st.columns(4)
                _dm1.metric("Class A",  _ecb_data.get("class_a", "—"))
                _dm2.metric("Class B",  _ecb_data.get("class_b", "—"))
                _dm3.metric("Class C",  _ecb_data.get("class_c", "—"))
                _dm4.metric("Liens",    _lien_count)

                # ── Composite 0-100 distress score ────────────────────────────
                # Replaces the old HPD-only 3-tier signal as the Deal Score's
                # distress input (below) — combines ACRIS foreclosures/liens,
                # DOB open violations/complaints, real HPD open-violation
                # count (already fetched above via _ecb_data — despite the
                # module's name, modules.ecb_fetcher actually queries HPD),
                # OATH/ECB hearings with an open balance, and Tax Lien Sale
                # List status, with user-configurable component weights.
                if _ds_bbl:
                    # DOB/HPD history is read from cache only here, never
                    # fetched — the "🏢 Property History" section further
                    # down the page (same _pip_{bbl} cache key) is the one
                    # place that fetches it. Avoids duplicating that section's
                    # 5-sub-request fetch earlier in the page's critical path;
                    # the DOB component below just shows a conservative 0/
                    # "not yet checked" until the user scrolls to that section.
                    _pip_dist = st.session_state.get(f"_pip_{_ds_bbl}", {})

                    with st.expander("⚙️ Distress score weights & additional signals", expanded=False):
                        st.caption(
                            "OATH/ECB hearings and Tax Lien Sale List are additional live NYC Open "
                            "Data checks, opt-in so they never delay the parcel-data/zoning lookup above."
                        )
                        if st.button("Check OATH/Tax Lien signals", key=f"_oath_taxlien_btn_{_ds_bbl}"):
                            with st.spinner("Checking OATH/ECB hearings + Tax Lien Sale List…"):
                                st.session_state[f"_oath_{_ds_bbl}"] = fetch_oath_hearings(
                                    _ds_zi.get("borough_code", ""), _ds_zi.get("block"), _ds_zi.get("lot"),
                                )
                                st.session_state[f"_taxlien_{_ds_bbl}"] = fetch_tax_lien_status(
                                    _ds_zi.get("borough_code", ""), _ds_zi.get("block"), _ds_zi.get("lot"),
                                )
                        _dw1, _dw2, _dw3, _dw4, _dw5 = st.columns(5)
                        _dw_acris = _dw1.slider("ACRIS", 0, 100, int(DEFAULT_WEIGHTS["acris"] * 100), key=f"_dw_acris_{_ds_bbl}")
                        _dw_dob   = _dw2.slider("DOB", 0, 100, int(DEFAULT_WEIGHTS["dob"] * 100), key=f"_dw_dob_{_ds_bbl}")
                        _dw_hpd   = _dw3.slider("HPD", 0, 100, int(DEFAULT_WEIGHTS["hpd"] * 100), key=f"_dw_hpd_{_ds_bbl}")
                        _dw_oath  = _dw4.slider("OATH", 0, 100, int(DEFAULT_WEIGHTS["oath"] * 100), key=f"_dw_oath_{_ds_bbl}")
                        _dw_lien  = _dw5.slider("Tax Lien", 0, 100, int(DEFAULT_WEIGHTS["tax_lien"] * 100), key=f"_dw_lien_{_ds_bbl}")

                    _oath_dist = st.session_state.get(f"_oath_{_ds_bbl}", {})
                    _taxlien_dist = st.session_state.get(f"_taxlien_{_ds_bbl}", {})

                    _composite_dist = compute_composite_distress_score(
                        acris_summary=_acris_ds.get("summary", {}),
                        dob_open_violations=_pip_dist.get("summary", {}).get("open_dob_viol", 0),
                        dob_open_complaints=_pip_dist.get("summary", {}).get("open_complaints", 0),
                        hpd_open_violations=_ecb_data.get("open_count", 0),
                        oath_data=_oath_dist,
                        tax_lien_data=_taxlien_dist,
                        weights={"acris": _dw_acris, "dob": _dw_dob, "hpd": _dw_hpd, "oath": _dw_oath, "tax_lien": _dw_lien},
                    )
                    # Persist for the "Export This Property" section further
                    # down the page (a different indentation scope), so it
                    # can include this composite score in the PDF/PPTX/Excel
                    # export without recomputing it.
                    st.session_state[f"_composite_dist_{_ds_bbl}"] = _composite_dist
                    # Bucket the 0-100 composite into the 0/1/2 level Deal
                    # Score's distress component already expects — keeps
                    # compute_deal_score()'s signature (and Site Finder's
                    # bulk pipeline, which calls it with its own lightweight
                    # signal) completely unchanged.
                    _ds_dist_level = 2 if _composite_dist["score"] >= 60 else (1 if _composite_dist["score"] >= 30 else 0)

                    _dist_tier_css = {"Minimal": "distress-low", "Moderate": "distress-low",
                                       "Elevated": "distress-medium", "Severe": "distress-high"}
                    st.markdown(
                        f'<div style="margin:8px 0 4px">'
                        f'<span class="{_dist_tier_css.get(_composite_dist["tier"], "distress-low")}">'
                        f'⚡ Composite Distress Score: {_composite_dist["score"]}/100 ({_composite_dist["tier"]})</span></div>',
                        unsafe_allow_html=True,
                    )
                    for _comp, _cd in _composite_dist["breakdown"].items():
                        st.caption(f"• {_comp.upper()}: {_cd['reasoning']}")
                else:
                    _ds_dist_level = _ecb_data.get("distress_level", 0)
                    if _lien_count >= 3:
                        _ds_dist_level = min(2, _ds_dist_level + 1)
                    _dist_labels = ["Low", "Medium", "High"]
                    _dist_css    = ["distress-low", "distress-medium", "distress-high"]
                    st.markdown(
                        f'<div style="margin:8px 0 12px">'
                        f'<span class="{_dist_css[_ds_dist_level]}">'
                        f'⚡ Distress: {_dist_labels[_ds_dist_level]}</span></div>',
                        unsafe_allow_html=True,
                    )
                if _ecb_data.get("violations"):
                    _vrows = [
                        {
                            "Date":  v.get("issue_date", "—"),
                            "Class": v.get("violation_type", "—"),
                            "Desc":  v.get("description", "—")[:60],
                            "Apt":   v.get("apartment", "—"),
                            "Status": v.get("status", "—"),
                        }
                        for v in _ecb_data["violations"]
                    ]
                    with st.expander(f"HPD Violations ({_ecb_data['count']} · {_ecb_data.get('open_count',0)} open)"):
                        st.dataframe(pd.DataFrame(_vrows), use_container_width=True, height=180)
                elif _ecb_data and not _ecb_data.get("error"):
                    st.success("No HPD violations found.")
                if _ecb_data.get("error"):
                    st.warning(f"HPD: {_ecb_data['error']}")
                st.markdown(
                    "Sources: "
                    "[HPD Open Violations (wvxf-dwi5)](https://data.cityofnewyork.us/Housing-Development/"
                    "Housing-Maintenance-Code-Violations/wvxf-dwi5) "
                    "· [ACRIS (NYC DOF)](https://a836-acris.nyc.gov/CP/)"
                )
                # Direct per-BBL deep links to any online-pulled data already
                # cached in this cell or by an opt-in fetch elsewhere on the
                # page — additive to the static Sources caption above, reads
                # existing cache keys only, triggers no new fetch.
                _src_links = []
                if _acris_ds.get("acris_url"):
                    _src_links.append(f"[Full ACRIS document history ↗]({_acris_ds['acris_url']})")
                _pip_dist = st.session_state.get(f"_pip_{_ds_bbl}", {})
                if _pip_dist.get("pip_url"):
                    _src_links.append(f"[NYC Property Information Portal (DOB+HPD+ECB) ↗]({_pip_dist['pip_url']})")
                if _ecb_data.get("hpd_url"):
                    _src_links.append(f"[HPD Online violation search ↗]({_ecb_data['hpd_url']})")
                _taxlien_dist = st.session_state.get(f"_taxlien_{_ds_bbl}", {})
                if _taxlien_dist.get("info_url"):
                    _src_links.append(f"[NYC DOF Tax Lien Sale info ↗]({_taxlien_dist['info_url']})")
                _oath_dist = st.session_state.get(f"_oath_{_ds_bbl}", {})
                if _oath_dist.get("oath_url"):
                    _src_links.append(f"[OATH/ECB hearing search ↗]({_oath_dist['oath_url']})")
                if _src_links:
                    st.caption("📎 " + "  ·  ".join(_src_links))

            # Compute nearby listings for Deal Score (even though we display Nearby Developments)
            _nearby_listings = [l for l in listings if float(l.get("distance_miles") or 99) < 0.15]

            # ─── CELL 4: Nearby Developments ─────────────────────────────────────
            with _ds_r2b:
                st.markdown("**🏗️ Nearby Developments**")
                _nd_key = f"_nd_{lat:.5f}_{lon:.5f}_{radius_miles:.2f}"
                if _nd_key not in st.session_state:
                    with st.spinner("Fetching nearby developments…"):
                        from modules.nearby_developments import fetch_nearby_developments
                        st.session_state[_nd_key] = fetch_nearby_developments(
                            lat, lon, radius_miles,
                            address=address_input,
                            neighborhood=neighborhood if neighborhood != "—" else "",
                            zip_code=zip_code if zip_code != "—" else "",
                        )
                _nd_devs, _nd_status = st.session_state[_nd_key]

                _nd_total_units = sum(d.get("units") or 0 for d in _nd_devs)
                _nd_total_sf    = sum(d.get("sqft")  or 0 for d in _nd_devs)
                _nd_c1, _nd_c2, _nd_c3 = st.columns(3)
                _nd_c1.metric("Projects",          len(_nd_devs))
                _nd_c2.metric("Units in Pipeline", f"{_nd_total_units:,}" if _nd_total_units else "—")
                _nd_c3.metric("SF in Pipeline",    f"{_nd_total_sf:,}"    if _nd_total_sf    else "—")

                if _nd_devs:
                    # Status breakdown
                    _nd_by_status: dict = {}
                    for _nd in _nd_devs:
                        _ns = _nd.get("status") or "Unknown"
                        _nd_by_status[_ns] = _nd_by_status.get(_ns, 0) + 1
                    _nd_stat_str = " · ".join(f"{v} {k}" for k, v in _nd_by_status.items())
                    st.caption(f"By status: {_nd_stat_str}")

                    _nd_rows = []
                    for _nd in _nd_devs:
                        _nd_rows.append({
                            "Address":  _nd.get("address", "—")[:45],
                            "Type":     _nd.get("asset_type", "—")[:20],
                            "Status":   _nd.get("status", "—"),
                            "Units":    _nd.get("units") or "—",
                            "Filed":    _nd.get("filing_date", "")[:10],
                            "Source":   _nd.get("source", "—"),
                        })
                    st.dataframe(
                        pd.DataFrame(_nd_rows),
                        use_container_width=True,
                        height=min(len(_nd_rows) * 35 + 40, 210),
                    )
                else:
                    st.info("No recent developments found within this radius.")
                st.caption("Sources: NYC DOB · Google News · The Real Deal · Commercial Observer · Bisnow")

            _ds_r3a, _ds_r3b = st.columns(2)

            # ─── CELL 5: Assemblage Detection ────────────────────────────────────
            with _ds_r3a:
                st.markdown("**🔗 Assemblage Detection**")
                _as_key = f"_assem_{_ds_bbl}"
                if _as_key not in st.session_state and _ds_bbl and len(str(_ds_bbl)) == 10:
                    try:
                        import math as _as_math
                        _100ft_mi  = 100 / 5280.0
                        _as_lat_d  = _100ft_mi / 69.0
                        _as_lon_d  = _100ft_mi / (69.0 * _as_math.cos(_as_math.radians(lat)))
                        _as_resp = requests.get(
                            "https://data.cityofnewyork.us/resource/64uk-42ks.json",
                            params={
                                "$where": (
                                    f"latitude > {lat - _as_lat_d:.6f} AND latitude < {lat + _as_lat_d:.6f} "
                                    f"AND longitude > {lon - _as_lon_d:.6f} AND longitude < {lon + _as_lon_d:.6f}"
                                ),
                                "$select": "bbl,lot,address,lotarea,lotfront,lotdepth,bldgclass,"
                                           "numfloors,residfar,commfar,builtfar,latitude,longitude,ownername",
                                "$limit": "50",
                            },
                            timeout=12,
                        )
                        st.session_state[_as_key] = _as_resp.json() if _as_resp.ok else []
                    except Exception:
                        st.session_state[_as_key] = []
                _as_lots = st.session_state.get(_as_key, [])

                if _as_lots and _ds_bbl and len(str(_ds_bbl)) == 10:
                    _adj_lots_as = [
                        l for l in _as_lots
                        if l.get("bbl") and str(l.get("bbl", "")).replace(" ", "") != str(_ds_bbl)
                    ]
                    _subj_la_as = _ub_lot_area or _sf(_ds_zi.get("lot_area_sqft"))
                    _as_max_far = _ub_max_far or max(
                        _sf(_ds_zi.get("far_residential")),
                        _sf(_ds_zi.get("far_commercial")),
                    )
                    _comb_la       = _subj_la_as + sum(float(l.get("lotarea") or 0) for l in _adj_lots_as)
                    _indiv_sf      = _subj_la_as * _as_max_far
                    _comb_sf       = _comb_la    * _as_max_far
                    _ub_uplift_pct = ((_comb_sf - _indiv_sf) / _indiv_sf * 100) if _indiv_sf > 0 else 0.0

                    # Same-owner detection — normalized string match against the
                    # subject's own PLUTO owner-of-record. A same-owner adjacent
                    # lot is a much stronger assemblage signal than mere physical
                    # adjacency (no separate acquisition negotiation needed).
                    def _norm_owner(name: str) -> str:
                        return " ".join(str(name or "").upper().split())
                    _subj_owner_norm = _norm_owner(_ds_zi.get("owner", ""))
                    _same_owner_lots = [
                        l for l in _adj_lots_as
                        if _subj_owner_norm and _norm_owner(l.get("ownername")) == _subj_owner_norm
                    ]

                    _am1, _am2, _am3, _am4 = st.columns(4)
                    _am1.metric("Adj Lots",  len(_adj_lots_as))
                    _am2.metric("Comb Area", f"{int(_comb_la):,} SF")
                    _am3.metric("Uplift",    f"{_ub_uplift_pct:.0f}%")
                    _am4.metric("Same-Owner Adj Lots", len(_same_owner_lots))

                    if _same_owner_lots:
                        st.markdown(
                            f'<div class="opportunity-flag">👤 {len(_same_owner_lots)} adjacent lot'
                            f'{"s" if len(_same_owner_lots) != 1 else ""} share the subject\'s owner of '
                            f'record ({_ds_zi.get("owner", "—")}) — '
                            f'{", ".join(l.get("address", "—") for l in _same_owner_lots)}</div>',
                            unsafe_allow_html=True,
                        )
                        st.caption(
                            "⚠️ Matched on normalized PLUTO owner-of-record string only — "
                            "does not resolve shared beneficial ownership through separate LLCs "
                            "(see ACRIS Parties for that)."
                        )

                    if _ub_uplift_pct > 30:
                        st.markdown(
                            f'<div class="opportunity-flag">🔗 Assemblage — '
                            f'{_ub_uplift_pct:.0f}% uplift · {int(_indiv_sf):,} → {int(_comb_sf):,} SF</div>',
                            unsafe_allow_html=True,
                        )
                    # Folium mini-map: red = subject, blue = adjacent lots
                    _as_fmap = folium.Map(
                        location=[lat, lon], zoom_start=17,
                        tiles="CartoDB positron",
                    )
                    folium.CircleMarker(
                        [lat, lon], radius=10, color="#7A2E2E",
                        fill=True, fill_opacity=0.85,
                        tooltip="Subject Property",
                    ).add_to(_as_fmap)
                    for _adj in _adj_lots_as:
                        _adj_lat = float(_adj.get("latitude") or lat)
                        _adj_lon = float(_adj.get("longitude") or lon)
                        folium.CircleMarker(
                            [_adj_lat, _adj_lon], radius=7, color="#2A3E63",
                            fill=True, fill_opacity=0.65,
                            tooltip=_adj.get("address", "Adjacent Lot"),
                        ).add_to(_as_fmap)
                    st_folium(_as_fmap, height=160, width="100%",
                              returned_objects=[], key="assemblage_mini_map")

                    if _adj_lots_as:
                        _as_rows = []
                        for _al in _adj_lots_as:
                            _al_la       = float(_al.get("lotarea") or 0)
                            _al_max_far  = max(_sf(_al.get("residfar") or 0),
                                               _sf(_al.get("commfar") or 0))
                            _al_blt_far  = _sf(_al.get("builtfar") or 0)
                            _al_max_sf   = int(_al_max_far * _al_la)
                            _al_built_sf = int(_al_blt_far * _al_la)
                            _al_unused_sf = max(0, _al_max_sf - _al_built_sf)
                            _as_rows.append({
                                "Address":          _al.get("address", "—"),
                                "Lot SF":           f"{int(_al_la):,}" if _al_la else "—",
                                "Max FAR (SF)":     f"{_al_max_sf:,}" if _al_max_sf else "—",
                                "Built FAR (SF)":   f"{_al_built_sf:,}" if _al_built_sf else "—",
                                "Unused SF":        f"{_al_unused_sf:,}" if _al_unused_sf else "—",
                                "Add'l Buildable":  f"{_al_unused_sf:,}" if _al_unused_sf else "—",
                                "Class":            _al.get("bldgclass", "—"),
                            })
                        st.dataframe(pd.DataFrame(_as_rows), use_container_width=True,
                                     height=min(len(_as_rows) * 35 + 40, 200))
                    else:
                        st.info("No adjacent lots within 100 ft.")
                else:
                    st.info("BBL required for assemblage analysis.")
                st.caption("NYC PLUTO · Adjacent = within 100 ft radius")

            # ─── CELL 6: Deal Score ──────────────────────────────────────────────
            with _ds_r3b:
                st.markdown("**🏆 Deal Score**")
                _sc_bench_1bd = bench.get("1 Bed") if bench else None
                _sc_premium   = (
                    (med_rent_all / _sc_bench_1bd - 1) * 100
                    if _sc_bench_1bd and _sc_bench_1bd > 0 else 0.0
                )
                _score_result = compute_deal_score(
                    unused_far_pct            = _ub_unused_pct,
                    distress_level            = _ds_dist_level,
                    neighborhood_rent_premium = _sc_premium,
                    zoning_dist               = _ds_zi.get("zoning_dist", ""),
                    listings_nearby           = len(_nearby_listings),
                    assemblage_uplift_pct     = _ub_uplift_pct,
                    has_overlay               = bool(_ds_zi.get("overlay")),
                )
                _sc_score = _score_result["score"]
                _sc_tier  = _score_result["tier"]
                _sc_break = _score_result["breakdown"]
                # Stashed so the "Save to Portfolio" button further down this
                # same render (Zoning & Property Data section) can attach the
                # same Deal Score shown here, instead of saving a property
                # with a blank score/tier — see _map_zinfo_to_portfolio_schema.
                st.session_state["_ds_last_score_result"] = _score_result

                _sc_clr = "#1F6B3A" if _sc_score >= 70 else ("#8B6914" if _sc_score >= 40 else "#7A2E2E")
                _sc_tbg = "#E6F0E5" if _sc_score >= 70 else ("#F5EBD3" if _sc_score >= 40 else "#F3E1DE")
                _sc_tfg = "#1F6B3A" if _sc_score >= 70 else ("#8B6914" if _sc_score >= 40 else "#7A2E2E")

                _sc_col1, _sc_col2 = st.columns([1, 2])
                with _sc_col1:
                    st.markdown(
                        f'<div style="text-align:center;padding:18px 10px 12px">'
                        f'<div class="deal-score-num" style="color:{_sc_clr}">{_sc_score}</div>'
                        f'<div style="font-size:0.70rem;color:#6B7280;margin-bottom:8px">out of 100</div>'
                        f'<span class="deal-tier-badge" style="background:{_sc_tbg};color:{_sc_tfg}">'
                        f'{_sc_tier}</span></div>',
                        unsafe_allow_html=True,
                    )
                with _sc_col2:
                    st.markdown("**Breakdown**")
                    for _cn, _cd in _sc_break.items():
                        _bar_pct = _cd["score"] / _cd["max"] if _cd["max"] > 0 else 0
                        st.markdown(
                            f"<div style='margin-bottom:8px'>"
                            f"<div style='display:flex;justify-content:space-between;font-size:0.78rem'>"
                            f"<span style='font-weight:600'>{_cn}</span>"
                            f"<span style='color:#6B7280'>{_cd['score']}/{_cd['max']}</span></div>"
                            f"<div style='background:#E8E3D4;border-radius:4px;height:6px;margin-top:3px'>"
                            f"<div style='background:{_sc_clr};width:{_bar_pct*100:.0f}%;"
                            f"height:6px;border-radius:4px'></div></div>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )
                st.caption("FAR 30% · Distress 25% · Location 20% · Zoning 15% · Activity 10%")

            # ── Area Underdevelopment ─────────────────────────────────────────
            _section_header(
                "🏗️", "Area Underdevelopment",
                f"All PLUTO lots within {radius_choice} · Underbuilt = unused FAR > {underbuilt_threshold_pct}% of max",
            )
            _und_key = f"_area_und_{lat:.5f}_{lon:.5f}_{radius_miles:.2f}"
            if _und_key not in st.session_state:
                with st.spinner("Fetching PLUTO lot data for area underdevelopment analysis…"):
                    _und_err = None
                    try:
                        import math as _math
                        _und_lat_d = radius_miles / 69.0
                        _und_lon_d = radius_miles / (69.0 * _math.cos(_math.radians(lat)))
                        _und_resp  = requests.get(
                            "https://data.cityofnewyork.us/resource/64uk-42ks.json",
                            params={
                                "$where": (
                                    f"latitude > {lat - _und_lat_d:.6f} AND latitude < {lat + _und_lat_d:.6f} "
                                    f"AND longitude > {lon - _und_lon_d:.6f} AND longitude < {lon + _und_lon_d:.6f}"
                                ),
                                "$select": "bbl,borocode,block,lot,address,lotarea,builtfar,residfar,commfar,bldgarea,"
                                           "numfloors,latitude,longitude,bldgclass,assessland,landuse,"
                                           "landmark,histdist",
                                "$limit": "1500",
                            },
                            timeout=25,
                        )
                        _und_resp.raise_for_status()
                        _und_raw = _und_resp.json()
                    except Exception as _und_exc:
                        _und_raw = []
                        _und_err = str(_und_exc)
                st.session_state[_und_key] = _und_raw
                st.session_state[f"{_und_key}_error"] = _und_err
                record_source_status("Area Underdevelopment (PLUTO)", ok=(_und_err is None), detail=_und_err or "")
            _und_raw = st.session_state.get(_und_key, [])
            _und_fetch_err = st.session_state.get(f"{_und_key}_error")
            if _und_fetch_err:
                st.warning(f"⚠️ PLUTO lot fetch failed — area underdevelopment analysis unavailable: {_und_fetch_err}")

            # Filter to actual radius + compute metrics
            _und_lots: list[dict] = []
            for _ur in _und_raw:
                try:
                    _ur_lat = float(_ur.get("latitude") or 0)
                    _ur_lon = float(_ur.get("longitude") or 0)
                    if not _ur_lat or not _ur_lon:
                        continue
                    import math as _math2
                    _ur_dist = 3958.8 * 2 * _math2.asin(_math2.sqrt(
                        _math2.sin(_math2.radians(_ur_lat - lat) / 2) ** 2 +
                        _math2.cos(_math2.radians(lat)) * _math2.cos(_math2.radians(_ur_lat)) *
                        _math2.sin(_math2.radians(_ur_lon - lon) / 2) ** 2
                    ))
                    if _ur_dist > radius_miles:
                        continue
                    _ur_la      = float(_ur.get("lotarea") or 0)
                    _ur_built   = float(_ur.get("builtfar") or 0)
                    _ur_max_f   = max(float(_ur.get("residfar") or 0), float(_ur.get("commfar") or 0))
                    _ur_bldg_sf = float(_ur.get("bldgarea") or 0)
                    _ur_built_sf= int(_ur_built * _ur_la) if _ur_la else int(_ur_bldg_sf)
                    _ur_max_sf  = int(_ur_max_f  * _ur_la)
                    _ur_unused  = max(0.0, _ur_max_f - _ur_built)
                    _ur_pct     = (_ur_unused / _ur_max_f * 100) if _ur_max_f > 0 else 0.0
                    _ur_add_sf  = int(_ur_unused * _ur_la)
                    _ur_flrs_raw= _ur.get("numfloors", "")
                    _ur_flrs    = (str(int(float(_ur_flrs_raw))) if _ur_flrs_raw and str(_ur_flrs_raw).replace(".", "").isdigit() else (_ur_flrs_raw or "—"))
                    _ur_assess_land = float(_ur.get("assessland") or 0)
                    _ur_is_vacant   = (_ur.get("landuse") == "11") or (_ur_bldg_sf <= 0)
                    _ur_opp = compute_opportunity_score({
                        "lot_sf": _ur_la, "far_max": _ur_max_f, "far_built": _ur_built,
                        "unused_far_pct": _ur_pct, "assess_land": _ur_assess_land,
                        "is_vacant": _ur_is_vacant,
                    })
                    _ur_landmark = bool(_ur.get("landmark"))
                    _ur_histdist = bool(_ur.get("histdist"))
                    _ur_rentstab = False
                    try:
                        _ur_rentstab = check_rent_stabilized(
                            _ur.get("borocode", ""), _ur.get("block"), _ur.get("lot"), _ur.get("address", ""),
                        ).get("status") == "confirmed"
                    except Exception:
                        pass
                    _und_lots.append({
                        "address":    _ur.get("address", "—"),
                        "lot_area":   _ur_la,
                        "built_far":  _ur_built,
                        "max_far":    _ur_max_f,
                        "built_sf":   _ur_built_sf,
                        "max_sf":     _ur_max_sf,
                        "unused_pct": _ur_pct,
                        "add_sf":     _ur_add_sf,
                        "lat":        _ur_lat,
                        "lon":        _ur_lon,
                        "floors":     _ur_flrs,
                        "bldg_class": _ur.get("bldgclass", "—"),
                        "underbuilt": _ur_pct > underbuilt_threshold_pct,
                        "dist_mi":    round(_ur_dist, 3),
                        "opportunity_score": _ur_opp["score"],
                        "opportunity_tier":  _ur_opp["tier"],
                        "is_landmark":  _ur_landmark,
                        "is_historic":  _ur_histdist,
                        "is_rentstab":  _ur_rentstab,
                    })
                except Exception:
                    continue

            # Keep the 300 nearest lots; analyze those
            _und_lots    = sorted(_und_lots, key=lambda x: x["dist_mi"])[:300]
            _und_total   = len(_und_lots)
            _und_ub_lots = [l for l in _und_lots if l["underbuilt"]]
            _und_ub_ct   = len(_und_ub_lots)
            _und_ub_pct  = (_und_ub_ct / _und_total * 100) if _und_total > 0 else 0
            _und_avg_far = (sum(l["unused_pct"] for l in _und_ub_lots) / _und_ub_ct) if _und_ub_ct > 0 else 0
            _und_avg_opp = (sum(l["opportunity_score"] for l in _und_ub_lots) / _und_ub_ct) if _und_ub_ct > 0 else 0

            _um1, _um2, _um3, _um4, _um5 = st.columns(5)
            _um1.metric("Total Lots Analyzed", f"{_und_total:,}")
            _um2.metric("Underbuilt Lots",      f"{_und_ub_ct:,}")
            _um3.metric("% Underbuilt",          f"{_und_ub_pct:.0f}%")
            _um4.metric("Avg Unused FAR (ub)",   f"{_und_avg_far:.0f}%")
            _um5.metric("Avg Opportunity Score (ub)", f"{_und_avg_opp:.0f}/100")

            def _und_color(pct: float) -> str:
                if pct >= 80: return "#1F6B3A"
                if pct >= 60: return "#1F6B3A"
                if pct >= 40: return "#1F6B3A"
                if pct >= 20: return "#1F6B3A"
                return "#9CA3AF"

            if _und_lots:
                _und_show_all = st.checkbox("Show all lots (including near-buildout)", value=False)
                _und_display  = _und_lots if _und_show_all else _und_ub_lots
                # Ranked by the same multi-factor Opportunity Score Site Finder's
                # boundary search uses (site_sourcing.compute_opportunity_score:
                # unused FAR + vacancy + assessed land basis + lot-size scale) —
                # not just raw unused-FAR%, which ignores vacancy/basis/scale.
                _und_display  = sorted(_und_display, key=lambda x: x["opportunity_score"], reverse=True)

                # Map + Table side by side
                _und_mc, _und_tc = st.columns([1, 1])
                with _und_mc:
                    st.markdown("**Underbuilt Lot Map**")
                    _und_map_center = [lat, lon]
                    _und_map_zoom   = 15
                    _und_fmap = folium.Map(location=_und_map_center, zoom_start=_und_map_zoom, tiles="CartoDB positron")
                    folium.Marker(
                        [lat, lon],
                        tooltip="Subject Property",
                        icon=folium.Icon(color="blue", icon="home"),
                    ).add_to(_und_fmap)
                    for _ul2 in _und_lots:
                        _ul2_color = _und_color(_ul2["unused_pct"])
                        folium.CircleMarker(
                            [_ul2["lat"], _ul2["lon"]],
                            radius=5,
                            color=_ul2_color,
                            fill=True, fill_color=_ul2_color, fill_opacity=0.7,
                            tooltip=(
                                f"{_ul2['address']} · "
                                f"Built {_ul2['built_far']:.2f} / Max {_ul2['max_far']:.2f} FAR · "
                                f"{_ul2['unused_pct']:.0f}% unused"
                            ),
                        ).add_to(_und_fmap)
                    st_folium(_und_fmap, width="100%", height=400, returned_objects=[], key="und_map")
                    st.caption("🌿 Light green = 20–40% unused · 🟢 Dark green = 60–80%+ unused · ⬤ Gray = near buildout")

                with _und_tc:
                    st.markdown(f"**{'Underbuilt' if not _und_show_all else 'All'} Lots** ({len(_und_display)} shown)")
                    _und_rows = []
                    for _ul2 in _und_display:
                        _und_rows.append({
                            "Address":       _ul2["address"],
                            "Lot SF":        f"{int(_ul2['lot_area']):,}",
                            "Built SF":      f"{_ul2['built_sf']:,}",
                            "Max SF":        f"{_ul2['max_sf']:,}",
                            "Built FAR":     _ul2['built_far'],
                            "Max FAR":       _ul2['max_far'],
                            "Unused FAR %":  round(_ul2['unused_pct'], 1),
                            "Add'l Build SF":f"{_ul2['add_sf']:,}",
                            "Opportunity":   f"{_ul2['opportunity_score']}/100 ({_ul2['opportunity_tier']})",
                            "Flag":          "🏗️ Underbuilt" if _ul2["underbuilt"] else "—",
                            "_lat":          _ul2["lat"],
                            "_lon":          _ul2["lon"],
                        })
                    _und_df = pd.DataFrame(_und_rows)
                    _und_display_cols = [c for c in _und_df.columns if not c.startswith("_")]
                    _und_sel = st.dataframe(
                        _und_df[_und_display_cols],
                        use_container_width=True,
                        height=min(len(_und_rows) * 35 + 40, 420),
                        on_select="rerun",
                        selection_mode="single-row",
                    )
                    # If a row is selected, re-center the map
                    _und_sel_rows = getattr(getattr(_und_sel, "selection", None), "rows", [])
                    if _und_sel_rows:
                        _sel_lot = _und_rows[_und_sel_rows[0]]
                        _und_fmap2 = folium.Map(location=[_sel_lot["_lat"], _sel_lot["_lon"]],
                                                zoom_start=17, tiles="CartoDB positron")
                        folium.Marker(
                            [lat, lon], tooltip="Subject Property",
                            icon=folium.Icon(color="blue", icon="home"),
                        ).add_to(_und_fmap2)
                        _sel_color = _und_color(_und_display[_und_sel_rows[0]]["unused_pct"])
                        folium.CircleMarker(
                            [_sel_lot["_lat"], _sel_lot["_lon"]],
                            radius=10, color=_sel_color, fill=True,
                            fill_color=_sel_color, fill_opacity=0.9,
                            tooltip=f"SELECTED: {_sel_lot['Address']} · {_sel_lot['Unused FAR %']}% unused",
                        ).add_to(_und_fmap2)
                        with _und_mc:
                            st_folium(_und_fmap2, width="100%", height=400,
                                      returned_objects=[], key="und_map_sel")
            else:
                st.info("No PLUTO lot data returned for this radius. Try a larger radius or check the address.")
            st.caption(
                f"Source: NYC PLUTO via Socrata (64uk-42ks) · "
                f"{_und_total} nearest lots within {radius_miles:.2f} mi analyzed · "
                f"Underbuilt threshold: unused FAR > {underbuilt_threshold_pct}% of max FAR"
            )

            # ── Live Scraping Status (shown above Market Insights) ────────────
            st.markdown(_scrape_status_html, unsafe_allow_html=True)

            # ── Market insights ────────────────────────────────────────────────
            _section_header("💡", "Market Insights")
            for insight in insights:
                st.markdown(f"• {insight}")

            # ── Comparables Analysis (6 tabs) ─────────────────────────────────────
            _section_header("📊", "Comparables Analysis",
                            "Residential Rental · Residential Condo · Commercial · Retail · Property Sales")

            _tab_res, _tab_res_condo, _tab_comm, _tab_retail, _tab_sales, _tab_cr = st.tabs([
                "🏠 Residential - Rental", "🏠 Residential - Condo", "🏢 Commercial",
                "🏪 Retail", "💰 Property Sales", "🏙️ CityRealty",
            ])

            # ── Fetch shared datasets once ────────────────────────────────────────

            # Commercial comps (shared between Commercial and Retail tabs)
            _comm_key = f"_comm_{lat:.5f}_{lon:.5f}_{radius_miles:.2f}"
            if _comm_key not in st.session_state:
                from modules.commercial_scraper import fetch_commercial_comps
                from modules.data_fetcher import fetch_commercial_listings as _fetch_comm_all
                _proxy_arg = scraping_key.strip() if has_proxy else None
                with st.spinner("Fetching commercial comps…"):
                    _cl_comm, _cl_comm_st = fetch_commercial_comps(lat, lon, radius_miles, _proxy_arg)
                    try:
                        _ln_comm, _ln_comm_st = _fetch_comm_all(lat, lon, radius_miles, _proxy_arg)
                    except Exception:
                        _ln_comm, _ln_comm_st = [], {}
                _all_comm = _cl_comm + _ln_comm
                # Store commercial status for Live Scraping Status panel on next run
                st.session_state["_comm_status_last"] = {
                    "loopnet":          (_ln_comm_st.get("loopnet","—") if isinstance(_ln_comm_st, dict) else str(_ln_comm_st)),
                    "crexi":            (_ln_comm_st.get("crexi","—")   if isinstance(_ln_comm_st, dict) else "—"),
                    "craigslist_comm":  (_cl_comm_st.get("overall","—") if isinstance(_cl_comm_st, dict) else str(_cl_comm_st)),
                }
                st.session_state[_comm_key] = {"listings": _all_comm}
                record_source_status(
                    "Commercial Comps", ok=True,
                    detail="" if _all_comm else "no commercial/loopnet/crexi results in radius",
                )
            _comm_listings = st.session_state[_comm_key]["listings"]

            # Sales comps (shared between Residential condo section and Property Sales tab)
            _sales_key = f"_sales_{lat:.5f}_{lon:.5f}_{radius_miles:.2f}_{zip_code}"
            if _sales_key not in st.session_state:
                from modules.data_fetcher import fetch_sales_comps as _fetch_sales
                with st.spinner("Fetching NYC sales comps…"):
                    _sales_listings_raw, _sales_status = _fetch_sales(
                        lat, lon, radius_miles,
                        zip_code=zip_code if zip_code != "—" else None,
                        neighborhood=neighborhood if neighborhood != "—" else None,
                    )
                st.session_state[_sales_key] = {"listings": _sales_listings_raw, "status": _sales_status}
                record_source_status(
                    "NYC Sales Comps", ok=(_sales_status not in ("error",) and not str(_sales_status).startswith("error")),
                    detail="" if _sales_listings_raw else str(_sales_status),
                )
            _sales_listings = st.session_state[_sales_key]["listings"]
            _sales_status = st.session_state[_sales_key].get("status", "")

            # ── Comps Reconciliation (rental vs. sales, implied cap rate / GRM) ──
            # Combines the rental comps (`listings`, fetched earlier for this
            # tab) with the sales comps just fetched above — the 5 comp tabs
            # below otherwise never talk to each other, leaving this
            # arithmetic to the analyst by hand.
            _rc_rent_psf_vals = [
                (l["rent"] * 12 / l["sqft"]) for l in listings
                if l.get("rent") and l.get("sqft") and l["sqft"] > 0
            ]
            _rc_sale_psf_vals = [
                l["price_psf"] for l in _sales_listings if l.get("price_psf")
            ] or [
                l["price"] / l["sqft"] for l in _sales_listings
                if l.get("price") and l.get("sqft") and l["sqft"] > 0
            ]
            _rc_result = reconcile_comps(_rc_rent_psf_vals, _rc_sale_psf_vals)
            if _rc_result:
                with st.expander("🔗 Comps Reconciliation — Implied Cap Rate & GRM", expanded=False):
                    st.caption(
                        f"Synthesized from {_rc_result['rent_comp_count']} rental comp(s) and "
                        f"{_rc_result['sale_comp_count']} sales comp(s) fetched above — median $/SF each, "
                        "not matched building-to-building. NOI assumes "
                        f"{OPEX_RATIO:.0%} opex ratio and 93% stabilized occupancy (same assumptions as the massing "
                        "scenarios' financials) — a rough reconciliation, not a substitute for building-specific underwriting."
                    )
                    _rc_c1, _rc_c2, _rc_c3, _rc_c4 = st.columns(4)
                    _rc_c1.metric("Median Rent $/SF/yr", f"${_rc_result['ann_rent_psf']:,.2f}")
                    _rc_c2.metric("Median Sale $/SF", f"${_rc_result['sale_psf']:,.2f}")
                    _rc_c3.metric("Implied GRM", f"{_rc_result['grm']:.1f}x" if _rc_result['grm'] else "—")
                    _rc_c4.metric("Implied Cap Rate", f"{_rc_result['cap_rate_pct']:.2f}%" if _rc_result['cap_rate_pct'] else "—")
            elif listings or _sales_listings:
                st.caption(
                    "🔗 Comps reconciliation unavailable — need both rental and sales comps with SF data to compute "
                    "implied cap rate / GRM (only one side is present for this property)."
                )

            # ── Tab 1: Residential - Rental ─────────────────────────────────────────
            with _tab_res:
                # Rent Summary
                st.markdown("#### 🏠 Rent Summary by Unit Type")
                display_cols = ["Unit Type", "# Listings", "Avg Rent", "Median Rent",
                                "Min Rent", "Max Rent", "Rent Range", "Avg $/SF"]
                st.dataframe(
                    summary_df[display_cols].set_index("Unit Type"),
                    use_container_width=True,
                    height=min(len(summary_df) * 35 + 38, 260),
                )

                # Comparable Listings Map
                st.markdown("#### 🗺️ Comparable Listings Map")
                st.caption(
                    "Colored markers = rental listings by unit type.  "
                    "Click any marker for rent, address, and source link."
                )
                listings_map = build_map(
                    listings=listings,
                    center_lat=lat,
                    center_lon=lon,
                    radius_miles=radius_miles,
                    subject_label=geo["formatted_address"],
                )
                st_folium(listings_map, width="100%", height=480,
                          returned_objects=[], key="listings_map")

                # Rent Charts
                st.markdown("#### 📊 Rent Charts")
                _rc1, _rc2 = st.columns(2)
                with _rc1:
                    st.plotly_chart(build_bar_chart(summary_df),
                                    use_container_width=True, config={"displayModeBar": False})
                with _rc2:
                    st.plotly_chart(build_range_chart(summary_df),
                                    use_container_width=True, config={"displayModeBar": False})

                # AI Summary
                with st.expander("🤖 AI Market Summary", expanded=False):
                    _ai_res_key = f"_ai_res_{lat:.5f}_{lon:.5f}_{radius_miles:.2f}"
                    if st.button("Generate AI Summary", key="gen_ai_res"):
                        st.session_state[_ai_res_key] = None  # force refresh
                    if _ai_res_key not in st.session_state:
                        st.session_state[_ai_res_key] = None
                    if st.session_state[_ai_res_key] is None:
                        if anthropic_key:
                            with st.spinner("Generating AI market summary…"):
                                _summ_dict = summary_df[["Unit Type","Avg Rent","Median Rent"]].to_dict("records")
                                st.session_state[_ai_res_key] = _generate_ai_summary(
                                    "residential rental", _summ_dict, listings[:10], anthropic_key
                                )
                        else:
                            st.caption("Add an Anthropic API key in the sidebar to enable AI summaries.")
                    if st.session_state.get(_ai_res_key):
                        st.markdown(st.session_state[_ai_res_key])

                # All Listings
                _res_display = []
                for _rl in listings:
                    _sq = _rl.get("sqft") or 0
                    _rt = _rl.get("rent") or 0
                    _psf = f"${_rt / _sq:.2f}" if _sq and _sq > 0 else "—"
                    _url = _rl.get("url") or ""
                    _link = (
                        f'<a href="{_url}" target="_blank" '
                        f'style="color:#8B6914;text-decoration:none;font-weight:600">View →</a>'
                        if _url else "—"
                    )
                    _res_display.append({
                        "Source":        _rl.get("source","—"),
                        "Reliability":   _rl.get("reliability", "—"),
                        "Address":       _rl.get("address","N/A"),
                        "Unit Type":     _rl.get("unit_type","—"),
                        "Beds":          _rl.get("bedrooms","—"),
                        "Rent/mo":       f"${_rt:,.0f}",
                        "$/SF":          _psf,
                        "Sqft":          _rl.get("sqft") or "—",
                        "Distance (mi)": f"{_rl.get('distance_miles',0):.2f}",
                        "Link":          _link,
                    })
                with st.expander(f"📋 All Residential Listings ({len(_res_display)} total)", expanded=False):
                    st.write(pd.DataFrame(_res_display).to_html(escape=False, index=False),
                             unsafe_allow_html=True)

            # ── Tab 2: Residential - Condo ───────────────────────────────────────
            with _tab_res_condo:
                # Reuses the same _sales_listings/_sales_status already fetched
                # once above for the whole Comparables Analysis section — no
                # new fetch. Filters specifically to condo building classes
                # (building_name holds the raw NYC Rolling Sales
                # building_class_category text, e.g. "13 CONDOS"), which is
                # narrower than the old "Residential" asset_type match that
                # also matched co-ops and one/two/three-family homes.
                _condo_sales = [l for l in _sales_listings if "CONDO" in str(l.get("building_name","")).upper()]
                if _condo_sales:
                    st.markdown("#### 🏢 Residential Condo Sale Comps")
                    _cs_prices = [l["price"] for l in _condo_sales if l.get("price")]
                    _cs_psf    = [l["price_psf"] for l in _condo_sales if l.get("price_psf")]
                    _cs_m1, _cs_m2, _cs_m3 = st.columns(3)
                    _cs_m1.metric("Sales Found",    len(_condo_sales))
                    _cs_m2.metric("Avg Sale Price", f"${int(sum(_cs_prices)/len(_cs_prices)):,}" if _cs_prices else "—")
                    _cs_m3.metric("Avg $/SF",       f"${sum(_cs_psf)/len(_cs_psf):.2f}" if _cs_psf else "—")

                    # Condo sales by unit type chart
                    _cs_rows_df = []
                    for _csl in _condo_sales:
                        _cs_rows_df.append({
                            "Address":    (_csl.get("address") or "—")[:60],
                            "Type":       _csl.get("asset_type","—"),
                            "Sale Price": f"${_csl['price']:,.0f}" if _csl.get("price") else "—",
                            "Sqft":       f"{_csl['sqft']:,}" if _csl.get("sqft") else "—",
                            "$/SF":       f"${_csl['price_psf']:.2f}" if _csl.get("price_psf") else "—",
                            "Date":       _csl.get("date","—"),
                            "Source":     _csl.get("source","—"),
                            "Reliability": _csl.get("reliability","—"),
                        })
                    # Condo sales bar chart (price by building_class_category)
                    _cs_by_type: dict = {}
                    for _csl in _condo_sales:
                        _bcc = _csl.get("building_name","")[:30] or _csl.get("asset_type","—")
                        _p   = _csl.get("price") or 0
                        if _p:
                            _cs_by_type.setdefault(_bcc, []).append(_p)
                    if _cs_by_type:
                        _cs_fig = go.Figure(go.Bar(
                            x=list(_cs_by_type.keys()),
                            y=[int(sum(v)/len(v)) for v in _cs_by_type.values()],
                            marker_color="#8B6914",
                        ))
                        _cs_fig.update_layout(
                            title="Avg Sale Price by Building Class",
                            xaxis_title="Class", yaxis_title="Avg Sale Price ($)",
                            height=300, margin=dict(l=40,r=20,t=40,b=60),
                            font=dict(size=11),
                        )
                        st.plotly_chart(_cs_fig, use_container_width=True,
                                        config={"displayModeBar": False})

                    with st.expander(f"📋 Residential Condo Sales ({len(_condo_sales)} found)", expanded=False):
                        st.dataframe(pd.DataFrame(_cs_rows_df), use_container_width=True,
                                     height=min(len(_cs_rows_df)*35+40, 340))
                elif str(_sales_status).startswith("error"):
                    st.warning(f"⚠️ NYC Rolling Sales fetch failed — condo sales unavailable: {_sales_status}")
                else:
                    st.info("No residential condo sales found within this radius.")

            # ── Tab 3: Commercial ────────────────────────────────────────────────
            with _tab_comm:
                _office_lst = [l for l in _comm_listings
                               if "office" in str(l.get("use_type") or l.get("asset_type","")).lower()
                               or ("retail" not in str(l.get("use_type") or l.get("asset_type","")).lower()
                                   and "industrial" not in str(l.get("use_type") or l.get("asset_type","")).lower())]
                _comm_for_tab = _office_lst if _office_lst else _comm_listings

                if not _comm_for_tab:
                    st.info("No commercial comps found. Try expanding the search radius.")
                else:
                    _co_rents = [l.get("rent") or l.get("price") or 0 for l in _comm_for_tab if l.get("rent") or l.get("price")]
                    _co_psf   = [l.get("psf_yr") or l.get("price_psf") or 0 for l in _comm_for_tab if l.get("psf_yr") or l.get("price_psf")]
                    _co_m1, _co_m2, _co_m3 = st.columns(3)
                    _co_m1.metric("Listings",    len(_comm_for_tab))
                    _co_m2.metric("Avg Rent/mo", f"${int(sum(_co_rents)/len(_co_rents)):,}" if _co_rents else "—")
                    _co_m3.metric("Avg $/SF/yr", f"${sum(_co_psf)/len(_co_psf):.2f}" if _co_psf else "—")

                    # Rent chart by use type
                    _co_by_type: dict = {}
                    for _cl in _comm_for_tab:
                        _ut = str(_cl.get("use_type") or _cl.get("asset_type") or "Other")[:30]
                        _rt = _cl.get("rent") or _cl.get("price") or 0
                        if _rt:
                            _co_by_type.setdefault(_ut, []).append(float(_rt))
                    if _co_by_type:
                        _co_fig = go.Figure(go.Bar(
                            x=list(_co_by_type.keys()),
                            y=[int(sum(v)/len(v)) for v in _co_by_type.values()],
                            marker_color="#8B6914",
                        ))
                        _co_fig.update_layout(
                            title="Avg Rent/mo by Use Type",
                            xaxis_title="Use Type", yaxis_title="Avg Rent/mo ($)",
                            height=280, margin=dict(l=40,r=20,t=40,b=60),
                            font=dict(size=11),
                        )
                        st.plotly_chart(_co_fig, use_container_width=True,
                                        config={"displayModeBar": False})

                # AI Summary
                with st.expander("🤖 AI Market Summary", expanded=False):
                    _ai_comm_key = f"_ai_comm_{lat:.5f}_{lon:.5f}_{radius_miles:.2f}"
                    if st.button("Generate AI Summary", key="gen_ai_comm"):
                        st.session_state[_ai_comm_key] = None
                    if _ai_comm_key not in st.session_state:
                        st.session_state[_ai_comm_key] = None
                    if st.session_state[_ai_comm_key] is None:
                        if anthropic_key and _comm_for_tab:
                            with st.spinner("Generating AI commercial summary…"):
                                _comm_summ = {"count": len(_comm_for_tab),
                                              "avg_rent": int(sum(_co_rents)/len(_co_rents)) if _co_rents else None,
                                              "avg_psf": round(sum(_co_psf)/len(_co_psf),2) if _co_psf else None}
                                st.session_state[_ai_comm_key] = _generate_ai_summary(
                                    "commercial office", _comm_summ, _comm_for_tab[:10], anthropic_key
                                )
                        else:
                            st.caption("Add an Anthropic API key in the sidebar to enable AI summaries.")
                    if st.session_state.get(_ai_comm_key):
                        st.markdown(st.session_state[_ai_comm_key])

                # All Listings
                if _comm_listings:
                    _co_disp = []
                    for _cl in _comm_listings:
                        _rt = _cl.get("rent") or _cl.get("price") or 0
                        _sq = _cl.get("sqft") or 0
                        _psf_v = _cl.get("psf_yr") or _cl.get("price_psf")
                        _co_disp.append({
                            "Source":    _cl.get("source","—"),
                            "Address":   (_cl.get("address") or "—")[:60],
                            "Use Type":  _cl.get("use_type") or _cl.get("asset_type") or "—",
                            "Rent/mo":   f"${_rt:,}" if _rt else "—",
                            "$/SF/yr":   f"${_psf_v:.2f}" if _psf_v else "—",
                            "Sqft":      f"{_sq:,}" if _sq else "—",
                            "Reliability": _cl.get("reliability","—"),
                        })
                    with st.expander(f"📋 All Commercial Listings ({len(_co_disp)} total)", expanded=False):
                        st.dataframe(pd.DataFrame(_co_disp), use_container_width=True,
                                     height=min(len(_co_disp)*35+40, 340))

                st.caption("Sources: Craigslist NYC · LoopNet · Crexi · No API key required")

            # ── Tab 4: Retail ────────────────────────────────────────────────────
            with _tab_retail:
                _retail_lst = [l for l in _comm_listings
                               if "retail" in str(l.get("use_type") or l.get("asset_type","")).lower()]

                if not _retail_lst:
                    st.info("No retail comps found. Try expanding the search radius.")
                else:
                    _rt_rents = [l.get("rent") or l.get("price") or 0 for l in _retail_lst if l.get("rent") or l.get("price")]
                    _rt_psf   = [l.get("psf_yr") or l.get("price_psf") or 0 for l in _retail_lst if l.get("psf_yr") or l.get("price_psf")]
                    _rt_m1, _rt_m2, _rt_m3 = st.columns(3)
                    _rt_m1.metric("Listings",    len(_retail_lst))
                    _rt_m2.metric("Avg Rent/mo", f"${int(sum(_rt_rents)/len(_rt_rents)):,}" if _rt_rents else "—")
                    _rt_m3.metric("Avg $/SF/yr", f"${sum(_rt_psf)/len(_rt_psf):.2f}" if _rt_psf else "—")

                    # Retail rent chart
                    _rt_by_src: dict = {}
                    for _rl in _retail_lst:
                        _src = _rl.get("source","Other")
                        _rv  = _rl.get("rent") or _rl.get("price") or 0
                        if _rv:
                            _rt_by_src.setdefault(_src, []).append(float(_rv))
                    if _rt_by_src:
                        _rt_fig = go.Figure(go.Bar(
                            x=list(_rt_by_src.keys()),
                            y=[int(sum(v)/len(v)) for v in _rt_by_src.values()],
                            marker_color="#1F6B3A",
                        ))
                        _rt_fig.update_layout(
                            title="Avg Retail Rent/mo by Source",
                            xaxis_title="Source", yaxis_title="Avg Rent/mo ($)",
                            height=280, margin=dict(l=40,r=20,t=40,b=60),
                            font=dict(size=11),
                        )
                        st.plotly_chart(_rt_fig, use_container_width=True,
                                        config={"displayModeBar": False})

                # AI Summary
                with st.expander("🤖 AI Market Summary", expanded=False):
                    _ai_ret_key = f"_ai_ret_{lat:.5f}_{lon:.5f}_{radius_miles:.2f}"
                    if st.button("Generate AI Summary", key="gen_ai_ret"):
                        st.session_state[_ai_ret_key] = None
                    if _ai_ret_key not in st.session_state:
                        st.session_state[_ai_ret_key] = None
                    if st.session_state[_ai_ret_key] is None:
                        if anthropic_key and _retail_lst:
                            with st.spinner("Generating AI retail summary…"):
                                _ret_summ = {"count": len(_retail_lst),
                                             "avg_rent": int(sum(_rt_rents)/len(_rt_rents)) if _rt_rents else None,
                                             "avg_psf": round(sum(_rt_psf)/len(_rt_psf),2) if _rt_psf else None}
                                st.session_state[_ai_ret_key] = _generate_ai_summary(
                                    "retail", _ret_summ, _retail_lst[:10], anthropic_key
                                )
                        else:
                            st.caption("Add an Anthropic API key in the sidebar to enable AI summaries.")
                    if st.session_state.get(_ai_ret_key):
                        st.markdown(st.session_state[_ai_ret_key])

                # All Listings
                if _retail_lst:
                    _ret_disp = []
                    for _rl in _retail_lst:
                        _rv = _rl.get("rent") or _rl.get("price") or 0
                        _sq = _rl.get("sqft") or 0
                        _pf = _rl.get("psf_yr") or _rl.get("price_psf")
                        _ret_disp.append({
                            "Source":    _rl.get("source","—"),
                            "Address":   (_rl.get("address") or "—")[:60],
                            "Use Type":  _rl.get("use_type") or _rl.get("asset_type") or "Retail",
                            "Rent/mo":   f"${_rv:,}" if _rv else "—",
                            "$/SF/yr":   f"${_pf:.2f}" if _pf else "—",
                            "Sqft":      f"{_sq:,}" if _sq else "—",
                            "Reliability": _rl.get("reliability","—"),
                        })
                    with st.expander(f"📋 All Retail Listings ({len(_ret_disp)} total)", expanded=False):
                        st.dataframe(pd.DataFrame(_ret_disp), use_container_width=True,
                                     height=min(len(_ret_disp)*35+40, 340))

                st.caption("Sources: Craigslist NYC · LoopNet · Crexi · No API key required")

            # ── Tab 5: Property Sales ─────────────────────────────────────────────
            with _tab_sales:
                if not _sales_listings:
                    st.info("No recent sales comps found. NYC Rolling Sales data may not cover this area/zip.")
                else:
                    _sp_prices = [l["price"] for l in _sales_listings if l.get("price")]
                    _sp_psf    = [l["price_psf"] for l in _sales_listings if l.get("price_psf")]
                    _sp_ppu    = [l["price_per_unit"] for l in _sales_listings if l.get("price_per_unit")]
                    _sp_m1, _sp_m2, _sp_m3, _sp_m4, _sp_m5 = st.columns(5)
                    _sp_m1.metric("Sales Found",    len(_sales_listings))
                    _sp_m2.metric("Avg Sale Price", f"${int(sum(_sp_prices)/len(_sp_prices)):,}" if _sp_prices else "—")
                    _sp_m3.metric("Avg $/SF",       f"${sum(_sp_psf)/len(_sp_psf):.2f}" if _sp_psf else "—")
                    _sp_m4.metric("Avg $/Unit",     f"${int(sum(_sp_ppu)/len(_sp_ppu)):,}" if _sp_ppu else "N/A",
                                  help="Only sales with a total-units figure on NYC Rolling Sales are included.")
                    # $/buildable SF: subject's own max-FAR buildable envelope
                    # (computed in the Underbuilt? panel above) against the
                    # area's avg sale price — not a per-comp buildable-SF
                    # figure (that would need a zoning lookup per sold
                    # parcel), but a genuine acquisition-basis-vs-buildable-
                    # envelope cross-reference for the subject site itself.
                    _sp_bsf = (sum(_sp_prices) / len(_sp_prices) / _ub_max_sf) if _sp_prices and _ub_max_sf > 0 else None
                    _sp_m5.metric("Avg Price ÷ Subject Buildable SF", f"${_sp_bsf:,.0f}" if _sp_bsf else "N/A",
                                  help="Area's avg sale price divided by the SUBJECT property's own max-FAR "
                                       "buildable SF — not a per-comp buildable-SF figure.")

                    # Sales chart: avg price by asset type
                    _sp_by_type: dict = {}
                    for _sl in _sales_listings:
                        _at = _sl.get("asset_type","—")
                        _p  = _sl.get("price") or 0
                        if _p:
                            _sp_by_type.setdefault(_at, []).append(float(_p))

                    if _sp_by_type:
                        _sp_fig = go.Figure(go.Bar(
                            x=list(_sp_by_type.keys()),
                            y=[int(sum(v)/len(v)) for v in _sp_by_type.values()],
                            marker_color="#8B6914",
                        ))
                        _sp_fig.update_layout(
                            title="Avg Sale Price by Asset Type",
                            xaxis_title="Asset Type", yaxis_title="Avg Sale Price ($)",
                            height=300, margin=dict(l=40,r=20,t=40,b=80),
                            font=dict(size=11),
                        )
                        st.plotly_chart(_sp_fig, use_container_width=True,
                                        config={"displayModeBar": False})

                    # $/SF by asset type
                    _sp_psf_by_type: dict = {}
                    for _sl in _sales_listings:
                        _at = _sl.get("asset_type","—")
                        _pf = _sl.get("price_psf") or 0
                        if _pf:
                            _sp_psf_by_type.setdefault(_at, []).append(float(_pf))
                    if _sp_psf_by_type:
                        _sp_psf_fig = go.Figure(go.Bar(
                            x=list(_sp_psf_by_type.keys()),
                            y=[round(sum(v)/len(v),2) for v in _sp_psf_by_type.values()],
                            marker_color="#1F6B3A",
                        ))
                        _sp_psf_fig.update_layout(
                            title="Avg $/SF by Asset Type",
                            xaxis_title="Asset Type", yaxis_title="Avg $/SF",
                            height=300, margin=dict(l=40,r=20,t=40,b=80),
                            font=dict(size=11),
                        )
                        st.plotly_chart(_sp_psf_fig, use_container_width=True,
                                        config={"displayModeBar": False})

                    # Price trend over time ($/SF vs. sale date, by asset type)
                    _sp_trend_pts = [
                        (_sl["date"], _sl["price_psf"], _sl.get("asset_type", "—"))
                        for _sl in _sales_listings if _sl.get("date") and _sl.get("price_psf")
                    ]
                    if len(_sp_trend_pts) >= 2:
                        _sp_trend_fig = go.Figure()
                        for _at in sorted({p[2] for p in _sp_trend_pts}):
                            _pts = sorted((p for p in _sp_trend_pts if p[2] == _at), key=lambda p: p[0])
                            _sp_trend_fig.add_trace(go.Scatter(
                                x=[p[0] for p in _pts], y=[p[1] for p in _pts],
                                mode="markers", name=_at,
                            ))
                        _sp_trend_fig.update_layout(
                            title="Sale $/SF Over Time", xaxis_title="Sale Date", yaxis_title="$/SF",
                            height=300, margin=dict(l=40, r=20, t=40, b=40), font=dict(size=11),
                        )
                        st.plotly_chart(_sp_trend_fig, use_container_width=True,
                                        config={"displayModeBar": False})

                # AI Summary
                with st.expander("🤖 AI Market Summary", expanded=False):
                    _ai_sales_key = f"_ai_sales_{lat:.5f}_{lon:.5f}_{radius_miles:.2f}"
                    if st.button("Generate AI Summary", key="gen_ai_sales"):
                        st.session_state[_ai_sales_key] = None
                    if _ai_sales_key not in st.session_state:
                        st.session_state[_ai_sales_key] = None
                    if st.session_state[_ai_sales_key] is None:
                        if anthropic_key and _sales_listings:
                            with st.spinner("Generating AI sales summary…"):
                                _s_summ = {"count": len(_sales_listings),
                                           "avg_price": int(sum(_sp_prices)/len(_sp_prices)) if _sp_prices else None,
                                           "avg_psf": round(sum(_sp_psf)/len(_sp_psf),2) if _sp_psf else None}
                                st.session_state[_ai_sales_key] = _generate_ai_summary(
                                    "property sales", _s_summ, _sales_listings[:10], anthropic_key
                                )
                        else:
                            st.caption("Add an Anthropic API key in the sidebar to enable AI summaries.")
                    if st.session_state.get(_ai_sales_key):
                        st.markdown(st.session_state[_ai_sales_key])

                # All Sales
                if _sales_listings:
                    _sp_rows = []
                    for _sl in _sales_listings:
                        _sp_rows.append({
                            "Address":     (_sl.get("address") or "—")[:60],
                            "Type":        _sl.get("asset_type","—"),
                            "Sale Price":  f"${_sl['price']:,.0f}" if _sl.get("price") else "—",
                            "Sqft":        f"{_sl['sqft']:,}" if _sl.get("sqft") else "—",
                            "$/SF":        f"${_sl['price_psf']:.2f}" if _sl.get("price_psf") else "—",
                            "Units":       _sl.get("total_units") or "—",
                            "$/Unit":      f"${_sl['price_per_unit']:,.0f}" if _sl.get("price_per_unit") else "—",
                            "Date":        _sl.get("date","—"),
                            "Source":      _sl.get("source","—"),
                            "Reliability": _sl.get("reliability","—"),
                        })
                    with st.expander(f"📋 All Sales ({len(_sp_rows)} total)", expanded=False):
                        st.dataframe(pd.DataFrame(_sp_rows), use_container_width=True,
                                     height=min(len(_sp_rows)*35+40, 380))
                st.caption("Source: NYC Rolling Sales (usep-8jbt) · NYC Open Data · No API key required")

            # ── Tab 6: CityRealty Building Comparables ────────────────────────────
            with _tab_cr:
                st.markdown("#### 🏙️ CityRealty — Comparable Buildings")
                st.caption(
                    "Recent sales and rental listings from comparable buildings in the area. "
                    "Click any building name to view its full history on CityRealty.com."
                )
                _cr_key = f"_cr_{neighborhood.lower()}_{borough.lower()}"
                if _cr_key not in st.session_state:
                    with st.spinner("Searching CityRealty for comparable buildings…"):
                        _cr_comps_raw, _cr_status = fetch_cityrealty_comps(
                            address_input.strip(), neighborhood, borough, lat, lon
                        )
                    st.session_state[_cr_key] = {"comps": _cr_comps_raw, "status": _cr_status}
                _cr_data   = st.session_state.get(_cr_key, {})
                _cr_comps  = _cr_data.get("comps", [])
                _cr_st     = _cr_data.get("status", {})

                # Quick-access neighbourhood browse links
                _cr_rent_url = _cr_st.get("hood_rent_url", "")
                _cr_sale_url = _cr_st.get("hood_sale_url", "")
                _cr_srch_url = _cr_st.get("cr_search_url", "https://www.cityrealty.com")
                _cr_lnk_cols = st.columns(3)
                _cr_lnk_cols[0].markdown(f"[🏠 {neighborhood} Rentals ↗]({_cr_rent_url})" if _cr_rent_url else "")
                _cr_lnk_cols[1].markdown(f"[💰 {neighborhood} Sales ↗]({_cr_sale_url})" if _cr_sale_url else "")
                _cr_lnk_cols[2].markdown(f"[🔍 Search CityRealty ↗]({_cr_srch_url})" if _cr_srch_url else "")

                record_source_status(
                    "CityRealty Comps", ok=(_cr_st.get("status") != "error"),
                    detail="" if _cr_st.get("status") != "error" else str(_cr_st.get("status")),
                )
                if _cr_st.get("status") == "error":
                    st.warning("⚠️ CityRealty search failed — results below may be incomplete or missing.")

                if _cr_comps:
                    st.markdown("**📊 Comparable Buildings Summary**")
                    # Build table format with building details and CityRealty links
                    _cr_table_rows = []
                    for _crd in _cr_comps:
                        _bname  = _crd.get("building_name") or _crd.get("address") or "Building"
                        _addr   = _crd.get("address", "")
                        _link   = _crd.get("link", "")
                        _hist_link = _crd.get("history_link", _link)
                        _ltype  = _crd.get("listing_type", "")
                        _sale   = _crd.get("last_sale", "") or "—"

                        # Build clickable links
                        _bld_link = f"[{_bname}]({_link})" if _link else _bname
                        _hist_lnk = f"[Sales History ↗]({_hist_link})" if _hist_link else "—"
                        _rent_lnk = f"[Rental Listings ↗]({_hist_link.replace('/sales', '/rentals')})" if _hist_link else "—"

                        _cr_table_rows.append({
                            "Building": _bld_link,
                            "Address": _addr[:50],
                            "Type": _ltype.title() if _ltype else "—",
                            "Last Sale": _sale,
                            "Sales Link": _hist_lnk,
                            "Rentals Link": _rent_lnk,
                        })

                    # Display as DataFrame table
                    _cr_df = pd.DataFrame(_cr_table_rows)
                    st.dataframe(
                        _cr_df,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Building": st.column_config.TextColumn("Building", width=180),
                            "Address": st.column_config.TextColumn("Address", width=150),
                            "Type": st.column_config.TextColumn("Type", width=90),
                            "Last Sale": st.column_config.TextColumn("Last Sale", width=100),
                            "Sales Link": st.column_config.LinkColumn("Sales History", width=120, display_text="View ↗"),
                            "Rentals Link": st.column_config.LinkColumn("Rentals", width=110, display_text="View ↗"),
                        },
                        height=min(400, 50 + 35 * len(_cr_table_rows)),
                    )

                    st.markdown("**💡 How to use:**")
                    st.caption(
                        "• Click any **Building** name to see the full property page on CityRealty\n"
                        "• Click **Sales History** to view recent sales/purchase prices\n"
                        "• Click **Rentals** to see current and recent rental listings\n"
                        "Use this data to benchmark your property's market position."
                    )
                else:
                    st.info(
                        f"No CityRealty building results found for **{neighborhood}**. "
                        f"Browse directly: [Rentals ↗]({_cr_rent_url}) · [Sales ↗]({_cr_sale_url}) · "
                        f"[Search ↗]({_cr_srch_url})"
                    )

                st.markdown("---")
                st.caption(
                    f"**Data Sources:** [CityRealty.com]({_cr_srch_url}) · "
                    "Building search via DuckDuckGo · No authentication required\n"
                    "Links point directly to CityRealty's official building pages with full transaction history"
                )

            # ── Photo Gallery (horizontal scroll carousel) ─────────────────────
            _photos_avail = [l for l in listings if l.get("photos")]
            if _photos_avail:
                st.markdown("---")
                st.markdown(
                    "<div class='section-label'>🖼️ Photo Gallery</div>",
                    unsafe_allow_html=True,
                )
                st.caption(
                    f"{len(_photos_avail)} listings have photos · "
                    "Scroll right to see more · Click any card to view listing"
                )

                def _gallery_card(listing: dict) -> str:
                    photo   = listing["photos"][0] if listing["photos"] else ""
                    rent    = listing.get("rent", 0)
                    utype   = listing.get("unit_type", "")
                    addr    = listing.get("address", "")[:34]
                    src     = listing.get("source", "")
                    url     = listing.get("url", "") or "#"
                    sqft    = listing.get("sqft")
                    sqft_s  = f" · {sqft:,.0f} SF" if sqft else ""
                    return (
                        f'<a href="{url}" target="_blank" class="gallery-card">'
                        f'<img src="{photo}" alt="{addr}" loading="lazy" '
                        f'onerror="this.style.display=\'none\'">'
                        f'<div class="gc-caption">'
                        f'<b>${rent:,.0f}/mo</b> · {utype}{sqft_s}<br>'
                        f'<span style="color:#6B7280">{addr}</span><br>'
                        f'<span class="gc-badge">{src}</span>'
                        f'</div></a>'
                    )

                # Row 1 — sorted by rent ascending (most affordable first)
                _row1 = sorted(_photos_avail, key=lambda x: x.get("rent", 0))[:12]
                # Row 2 — sorted by rent descending (most expensive)
                _row2 = sorted(_photos_avail, key=lambda x: x.get("rent", 0), reverse=True)[:12]

                _row1_html = "".join(_gallery_card(l) for l in _row1)
                _row2_html = "".join(_gallery_card(l) for l in _row2)

                st.markdown(
                    f"<div style='margin-bottom:4px;font-size:0.72rem;color:#6B7280;font-weight:600'>"
                    f"MOST AFFORDABLE</div>"
                    f"<div class='gallery-scroll-row'>{_row1_html}</div>"
                    f"<div style='margin-bottom:4px;margin-top:6px;font-size:0.72rem;color:#6B7280;font-weight:600'>"
                    f"PREMIUM LISTINGS</div>"
                    f"<div class='gallery-scroll-row'>{_row2_html}</div>",
                    unsafe_allow_html=True,
                )

            # ── Neighborhood Overview ───────────────────────────────────────────
            _section_header("🏘️", f"Neighborhood Overview — {neighborhood}")
            _hood_key = f"_hood_{neighborhood.lower()}_{borough.lower()}"
            if _hood_key not in st.session_state:
                with st.spinner(f"Researching {neighborhood} market data…"):
                    st.session_state[_hood_key] = fetch_neighborhood_data(neighborhood, borough)
            _hood_data = st.session_state.get(_hood_key, {})

            if _hood_data and not _hood_data.get("error"):
                _hb_res  = _hood_data.get("residential", "")
                _hb_com  = _hood_data.get("commercial", "")
                _hb_list = _hood_data.get("bullets", [])
                _hb_src  = _hood_data.get("sources", [])
                _res_d   = _hood_data.get("res_data", {})
                _ret_d   = _hood_data.get("retail_data", {})
                _com_d   = _hood_data.get("commercial_data", {})

                if _hb_res or _hb_com or _hb_list or _res_d.get("studio_rent") or _ret_d.get("asking_rent_psf"):
                    # ── Structured data cards ──────────────────────────────────
                    _hc1, _hc2, _hc3 = st.columns(3)
                    with _hc1:
                        st.markdown("**🏠 Residential Rents**")
                        _res_rows = [
                            ("Studio",    _res_d.get("studio_rent")),
                            ("1 Bed",     _res_d.get("one_bd_rent")),
                            ("2 Bed",     _res_d.get("two_bd_rent")),
                            ("3 Bed",     _res_d.get("three_bd_rent")),
                        ]
                        _any_res = any(v for _, v in _res_rows)
                        if _any_res:
                            for _label, _val in _res_rows:
                                _vstr = f"${_val:,}/mo" if _val else "—"
                                st.markdown(
                                    f"<div style='display:flex;justify-content:space-between;font-size:0.83rem;"
                                    f"padding:2px 0;border-bottom:1px solid #E8E3D4'>"
                                    f"<span style='color:#6B7280'>{_label}</span>"
                                    f"<b>{_vstr}</b></div>",
                                    unsafe_allow_html=True,
                                )
                            if _res_d.get("condo_psf"):
                                st.caption(f"Condo: ${_res_d['condo_psf']:,}/SF")
                        else:
                            if _hb_res:
                                st.markdown(f"<div style='font-size:0.84rem;color:#3D4152;padding:4px 0'>{_hb_res[:200]}</div>", unsafe_allow_html=True)
                    with _hc2:
                        st.markdown("**🏪 Retail Rents**")
                        if _ret_d.get("asking_rent_psf"):
                            st.markdown(
                                f"<div style='font-size:1.1rem;font-weight:700;color:#1A1D2E'>"
                                f"${_ret_d['asking_rent_psf']:,} <span style='font-size:0.75rem;font-weight:400;color:#6B7280'>/SF/yr asking</span></div>",
                                unsafe_allow_html=True,
                            )
                        if _ret_d.get("vacancy_pct"):
                            st.caption(f"Vacancy: {_ret_d['vacancy_pct']:.1f}%")
                        if _ret_d.get("tenant_types"):
                            st.markdown(
                                " ".join(f"<span style='background:#E8E3D4;color:#4C5FA6;border-radius:12px;padding:2px 8px;font-size:0.72rem;margin:2px'>{t}</span>" for t in _ret_d["tenant_types"]),
                                unsafe_allow_html=True,
                            )
                        if not _ret_d.get("asking_rent_psf") and _hb_com:
                            st.markdown(f"<div style='font-size:0.84rem;color:#3D4152;padding:4px 0'>{_hb_com[:200]}</div>", unsafe_allow_html=True)
                    with _hc3:
                        st.markdown("**🏢 Commercial / Office**")
                        if _com_d.get("asking_rent_psf"):
                            st.markdown(
                                f"<div style='font-size:1.1rem;font-weight:700;color:#1A1D2E'>"
                                f"${_com_d['asking_rent_psf']:,} <span style='font-size:0.75rem;font-weight:400;color:#6B7280'>/SF/yr asking</span></div>",
                                unsafe_allow_html=True,
                            )
                        if _com_d.get("vacancy_pct"):
                            st.caption(f"Vacancy: {_com_d['vacancy_pct']:.1f}%")
                        if _com_d.get("tenant_types"):
                            st.markdown(
                                " ".join(f"<span style='background:#E4E8F1;color:#8B6914;border-radius:12px;padding:2px 8px;font-size:0.72rem;margin:2px'>{t}</span>" for t in _com_d["tenant_types"]),
                                unsafe_allow_html=True,
                            )

                    # ── Market Insights ────────────────────────────────────────
                    if _hb_list:
                        st.markdown("**📊 Market Insights**")
                        for _b in _hb_list[:6]:
                            st.markdown(f"- {_b}")

                    if _hb_src:
                        with st.expander(f"Sources ({len(_hb_src)})", expanded=False):
                            for _s in _hb_src[:8]:
                                _stitle = _s.get("title", "")
                                _surl   = _s.get("url", "")
                                if _stitle and _surl:
                                    st.markdown(f"- [{_stitle}]({_surl})")
                else:
                    st.info(f"No neighborhood data found for {neighborhood}.")
            elif _hood_data and _hood_data.get("error"):
                st.info(f"Neighborhood data unavailable: {_hood_data['error']}")

            # ── Competing / Comparable Developments ────────────────────────────
            _section_header("🏗️", "Competing & Comparable Developments")
            st.caption(
                f"Recent or under-construction residential developments in {neighborhood}, "
                "sourced from real estate trade press RSS feeds (The Real Deal, Commercial "
                "Observer, Bisnow, Crain's NY, PincusCo — the last two best-effort, see below) "
                "with a web-search fallback."
            )
            st.caption(
                "ℹ️ Crain's New York Business and PincusCo don't have a confirmed public RSS "
                "feed — those two sources may contribute nothing even when the others find "
                "results. PincusCo's full news feed is a paid subscription; only a public "
                "teaser feed (if one exists) is attempted here, consistent with this app's "
                "free/keyless-only design."
            )

            _comps_key = f"_comps_{neighborhood.lower()}_{zip_code}"
            if _comps_key not in st.session_state:
                with st.spinner(f"Researching competing developments in {neighborhood}…"):
                    _cd_devs, _cd_status = search_competing_devs(
                        neighborhood, borough, lat, lon, zip_code
                    )
                st.session_state[_comps_key] = {"devs": _cd_devs, "status": _cd_status}
                record_source_status(
                    "Competing Developments", ok=(_cd_status != "error"),
                    detail="" if _cd_status != "error" else "RSS + web search fallback all failed",
                )
            _comps_data = st.session_state.get(_comps_key, {})
            _comp_devs = _comps_data.get("devs", [])
            _comp_devs_status = _comps_data.get("status", "")

            if _comp_devs_status == "error":
                st.warning("⚠️ Competing-development search failed — results below may be incomplete or missing.")

            if _comp_devs:
                # ── Pipeline Summary ──────────────────────────────────────────
                _pipeline_sum = generate_pipeline_summary(_comp_devs, neighborhood)
                st.markdown("**📋 Development Pipeline Summary**")
                st.markdown(_pipeline_sum)

                # Map
                _comp_map = folium.Map(
                    location=[lat, lon],
                    zoom_start=14,
                    tiles="CartoDB positron",
                )
                folium.Marker(
                    [lat, lon],
                    tooltip="Subject Property",
                    icon=folium.Icon(color="red", icon="home", prefix="fa"),
                ).add_to(_comp_map)
                for _cd in _comp_devs:
                    if _cd.get("lat") and _cd.get("lon"):
                        _popup_html = (
                            f"<b>{_cd['name']}</b><br>"
                            f"{_cd.get('address','')}<br>"
                            + (f"~{_cd['units']} units<br>" if _cd.get("units") else "")
                            + (f"Est. ${_cd['est_rent_min']:,}–${_cd['est_rent_max']:,}/mo<br>"
                               if _cd.get("est_rent_min") else "")
                            + (f"<a href='{_cd['source_url']}' target='_blank'>Source →</a>"
                               if _cd.get("source_url") else "")
                        )
                        folium.Marker(
                            [_cd["lat"], _cd["lon"]],
                            tooltip=_cd["name"][:40],
                            popup=folium.Popup(_popup_html, max_width=260),
                            icon=folium.Icon(color="purple", icon="building", prefix="fa"),
                        ).add_to(_comp_map)

                _cm1, _cm2 = st.columns([3, 2])
                with _cm1:
                    st_folium(_comp_map, width=None, height=340,
                              returned_objects=[], key="comps_map")
                with _cm2:
                    _cd_rows = []
                    for _cd in _comp_devs:
                        _rent_s = "—"
                        if _cd.get("est_rent_min") and _cd.get("est_rent_max"):
                            _rent_s = f"${_cd['est_rent_min']:,}–${_cd['est_rent_max']:,}"
                        elif _cd.get("est_rent_min"):
                            _rent_s = f"${_cd['est_rent_min']:,}+"
                        _cd_rows.append({
                            "Development": _cd.get("name", "—")[:40],
                            "Address":     _cd.get("address", "—")[:35],
                            "Units":       _cd.get("units", "—") or "—",
                            "Est. Rent":   _rent_s,
                            "Source":      _cd.get("source_url", "") or "",
                        })
                    if _cd_rows:
                        _cd_df = pd.DataFrame(_cd_rows)
                        st.dataframe(
                            _cd_df,
                            use_container_width=True,
                            hide_index=True,
                            height=min(340, 40 + 35 * len(_cd_rows)),
                            column_config={
                                "Source": st.column_config.LinkColumn(
                                    "Source", display_text="View →"
                                )
                            },
                        )
            else:
                st.info(
                    "No competing development data found for this neighborhood. "
                    "This may be due to limited search results or a network issue."
                )

            # ── Recent News & Transactions ─────────────────────────────────────
            _section_header("📰", "Recent News & Transactions")
            st.caption(
                "Sourced from The Real Deal, Commercial Observer, Bisnow, Google News, Crain's NY "
                "and PincusCo RSS feeds (last two best-effort — see the Competing Developments "
                "note above), with a web-search fallback if the feeds find nothing."
            )
            _articles_key = f"_articles_{address_input.strip()[:40].lower()}_{neighborhood.lower()}"
            if _articles_key not in st.session_state:
                with st.spinner("Searching real estate news…"):
                    _art_list, _art_status = fetch_nearby_articles(
                        address_input.strip(), neighborhood, borough
                    )
                st.session_state[_articles_key] = {"articles": _art_list, "status": _art_status}
                record_source_status(
                    "News & Transactions", ok=(_art_status != "error"),
                    detail="" if _art_status != "error" else "RSS + web search fallback all failed",
                )
            _articles_data = st.session_state.get(_articles_key, {})
            _articles = _articles_data.get("articles", [])
            _articles_status = _articles_data.get("status", "")

            if _articles_status == "error":
                st.warning("⚠️ News search failed — results below may be incomplete or missing.")

            if _articles:
                _art_cols = st.columns(2)
                for _ai, _art in enumerate(_articles[:8]):
                    _src = _art.get("source", {})
                    _bg  = _src.get("bg", "#6B7280")
                    _fg  = _src.get("fg", "#FFFFFF")
                    _lbl = _src.get("label", "Web")
                    _dt  = _art.get("date_approx", "")
                    with _art_cols[_ai % 2]:
                        st.markdown(
                            f"<div style='background:#FFFFFF;border:1px solid #DCD5C2;"
                            f"border-radius:10px;padding:10px 14px;margin-bottom:8px'>"
                            f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:4px'>"
                            f"<span style='background:{_bg};color:{_fg};border-radius:10px;padding:2px 8px;font-size:0.68rem;font-weight:700'>{_lbl}</span>"
                            f"<span style='font-size:0.68rem;color:#9CA3AF'>{_dt}</span>"
                            f"</div>"
                            f"<div style='font-size:0.82rem;font-weight:600;color:#1A1D2E;margin-bottom:4px'>"
                            f"<a href='{_art['url']}' target='_blank' style='color:#1A1D2E;text-decoration:none'>"
                            f"{_art['title'][:80]}{'…' if len(_art['title']) > 80 else ''}</a></div>"
                            f"<div style='font-size:0.75rem;color:#6B7280;line-height:1.4'>{_art.get('snippet','')[:150]}</div>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )
            else:
                st.info(f"No news articles found for {neighborhood}. Results may be limited by search availability.")

            # ── NYC Zoning Information (ZOLA / PLUTO) ─────────────────────────
            _section_header("📐", "Zoning & Property Data", "NYC Planning ZOLA · PLUTO · ACRIS")

            # Subject property — auto-fetched, keyed by lat/lon so it updates
            # automatically whenever the main search address changes.
            _subject_addr   = st.session_state.get("address_raw", geo.get("formatted_address", ""))
            _zola_subj_key  = f"_zola_subject_{lat:.5f}_{lon:.5f}"

            # Same key as CELL 1's pre-fetch above — only treat it as "done"
            # if it actually succeeded, so a transient failure doesn't
            # permanently block this section (Zoning Summary, massing/floor
            # plates, Underwriting, Export, Risk Analysis) for the session.
            _zola_subj_cached = st.session_state.get(_zola_subj_key)
            if (_zola_subj_cached is None or "error" in _zola_subj_cached) and _subject_addr:
                with st.spinner("Fetching zoning data from NYC Planning…"):
                    st.session_state[_zola_subj_key] = fetch_zoning_info(
                        _subject_addr, lat=lat, lon=lon
                    )

            # Active zoning info — default to subject property
            _zinfo = st.session_state.get(_zola_subj_key)

            # Optional override for a different address
            with st.expander("🔍 Look up a different address", expanded=False):
                _ov_col1, _ov_col2 = st.columns([4, 1])
                with _ov_col1:
                    _ov_addr = st.text_input(
                        "Address",
                        key="zola_override_input",
                        placeholder="e.g. 350 West 42nd St, Manhattan",
                        label_visibility="collapsed",
                    )
                with _ov_col2:
                    _ov_btn = st.button("Look Up", key="zola_lookup_btn")
                if _ov_addr and len(_ov_addr.strip()) >= 3:
                    _ov_ac_key = f"_ac_suggest_{_ov_addr.strip().lower()}"
                    if _ov_ac_key not in st.session_state:
                        from modules.zola_fetcher import geosearch_autocomplete
                        st.session_state[_ov_ac_key] = geosearch_autocomplete(_ov_addr.strip())
                    _ov_suggestions = st.session_state.get(_ov_ac_key, [])
                    if _ov_suggestions:
                        _ov_ac_cols = st.columns(min(3, len(_ov_suggestions)))
                        for _ov_ac_i, _ov_ac_s in enumerate(_ov_suggestions):
                            with _ov_ac_cols[_ov_ac_i % len(_ov_ac_cols)]:
                                if st.button(_ov_ac_s["label"][:40], key=f"_ov_ac_btn_{_ov_ac_key}_{_ov_ac_i}", use_container_width=True):
                                    st.session_state["zola_override_input"] = _ov_ac_s["label"]
                                    st.rerun()
                if _ov_btn and _ov_addr.strip():
                    _ov_cache = f"_zola_ov_{_ov_addr.strip().lower()}"
                    if _ov_cache not in st.session_state:
                        with st.spinner("Fetching…"):
                            st.session_state[_ov_cache] = fetch_zoning_info(
                                _ov_addr.strip(), lat=lat, lon=lon
                            )
                    st.session_state["_zola_active_override"] = _ov_cache

            # Use override if set
            _ov_active = st.session_state.get("_zola_active_override")
            if _ov_active and _ov_active in st.session_state:
                _zinfo = st.session_state[_ov_active]
                _zinfo_label = st.session_state.get("zola_override_input", "")
            else:
                _zinfo_label = _subject_addr

            st.caption(
                f"Analyzing: **{_zinfo_label}** &nbsp;·&nbsp; "
                "Data via NYC Planning Labs GeoSearch + PLUTO. No API key required."
            )

            if _zinfo:
                if "error" in _zinfo:
                    st.warning(f"Zoning lookup: {_zinfo['error']}")
                    if st.button("🔄 Retry zoning lookup", key="_zinfo_retry_btn"):
                        st.session_state.pop(_ov_active if _ov_active else _zola_subj_key, None)
                        st.rerun()
                else:
                    # ── Header: BBL + ZOLA link ──────────────────────────────
                    _bbl_disp = _zinfo.get("bbl", "—")
                    _zola_url = _zinfo.get("zola_url", "")
                    _matched  = _zinfo.get("matched_label", "")
                    _zola_link = (
                        f'&nbsp;&nbsp;<a href="{_zola_url}" target="_blank" '
                        f'style="color:#8B6914;font-weight:600">View on ZOLA →</a>'
                        if _zola_url else ""
                    )
                    st.markdown(
                        f"<div style='margin-bottom:12px;padding:8px 12px;"
                        f"background:#E8E3D4;border-radius:8px;border-left:3px solid #8B6914'>"
                        f"<b>BBL:</b> {_bbl_disp} &nbsp;·&nbsp; "
                        f"Borough {_zinfo.get('borough_code','—')} &nbsp;·&nbsp; "
                        f"Block {_zinfo.get('block','—')} &nbsp;·&nbsp; "
                        f"Lot {_zinfo.get('lot','—')}"
                        f"{_zola_link}"
                        f"<br><span style='color:#6B7280;font-size:0.82rem'>{_matched}</span>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

                    if _bbl_disp and _bbl_disp != "—":
                        if st.button("☆ Save to Portfolio", key="pa_save_to_portfolio"):
                            from modules.portfolio_db import save_property
                            _pa_save_dict = _map_zinfo_to_portfolio_schema(_zinfo, _zinfo_label, lat, lon)
                            # Carry over the same Deal Score / tax-abatement /
                            # rent-stabilization signals already computed
                            # on-screen for this property, so a save from this
                            # tab is as rich as a Site Finder save (previously
                            # these were silently dropped — see the Portfolio
                            # comparison-view data-parity note in the review).
                            _pa_score = st.session_state.get("_ds_last_score_result")
                            if _pa_score:
                                _pa_save_dict["deal_score"] = _pa_score
                            _pa_abate = st.session_state.get(f"_abate_{_bbl_disp}")
                            if _pa_abate:
                                _pa_save_dict["tax_abatement"] = _pa_abate
                            _pa_rentstab = st.session_state.get(f"_rentstab_{_bbl_disp}")
                            if _pa_rentstab:
                                _pa_save_dict["rent_stab_signal"] = _pa_rentstab
                            save_property(_pa_save_dict, status="Watching")
                            st.success("Saved to Portfolio.")

                    # ── ACRIS Property History ───────────────────────────────
                    _acris_key = f"_acris_{_bbl_disp}"
                    if _acris_key not in st.session_state and _bbl_disp != "—":
                        with st.spinner("Fetching ACRIS document history…"):
                            st.session_state[_acris_key] = fetch_acris(_bbl_disp)
                            record_source_status(
                                "ACRIS",
                                ok=(not st.session_state[_acris_key].get("error")),
                                detail=st.session_state[_acris_key].get("error") or "",
                            )
                    _acris = st.session_state.get(_acris_key, {})
                    _acris_sum = _acris.get("summary", {}) if _acris else {}
                    if _acris and _acris.get("acris_url"):
                        st.session_state["_acris_data_url"] = _acris["acris_url"]

                    if _acris_sum:
                        # Confidence badge
                        _acris_conf = _acris.get("confidence", "None")
                        _acris_method = _acris.get("match_method", "")
                        _conf_color = {"High": "#1F6B3A", "Medium": "#8B6914", "Low": "#7A2E2E", "None": "#6B7280"}.get(_acris_conf, "#6B7280")
                        st.markdown(
                            f"<span style='background:{_conf_color};color:white;padding:2px 8px;"
                            f"border-radius:10px;font-size:0.68rem;font-weight:700'>"
                            f"Match Confidence: {_acris_conf}</span> "
                            f"<span style='font-size:0.68rem;color:#6B7280'>{_acris_method}</span>",
                            unsafe_allow_html=True,
                        )
                        _ac1, _ac2, _ac3, _ac4 = st.columns(4)
                        def _acris_card(col, icon, label, value, sub=""):
                            with col:
                                st.markdown(
                                    f"<div style='background:#FFFFFF;border:1px solid #DCD5C2;"
                                    f"border-radius:10px;padding:10px 14px;margin-bottom:8px'>"
                                    f"<div style='font-size:0.68rem;color:#6B7280;font-weight:700;"
                                    f"text-transform:uppercase;letter-spacing:0.06em'>{icon} {label}</div>"
                                    f"<div style='font-size:1.05rem;font-weight:700;color:#1A1D2E;"
                                    f"margin:2px 0'>{value}</div>"
                                    f"<div style='font-size:0.72rem;color:#9CA3AF'>{sub}</div>"
                                    f"</div>",
                                    unsafe_allow_html=True,
                                )

                        _sale_price = _acris_sum.get("latest_sale_price")
                        _sale_date  = _acris_sum.get("latest_sale_date", "—") or "—"
                        _acris_card(_ac1, "🏷️", "Last Sale",
                                    f"${_sale_price:,.0f}" if _sale_price else "—",
                                    _sale_date[:7] if _sale_date != "—" else "")

                        _mtge_amt = _acris_sum.get("active_mortgage_amt")
                        _acris_card(_ac2, "🏦", "Mortgage",
                                    f"${_mtge_amt:,.0f}" if _mtge_amt else "—",
                                    (_acris_sum.get("active_lender") or "")[:28])

                        _acris_card(_ac3, "✈️", "Air Rights",
                                    "Available" if _acris_sum.get("has_air_rights") else "None found",
                                    f"{len(_acris.get('air_rights',[]))} doc(s)" if _acris_sum.get("has_air_rights") else "")

                        _acris_card(_ac4, "📋", "UCC / Liens",
                                    str(_acris_sum.get("open_liens", 0)),
                                    f"{_acris_sum.get('total_docs', 0)} docs · "
                                    f"{_acris_sum.get('foreclosure_count', 0)} forecl.")

                        _acris_url = _acris.get("acris_url", "")
                        _acris_block = str(_zinfo.get("block", "")).zfill(5)
                        _acris_lot   = str(_zinfo.get("lot", "")).zfill(4)
                        _acris_bbl_label = f"Block: {_acris_block} · Lot: {_acris_lot}" if _acris_block.strip("0") else ""
                        if _acris_url:
                            st.caption(
                                f"Document history from [NYC ACRIS]({_acris_url}) · "
                                f"{_acris_sum.get('total_docs', 0)} recorded documents"
                                + (f" · {_acris_bbl_label}" if _acris_bbl_label else "")
                            )

                        with st.expander("📜 Full Property History (ACRIS)", expanded=False):
                            _all_docs = _acris.get("documents", [])
                            if _all_docs:
                                _doc_rows = []
                                for _d in _all_docs[:80]:
                                    _parties_str = "; ".join(
                                        f"{p['role']}: {p['name']}" for p in _d.get("parties", [])
                                    )
                                    _amt = _d.get("amount")
                                    # Determine category tag
                                    _dt = str(_d.get("doc_type", "")).upper()
                                    if any(x in _dt for x in ("DEED", "SPECDEED")):
                                        _cat = "Sale/Deed"
                                    elif any(x in _dt for x in ("MTGE", "MORTGAGE", "LNAGMT")):
                                        _cat = "Mortgage"
                                    elif any(x in _dt for x in ("FORECL", "LIS PEN", "DEFAULT")):
                                        _cat = "Foreclosure"
                                    elif _dt.startswith("UCC"):
                                        _cat = "UCC/Lien"
                                    elif any(x in _dt for x in ("AIR", "DEVEL", "TRIGHT")):
                                        _cat = "Air Rights"
                                    elif "ASSG" in _dt:
                                        _cat = "Assignment"
                                    else:
                                        _cat = "Other"
                                    _doc_rows.append({
                                        "Date":      _d.get("date", "—"),
                                        "Category":  _cat,
                                        "Doc Type":  _d.get("doc_type", "—"),
                                        "Amount":    f"${_amt:,.0f}" if _amt and _amt > 0 else "—",
                                        "Parties":   _parties_str[:70] or "—",
                                        "Doc Link":  _d.get("doc_url", ""),
                                    })
                                _doc_df = pd.DataFrame(_doc_rows)
                                st.dataframe(
                                    _doc_df,
                                    use_container_width=True,
                                    hide_index=True,
                                    height=min(500, 40 + 35 * len(_doc_rows)),
                                    column_config={
                                        "Doc Link": st.column_config.LinkColumn(
                                            "Doc Link", display_text="View →"
                                        )
                                    },
                                )
                            else:
                                st.info("No ACRIS documents found for this BBL.")

                        # ── Extract and display ACRIS Sales, Mortgages, Liens ───────
                        st.markdown("---")

                        _sales = _extract_sales_from_acris(_acris)
                        _mortgages = _extract_mortgages_from_acris(_acris)
                        _liens = _extract_liens_from_acris(_acris)

                        # Sales History table
                        if _sales:
                            st.markdown(
                                "<div style='font-size:0.72rem;font-weight:700;letter-spacing:0.08em;"
                                "text-transform:uppercase;color:#6B7280;margin-bottom:8px'>"
                                "💰 Sales History (ACRIS)</div>",
                                unsafe_allow_html=True,
                            )
                            _sales_rows = [{
                                "Date":       s.get("date", ""),
                                "Seller":     s.get("seller", "")[:50],
                                "Buyer":      s.get("buyer", "")[:50],
                                "Price":      f"${s.get('amount', 0):,.0f}" if s.get('amount') else "—",
                                "Doc Type":   s.get("doc_type", ""),
                                "Doc Link":   s.get("doc_url", ""),
                            } for s in _sales[:30]]
                            st.dataframe(
                                pd.DataFrame(_sales_rows),
                                use_container_width=True,
                                hide_index=True,
                                height=min(400, 40 + 35 * len(_sales_rows)),
                                column_config={
                                    "Doc Link": st.column_config.LinkColumn(
                                        "Doc Link", display_text="View →"
                                    )
                                },
                            )
                            st.caption(f"Total: {len(_sales)} deeds/sales found")

                        # Mortgages table
                        if _mortgages:
                            st.markdown(
                                "<div style='font-size:0.72rem;font-weight:700;letter-spacing:0.08em;"
                                "text-transform:uppercase;color:#6B7280;margin-bottom:8px'>"
                                "🏦 Mortgages (ACRIS)</div>",
                                unsafe_allow_html=True,
                            )
                            _mtg_rows = [{
                                "Date":       m.get("date", ""),
                                "Lender":     m.get("lender", "")[:50],
                                "Borrower":   m.get("borrower", "")[:50],
                                "Amount":     f"${m.get('amount', 0):,.0f}" if m.get('amount') else "—",
                                "Doc Type":   m.get("doc_type", ""),
                                "Doc Link":   m.get("doc_url", ""),
                            } for m in _mortgages[:30]]
                            st.dataframe(
                                pd.DataFrame(_mtg_rows),
                                use_container_width=True,
                                hide_index=True,
                                height=min(400, 40 + 35 * len(_mtg_rows)),
                                column_config={
                                    "Doc Link": st.column_config.LinkColumn(
                                        "Doc Link", display_text="View →"
                                    )
                                },
                            )
                            st.caption(f"Total: {len(_mortgages)} mortgages found")

                        # Liens/UCC table
                        if _liens:
                            st.markdown(
                                "<div style='font-size:0.72rem;font-weight:700;letter-spacing:0.08em;"
                                "text-transform:uppercase;color:#6B7280;margin-bottom:8px'>"
                                "⚖️ Liens & UCC (ACRIS)</div>",
                                unsafe_allow_html=True,
                            )
                            _lien_rows = [{
                                "Date":       l.get("date", ""),
                                "Type":       l.get("type", ""),
                                "Parties":    l.get("parties", "")[:60],
                                "Doc Link":   l.get("doc_url", ""),
                            } for l in _liens[:30]]
                            st.dataframe(
                                pd.DataFrame(_lien_rows),
                                use_container_width=True,
                                hide_index=True,
                                height=min(400, 40 + 35 * len(_lien_rows)),
                                column_config={
                                    "Doc Link": st.column_config.LinkColumn(
                                        "Doc Link", display_text="View →"
                                    )
                                },
                            )
                            st.caption(f"Total: {len(_liens)} liens/UCC found")

                    # ── NYC Property Information Portal ───────────────────────
                    st.markdown("---")
                    st.markdown(
                        "<div style='font-size:0.72rem;font-weight:700;letter-spacing:0.08em;"
                        "text-transform:uppercase;color:#6B7280;margin-bottom:8px'>"
                        "🏛️ Full Property History — DOB, HPD & ECB Records</div>",
                        unsafe_allow_html=True,
                    )
                    _pip_key = f"_pip_{_bbl_disp}"
                    if _pip_key not in st.session_state and _bbl_disp != "—":
                        with st.spinner("Fetching DOB permits, complaints & violation history…"):
                            st.session_state[_pip_key] = fetch_property_history(
                                _bbl_disp,
                                borough_name=borough,
                                address=address_input.strip(),
                            )
                            record_source_status(
                                "DOB/HPD Property History",
                                ok=(not st.session_state[_pip_key].get("error")),
                                detail=st.session_state[_pip_key].get("error") or "",
                            )
                    _pip = st.session_state.get(_pip_key, {})
                    _pip_sum = _pip.get("summary", {}) if _pip else {}
                    _pip_url = _pip.get("pip_url", "")

                    if _pip_url:
                        st.markdown(
                            f"🔗 [View on NYC Property Information Portal ↗]({_pip_url})",
                        )

                    # ── Assessed Values (PLUTO) ───────────────────────────────
                    _assess_land = _zinfo.get("assess_land")
                    _assess_total = _zinfo.get("assess_total")
                    try:
                        _assess_land = float(_assess_land) if _assess_land else None
                    except (TypeError, ValueError):
                        _assess_land = None
                    try:
                        _assess_total = float(_assess_total) if _assess_total else None
                    except (TypeError, ValueError):
                        _assess_total = None
                    if _assess_land or _assess_total:
                        st.markdown(
                            "<div style='font-size:0.72rem;font-weight:700;letter-spacing:0.08em;"
                            "text-transform:uppercase;color:#6B7280;margin-bottom:8px'>"
                            "💵 Assessed Values (NYC PLUTO)</div>",
                            unsafe_allow_html=True,
                        )
                        _av1, _av2 = st.columns(2)
                        with _av1:
                            _land_val = f"${_assess_land:,.0f}" if _assess_land else "—"
                            st.markdown(
                                f"<div style='background:#FFFFFF;border:1px solid #DCD5C2;"
                                f"border-radius:8px;padding:12px 14px'>"
                                f"<div style='font-size:0.65rem;color:#6B7280;font-weight:700'>"
                                f"LAND VALUE</div>"
                                f"<div style='font-size:1.2rem;font-weight:700;color:#1A1D2E'>"
                                f"{_land_val}"
                                f"</div></div>",
                                unsafe_allow_html=True,
                            )
                        with _av2:
                            _total_val = f"${_assess_total:,.0f}" if _assess_total else "—"
                            st.markdown(
                                f"<div style='background:#FFFFFF;border:1px solid #DCD5C2;"
                                f"border-radius:8px;padding:12px 14px'>"
                                f"<div style='font-size:0.65rem;color:#6B7280;font-weight:700'>"
                                f"TOTAL VALUE</div>"
                                f"<div style='font-size:1.2rem;font-weight:700;color:#1A1D2E'>"
                                f"{_total_val}"
                                f"</div></div>",
                                unsafe_allow_html=True,
                            )

                    if _pip_sum:
                        _pp1, _pp2, _pp3, _pp4, _pp5 = st.columns(5)
                        def _pip_card(col, icon, label, val, sub=""):
                            with col:
                                st.markdown(
                                    f"<div style='background:#FFFFFF;border:1px solid #DCD5C2;"
                                    f"border-radius:8px;padding:8px 10px;text-align:center'>"
                                    f"<div style='font-size:0.62rem;color:#6B7280;font-weight:700;"
                                    f"text-transform:uppercase;letter-spacing:0.05em'>{icon} {label}</div>"
                                    f"<div style='font-size:1.1rem;font-weight:700;color:#1A1D2E;margin:2px 0'>{val}</div>"
                                    f"<div style='font-size:0.65rem;color:#9CA3AF'>{sub}</div>"
                                    f"</div>",
                                    unsafe_allow_html=True,
                                )
                        _pip_card(_pp1, "📋", "DOB Permits",    _pip_sum.get("total_permits", 0),
                                  f"{_pip_sum.get('active_permits', 0)} active")
                        _pip_card(_pp2, "🏗️", "DOB Jobs",       _pip_sum.get("total_jobs", 0),
                                  f"{_pip_sum.get('new_building_jobs', 0)} NB · {_pip_sum.get('alteration_jobs', 0)} Alt")
                        _pip_card(_pp3, "⚠️", "DOB Violations", _pip_sum.get("total_dob_viol", 0),
                                  f"{_pip_sum.get('open_dob_viol', 0)} open")
                        _pip_card(_pp4, "📣", "DOB Complaints",  _pip_sum.get("total_complaints", 0),
                                  f"{_pip_sum.get('open_complaints', 0)} open")
                        _pip_card(_pp5, "🏠", "Dwelling Units",  _pip_sum.get("dwelling_units", "—"), "HPD registered")

                        # ── Expandable DOB detail tables ──────────────────────
                        with st.expander("🏗️ DOB Job Filings", expanded=False):
                            _jobs = _pip.get("jobs", [])
                            if _jobs:
                                _job_rows = [{
                                    "Date":        j.get("filing_date", ""),
                                    "Job #":       j.get("job_number", ""),
                                    "Type":        j.get("job_type", ""),
                                    "Status":      j.get("job_status", ""),
                                    "Description": j.get("description", "")[:80],
                                    "Existing SF": j.get("existing_sqft", ""),
                                    "Proposed SF": j.get("proposed_sqft", ""),
                                    "Owner":       j.get("owner", "")[:30],
                                } for j in _jobs[:60]]
                                st.dataframe(pd.DataFrame(_job_rows), use_container_width=True,
                                             hide_index=True, height=min(400, 40+35*len(_job_rows)))
                            else:
                                st.info("No DOB job filings found.")

                        with st.expander("📋 DOB Permit Issuances", expanded=False):
                            _perms = _pip.get("permits", [])
                            if _perms:
                                _perm_rows = [{
                                    "Issued":      p.get("issuance_date", ""),
                                    "Expires":     p.get("expiration_date", ""),
                                    "Permit Type": p.get("permit_type", ""),
                                    "Job Type":    p.get("job_type", ""),
                                    "Status":      p.get("permit_status", ""),
                                    "Description": p.get("description", "")[:80],
                                    "Owner":       p.get("owner", "")[:30],
                                    "Permittee":   p.get("permittee", "")[:30],
                                } for p in _perms[:80]]
                                st.dataframe(pd.DataFrame(_perm_rows), use_container_width=True,
                                             hide_index=True, height=min(400, 40+35*len(_perm_rows)))
                            else:
                                st.info("No DOB permit issuances found.")

                        with st.expander("⚠️ DOB Violations", expanded=False):
                            _dobv = _pip.get("dob_violations", [])
                            if _dobv:
                                _dobv_rows = [{
                                    "Issued":      v.get("issue_date", ""),
                                    "Category":    v.get("category", ""),
                                    "Description": v.get("description", "")[:80],
                                    "Status":      v.get("status", ""),
                                    "Closed":      v.get("disposition_date", ""),
                                    "ECB #":       v.get("ecb_number", ""),
                                } for v in _dobv[:60]]
                                st.dataframe(pd.DataFrame(_dobv_rows), use_container_width=True,
                                             hide_index=True, height=min(400, 40+35*len(_dobv_rows)))
                            else:
                                st.info("No DOB violations found.")

                        with st.expander("📣 DOB Complaints", expanded=False):
                            _comps_dob = _pip.get("complaints", [])
                            if _comps_dob:
                                _comp_rows = [{
                                    "Date":        c.get("date", ""),
                                    "Category":    c.get("category", ""),
                                    "Description": c.get("description", "")[:80],
                                    "Status":      c.get("status", ""),
                                    "Disposition": c.get("disposition", "")[:40],
                                    "Unit":        c.get("unit", ""),
                                } for c in _comps_dob[:60]]
                                st.dataframe(pd.DataFrame(_comp_rows), use_container_width=True,
                                             hide_index=True, height=min(400, 40+35*len(_comp_rows)))
                            else:
                                st.info("No DOB complaints found.")

                        _hpd_bld = _pip.get("hpd_building", {})
                        if _hpd_bld:
                            st.caption(
                                f"HPD Building ID: **{_hpd_bld.get('building_id','—')}** · "
                                f"Registration ID: {_hpd_bld.get('registration_id','—')} · "
                                f"Dwelling Units: {_hpd_bld.get('dwelling_units','—')} · "
                                f"Management Program: {_hpd_bld.get('management_program','—') or 'None'}"
                            )

                    elif _pip and _pip.get("error"):
                        st.warning(f"Property history unavailable: {_pip['error']}")
                    elif _bbl_disp != "—":
                        st.info("Fetching property history… rerun if empty.")

                    if _pip_url:
                        st.caption(
                            f"Sources: NYC Open Data DOB (ipu4-2q9a, ic3t-wcy2, eabe-havv, 3h2n-5cm9) · "
                            f"HPD Buildings (kj4p-ruqc) · "
                            f"[NYC Property Information Portal ↗]({_pip_url})"
                        )

                    # ── Tax Abatement, Rent Stabilization & Transit ──────────
                    st.markdown("##### 🏛️ Tax Abatement, Rent Stabilization & Transit")
                    st.caption(
                        "The abatement and rent-stabilization signals below are rules-based "
                        "ESTIMATES, not authoritative — NYC has no free public API for either. "
                        "Confirm with NYC DOF / DHCR before relying on them."
                    )

                    _abate_key = f"_abate_{_bbl_disp}"
                    if _abate_key not in st.session_state and _bbl_disp != "—":
                        st.session_state[_abate_key] = fetch_tax_abatement_signal(_zinfo)
                    _abate = st.session_state.get(_abate_key, {})
                    record_source_status(
                        "Tax Abatement Estimate", ok=(not _abate.get("error")), detail=_abate.get("error") or ""
                    )

                    _rentstab_key = f"_rentstab_{_bbl_disp}"
                    if _rentstab_key not in st.session_state and _bbl_disp != "—":
                        st.session_state[_rentstab_key] = fetch_rent_stabilization_signal(_zinfo)
                    _rentstab = st.session_state.get(_rentstab_key, {})
                    record_source_status(
                        "Rent Stabilization Estimate", ok=(not _rentstab.get("error")), detail=_rentstab.get("error") or ""
                    )

                    # Ground-truth registry lookup (NYC Rent Guidelines Board
                    # building list) — same modules.rent_stab_registry check
                    # Site Finder already uses via enrich_property(), now also
                    # wired into this primary diligence tab instead of only
                    # the unverified PLUTO-only heuristic above.
                    _rentstab_reg_key = f"_rentstab_registry_{_bbl_disp}"
                    if _rentstab_reg_key not in st.session_state and _bbl_disp != "—":
                        st.session_state[_rentstab_reg_key] = check_rent_stabilized(
                            _zinfo.get("borough_code", ""), _zinfo.get("block"), _zinfo.get("lot"),
                            _zinfo.get("address_pluto") or st.session_state.get("address_raw", ""),
                        )
                    _rentstab_registry = st.session_state.get(_rentstab_reg_key, {})

                    _transit_key = f"_transit_{lat:.5f}_{lon:.5f}"
                    if _transit_key not in st.session_state:
                        st.session_state[_transit_key] = fetch_transit_proximity(lat, lon)
                    _transit = st.session_state.get(_transit_key, {})
                    record_source_status(
                        "Transit Proximity", ok=(not _transit.get("error")), detail=_transit.get("error") or ""
                    )

                    _zip_for_demo = _zinfo.get("zip_code", "")
                    _demo_key = f"_demo_{_zip_for_demo}"
                    if _demo_key not in st.session_state and _zip_for_demo:
                        st.session_state[_demo_key] = fetch_demographics(_zip_for_demo)
                    _demo = st.session_state.get(_demo_key, {})
                    record_source_status(
                        "Demographics (Census)", ok=(not _demo.get("error")), detail=_demo.get("error") or ""
                    )

                    _tr1, _tr2 = st.columns(2)
                    with _tr1:
                        if _abate.get("error"):
                            st.caption(f"Tax abatement: {_abate['error']}")
                        else:
                            _exempt = _abate.get("currently_exempt")
                            _exempt_lbl = (
                                f"✅ Currently exempt (${_abate['exempt_value']:,.0f})" if _exempt and _abate.get("exempt_value")
                                else ("✅ Currently exempt" if _exempt else "No current exemption on record")
                            )
                            st.markdown(f"**Tax Exemption Status** — {_exempt_lbl}  \n"
                                        f"<span style='font-size:0.72rem;color:#6B7280'>Verified from PLUTO</span>",
                                        unsafe_allow_html=True)
                            _progs = [p for p in _abate.get("estimated_programs", []) if p.get("eligible_estimate")]
                            if _progs:
                                st.caption("Estimated (unverified) eligibility: " +
                                           ", ".join(f"{p['program']} ({p['confidence']:.0%} conf.)" for p in _progs))

                        if _rentstab_registry.get("status") == "confirmed":
                            st.markdown(
                                f"**Rent Stabilization** — ✅ Confirmed on NYC Rent Guidelines "
                                f"Board building list "
                                f"<span style='font-size:0.72rem;color:#6B7280'>"
                                f"(ground truth, matched by {_rentstab_registry.get('match_type', 'record')})</span>",
                                unsafe_allow_html=True,
                            )
                            for _note in _rentstab_registry.get("notes", []):
                                st.caption(f"• {_note}")
                        elif _rentstab.get("error"):
                            st.caption(f"Rent stabilization: {_rentstab['error']}")
                        else:
                            _rs_lbl = "⚠️ Likely Rent Stabilized" if _rentstab.get("likely_stabilized") else "Unlikely rent stabilized"
                            _rs_registry_note = (
                                " · not found on NYC Rent Guidelines Board building list (not proof of unstabilized)"
                                if _rentstab_registry.get("status") == "not_found" else ""
                            )
                            st.markdown(
                                f"**Rent Stabilization** — {_rs_lbl} "
                                f"<span style='font-size:0.72rem;color:#6B7280'>(estimated, {_rentstab.get('confidence', 0):.0%} conf. — not verified{_rs_registry_note})</span>  \n"
                                f"<a href='{_rentstab.get('dhcr_lookup_url', '')}' target='_blank' "
                                f"style='font-size:0.75rem'>Confirm via DHCR building list →</a>",
                                unsafe_allow_html=True,
                            )

                    with _tr2:
                        if _transit.get("error"):
                            st.caption(f"Transit: {_transit['error']}")
                        elif _transit.get("nearest_station"):
                            _lines = ", ".join(_transit.get("nearest_lines", [])) or "—"
                            st.markdown(
                                f"**🚇 Nearest Subway** — {_transit['nearest_station']} ({_lines})  \n"
                                f"{_transit.get('distance_miles', '—')} mi away · "
                                f"{_transit.get('stations_within_half_mile', 0)} station(s) within ½ mi"
                            )
                        if _demo.get("error"):
                            st.caption(f"Demographics: {_demo['error']}")
                        elif _demo.get("population") is not None:
                            _inc = _demo.get("median_household_income")
                            st.markdown(
                                f"**ZIP {_demo.get('zcta','')} Demographics** (Census ACS 5-Yr)  \n"
                                f"Population: {_demo['population']:,} · "
                                f"Median HH Income: {'${:,}'.format(_inc) if _inc else '—'}"
                            )

                    # ── Environmental & Flood Zone ────────────────────────────
                    st.markdown("##### 🌊 Environmental & Flood Zone")
                    st.caption(
                        "Flood zone is a live FEMA lookup. Spill incidents are a coarse "
                        "county-wide filter (not a precise-radius match around this property) — "
                        "always confirm via the official DEC search tool linked below."
                    )
                    _flood_key = f"_flood_{lat:.5f}_{lon:.5f}"
                    if _flood_key not in st.session_state:
                        from modules.environmental_fetcher import fetch_flood_zone, fetch_dec_spill_incidents
                        st.session_state[_flood_key] = fetch_flood_zone(lat, lon)
                    _flood = st.session_state.get(_flood_key, {})
                    record_source_status(
                        "FEMA Flood Zone", ok=(not _flood.get("error")), detail=_flood.get("error") or ""
                    )

                    _dec_key = f"_dec_spills_{borough}"
                    if _dec_key not in st.session_state:
                        from modules.environmental_fetcher import fetch_dec_spill_incidents as _fetch_dec
                        st.session_state[_dec_key] = _fetch_dec(borough)
                    _dec = st.session_state.get(_dec_key, {})
                    record_source_status(
                        "NYS DEC Spill Incidents", ok=(not _dec.get("error")), detail=_dec.get("error") or ""
                    )

                    _env1, _env2 = st.columns(2)
                    with _env1:
                        if _flood.get("error"):
                            st.caption(f"Flood zone: {_flood['error']}")
                        else:
                            _sfha = _flood.get("in_special_flood_hazard_area")
                            _flood_icon = "🔴" if _sfha else ("🟡" if _sfha is False and _flood.get("flood_zone") == "X500" else "🟢" if _sfha is False else "⚪")
                            st.markdown(
                                f"**{_flood_icon} FEMA Flood Zone** — {_flood.get('flood_zone') or 'Not mapped'}  \n"
                                f"<span style='font-size:0.78rem;color:#3D4152'>{_flood.get('zone_description','')}</span>",
                                unsafe_allow_html=True,
                            )
                            if _sfha:
                                st.caption("⚠️ Special Flood Hazard Area — flood insurance likely required for federally-backed financing; factor into construction/insurance underwriting.")
                    with _env2:
                        if _dec.get("error"):
                            st.caption(f"DEC spill incidents: {_dec['error']}")
                        else:
                            st.markdown(
                                f"**🛢️ DEC Spill Incidents ({_dec.get('county','—')} County)** — {_dec.get('count', 0)} record(s) "
                                f"<span style='font-size:0.72rem;color:#6B7280'>(county-wide, not property-specific)</span>",
                                unsafe_allow_html=True,
                            )
                            st.caption(f"[Search official DEC spills database for this address ↗]({_dec.get('search_tool_url', '')})")

                    # ── Adjacent Lot Aggregation ──────────────────────────────
                    _subj_bbl = _zinfo.get("bbl", "")
                    with st.expander("🏘️ Add Adjacent Lots", expanded=False):
                        st.caption(
                            "Enter addresses of neighboring lots on the same block. "
                            "Adjacent lots will be merged into a combined parcel for massing analysis."
                        )
                        # Input rows for up to 3 additional lots
                        _adj_addrs = st.session_state.get("_adj_lots_inputs", ["", "", ""])
                        _new_addrs = []
                        for _ai in range(3):
                            _ac1, _ac2 = st.columns([4, 1])
                            with _ac1:
                                _ainput = st.text_input(
                                    f"Adjacent Lot {_ai + 1}",
                                    value=_adj_addrs[_ai] if _ai < len(_adj_addrs) else "",
                                    key=f"_adj_lot_input_{_ai}",
                                    placeholder="e.g. 123 Main St, Brooklyn, NY",
                                    label_visibility="collapsed",
                                )
                            with _ac2:
                                _alookup = st.button("Look Up", key=f"_adj_lot_btn_{_ai}")
                            _new_addrs.append(_ainput)

                            if _alookup and _ainput.strip():
                                _adj_cache_key = f"_adj_lot_{_ainput.strip().lower()}"
                                if _adj_cache_key not in st.session_state:
                                    with st.spinner(f"Looking up lot {_ai + 1}…"):
                                        st.session_state[_adj_cache_key] = fetch_zoning_info(
                                            _ainput.strip(), lat=lat, lon=lon
                                        )

                            # Show result if cached
                            _adj_ck = f"_adj_lot_{_ainput.strip().lower()}" if _ainput.strip() else None
                            if _adj_ck and _adj_ck in st.session_state:
                                _adj_res = st.session_state[_adj_ck]
                                if _adj_res and "error" not in _adj_res:
                                    _adj_bbl = _adj_res.get("bbl", "")
                                    _adj_lf  = _adj_res.get("lot_frontage_ft", "—")
                                    _adj_ld  = _adj_res.get("lot_depth_ft", "—")
                                    _adj_la  = _adj_res.get("lot_area_sqft", "—")
                                    _adj_ok  = _is_adjacent(_subj_bbl, _adj_bbl)
                                    _status  = "✅ Adjacent (same block)" if _adj_ok else "⚠️ Different block — won't be merged"
                                    st.markdown(
                                        f"<div style='font-size:0.78rem;padding:4px 8px;"
                                        f"background:#FCFAF3;border-radius:6px;border:1px solid #DCD5C2;margin-bottom:4px'>"
                                        f"BBL: <b>{_adj_bbl}</b> &nbsp;·&nbsp; "
                                        f"{_adj_lf} ft × {_adj_ld} ft = {_adj_la} SF &nbsp;·&nbsp; {_status}"
                                        f"</div>",
                                        unsafe_allow_html=True,
                                    )
                                elif _adj_res and "error" in _adj_res:
                                    st.warning(f"Lot {_ai + 1}: {_adj_res['error']}")
                                else:
                                    st.warning(f"Lot {_ai + 1}: Not found.")

                        st.session_state["_adj_lots_inputs"] = _new_addrs

                        # Collect all valid adjacent lots
                        _valid_adj = []
                        for _ainput in _new_addrs:
                            if not _ainput.strip():
                                continue
                            _adj_ck = f"_adj_lot_{_ainput.strip().lower()}"
                            _adj_res = st.session_state.get(_adj_ck)
                            if _adj_res and "error" not in _adj_res:
                                _adj_bbl = _adj_res.get("bbl", "")
                                if _is_adjacent(_subj_bbl, _adj_bbl):
                                    _valid_adj.append(_adj_res)

                        if _valid_adj:
                            st.success(f"{len(_valid_adj)} adjacent lot(s) found — will be merged with subject parcel.")
                            st.session_state["_adj_lots_use_combined"] = st.checkbox(
                                "Use combined lot for massing analysis",
                                value=st.session_state.get("_adj_lots_use_combined", True),
                                key="_adj_lots_use_combined_cb",
                            )
                            st.session_state["_adj_lots_valid"] = _valid_adj
                        else:
                            st.session_state["_adj_lots_valid"] = []
                            if any(a.strip() for a in _new_addrs):
                                st.info("No adjacent lots found on the same block yet. Use 'Look Up' for each address.")

                    def _zrow(label, val, width="160px"):
                        v = str(val) if val and str(val) != "—" else None
                        body = f"<b>{v}</b>" if v else "<span style='color:#9CA3AF'>—</span>"
                        return (
                            f"<div style='display:flex;gap:8px;margin-bottom:5px'>"
                            f"<span style='color:#6B7280;min-width:{width}'>{label}</span>"
                            f"{body}</div>"
                        )

                    # ── Key Zoning Requirements (above detail columns) ────────
                    _primary_zone = _zinfo.get("zoning_dist", "")
                    _zrules = get_zoning_rules(_primary_zone)
                    if _zrules:
                        st.markdown(
                            "<div style='font-size:0.72rem;font-weight:700;letter-spacing:0.08em;"
                            "text-transform:uppercase;color:#6B7280;margin-bottom:8px'>"
                            "📋 Key Zoning Requirements & Approval Triggers</div>",
                            unsafe_allow_html=True,
                        )
                    if _zrules:
                        _bullets = []
                        _bfar = _zrules.get("base_far", 0)
                        _mfar = _zrules.get("max_far", 0)
                        _rfar = _zrules.get("res_far", 0)
                        _bh   = _zrules.get("base_height_ft", 0)
                        _mh   = _zrules.get("max_height_ft", 0)
                        _fr   = _zrules.get("front_yard_ft", 0)
                        _rr   = _zrules.get("rear_yard_ft", 0)
                        _sy   = _zrules.get("side_yard_ft", 0)
                        _lc   = _zrules.get("lot_coverage_pct", 0)
                        _bullets.append(
                            f"**FAR:** Base {_bfar} (max {_mfar} with bonuses)"
                            + (f" · Residential FAR {_rfar}" if _rfar else "")
                        )
                        if _zrules.get("sky_exp_plane"):
                            _bullets.append("**Height:** Sky Exposure Plane governs envelope — buildings must step back from the street wall above base height (slope: 2.7:1 horizontal). No fixed height limit.")
                        elif _bh and _mh and _bh != _mh:
                            _bullets.append(f"**Height:** Base (street wall) {_bh} ft · Maximum {_mh} ft after setback · Contextual street wall required")
                        elif _mh:
                            _bullets.append(f"**Height:** Maximum {_mh} ft (absolute limit)")
                        if _fr or _rr or _sy:
                            _bullets.append(f"**Setbacks:** Front yard {_fr} ft · Rear yard {_rr} ft · Side yard {_sy} ft per side")
                        if _lc:
                            _bullets.append(f"**Lot Coverage:** Maximum {_lc}% of lot area")
                        if _zrules.get("contextual"):
                            _bullets.append("**Contextual District:** Street wall height and setback must match prevailing neighborhood context — community board review likely")
                        if _zrules.get("tower_rules"):
                            _bullets.append("**Tower-on-Base:** Open space at grade required (typically 20–30% of lot) · Tower floor plate constraints apply")
                        if _mfar > _bfar:
                            _bullets.append(f"**Bonus FAR ({_mfar} max):** Available via Inclusionary Housing (MIH/IH) — 20–25% affordable units required. May require ULURP / CPC approval")
                        # Overlay district
                        _overlay = _zinfo.get("overlay") or ""
                        if _overlay and _overlay != "—":
                            _ov_info = COMMERCIAL_OVERLAYS.get(_overlay, {})
                            _ov_uses = _ov_info.get("uses", "local retail and service establishments")
                            _ov_far  = _ov_info.get("comm_far", "")
                            _ov_far_str = f" · Commercial FAR up to {_ov_far}" if _ov_far else ""
                            _bullets.append(f"**Commercial Overlay ({_overlay}):** Permits {_ov_uses}{_ov_far_str}. Activates ground-floor commercial on this residential lot.")
                        # Special district
                        for _sp_key in ["special_dist", "special_dist2", "special_dist3"]:
                            _sp = _zinfo.get(_sp_key)
                            if _sp and _sp != "—":
                                _sp_info = get_special_district_info(_sp)
                                if _sp_info:
                                    _bullets.append(
                                        f"**Special District ({_sp} — {_sp_info['name']}):** "
                                        f"{_sp_info['description'][:120]}… "
                                        f"[NYC Planning →]({_sp_info['url']})"
                                    )
                                else:
                                    _bullets.append(f"**Special District ({_sp}):** Additional design, use, and bulk regulations apply — consult NYC Planning special district text")
                        # Historic district
                        _hist = _zinfo.get("historic_dist")
                        if _hist and _hist != "—":
                            _bullets.append(
                                f"**Historic District ({_hist}):** LPC review required for any exterior changes or new construction. "
                                f"[LPC website →](https://www.nyc.gov/site/lpc/index.page)"
                            )
                        # Split zone
                        if _zinfo.get("split_zone") == "Y":
                            _z2 = _zinfo.get("zoning_dist2", "")
                            _bullets.append(f"**Split Zone:** Lot straddles {_primary_zone} and {_z2 or 'a secondary zone'} — most restrictive standards apply per NYC ZR.")
                        _bullets.append("**Approval Path:** As-of-right developments file only DOB permit. Bonus FAR, special permits, or variances require ULURP (typically 12–18 months)")
                        _bullets_html = "".join(f"<li style='margin-bottom:5px;font-size:0.82rem;color:#3D4152'>{b}</li>" for b in _bullets)
                        st.markdown(
                            f"<ul style='padding-left:18px;margin:0'>{_bullets_html}</ul>",
                            unsafe_allow_html=True,
                        )
                        st.caption(
                            f"Rules per NYC Zoning Resolution for {_primary_zone}. "
                            + (f"Verify on [ZOLA →]({_zola_url})" if _zola_url else "Verify on NYC ZOLA.")
                            + " · Data sourced from [NYC Open Data / PLUTO](https://opendata.cityofnewyork.us)."
                        )
                        st.markdown("---")

                    def _render_lot_zoning_cols(zi):
                        """Render 3-column zoning detail for a single lot's zinfo dict."""
                        _zc1, _zc2, _zc3 = st.columns(3)
                        with _zc1:
                            st.markdown("**🏙️ Zoning Districts**")
                            st.markdown(
                                _zrow("Primary District",  zi.get("zoning_dist")) +
                                _zrow("Secondary District",zi.get("zoning_dist2")) +
                                _zrow("Tertiary District", zi.get("zoning_dist3")) +
                                _zrow("Commercial Overlay",zi.get("overlay")) +
                                _zrow("Overlay 2",         zi.get("overlay2")) +
                                _zrow("Special District",  zi.get("special_dist")) +
                                _zrow("Special District 2",zi.get("special_dist2")) +
                                _zrow("Limited Height",    zi.get("ltd_height")) +
                                _zrow("Split Zone",        zi.get("split_zone")) +
                                _zrow("Land Use",          zi.get("land_use")) +
                                _zrow("Historic District", zi.get("historic_dist")) +
                                _zrow("Landmark",          zi.get("landmark")),
                                unsafe_allow_html=True,
                            )
                            st.markdown("**💰 Assessment & Ownership**")
                            st.markdown(
                                _zrow("Owner",           zi.get("owner")) +
                                _zrow("Tax Class",       zi.get("tax_class")) +
                                _zrow("Assessed Land",   zi.get("assess_land")) +
                                _zrow("Assessed Total",  zi.get("assess_total")) +
                                _zrow("Exemption Total", zi.get("exempt_total")),
                                unsafe_allow_html=True,
                            )
                        with _zc2:
                            st.markdown("**📐 FAR — Development Rights**")
                            st.markdown(
                                _zrow("Residential FAR",  zi.get("far_residential")) +
                                _zrow("Commercial FAR",   zi.get("far_commercial")) +
                                _zrow("Facility FAR",     zi.get("far_facility")) +
                                _zrow("Built FAR",        zi.get("far_built")) +
                                _zrow("Existing FAR",     zi.get("far_existing")),
                                unsafe_allow_html=True,
                            )
                            st.markdown("**📏 Lot Dimensions**")
                            _la = zi.get("lot_area_sqft", "—")
                            _lf = zi.get("lot_frontage_ft", "—")
                            _ld = zi.get("lot_depth_ft", "—")
                            st.markdown(
                                _zrow("Lot Area",     f"{_la} SF" if _la != "—" else "—") +
                                _zrow("Lot Frontage", f"{_lf} ft" if _lf != "—" else "—") +
                                _zrow("Lot Depth",    f"{_ld} ft" if _ld != "—" else "—") +
                                _zrow("Lot Type",     zi.get("lot_type")) +
                                _zrow("Irregular",    zi.get("irr_lot")) +
                                _zrow("Easements",    zi.get("easements")),
                                unsafe_allow_html=True,
                            )
                            st.markdown("**📍 Location**")
                            _street_type = classify_street_type(
                                zi.get("address_pluto") or st.session_state.get("address_raw", "")
                            )
                            st.markdown(
                                _zrow("Community Board", zi.get("community_board")) +
                                _zrow("ZIP Code",        zi.get("zip_code")) +
                                _zrow("NTA",             zi.get("nta")) +
                                _zrow("PLUTO Address",   zi.get("address_pluto")) +
                                _zrow("Street Type",     _street_type),
                                unsafe_allow_html=True,
                            )
                        with _zc3:
                            st.markdown("**🏗️ Building**")
                            _ba  = zi.get("bldg_area_sqft", "—")
                            _bfr = zi.get("bldg_frontage_ft", "—")
                            _bdp = zi.get("bldg_depth_ft", "—")
                            st.markdown(
                                _zrow("Building Area",    f"{_ba} SF"  if _ba  != "—" else "—") +
                                _zrow("Bldg Frontage",    f"{_bfr} ft" if _bfr != "—" else "—") +
                                _zrow("Bldg Depth",       f"{_bdp} ft" if _bdp != "—" else "—") +
                                _zrow("Floors",           (lambda v: str(int(float(str(v).replace(",","")))) if v and str(v).replace(",","").replace(".","").isdigit() else v)(zi.get("num_floors"))) +
                                _zrow("Num. Buildings",   zi.get("num_buildings")) +
                                _zrow("Year Built",       zi.get("year_built")) +
                                _zrow("Year Last Mod.",   zi.get("year_last_mod")) +
                                _zrow("Building Class",   zi.get("bldg_class")) +
                                _zrow("Basement",         zi.get("basement")) +
                                _zrow("Extensions",       zi.get("extensions")) +
                                _zrow("Condo Number",     zi.get("condo_no")) +
                                _zrow("Res. Units",       zi.get("units_res")) +
                                _zrow("Total Units",      zi.get("units_total")),
                                unsafe_allow_html=True,
                            )

                    _tab_adj = st.session_state.get("_adj_lots_valid", [])
                    if _tab_adj:
                        _tab_labels = ["Subject Lot"] + [
                            f"Lot {_ai + 2} — {_al.get('matched_label', _al.get('bbl',''))[:30]}"
                            for _ai, _al in enumerate(_tab_adj)
                        ]
                        _lot_tabs = st.tabs(_tab_labels)
                        with _lot_tabs[0]:
                            _render_lot_zoning_cols(_zinfo)
                        for _ai, _al in enumerate(_tab_adj):
                            with _lot_tabs[_ai + 1]:
                                _render_lot_zoning_cols(_al)
                    else:
                        _render_lot_zoning_cols(_zinfo)

                    # ── Local Law 97 Carbon-Emissions Compliance (opt-in) ────
                    # Additive — sits after the existing FAR/zoning summary
                    # above, doesn't touch or reorder any of it. Gated behind
                    # a button (same opt-in convention as LPC/ULURP/OATH/
                    # Tax-Lien) so it never adds an automatic fetch to the
                    # page's critical path.
                    st.markdown("---")
                    with st.expander("🌎 Local Law 97 Carbon-Emissions Compliance (estimate)", expanded=False):
                        from modules.carbon_compliance import (
                            compute_ll97_compliance, map_landuse_to_occupancy_group,
                            LL97_EMISSIONS_LIMITS_KGCO2E_PER_SF,
                        )
                        from modules.ll84_fetcher import fetch_ll84_emissions
                        st.caption(
                            "Applies LL97's published per-occupancy-group emissions limits against the "
                            "property's actual reported LL84 energy-disclosure filing, when one exists "
                            "(buildings under ~25,000 SF are typically not covered by LL84 and won't have "
                            "a filing — that's expected, not an error). Coefficients require confirmation "
                            "against NYC DOB's official LL97 rules before relying on this for underwriting."
                        )
                        _ll97_occ_default = map_landuse_to_occupancy_group(_zinfo.get("land_use", "")) or "Multifamily Residential"
                        _ll97_c1, _ll97_c2 = st.columns(2)
                        _ll97_occ = _ll97_c1.selectbox(
                            "Occupancy group", list(LL97_EMISSIONS_LIMITS_KGCO2E_PER_SF.keys()),
                            index=list(LL97_EMISSIONS_LIMITS_KGCO2E_PER_SF.keys()).index(_ll97_occ_default),
                            key=f"_ll97_occ_{_bbl_disp}",
                        )
                        _ll97_period = _ll97_c2.selectbox(
                            "Compliance period", ["2024-2029", "2030-2034"], key=f"_ll97_period_{_bbl_disp}",
                        )
                        if st.button("Check LL84 filing & LL97 compliance", key=f"_ll97_btn_{_bbl_disp}"):
                            with st.spinner("Checking LL84 energy disclosure…"):
                                st.session_state[f"_ll84_{_bbl_disp}"] = fetch_ll84_emissions(_bbl_disp)
                        _ll84 = st.session_state.get(f"_ll84_{_bbl_disp}", {})
                        _ll97_bldg_sf = _sf(_zinfo.get("bldg_area_sqft"))
                        _ll97_actual = _ll84.get("total_ghg_emissions_metric_tons") if _ll84.get("reported") else None
                        _ll97_result = compute_ll97_compliance(
                            _ll97_bldg_sf, _ll97_occ, annual_emissions_tons_co2e=_ll97_actual, period=_ll97_period,
                        )
                        if _ll97_result.get("error"):
                            st.caption(f"⚠️ {_ll97_result['error']}")
                        else:
                            _ll97_m1, _ll97_m2, _ll97_m3 = st.columns(3)
                            _ll97_m1.metric("Emissions Limit", f"{_ll97_result['emissions_limit_tons']:,.0f} tons CO2e/yr")
                            _ll97_m2.metric(
                                "Reported Emissions",
                                f"{_ll97_actual:,.0f} tons CO2e/yr" if _ll97_actual is not None else "N/A",
                            )
                            _ll97_m3.metric(
                                "Est. Annual Penalty",
                                f"${_ll97_result['estimated_annual_penalty']:,.0f}" if _ll97_result.get("estimated_annual_penalty") else "N/A",
                            )
                            st.caption(f"Compliance status: {_ll97_result['compliance_status']}")
                            if _ll84 and not _ll84.get("reported") and _ll84.get("verified"):
                                st.caption("ℹ️ No LL84 filing found for this BBL — likely under the ~25,000 SF disclosure threshold, or not yet filed.")

                    # ── Zoning Envelope Rules ────────────────────────────────
                    if _zrules:
                        st.markdown("---")
                        st.markdown(
                            "<div style='font-size:0.72rem;font-weight:700;letter-spacing:0.08em;"
                            "text-transform:uppercase;color:#6B7280;margin-bottom:8px'>"
                            "📐 Zoning Development Envelope</div>",
                            unsafe_allow_html=True,
                        )
                        st.caption(_zrules.get("description", ""))

                        # ── Check for split/multiple zones ──────────────────────
                        _zone_2 = _zinfo.get("zoning_dist2", "")
                        _zone_3 = _zinfo.get("zoning_dist3", "")
                        _all_zones = [_primary_zone] + [z for z in [_zone_2, _zone_3] if z and z != "—"]
                        _is_split_z = len(_all_zones) > 1

                        if _is_split_z:
                            st.warning(
                                f"🔀 **Split Zoning:** This lot is regulated by {len(_all_zones)} zoning districts: "
                                f"{' + '.join(_all_zones)}. Most restrictive standards apply per NYC ZR. "
                                f"Development must comply with ALL districts."
                            )

                        _zcite = get_zoning_citations(_primary_zone)

                        def _erow(lbl, val, width="165px", link=None):
                            v = str(val) if val not in (None, 0, "0", "") else None
                            if v and link:
                                body = f"<b><a href='{link}' target='_blank' style='color:#8B6914;text-decoration:none'>{v} ↗</a></b>"
                            elif v:
                                body = f"<b>{v}</b>"
                            else:
                                body = "<span style='color:#9CA3AF'>—</span>"
                            return (
                                f"<div style='display:flex;gap:8px;margin-bottom:5px'>"
                                f"<span style='color:#6B7280;min-width:{width}'>{lbl}</span>"
                                f"{body}</div>"
                            )

                        _ec1, _ec2, _ec3 = st.columns(3)

                        # ── Column 1: FAR Limits (all types + split zone comparison) ──
                        with _ec1:
                            st.markdown("**FAR Limits**")
                            _facil_far_v = float(str(_zinfo.get("far_facility") or 0).replace(",", ""))
                            _built_far_v = float(str(_zinfo.get("builtfar") or _zinfo.get("built_far") or 0).replace(",", ""))
                            _far_html = (
                                _erow("Base FAR",         _zrules.get("base_far"),
                                      link=_zcite.get("far_url")) +
                                _erow("Max FAR (w/ bonus)", _zrules.get("max_far"),
                                      link=_zcite.get("far_url")) +
                                _erow("Residential FAR",  _zrules.get("res_far"),
                                      link=_zcite.get("far_url")) +
                                _erow("Commercial FAR",   _zrules.get("comm_far"),
                                      link=_zcite.get("far_url"))
                            )
                            # ── Split zone: show BOTH zones FAR comparison ──────────
                            if _is_split_z and _zone_2:
                                _zrules_2 = get_zoning_rules(_zone_2)
                                if _zrules_2:
                                    _far_html += (
                                        f"<div style='margin-top:8px;border-top:1px solid #DCD5C2;padding-top:8px'>"
                                        f"<b style='color:#6B7280;font-size:0.85em'>Secondary Zone ({_zone_2})</b>"
                                        f"</div>" +
                                        _erow("Base FAR",         _zrules_2.get("base_far"),
                                              link=get_zoning_citations(_zone_2).get("far_url")) +
                                        _erow("Max FAR",          _zrules_2.get("max_far"),
                                              link=get_zoning_citations(_zone_2).get("far_url")) +
                                        _erow("Residential FAR",  _zrules_2.get("res_far"),
                                              link=get_zoning_citations(_zone_2).get("far_url")) +
                                        _erow("Commercial FAR",   _zrules_2.get("comm_far"),
                                              link=get_zoning_citations(_zone_2).get("far_url"))
                                    )
                            _far_html += (
                                (_erow("Facility FAR",    f"{_facil_far_v:g}",
                                       link=_zcite.get("far_url")) if _facil_far_v > 0 else "") +
                                (_erow("Built FAR (actual)", f"{_built_far_v:g}") if _built_far_v > 0 else "")
                            )
                            st.markdown(_far_html, unsafe_allow_html=True)
                            if _zcite.get("far_citation"):
                                st.caption(f"📖 [{_zcite['far_citation']}]({_zcite.get('far_url', '#')})")
                            if _zcite.get("mih_eligible"):
                                st.caption(f"🏠 [Mandatory Inclusionary Housing (MIH)]({_zcite.get('mih_url','#')}) may unlock bonus FAR")
                            if _zcite.get("quality_housing"):
                                st.caption(f"🏗️ [Quality Housing Program]({_zcite.get('far_url','#')}) — alternative bulk envelope available")

                        # ── Column 2: Height & Setbacks ──────────────────────────
                        with _ec2:
                            st.markdown("**Height & Setbacks**")
                            _bh = _zrules.get("base_height_ft", 0)
                            _mh = _zrules.get("max_height_ft", 0)
                            _fr = _zrules.get("front_yard_ft", 0)
                            _rr = _zrules.get("rear_yard_ft", 0)
                            _sy = _zrules.get("side_yard_ft", 0)
                            _sep = _zrules.get("sky_exp_plane", False)
                            _ht_html = (
                                _erow("Base Height",
                                      f"{_bh} ft (street-wall max)" if _bh else "Sky Exposure Plane governs",
                                      link=_zcite.get("height_url")) +
                                _erow("Max Height",
                                      f"{_mh} ft (absolute)" if _mh else ("No absolute cap" if _sep else "—"),
                                      link=_zcite.get("height_url")) +
                                (_erow("SEP Setback",
                                       "2.7:1 slope above base height",
                                       link=_zcite.get("height_url")) if _sep else "") +
                                _erow("Front Yard Depth", f"{_fr} ft" if _fr else "None required",
                                      link=_zcite.get("height_url")) +
                                _erow("Rear Yard Depth",  f"{_rr} ft" if _rr else "None required",
                                      link=_zcite.get("height_url")) +
                                _erow("Side Yard Depth",  f"{_sy} ft/side" if _sy else "None required",
                                      link=_zcite.get("height_url"))
                            )
                            st.markdown(_ht_html, unsafe_allow_html=True)
                            if _zcite.get("height_citation"):
                                st.caption(f"📖 [{_zcite['height_citation']}]({_zcite.get('height_url','#')})")

                        # ── Column 3: Lot Coverage + Controls + Citations ─────────
                        with _ec3:
                            st.markdown("**Lot Coverage & Controls**")
                            _lc = _zrules.get("lot_coverage_pct", 0)
                            _ctrl_html = (
                                _erow("Max Lot Coverage",  f"{_lc}%" if _lc else "No direct limit",
                                      link=_zcite.get("far_url")) +
                                _erow("Contextual Rules",  "Yes — street-wall + base/max" if _zrules.get("contextual") else "No") +
                                _erow("Tower Rules",       "Yes — tower-on-base w/ open space" if _zrules.get("tower_rules") else "No") +
                                _erow("Sky Exp. Plane",    "Yes — 2.7:1 slope" if _zrules.get("sky_exp_plane") else "No") +
                                _erow("Use Regulations",   _zcite.get("use_citation", "ZR § Use Regulations"),
                                      link=_zcite.get("use_url")) +
                                _erow("Off-Street Parking", _zcite.get("parking_citation", ""),
                                      link=_zcite.get("parking_url"))
                            )
                            st.markdown(_ctrl_html, unsafe_allow_html=True)
                            if _zcite.get("lot_cov_citation"):
                                st.caption(f"📖 [{_zcite['lot_cov_citation']}]({_zcite.get('far_url','#')})")

                        # ── ZR Citation footer ────────────────────────────────────
                        if _zcite.get("article_url"):
                            st.markdown(
                                f"<div style='margin-top:8px;font-size:0.72rem;color:#6B7280'>"
                                f"📚 <b>NYC Zoning Resolution:</b> "
                                f"<a href='{_zcite['article_url']}' target='_blank' style='color:#8B6914'>Bulk Regulations</a> · "
                                f"<a href='{_zcite.get('use_url',_zcite['article_url'])}' target='_blank' style='color:#8B6914'>Use Regulations</a> · "
                                f"<a href='{_zcite.get('parking_url',_zcite['article_url'])}' target='_blank' style='color:#8B6914'>Parking Regulations</a> · "
                                f"<a href='{_zcite.get('zr_main_url','https://zoningresolution.planning.nyc.gov')}' target='_blank' style='color:#8B6914'>Full ZR Browser</a> · "
                                f"<a href='{_zcite.get('zola_url','https://zola.planning.nyc.gov')}' target='_blank' style='color:#8B6914'>ZOLA Map</a>"
                                f"</div>",
                                unsafe_allow_html=True,
                            )

                        # ── 10 Massing Scenario Tiles ────────────────────────

                        # Parse base lot dimensions from subject property
                        def _parse_dim(val):
                            try:
                                s = str(val).replace(",", "")
                                return float(s) if s not in ("—", "", "None") else 0.0
                            except (ValueError, TypeError):
                                return 0.0

                        _lf_v = _parse_dim(_zinfo.get("lot_frontage_ft", 0))
                        _ld_v = _parse_dim(_zinfo.get("lot_depth_ft", 0))
                        _la_v = _parse_dim(_zinfo.get("lot_area_sqft", 0))
                        if _la_v <= 0 and _lf_v > 0 and _ld_v > 0:
                            _la_v = _lf_v * _ld_v
                        if _lf_v <= 0 and _la_v > 0:
                            _lf_v = (_la_v ** 0.5) * 0.8
                        if _ld_v <= 0 and _la_v > 0:
                            _ld_v = _la_v / max(10, _lf_v)

                        # Apply adjacent lot aggregation if enabled
                        _valid_adj = st.session_state.get("_adj_lots_valid", [])
                        _use_combined = (
                            _valid_adj and
                            st.session_state.get("_adj_lots_use_combined", True)
                        )
                        _using_combined = False
                        if _use_combined:
                            _all_lots = [_zinfo] + _valid_adj
                            _comb_lf = sum(_parse_dim(l.get("lot_frontage_ft", 0)) for l in _all_lots)
                            _comb_ld = max(_parse_dim(l.get("lot_depth_ft", 0)) for l in _all_lots)
                            _comb_la = sum(_parse_dim(l.get("lot_area_sqft", 0)) for l in _all_lots)
                            if _comb_lf > 0 and _comb_ld > 0 and _comb_la > 0:
                                _lf_v = _comb_lf
                                _ld_v = _comb_ld
                                _la_v = _comb_la
                                _using_combined = True

                        if _lf_v > 0 and _ld_v > 0 and _la_v > 0:
                            st.markdown("---")
                            st.markdown(
                                "<div class='section-label'>🏗️ Design & Massing Scenarios</div>",
                                unsafe_allow_html=True,
                            )

                            _far_used = _zrules.get("res_far") or _zrules.get("base_far", 0)
                            _lot_label = (
                                f"Combined Lot ({1 + len(_valid_adj)} parcels): "
                                if _using_combined else "Lot: "
                            )
                            st.caption(
                                f"{_lot_label}{_lf_v:.0f}′ × {_ld_v:.0f}′ = {_la_v:,.0f} SF  ·  "
                                f"District: {_primary_zone}  ·  "
                                f"Base FAR: {_zrules.get('base_far',0)}  ·  "
                                f"Max buildable: {_la_v * _far_used:,.0f} SF"
                            )

                            # ── Existing Building Callout ─────────────────────
                            _ex_yr   = _zinfo.get("year_built", "—") or "—"
                            _ex_flrs_raw = _zinfo.get("num_floors", "—") or "—"
                            _ex_flrs = (str(int(float(str(_ex_flrs_raw).replace(",","")))) if str(_ex_flrs_raw).replace(",","").replace(".","").isdigit() else _ex_flrs_raw)
                            _ex_ba   = _zinfo.get("bldg_area_sqft", "—") or "—"
                            _ex_cls  = _zinfo.get("bldg_class", "—") or "—"
                            _ex_units= _zinfo.get("units_res", "—") or "—"
                            _ex_lmod = _zinfo.get("year_last_mod", "—") or "—"
                            if _ex_yr != "—":
                                st.markdown(
                                    f"<div style='background:#E6F0E5;border:1px solid #E6F0E5;"
                                    f"border-radius:8px;padding:10px 14px;margin-bottom:12px'>"
                                    f"<span style='font-size:0.72rem;font-weight:700;color:#1F6B3A;"
                                    f"text-transform:uppercase;letter-spacing:0.06em'>📦 Existing Structure</span>"
                                    f"<div style='margin-top:4px;font-size:0.84rem;color:#3D4152'>"
                                    f"<b>Class {_ex_cls}</b> &nbsp;·&nbsp; Built <b>{_ex_yr}</b>"
                                    f" (last mod. {_ex_lmod}) &nbsp;·&nbsp; "
                                    f"<b>{_ex_flrs}</b> floors &nbsp;·&nbsp; "
                                    f"<b>{_ex_ba} SF</b> gross &nbsp;·&nbsp; "
                                    f"<b>{_ex_units}</b> residential units"
                                    f"</div></div>",
                                    unsafe_allow_html=True,
                                )

                            # Existing building dict for Option 1 (Gut Renovation)
                            _existing_bldg = {
                                "floors":     float(str(_ex_flrs).replace(",","")) if str(_ex_flrs).replace(",","").replace(".","").isdigit() else 0,
                                "area":       _parse_dim(_ex_ba),
                                "year_built": _ex_yr,
                            }

                            # Lot widths for combined boundary visualization
                            _lot_widths = None
                            if _using_combined:
                                _lot_widths = (
                                    [_parse_dim(_zinfo.get("lot_frontage_ft", 0))] +
                                    [_parse_dim(l.get("lot_frontage_ft", 0)) for l in _valid_adj]
                                )

                            # ── Available FAR values for selector ────────────────
                            _facil_far_v = 0.0
                            try:
                                _facil_far_v = float(str(_zinfo.get("far_facility") or 0).replace(",", ""))
                            except (ValueError, TypeError):
                                pass
                            _res_far_v   = float(_zrules.get("res_far",  0) or 0)
                            _comm_far_v  = float(_zrules.get("comm_far", 0) or 0)
                            _base_far_v  = float(_zrules.get("base_far", 0) or 0)
                            _max_far_raw = float(_zrules.get("max_far",  0) or 0)
                            _far_sel_opts = ["Auto (Max)"]
                            if _res_far_v > 0:
                                _far_sel_opts.append(f"Residential ({_res_far_v:g})")
                            if _comm_far_v > 0:
                                _far_sel_opts.append(f"Commercial ({_comm_far_v:g})")
                            if _facil_far_v > 0:
                                _far_sel_opts.append(f"Facility ({_facil_far_v:g})")
                            if _base_far_v > 0 and _base_far_v not in (_res_far_v, _comm_far_v):
                                _far_sel_opts.append(f"Base ({_base_far_v:g})")
                            if _max_far_raw > 0 and _max_far_raw > max(_res_far_v, _comm_far_v, _base_far_v, 0):
                                _far_sel_opts.append(f"Bonus/Max ({_max_far_raw:g})")

                            # ── Development Refinement Options ───────────────
                            with st.expander("⚙️ Development Refinement Options", expanded=False):
                                _rc1, _rc2 = st.columns(2)
                                with _rc1:
                                    _dev_focus = st.radio(
                                        "Development Focus (Primary Use)",
                                        ["Residential", "Commercial", "Retail"],
                                        index=["Residential", "Commercial", "Retail"].index(
                                            st.session_state.get("dev_focus", "Residential")
                                        ),
                                        horizontal=True,
                                        key="dev_focus",
                                    )
                                with _rc2:
                                    _sub_comps = st.multiselect(
                                        "Sub-Components",
                                        ["Ground Floor Retail", "Commercial Office", "Residential Above"],
                                        default=st.session_state.get("dev_sub_comps", ["Ground Floor Retail"]),
                                        key="dev_sub_comps",
                                    )
                                # Neighbor toggle
                                _show_nbrs = st.checkbox(
                                    "Show neighboring properties in massing diagrams",
                                    value=st.session_state.get("show_nbr_toggle", False),
                                    key="show_nbr_toggle",
                                )
                                # FAR type selector
                                st.markdown(
                                    "<div style='margin-top:10px;font-size:0.75rem;font-weight:600;"
                                    "color:#3D4152'>📐 FAR Type for Scenario Calculations</div>",
                                    unsafe_allow_html=True,
                                )
                                _saved_far_sel = st.session_state.get("_far_sel_val", "Auto (Max)")
                                _far_sel_idx = (
                                    _far_sel_opts.index(_saved_far_sel)
                                    if _saved_far_sel in _far_sel_opts else 0
                                )
                                st.radio(
                                    "FAR type",
                                    _far_sel_opts,
                                    index=_far_sel_idx,
                                    horizontal=True,
                                    key="_far_sel_val",
                                    label_visibility="collapsed",
                                    help="Selects which FAR type drives all massing scenario calculations and the Max Buildable SF.",
                                )

                            _dev_focus  = st.session_state.get("dev_focus", "Residential")
                            _sub_comps  = st.session_state.get("dev_sub_comps", ["Ground Floor Retail"])
                            _show_nbrs  = st.session_state.get("show_nbr_toggle", False)
                            _far_sel    = st.session_state.get("_far_sel_val", "Auto (Max)")
                            _sub_key    = "_".join(sorted(_sub_comps))

                            # Compute effective FAR from user selection
                            if _far_sel.startswith("Residential"):
                                _effective_far = _res_far_v
                            elif _far_sel.startswith("Commercial"):
                                _effective_far = _comm_far_v
                            elif _far_sel.startswith("Facility"):
                                _effective_far = _facil_far_v
                            elif _far_sel.startswith("Base"):
                                _effective_far = _base_far_v
                            elif _far_sel.startswith("Bonus") or _far_sel.startswith("Max"):
                                _effective_far = _max_far_raw
                            else:  # Auto (Max)
                                _effective_far = max(_res_far_v, _comm_far_v, _facil_far_v, _base_far_v, _max_far_raw)

                            # Build effective zrules — override all FAR fields with selected value
                            _zrules_effective = dict(_zrules)
                            if not _far_sel.startswith("Auto") and _effective_far > 0:
                                _zrules_effective["res_far"]  = _effective_far
                                _zrules_effective["comm_far"] = _effective_far
                                _zrules_effective["base_far"] = _effective_far
                                _zrules_effective["max_far"]  = _effective_far

                            # Fetch neighbor lots from PLUTO if toggle enabled
                            _nbr_lots: list = []
                            if _show_nbrs and _zinfo.get("block") and _zinfo.get("borough_code"):
                                _nbr_cache_key = f"_nbr_{_zinfo.get('block')}_{_zinfo.get('borough_code')}"
                                if _nbr_cache_key not in st.session_state:
                                    _nbr_err = None
                                    try:
                                        import requests as _req
                                        _nbr_resp = _req.get(
                                            "https://data.cityofnewyork.us/resource/64uk-42ks.json",
                                            params={
                                                "$where": f"block='{_zinfo.get('block')}' AND borocode='{_zinfo.get('borough_code')}'",
                                                "$select": "lot,address,lotfront,lotdepth,bldgarea,numfloors,heightroof,bldgclass",
                                                "$limit": "20",
                                            },
                                            timeout=8,
                                        )
                                        _nbr_resp.raise_for_status()
                                        _nbr_raw = _nbr_resp.json()
                                        # Tag each with side relative to subject lot
                                        _subj_lot_int = int(re.sub(r"\D", "", str(_zinfo.get("lot", "0"))) or "0")
                                        for _nb in _nbr_raw:
                                            _nb_lot = int(re.sub(r"\D", "", str(_nb.get("lot", "0"))) or "0")
                                            if _nb_lot != _subj_lot_int:
                                                _nb["_side"] = "left" if _nb_lot < _subj_lot_int else "right"
                                        st.session_state[_nbr_cache_key] = [
                                            nb for nb in _nbr_raw if nb.get("_side")
                                        ]
                                    except Exception as _nbr_exc:
                                        st.session_state[_nbr_cache_key] = []
                                        _nbr_err = str(_nbr_exc)
                                    record_source_status(
                                        "Neighbor Lots (PLUTO, massing)", ok=(_nbr_err is None), detail=_nbr_err or ""
                                    )
                                    if _nbr_err:
                                        st.caption(f"⚠️ Neighbor lot fetch failed: {_nbr_err}")
                                _nbr_lots = st.session_state.get(_nbr_cache_key, [])

                            # Build / retrieve massing options
                            _far_sel_key = _far_sel.split("(")[0].strip().replace(" ", "_")
                            _mass_key = (
                                f"_massing_{_bbl_disp}_comb{len(_valid_adj)}"
                                f"_f{_dev_focus}_s{_sub_key}_n{int(_show_nbrs)}_far{_far_sel_key}"
                                if _using_combined else
                                f"_massing_{_bbl_disp}"
                                f"_f{_dev_focus}_s{_sub_key}_n{int(_show_nbrs)}_far{_far_sel_key}"
                            )
                            if _mass_key not in st.session_state:
                                st.session_state[_mass_key] = build_massing_options(
                                    _lf_v, _ld_v, _la_v, _primary_zone, _zrules_effective,
                                    lot_widths=_lot_widths,
                                    existing_bldg=_existing_bldg if _existing_bldg["floors"] > 0 else None,
                                    focus=_dev_focus,
                                    sub_components=_sub_comps,
                                    show_neighbors=_show_nbrs,
                                    neighbor_lots=_nbr_lots,
                                )
                            _options = st.session_state.get(_mass_key, [])

                            # Compute avg rents from comps data for revenue projections
                            _avg_rents = avg_rents_from_listings(listings)

                            # ── Underwriting Engine wiring ────────────────────────
                            # Reuses the same multi-year pro forma / IRR engine
                            # already proven in the Site Finder tab
                            # (modules/underwriting_engine.py) instead of only
                            # the single-year NOI/cap-value snapshot above.
                            # Builds an acquisition-cost basis once (reusing
                            # estimate_acquisition_cost + the same zinfo
                            # normalization the Portfolio-save button uses),
                            # then runs a full construction->stabilization->
                            # exit cash flow per massing scenario.
                            _uw_acq = None
                            try:
                                from modules.site_finder_valuation import estimate_acquisition_cost as _uw_est_acq
                                from modules.underwriting_engine import (
                                    build_cash_flows as _uw_build_cf, simple_sponsor_returns as _uw_simple_returns,
                                    lp_gp_waterfall as _uw_waterfall, run_sensitivity as _uw_run_sensitivity,
                                    solve_land_residual_value as _uw_solve_land_residual,
                                    DEFAULT_HOLD_YEARS_POST_STAB as _UW_D_HOLD, DEFAULT_RENT_GROWTH_PCT as _UW_D_RENTG,
                                    DEFAULT_EXPENSE_GROWTH_PCT as _UW_D_EXPG, DEFAULT_EXIT_CAP_SPREAD_BPS as _UW_D_EXITSPREAD,
                                    DEFAULT_CONSTRUCTION_LTC as _UW_D_LTC, DEFAULT_CONSTRUCTION_RATE as _UW_D_CRATE,
                                    DEFAULT_PERM_LTV as _UW_D_LTV, DEFAULT_PERM_DSCR_MIN as _UW_D_DSCR,
                                    DEFAULT_PERM_RATE as _UW_D_PRATE, DEFAULT_PERM_AMORT_YEARS as _UW_D_AMORT,
                                    DEFAULT_PREFERRED_RETURN_PCT as _UW_D_PREF, DEFAULT_PROMOTE_TIERS as _UW_D_TIERS,
                                    DEFAULT_GP_CO_INVEST_PCT as _UW_D_GPCO,
                                )
                                from modules.site_finder_valuation import _HARD_COST_PSF_GROUND_UP as _UW_HC_GU, _HARD_COST_PSF_CONVERSION as _UW_HC_CONV

                                _uw_bbl = (_zinfo or {}).get("bbl", "—")
                                _uw_acris_sum = st.session_state.get(f"_acris_{_uw_bbl}", {}).get("summary", {}) or {}
                                _uw_sale_psf_vals = [l["price_psf"] for l in _sales_listings if l.get("price_psf")]
                                _uw_mc = None
                                if _uw_sale_psf_vals:
                                    _uw_mc = {
                                        "median_price_psf": sorted(_uw_sale_psf_vals)[len(_uw_sale_psf_vals) // 2],
                                        "count": len(_uw_sale_psf_vals),
                                    }
                                _uw_prop_base = _map_zinfo_to_portfolio_schema(_zinfo, _zinfo_label, lat, lon)
                                _uw_prop_base.update({
                                    "last_sale_price": _uw_acris_sum.get("latest_sale_price"),
                                    "last_sale_date":  _uw_acris_sum.get("latest_sale_date"),
                                    "market_comps":    _uw_mc,
                                    "is_vacant":       "vacant" in str((_zinfo or {}).get("land_use", "")).lower(),
                                    "landuse_code":    "",  # not exposed by zola_fetcher — falls back to the default assessment ratio
                                })
                                _uw_acq = _uw_est_acq(_uw_prop_base)
                            except Exception:
                                _uw_acq = None

                            def _build_uw_scenario_dict(_o: dict) -> dict:
                                """Shared massing-option -> underwriting_engine scenario
                                dict adapter, reused by both the quick summary-table IRR
                                column and the full pro forma deep-dive panel below."""
                                _net_sf   = _o.get("net_rentable_sqft", 0)
                                _gross_sf = _o.get("total_sqft", 0)
                                _hard_psf = _UW_HC_CONV if _o.get("is_conversion") else _UW_HC_GU
                                return {
                                    "scenario_id": f"massing_{_o.get('number','')}",
                                    "label": _o.get("name", "—"),
                                    "use_type": "rental",
                                    "development_type": "conversion" if _o.get("is_conversion") else "ground_up",
                                    "lot_sf": _la_v,
                                    "gross_buildable_sf": _gross_sf,
                                    "residential_gross_sf": _gross_sf,
                                    "net_buildable_sf": _net_sf,
                                    "retail_sf": 0.0,
                                    "net_retail_sf": 0.0,
                                    "hard_cost_psf": _hard_psf,
                                    "hard_cost_basis": "conversion/renovation" if _o.get("is_conversion") else "ground-up new construction",
                                    "assumptions_note": [],
                                }

                            if _options:
                                # ── Summary Metrics Table ─────────────────────
                                _max_far_val = _effective_far if _effective_far > 0 else max(_res_far_v, _comm_far_v, _base_far_v)
                                _far_type_label = (
                                    _far_sel.split("(")[0].strip() if not _far_sel.startswith("Auto")
                                    else ("Comm. FAR" if (_comm_far_v > _res_far_v and _comm_far_v > 0)
                                    else ("Res. FAR" if _res_far_v > 0 else "Base FAR"))
                                )
                                _max_bldg_sf = int(_la_v * _max_far_val) if _max_far_val > 0 else 0
                                _sum_rows = []
                                for _o in _options:
                                    _net_sf    = _o.get("net_rentable_sqft", 0)
                                    _gross_sf  = _o.get("total_sqft", 0)
                                    _units     = _o.get("units_est", max(1, int(_net_sf / 750)))
                                    _far_used_pct = (
                                        f"{int(_gross_sf / _max_bldg_sf * 100)}%"
                                        if _max_bldg_sf > 0 else "—"
                                    )
                                    # Same NOI/cap-value math each scenario's own
                                    # "Unit Mix & Financials" expander computes
                                    # further down — surfaced here too so
                                    # scenarios can be ranked by economics
                                    # without opening all of them one at a time.
                                    _noi_val, _cap_val = None, None
                                    if _net_sf > 0:
                                        try:
                                            _sum_umix = optimize_unit_mix(_net_sf, neighborhood)
                                            _sum_rev = compute_revenue(
                                                _sum_umix, _avg_rents,
                                                risk_level=_o.get("risk_level", "MED"), borough=borough,
                                            )
                                            _noi_val = _sum_rev["noi"]
                                            _cap_val = _sum_rev["est_cap_value"]
                                        except Exception:
                                            pass

                                    # Multi-year IRR / equity multiple via the
                                    # same Underwriting Engine used in Site
                                    # Finder — a real construction->
                                    # stabilization->exit pro forma, not just
                                    # the Year-1 NOI/cap-value snapshot above.
                                    _irr_val, _em_val = None, None
                                    if _uw_acq is not None and _gross_sf > 0:
                                        try:
                                            _uw_scn = _build_uw_scenario_dict(_o)
                                            _uw_cf = _uw_build_cf(
                                                _uw_scn, _uw_acq, avg_rents=_avg_rents,
                                                risk_level=_o.get("risk_level", "MED"), borough=borough,
                                            )
                                            _uw_returns = _uw_simple_returns(_uw_cf["annual_cash_flows"])
                                            _irr_val = _uw_returns["irr"]
                                            _em_val = _uw_returns["equity_multiple"]
                                        except Exception:
                                            pass

                                    # Feasibility score (Batch D item 3) — additive column;
                                    # every other field in this row is unchanged.
                                    _sum_feas = compute_massing_feasibility_score(
                                        _o, lot_frontage_ft=_lf_v, lot_area_sqft=_la_v, lot_depth_ft=_ld_v,
                                        zoning_dist=_primary_zone, max_far=_max_far_val,
                                        is_landmark=bool(_zinfo.get("landmark") and _zinfo.get("landmark") != "—"),
                                        is_historic_district=bool(_zinfo.get("historic_dist") and _zinfo.get("historic_dist") != "—"),
                                    )

                                    _sum_rows.append({
                                        "#":           _o.get("number", ""),
                                        "Scenario":    _o.get("name", "—"),
                                        "Risk":        _o.get("risk_level", "—"),
                                        "Feasibility": f"{_sum_feas['score']}/100 ({_sum_feas['tier']})",
                                        "Stories":     _o.get("floors", 0),
                                        "Height (ft)": _o.get("height_ft", 0),
                                        "Gross SF":    _gross_sf,
                                        "Max Bldg SF": _max_bldg_sf,
                                        "FAR Used":    _far_used_pct,
                                        "Net SF":      _net_sf,
                                        "Est. Units":  _units,
                                        "Levered IRR": _irr_val,
                                        "Equity Multiple": _em_val,
                                        "Loss %":      f"{int(_o.get('loss_factor',0.15)*100)}%",
                                        "Est. NOI":    _noi_val,
                                        "Est. Cap Value": _cap_val,
                                    })
                                _sum_df = pd.DataFrame(_sum_rows)
                                with st.expander("📊 All Scenarios — Summary Table", expanded=True):
                                    st.caption(
                                        "Est. NOI / Cap Value use a single stabilized-year assumption set. "
                                        "Levered IRR / Equity Multiple run the full Underwriting Engine "
                                        "(construction → stabilization → exit, with financing) using default "
                                        "assumptions and a Simple Sponsor equity structure"
                                        + (" — unavailable (no acquisition basis found)." if _uw_acq is None else ".")
                                        + " Both are preliminary screening comparisons, not a substitute for a full pro forma."
                                    )
                                    st.dataframe(
                                        _sum_df,
                                        use_container_width=True,
                                        hide_index=True,
                                        column_config={
                                            "#":           st.column_config.NumberColumn("#", width="small"),
                                            "Gross SF":    st.column_config.NumberColumn("Gross SF", format="%d"),
                                            "Max Bldg SF": st.column_config.NumberColumn("Max Bldg SF", format="%d",
                                                            help=f"Max buildable SF = lot area × {_far_type_label} ({_max_far_val})"),
                                            "Net SF":      st.column_config.NumberColumn("Net SF",   format="%d"),
                                            "Est. Units":  st.column_config.NumberColumn("Est. Units", format="%d"),
                                            "Stories":     st.column_config.NumberColumn("Stories",  format="%d"),
                                            "Height (ft)": st.column_config.NumberColumn("Height (ft)", format="%d"),
                                            "Levered IRR": st.column_config.NumberColumn("Levered IRR", format="percent"),
                                            "Equity Multiple": st.column_config.NumberColumn("Equity Multiple", format="%.2fx"),
                                            "Est. NOI":    st.column_config.NumberColumn("Est. NOI", format="$%d"),
                                            "Est. Cap Value": st.column_config.NumberColumn("Est. Cap Value", format="$%d"),
                                        },
                                    )
                                    _best_by_cap = max(
                                        (r for r in _sum_rows if r["Est. Cap Value"]),
                                        key=lambda r: r["Est. Cap Value"], default=None,
                                    )
                                    _best_by_irr = max(
                                        (r for r in _sum_rows if r["Levered IRR"] is not None),
                                        key=lambda r: r["Levered IRR"], default=None,
                                    )
                                    if _best_by_cap:
                                        st.caption(f"💡 Highest estimated cap value: **{_best_by_cap['Scenario']}** (${_best_by_cap['Est. Cap Value']:,.0f})")
                                    if _best_by_irr:
                                        st.caption(f"💡 Highest levered IRR: **{_best_by_irr['Scenario']}** ({_best_by_irr['Levered IRR']:.1%})")

                                # ── Entitlement Path — decision framing ──────
                                # Groups the 10 scenarios by APPROVAL TYPE
                                # (as-of-right / minor mod / BSA variance /
                                # ULURP rezoning) instead of leaving them as a
                                # flat tile list — each path's typical
                                # timeline/cost comes from
                                # modules/zoning_rules.ENTITLEMENT_PATHS.
                                with st.expander("🏛️ Entitlement Path — Decision View", expanded=False):
                                    st.caption(
                                        "Scenarios grouped by the approval path they'd realistically require — "
                                        "illustrative NYC rules-of-thumb, not a substitute for land-use counsel's "
                                        "project-specific assessment."
                                    )
                                    _ent_groups: dict = {}
                                    for _eo in _options:
                                        _epath = estimate_entitlement_path(_eo.get("risk_level", ""), _eo.get("description", ""))
                                        _ent_groups.setdefault(_epath["path_key"], {"info": _epath, "scenarios": []})
                                        _ent_groups[_epath["path_key"]]["scenarios"].append(_eo.get("name", "—"))
                                    _ent_order = ["as_of_right", "minor_modification", "bsa_variance", "ulurp_rezoning"]
                                    for _ek in _ent_order:
                                        if _ek not in _ent_groups:
                                            continue
                                        _eg = _ent_groups[_ek]
                                        _einfo = _eg["info"]
                                        st.markdown(
                                            f"**{_einfo['label']}** — {', '.join(_eg['scenarios'])}\n\n"
                                            f"- *Timeline:* {_einfo['timeline']}\n"
                                            f"- *Cost range:* {_einfo['cost_range']}\n"
                                            f"- *Approval likelihood:* {_einfo['approval_probability']}\n"
                                            f"- {_einfo['description']}"
                                        )
                                        st.markdown("---")

                            if _options:
                                # ── Risk badge helper ────────────────────────
                                def _risk_badge(rl: str) -> str:
                                    if rl == "LOW":
                                        return "<span class='risk-low'>🟢 Low Risk</span>"
                                    elif rl == "HIGH":
                                        return "<span class='risk-high'>🔴 High Risk</span>"
                                    return "<span class='risk-med'>🟡 Med Risk</span>"

                                # ── Tile renderer ────────────────────────────
                                # Feasibility score (Batch D item 3) — computed once, reused by
                                # every tile below and the summary table further down. Additive:
                                # doesn't touch any of the 10 scenario dicts or _calc_massing()'s
                                # own return value.
                                _mass_m = _calc_massing(_lf_v, _ld_v, _la_v, _zrules) if _zrules else {}

                                def _render_tile(opt: dict, key_suffix: str):
                                    rl = opt.get("risk_level", "MED")
                                    _tile_gross   = opt.get("total_sqft", 0)
                                    _tile_net     = opt.get("net_rentable_sqft", 0)
                                    _tile_max_sf  = int(_la_v * _max_far_val) if _max_far_val > 0 else 0
                                    _feas = compute_massing_feasibility_score(
                                        opt, lot_frontage_ft=_lf_v, lot_area_sqft=_la_v, lot_depth_ft=_ld_v,
                                        zoning_dist=_primary_zone, max_far=_max_far_val,
                                        is_landmark=bool(_zinfo.get("landmark") and _zinfo.get("landmark") != "—"),
                                        is_historic_district=bool(_zinfo.get("historic_dist") and _zinfo.get("historic_dist") != "—"),
                                    )
                                    _feas_color = {"Strong": "#1F6B3A", "Viable": "#8B6914",
                                                   "Constrained": "#B45309", "Weak": "#7A2E2E"}.get(_feas["tier"], "#6B7280")
                                    st.markdown(
                                        f"<div style='background:#FFFFFF;border:1px solid #DCD5C2;"
                                        f"border-radius:12px;padding:8px 10px 4px'>"
                                        f"{_risk_badge(rl)}"
                                        f"<span style='float:right;font-size:0.62rem;font-weight:700;color:{_feas_color}' "
                                        f"title='Massing feasibility: FAR utilization, frontage/height fit, lot depth, "
                                        f"zoning flexibility, landmark risk'>"
                                        f"Feasibility: {_feas['score']}/100 ({_feas['tier']})</span>"
                                        f"<div style='font-weight:700;font-size:0.72rem;margin:5px 0 1px'>"
                                        f"{opt['name']}</div></div>",
                                        unsafe_allow_html=True,
                                    )
                                    st.plotly_chart(
                                        opt["fig"],
                                        use_container_width=True,
                                        config={"displayModeBar": False},
                                        key=f"mass_{key_suffix}",
                                    )
                                    # 4-metric row: compact HTML (st.metric is too large for narrow tiles)
                                    _tile_max_sf_str = f"{_tile_max_sf:,}" if _tile_max_sf else "—"
                                    _tile_ht_str = f"{opt.get('height_ft',0)}ft/{opt.get('floors',0)}fl"
                                    st.markdown(
                                        f"<div style='display:grid;grid-template-columns:repeat(4,1fr);"
                                        f"gap:3px;margin:6px 0'>"
                                        f"<div style='text-align:center;padding:5px 2px;background:#E8E3D4;border-radius:6px'>"
                                        f"<div style='font-size:0.55rem;color:#6B7280;font-weight:700;text-transform:uppercase;"
                                        f"letter-spacing:0.04em;line-height:1.2'>Gross SF</div>"
                                        f"<div style='font-size:0.82rem;font-weight:700;color:#1A1D2E;line-height:1.3'>{_tile_gross:,}</div></div>"
                                        f"<div style='text-align:center;padding:5px 2px;background:#E4E8F1;border-radius:6px' "
                                        f"title='Lot area × {_far_type_label} ({_max_far_val})'>"
                                        f"<div style='font-size:0.55rem;color:#2A3E63;font-weight:700;text-transform:uppercase;"
                                        f"letter-spacing:0.04em;line-height:1.2'>Max Bldg SF</div>"
                                        f"<div style='font-size:0.82rem;font-weight:700;color:#2A3E63;line-height:1.3'>{_tile_max_sf_str}</div></div>"
                                        f"<div style='text-align:center;padding:5px 2px;background:#E6F0E5;border-radius:6px'>"
                                        f"<div style='font-size:0.55rem;color:#1F6B3A;font-weight:700;text-transform:uppercase;"
                                        f"letter-spacing:0.04em;line-height:1.2'>Net Rentable</div>"
                                        f"<div style='font-size:0.82rem;font-weight:700;color:#1F6B3A;line-height:1.3'>{_tile_net:,}</div></div>"
                                        f"<div style='text-align:center;padding:5px 2px;background:#EDE7F3;border-radius:6px'>"
                                        f"<div style='font-size:0.55rem;color:#6B4E8E;font-weight:700;text-transform:uppercase;"
                                        f"letter-spacing:0.04em;line-height:1.2'>Ht / Floors</div>"
                                        f"<div style='font-size:0.82rem;font-weight:700;color:#6B4E8E;line-height:1.3'>{_tile_ht_str}</div></div>"
                                        f"</div>",
                                        unsafe_allow_html=True,
                                    )

                                    # Strategy + description (collapsible)
                                    with st.expander("📋 Strategy & Description", expanded=False):
                                        st.markdown(
                                            f"<div style='font-size:0.84rem;line-height:1.5;color:#3D4152'>"
                                            f"<b>Strategy:</b> {opt.get('strategy','')}</div>"
                                            f"<div style='font-size:0.82rem;line-height:1.5;color:#3D4152;"
                                            f"margin-top:6px'>{opt.get('description','')}</div>",
                                            unsafe_allow_html=True,
                                        )

                                    # Unit mix + financials + floor plates
                                    with st.expander("📊 Unit Mix, Financials & Floor Plans", expanded=False):
                                        _tab_mix, _tab_fp, _tab_stack = st.tabs(
                                            ["💰 Unit Mix & Financials", "🏢 Floor Plates", "🏗️ Floor-by-Floor Stack"]
                                        )
                                        _nrsf = opt.get("net_rentable_sqft", 0)
                                        _is_c = opt.get("is_conversion", False)
                                        with _tab_mix:
                                            if _nrsf > 0:
                                                _umix = optimize_unit_mix(_nrsf, neighborhood)
                                                _rev  = compute_revenue(
                                                    _umix, _avg_rents,
                                                    risk_level=rl, borough=borough
                                                )
                                                st.markdown(
                                                    f"**Unit Mix** "
                                                    f"({'Conversion' if _is_c else 'New Build'}, "
                                                    f"{int(opt.get('loss_factor',0.15)*100)}% loss factor)"
                                                )
                                                _mix_rows = []
                                                for _ut in ["Studio","1 Bed","2 Bed","3 Bed","4+ Bed"]:
                                                    if _ut in _umix and _umix[_ut]["count"] > 0:
                                                        _ui = _umix[_ut]
                                                        _mix_rows.append({
                                                            "Unit": _ut,
                                                            "Count": _ui["count"],
                                                            "Avg SF": f"{_ui['avg_sf']:,.0f}",
                                                            "% of Units": f"{_ui['pct_units']*100:.0f}%",
                                                            "Monthly Rent": f"${_avg_rents.get(_ut, 0):,.0f}" if _avg_rents.get(_ut) else "—",
                                                        })
                                                if _mix_rows:
                                                    st.dataframe(
                                                        pd.DataFrame(_mix_rows),
                                                        use_container_width=True,
                                                        hide_index=True,
                                                    )
                                                st.markdown("**Revenue Projection**")
                                                _fin_rows = [
                                                    {"Metric": "Gross Annual Rent",  "Value": f"${_rev['gross_annual_rent']:,.0f}"},
                                                    {"Metric": f"EGI ({int(_rev['occupancy_used']*100)}% occ.)", "Value": f"${_rev['egi']:,.0f}"},
                                                    {"Metric": "Operating Expenses (35%)", "Value": f"${_rev['opex']:,.0f}"},
                                                    {"Metric": "Net Operating Income",     "Value": f"${_rev['noi']:,.0f}"},
                                                    {"Metric": f"Est. Cap Value ({_rev['cap_rate_used']*100:.2f}% cap)", "Value": f"${_rev['est_cap_value']:,.0f}"},
                                                ]
                                                st.dataframe(
                                                    pd.DataFrame(_fin_rows),
                                                    use_container_width=True,
                                                    hide_index=True,
                                                )
                                                _hood_sf = get_avg_sf(neighborhood)
                                                st.caption(
                                                    f"Avg SF assumptions for {neighborhood}: "
                                                    + " | ".join(f"{k}: {v:,.0f}" for k,v in _hood_sf.items())
                                                )
                                        with _tab_fp:
                                            _fp_w = max(20.0, opt.get("footprint_sqft", 400) ** 0.5)
                                            _fp_d = max(20.0, opt.get("footprint_sqft", 400) / max(1, _fp_w))
                                            _is_mu = opt.get("name","").lower().find("mixed") >= 0
                                            _fpc1, _fpc2 = st.columns(2)
                                            with _fpc1:
                                                st.plotly_chart(
                                                    floor_plate_fig(_fp_w, _fp_d, is_ground=True, is_mixed_use=_is_mu),
                                                    use_container_width=True,
                                                    config={"displayModeBar": False},
                                                    key=f"fp_gnd_{key_suffix}",
                                                )
                                            with _fpc2:
                                                st.plotly_chart(
                                                    floor_plate_fig(_fp_w, _fp_d, is_ground=False),
                                                    use_container_width=True,
                                                    config={"displayModeBar": False},
                                                    key=f"fp_upr_{key_suffix}",
                                                )
                                            st.caption("Indicative floor plate layout — unit sizes and placement are schematic.")

                                        with _tab_stack:
                                            _stack = build_floor_stack(opt, _mass_m)
                                            if not _stack:
                                                st.caption("Floor stack unavailable for this scenario.")
                                            else:
                                                _stack_floor = st.select_slider(
                                                    "Floor", options=[f["floor_num"] for f in _stack],
                                                    key=f"stack_floor_{key_suffix}",
                                                )
                                                _sel_floor = next(f for f in _stack if f["floor_num"] == _stack_floor)
                                                st.markdown(
                                                    f"**Floor {_sel_floor['floor_num']}** — {_sel_floor['program_label']} "
                                                    f"({_sel_floor['gross_sf']:,} SF)"
                                                    + (" · ⚠️ within setback/upper-tier zone" if _sel_floor["is_in_setback_zone"] else "")
                                                )
                                                st.plotly_chart(
                                                    floor_plate_fig(_fp_w, _fp_d, is_ground=(_sel_floor["floor_num"] == 1),
                                                                     is_mixed_use=_is_mu),
                                                    use_container_width=True,
                                                    config={"displayModeBar": False},
                                                    key=f"fp_stack_{key_suffix}",
                                                )
                                                st.caption(
                                                    "Reuses the same schematic floor-plate drawing per floor — the "
                                                    "footprint doesn't yet narrow above the setback line (a documented "
                                                    "limitation, not a bug)."
                                                )
                                                with st.expander("All floors", expanded=False):
                                                    _stack_rows = [{
                                                        "Floor": f["floor_num"], "Program": f["program_label"],
                                                        "Gross SF": f"{f['gross_sf']:,}",
                                                        "Zone": "Setback/Upper Tier" if f["is_in_setback_zone"] else "Base Height",
                                                    } for f in _stack]
                                                    st.dataframe(pd.DataFrame(_stack_rows), use_container_width=True, hide_index=True)

                                # ── Display tiles by risk tier ───────────────
                                for _tier, _tier_label, _tier_color in [
                                    ("LOW",  "🟢 Low Risk Scenarios",    "#E6F0E5"),
                                    ("MED",  "🟡 Medium Risk Scenarios", "#F5EBD3"),
                                    ("HIGH", "🔴 High Risk Scenarios",   "#F3E1DE"),
                                ]:
                                    _tier_opts = [o for o in _options if o.get("risk_level") == _tier]
                                    if not _tier_opts:
                                        continue
                                    st.markdown(
                                        f"<div style='background:{_tier_color};border-radius:8px;"
                                        f"padding:6px 14px;margin:16px 0 8px;font-weight:700;font-size:0.85rem'>"
                                        f"{_tier_label}</div>",
                                        unsafe_allow_html=True,
                                    )
                                    if _tier == "HIGH" and len(_tier_opts) > 3:
                                        _tile_rows = [_tier_opts[:3], _tier_opts[3:]]
                                    else:
                                        _tile_rows = [_tier_opts]
                                    for _tile_row in _tile_rows:
                                        _tcols = st.columns(len(_tile_row))
                                        for _tc, _topt in zip(_tcols, _tile_row):
                                            with _tc:
                                                _render_tile(
                                                    _topt,
                                                    f"{_topt['name'].replace(' ','_').replace('/','_')}_{_bbl_disp}_{_far_sel_key}",
                                                )

                                # ── Side-by-side comparison panel ───────────
                                st.markdown("---")
                                st.markdown(
                                    "<div class='section-label'>📐 Side-by-Side Comparison</div>",
                                    unsafe_allow_html=True,
                                )
                                _all_names = [o["name"] for o in _options]
                                _selected_names = st.multiselect(
                                    "Select 2–3 scenarios to compare",
                                    _all_names,
                                    max_selections=3,
                                    key=f"massing_compare_{_bbl_disp}",
                                    help="Pick any 2 or 3 scenarios to view side by side with full metrics.",
                                )
                                if len(_selected_names) >= 2:
                                    _sel_opts = [o for o in _options if o["name"] in _selected_names]
                                    _cmp_cols = st.columns(len(_sel_opts))
                                    for _cc, _so in zip(_cmp_cols, _sel_opts):
                                        with _cc:
                                            st.markdown(
                                                f"{_risk_badge(_so.get('risk_level','MED'))} "
                                                f"**{_so['name']}**",
                                                unsafe_allow_html=True,
                                            )
                                            st.plotly_chart(
                                                _so["fig"],
                                                use_container_width=True,
                                                config={"displayModeBar": False},
                                                key=f"cmp_{_so['name'].replace(' ','_')}_{_bbl_disp}",
                                            )
                                            _cmp_data = [
                                                ("Gross Area",    f"{_so.get('total_sqft',0):,} SF"),
                                                ("Net Rentable",  f"{_so.get('net_rentable_sqft',0):,} SF"),
                                                ("Height",        f"{_so.get('height_ft',0)} ft"),
                                                ("Floors",        str(_so.get("floors",0))),
                                                ("Floor Plate",   f"{_so.get('typical_floor_sqft',0):,} SF"),
                                                ("Loss Factor",   f"{int(_so.get('loss_factor',0.15)*100)}%"),
                                            ]
                                            _cmp_nrsf = _so.get("net_rentable_sqft", 0)
                                            if _cmp_nrsf > 0:
                                                try:
                                                    _cmp_umix = optimize_unit_mix(_cmp_nrsf, neighborhood)
                                                    _cmp_rev = compute_revenue(
                                                        _cmp_umix, _avg_rents,
                                                        risk_level=_so.get("risk_level", "MED"), borough=borough,
                                                    )
                                                    _cmp_data.append(("Est. NOI", f"${_cmp_rev['noi']:,.0f}"))
                                                    _cmp_data.append(("Est. Cap Value", f"${_cmp_rev['est_cap_value']:,.0f}"))
                                                except Exception:
                                                    pass
                                            for _ck, _cv in _cmp_data:
                                                st.markdown(
                                                    f"<div style='display:flex;justify-content:space-between;"
                                                    f"border-bottom:1px solid #E8E3D4;padding:4px 0;"
                                                    f"font-size:0.79rem'>"
                                                    f"<span style='color:#6B7280'>{_ck}</span>"
                                                    f"<b>{_cv}</b></div>",
                                                    unsafe_allow_html=True,
                                                )
                                            st.markdown(
                                                f"<div style='margin-top:8px;font-size:0.73rem;color:#3D4152'>"
                                                f"{_so.get('strategy','')}</div>",
                                                unsafe_allow_html=True,
                                            )
                                elif _selected_names:
                                    st.caption("Select at least 2 scenarios to enable comparison.")

                                # ── Underwriting Pro Forma — Deep Dive ───────
                                # Full editable pro forma for one selected
                                # scenario (financing/hold assumptions,
                                # equity structure, sensitivity/stress test) —
                                # reuses the exact modules.underwriting_engine
                                # machinery and UI pattern already proven in
                                # Site Finder's _render_underwriting_section(),
                                # rather than re-implementing it, so results
                                # are directly comparable across both tabs.
                                st.markdown("---")
                                st.markdown(
                                    "<div class='section-label'>📊 Underwriting Pro Forma — Deep Dive</div>",
                                    unsafe_allow_html=True,
                                )
                                st.caption(
                                    "Full construction → stabilization → exit pro forma for one scenario at a "
                                    "time, with editable financing/hold assumptions, an equity-structure toggle, "
                                    "and a sensitivity/stress test. Not a lender-grade or GP-facing underwriting "
                                    "package; assumptions are editable rules of thumb."
                                )
                                if _uw_acq is None:
                                    st.info("No acquisition-cost basis available for this property — underwriting pro forma unavailable.")
                                else:
                                    from modules.site_finder_ui import _pct_input as _uwd_pct_input, _flatten_underwriting_for_export as _uwd_flatten

                                    _uwd_key_base = f"pa_uw_{_bbl_disp}_{_far_sel_key}"
                                    _uwd_default_name = _best_by_irr["Scenario"] if _best_by_irr else _all_names[0]
                                    _uwd_chosen_name = st.selectbox(
                                        "Scenario to underwrite", options=_all_names,
                                        index=_all_names.index(_uwd_default_name) if _uwd_default_name in _all_names else 0,
                                        key=f"{_uwd_key_base}_scenario",
                                    )
                                    _uwd_opt = next(o for o in _options if o["name"] == _uwd_chosen_name)
                                    _uwd_scenario = _build_uw_scenario_dict(_uwd_opt)

                                    with st.expander("⚙️ Financing & Hold Assumptions", expanded=False):
                                        uc1, uc2, uc3 = st.columns(3)
                                        with uc1:
                                            _uwd_hold = st.number_input("Hold period (yrs)", min_value=1, max_value=20,
                                                                          value=_UW_D_HOLD, key=f"{_uwd_key_base}_hold")
                                            _uwd_rentg = _uwd_pct_input("Rent growth %/yr", _UW_D_RENTG, f"{_uwd_key_base}_rentg")
                                            _uwd_expg = _uwd_pct_input("Expense growth %/yr", _UW_D_EXPG, f"{_uwd_key_base}_expg")
                                        with uc2:
                                            _uwd_exitspread = st.number_input("Exit cap spread (bps over going-in)", min_value=-200, max_value=500,
                                                                                value=_UW_D_EXITSPREAD, step=10, key=f"{_uwd_key_base}_exitspread")
                                            _uwd_ltc = _uwd_pct_input("Construction LTC %", _UW_D_LTC, f"{_uwd_key_base}_ltc")
                                            _uwd_crate = _uwd_pct_input("Construction rate %", _UW_D_CRATE, f"{_uwd_key_base}_crate", step=0.125)
                                        with uc3:
                                            _uwd_ltv = _uwd_pct_input("Perm loan LTV %", _UW_D_LTV, f"{_uwd_key_base}_ltv")
                                            _uwd_dscr = st.number_input("Perm loan min DSCR", min_value=1.0, max_value=2.0,
                                                                          value=_UW_D_DSCR, step=0.05, key=f"{_uwd_key_base}_dscr")
                                            _uwd_prate = _uwd_pct_input("Perm loan rate %", _UW_D_PRATE, f"{_uwd_key_base}_prate", step=0.125)
                                        _uwd_amort = st.number_input("Perm loan amortization (yrs)", min_value=10, max_value=40,
                                                                       value=_UW_D_AMORT, key=f"{_uwd_key_base}_amort")

                                    _uwd_financing_kwargs = {
                                        "construction_ltc": _uwd_ltc, "construction_rate": _uwd_crate,
                                        "perm_ltv": _uwd_ltv, "perm_dscr_min": _uwd_dscr,
                                        "perm_rate": _uwd_prate, "perm_amort_years": _uwd_amort,
                                    }
                                    _uwd_cf_kwargs = {
                                        "avg_rents": _avg_rents, "risk_level": _uwd_opt.get("risk_level", "MED"),
                                        "borough": borough, "market_comps": _uw_mc,
                                        "hold_years": _uwd_hold, "rent_growth_pct": _uwd_rentg,
                                        "expense_growth_pct": _uwd_expg, "exit_cap_spread_bps": _uwd_exitspread,
                                        "financing_kwargs": _uwd_financing_kwargs,
                                    }

                                    _uwd_equity_choice = st.radio(
                                        "Equity Structure", ["Simple Sponsor IRR", "LP/GP Waterfall"],
                                        key=f"{_uwd_key_base}_equity", horizontal=True,
                                    )
                                    _uwd_equity_structure = "waterfall" if _uwd_equity_choice == "LP/GP Waterfall" else "simple"

                                    _uwd_waterfall_kwargs = {}
                                    if _uwd_equity_structure == "waterfall":
                                        with st.expander("💼 Waterfall Assumptions", expanded=True):
                                            uw1, uw2 = st.columns(2)
                                            with uw1:
                                                _uwd_pref = _uwd_pct_input("Preferred return %", _UW_D_PREF, f"{_uwd_key_base}_pref")
                                            with uw2:
                                                _uwd_gpco = _uwd_pct_input("GP co-invest % of equity", _UW_D_GPCO, f"{_uwd_key_base}_gpco")
                                            st.caption("Promote tiers (GP % of cash above each IRR hurdle):")
                                            _uwd_tiers = []
                                            for _uwd_ti, (lo, hi, default_pct) in enumerate(_UW_D_TIERS):
                                                hi_label = f"{hi:.0%}" if hi is not None else "∞"
                                                gp_pct = st.slider(f"{lo:.0%}–{hi_label} IRR", 0.0, 1.0, default_pct, step=0.05,
                                                                    key=f"{_uwd_key_base}_tier{_uwd_ti}", format="%.0f%%")
                                                _uwd_tiers.append((lo, hi, gp_pct))
                                            _uwd_waterfall_kwargs = {"preferred_return_pct": _uwd_pref, "promote_tiers": _uwd_tiers, "gp_co_invest_pct": _uwd_gpco}

                                    _uwd_cf_result = _uw_build_cf(_uwd_scenario, _uw_acq, **_uwd_cf_kwargs)

                                    if _uwd_equity_structure == "waterfall":
                                        _uwd_returns = _uw_waterfall(_uwd_cf_result["annual_cash_flows"], **_uwd_waterfall_kwargs)
                                        _uwd_headline_irr, _uwd_headline_em = _uwd_returns["lp_irr"], _uwd_returns["lp_equity_multiple"]
                                    else:
                                        _uwd_returns = _uw_simple_returns(_uwd_cf_result["annual_cash_flows"])
                                        _uwd_headline_irr, _uwd_headline_em = _uwd_returns["irr"], _uwd_returns["equity_multiple"]

                                    um1, um2, um3, um4 = st.columns(4)
                                    um1.metric("Levered IRR" + (" (LP)" if _uwd_equity_structure == "waterfall" else ""),
                                               f"{_uwd_headline_irr:.1%}" if _uwd_headline_irr is not None else "N/A")
                                    um2.metric("Equity Multiple" + (" (LP)" if _uwd_equity_structure == "waterfall" else ""),
                                               f"{_uwd_headline_em:.2f}x" if _uwd_headline_em is not None else "N/A")
                                    um3.metric("Total Dev. Cost", f"${_uwd_cf_result['total_dev_cost']:,.0f}")
                                    um4.metric("Year 1 NOI", f"${_uwd_cf_result['year1_noi']:,.0f}" if _uwd_cf_result["year1_noi"] else "—")

                                    # Acquisition-analysis output metrics — None for a condo
                                    # sellout (no stabilized Year-1 NOI/debt service to divide by).
                                    um5, um6, um7 = st.columns(3)
                                    _uwd_dscr = _uwd_cf_result.get("achieved_dscr_yr1")
                                    _uwd_coc = _uwd_cf_result.get("cash_on_cash_yr1")
                                    _uwd_yoc = _uwd_cf_result.get("yield_on_cost")
                                    um5.metric("Achieved DSCR (Yr 1)", f"{_uwd_dscr:.2f}x" if _uwd_dscr is not None else "N/A")
                                    um6.metric("Cash-on-Cash (Yr 1)", f"{_uwd_coc:.1%}" if _uwd_coc is not None else "N/A")
                                    um7.metric("Yield on Cost", f"{_uwd_yoc:.1%}" if _uwd_yoc is not None else "N/A")

                                    if _uwd_equity_structure == "waterfall":
                                        ug1, ug2 = st.columns(2)
                                        ug1.metric("GP IRR", f"{_uwd_returns['gp_irr']:.1%}" if _uwd_returns["gp_irr"] is not None else "N/A")
                                        ug2.metric("GP Promote ($)", f"${_uwd_returns['total_gp_promote']:,.0f}")
                                        st.caption(_uwd_returns.get("note", ""))

                                    with st.expander("Annual Cash Flow Detail", expanded=False):
                                        _uwd_cf_rows = [{
                                            "Year": c["year"], "Phase": c["phase"], "NOI": f"${c['noi']:,.0f}",
                                            "Debt Service": f"${c['debt_service']:,.0f}",
                                            "Reversion": f"${c['reversion_proceeds']:,.0f}" if c["reversion_proceeds"] else "—",
                                            "Equity CF": f"${c['equity_cf']:,.0f}",
                                        } for c in _uwd_cf_result["annual_cash_flows"]]
                                        st.dataframe(pd.DataFrame(_uwd_cf_rows), use_container_width=True, hide_index=True)

                                    with st.expander("Financing Detail", expanded=False):
                                        _uwd_fin = _uwd_cf_result["financing"]
                                        st.markdown(
                                            f"- Construction loan: ${_uwd_fin['construction_loan_amount']:,.0f} "
                                            f"(interest accrued: ${_uwd_fin['construction_interest_accrued']:,.0f})\n"
                                            f"- Permanent loan: ${_uwd_fin['perm_loan_amount']:,.0f} "
                                            f"(binding constraint: {_uwd_fin['binding_constraint']})\n"
                                            f"- Annual debt service: ${_uwd_fin['annual_debt_service']:,.0f}\n"
                                            f"- {_uwd_fin['note']}"
                                        )

                                    with st.expander("🔨 Trade-Level Budget Detail", expanded=False):
                                        st.caption(
                                            "Splits the same blended hard-cost rate used above into illustrative "
                                            "trade line items (site work, structure, envelope, MEP, interior "
                                            "finishes, general conditions) — a rule-of-thumb split, not a GC bid."
                                        )
                                        from modules.construction_budget_estimator import (
                                            estimate_trade_level_budget, BUDGET_TIER_MULTIPLIERS,
                                            RENOVATION_SCOPE_MULTIPLIERS,
                                        )
                                        _tlb_c1, _tlb_c2, _tlb_c3 = st.columns(3)
                                        _tlb_tier = _tlb_c1.selectbox(
                                            "Budget tier", list(BUDGET_TIER_MULTIPLIERS.keys()),
                                            index=1, key=f"{_uwd_key_base}_tlb_tier",
                                        )
                                        _tlb_scope = None
                                        if _uwd_scenario["development_type"] == "conversion":
                                            _tlb_scope = _tlb_c2.selectbox(
                                                "Renovation scope", list(RENOVATION_SCOPE_MULTIPLIERS.keys()),
                                                index=1, key=f"{_uwd_key_base}_tlb_scope",
                                            )
                                        _tlb_wage = _tlb_c3.checkbox(
                                            "Prevailing wage", value=False, key=f"{_uwd_key_base}_tlb_wage",
                                        )
                                        _tlb_result = estimate_trade_level_budget(
                                            _uwd_scenario["gross_buildable_sf"],
                                            development_type=_uwd_scenario["development_type"],
                                            budget_tier=_tlb_tier, renovation_scope=_tlb_scope,
                                            prevailing_wage=_tlb_wage,
                                        )
                                        if _tlb_result["error"]:
                                            st.caption(f"⚠️ {_tlb_result['error']}")
                                        else:
                                            _tlb_rows = [
                                                {"Trade": t, "$/SF": f"${d['psf']:,.2f}", "Total": f"${d['total']:,.0f}"}
                                                for t, d in _tlb_result["trade_breakdown"].items()
                                            ]
                                            st.dataframe(pd.DataFrame(_tlb_rows), use_container_width=True, hide_index=True)
                                            st.metric("Total Hard Cost (Trade-Level)", f"${_tlb_result['total_hard_cost']:,.0f}")
                                            # Stash for the Excel export's Construction Budget sheet (additive —
                                            # the sheet's existing 5-line fallback is unaffected when this key
                                            # isn't present, which is every other scenario/property as before).
                                            st.session_state[f"_uw_trade_budget_{_bbl_disp}"] = _tlb_result

                                    with st.expander("🎯 Land Residual Solver", expanded=False):
                                        st.caption(
                                            "Reverse-solves the maximum land/acquisition price this scenario can "
                                            "pay and still hit a target sponsor IRR — every other assumption above "
                                            "held fixed."
                                        )
                                        _uwd_lr_target = _uwd_pct_input("Target IRR", 0.15, f"{_uwd_key_base}_lr_target")
                                        if st.button("Solve for Max Land Value", key=f"{_uwd_key_base}_lr_btn"):
                                            st.session_state[f"{_uwd_key_base}_lr_result"] = _uw_solve_land_residual(
                                                _uwd_scenario, _uw_acq, target_irr=_uwd_lr_target, **_uwd_cf_kwargs,
                                            )
                                        _uwd_lr_cached = st.session_state.get(f"{_uwd_key_base}_lr_result")
                                        if _uwd_lr_cached:
                                            if _uwd_lr_cached["land_value"] is not None:
                                                lr1, lr2 = st.columns(2)
                                                lr1.metric("Max Supportable Land Value", f"${_uwd_lr_cached['land_value']:,.0f}")
                                                lr2.metric("Achieved IRR", f"{_uwd_lr_cached['achieved_irr']:.1%}" if _uwd_lr_cached["achieved_irr"] is not None else "N/A")
                                            if _uwd_lr_cached.get("note"):
                                                st.caption(f"ℹ️ {_uwd_lr_cached['note']}")

                                    with st.expander("📉 Sensitivity / Stress Test", expanded=False):
                                        if st.button("Run Sensitivity", key=f"{_uwd_key_base}_sens_btn"):
                                            _uwd_sens = _uw_run_sensitivity(
                                                _uwd_scenario, _uw_acq, base_kwargs=_uwd_cf_kwargs,
                                                equity_structure=_uwd_equity_structure, waterfall_kwargs=_uwd_waterfall_kwargs,
                                            )
                                            st.session_state[f"{_uwd_key_base}_sens_result"] = _uwd_sens

                                        _uwd_sens_cached = st.session_state.get(f"{_uwd_key_base}_sens_result")
                                        if _uwd_sens_cached:
                                            _uwd_tornado = _uwd_sens_cached["tornado_ranking"]
                                            _uwd_fig = go.Figure(go.Bar(
                                                x=[t["irr_range"] * 100 for t in _uwd_tornado],
                                                y=[t["lever"].replace("_", " ").title() for t in _uwd_tornado],
                                                orientation="h",
                                            ))
                                            _uwd_fig.update_layout(
                                                title="IRR Sensitivity (percentage-point swing)", xaxis_title="IRR range (pp)",
                                                height=280, margin=dict(l=10, r=10, t=40, b=10),
                                            )
                                            st.plotly_chart(_uwd_fig, use_container_width=True)
                                            for lever, rows in _uwd_sens_cached["grid"].items():
                                                st.markdown(f"**{lever.replace('_', ' ').title()}**")
                                                _uwd_grid_row = {f"{r['delta_pct']:+.0%}": (f"{r['irr']:.1%}" if r["irr"] is not None else "N/A") for r in rows}
                                                st.dataframe(pd.DataFrame([_uwd_grid_row]), use_container_width=True, hide_index=True)
                                        else:
                                            st.caption(
                                                "Not yet run — click above to stress-test rent, hard cost, exit cap "
                                                "rate, interest rate, hold period, vacancy, leverage, acquisition "
                                                "price, and operating expenses."
                                            )

                                    # Stash a flattened summary for the "Export This Property" section below.
                                    st.session_state[f"_uw_deepdive_{_bbl_disp}"] = _uwd_flatten(
                                        _uwd_scenario, _uwd_cf_result, _uwd_returns, _uwd_equity_structure
                                    )
                        else:
                            st.info(
                                "Lot dimensions not available in PLUTO for this property. "
                                "Massing diagrams require frontage, depth, and lot area data."
                            )
                    elif _primary_zone:
                        st.info(
                            f"Zoning rules for **{_primary_zone}** are not in our reference table. "
                            f"[View full zoning details on ZOLA]({_zola_url})"
                        )

            # ── Export This Property (PDF / PowerPoint / Excel) ─────────────────
            # Reuses modules/report_exporter.py's builders (proven in Site
            # Finder) via the same zinfo->normalized-schema adapter the
            # Portfolio save button uses — previously this tab had zero
            # export capability, no way to turn a diligence session into a
            # shareable memo.
            _exp_bbl = (_zinfo or {}).get("bbl", "—")
            if _exp_bbl and _exp_bbl != "—":
                with st.expander("⬇️ Export This Property", expanded=False):
                    from modules.report_exporter import (
                        build_pdf_report, build_pptx_report, build_excel_workbook, compose_fallback_ic_summary,
                    )

                    _exp_prop = _map_zinfo_to_portfolio_schema(_zinfo, _zinfo_label, lat, lon)
                    _exp_score = st.session_state.get("_ds_last_score_result")
                    if _exp_score:
                        _exp_prop["deal_score"] = _exp_score
                    _exp_abate = st.session_state.get(f"_abate_{_exp_bbl}")
                    if _exp_abate:
                        _exp_prop["tax_abatement"] = _exp_abate
                    _exp_rentstab = st.session_state.get(f"_rentstab_{_exp_bbl}")
                    if _exp_rentstab:
                        _exp_prop["rent_stab_signal"] = _exp_rentstab
                    _exp_uw = st.session_state.get(f"_uw_deepdive_{_exp_bbl}")
                    if _exp_uw:
                        _exp_prop["underwriting"] = _exp_uw
                        # Additive — only present if the Trade-Level Budget Detail
                        # expander above was opened/computed for this property;
                        # report_exporter.py's Construction Budget sheet falls back
                        # to its existing 5-line summary whenever this key is absent.
                        _exp_trade_budget = st.session_state.get(f"_uw_trade_budget_{_exp_bbl}")
                        if _exp_trade_budget and not _exp_trade_budget.get("error"):
                            _exp_prop["underwriting"]["trade_budget"] = _exp_trade_budget
                    _exp_sales_listings = st.session_state.get(_sales_key, {}).get("listings", [])
                    if _exp_sales_listings:
                        _exp_prop["market_comps"] = {"comps": _exp_sales_listings, "count": len(_exp_sales_listings)}
                    _exp_composite_dist = st.session_state.get(f"_composite_dist_{_exp_bbl}")
                    if _exp_composite_dist:
                        _exp_prop["composite_distress"] = _exp_composite_dist
                    _exp_prop.setdefault("strategies", [])

                    # Auto-composed IC summary (no LLM required) — previously
                    # this tab's exports always passed ic_summary=None, so the
                    # Thesis/Risks/Next-Steps section never appeared at all.
                    _exp_ic_summary = compose_fallback_ic_summary(_exp_prop)
                    st.caption(
                        f"IC summary auto-composed from the signals above "
                        f"(recommendation: {_exp_ic_summary['recommendation']}) — not an LLM-generated memo."
                    )

                    # ── Per-section export customization — all checked by
                    # default so the export content matches today's output
                    # exactly unless the user deliberately unchecks something.
                    st.markdown("**Sections to include in the export:**")
                    _sec_cols = st.columns(4)
                    _included_sections = {}
                    _section_labels = [
                        ("thesis", "Investment Thesis / IC Summary"),
                        ("zoning", "Zoning & Parcel Summary"),
                        ("ownership", "Ownership"),
                        ("business_plan", "Acquisition & Business Plan"),
                        ("underwriting", "Underwriting Pro Forma"),
                        ("distress", "Distress Signals"),
                        ("tax_abatement_rent_stab", "Tax Abatement & Rent Stabilization"),
                        ("market_comps", "Market Comps"),
                    ]
                    for _sec_i, (_sec_key, _sec_label) in enumerate(_section_labels):
                        with _sec_cols[_sec_i % 4]:
                            _included_sections[_sec_key] = st.checkbox(
                                _sec_label, value=True, key=f"_exp_sec_{_sec_key}_{_exp_bbl}",
                            )

                    if not _exp_score and not _exp_abate:
                        st.caption(
                            "Tip: Deal Score / Tax Abatement / Rent Stabilization sections above haven't "
                            "run yet for this property — scroll up to compute them before exporting for a "
                            "richer report."
                        )
                    if not _exp_uw:
                        st.caption(
                            "Tip: run the Underwriting Pro Forma — Deep Dive section above (under a massing "
                            "scenario) to include IRR/equity-multiple detail in the exported report."
                        )

                    _exp1, _exp2, _exp3 = st.columns(3)
                    with _exp1:
                        if st.button("📄 Build PDF report", key="pa_pdf_btn", use_container_width=True):
                            try:
                                st.session_state["_pa_pdf_bytes"] = build_pdf_report(
                                    _exp_prop, _exp_ic_summary, included_sections=_included_sections,
                                )
                            except ImportError as exc:
                                st.error(str(exc))
                        if st.session_state.get("_pa_pdf_bytes"):
                            st.download_button(
                                "Download PDF", data=st.session_state["_pa_pdf_bytes"],
                                file_name=f"{_exp_bbl}_report.pdf", mime="application/pdf",
                                use_container_width=True,
                            )
                    with _exp2:
                        if st.button("📽️ Build PowerPoint pitch", key="pa_pptx_btn", use_container_width=True):
                            try:
                                st.session_state["_pa_pptx_bytes"] = build_pptx_report(
                                    _exp_prop, _exp_ic_summary, included_sections=_included_sections,
                                )
                            except ImportError as exc:
                                st.error(str(exc))
                        if st.session_state.get("_pa_pptx_bytes"):
                            st.download_button(
                                "Download PowerPoint", data=st.session_state["_pa_pptx_bytes"],
                                file_name=f"{_exp_bbl}_pitch.pptx",
                                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                                use_container_width=True,
                            )
                    with _exp3:
                        if st.button("📊 Build Excel workbook", key="pa_xlsx_btn", use_container_width=True):
                            try:
                                st.session_state["_pa_xlsx_bytes"] = build_excel_workbook(
                                    [_exp_prop], included_sections=_included_sections,
                                )
                            except ImportError as exc:
                                st.error(str(exc))
                        if st.session_state.get("_pa_xlsx_bytes"):
                            st.download_button(
                                "Download Excel workbook", data=st.session_state["_pa_xlsx_bytes"],
                                file_name=f"{_exp_bbl}_report.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                use_container_width=True,
                            )

            # ── Combined Site Map (subject + comps + permits + assemblage) ──────
            # No single map anywhere else in the app combines all four layers —
            # each exists separately (subject-only map, assemblage-only map,
            # comps-only map). Reuses the already-fetched data from the
            # sections above (comps, nearby-developments pipeline, adjacent
            # lots) via the same session_state-lookup pattern the Investment
            # Risk Analysis section below already uses, since those sections
            # may not have run for this exact BBL yet if the user hasn't
            # scrolled through them. pydeck (st.pydeck_chart), matching the
            # Site Finder map's proven native-element approach — not folium.
            _section_header("🗺️", "Combined Site Map")
            try:
                import pydeck as _cm_pdk
                from pydeck.data_utils import compute_view as _cm_compute_view

                _cm_comps = st.session_state.get(_sales_key, {}).get("listings", [])
                _cm_permits = st.session_state.get(_nd_key, ([], {}))[0]
                _cm_assemblage = [
                    l for l in st.session_state.get(f"_assem_{_ds_bbl}", [])
                    if l.get("bbl") and str(l.get("bbl", "")).replace(" ", "") != str(_ds_bbl)
                ]

                _cm_layers = []
                _cm_fit_points = [[lon, lat]]
                _cm_layers.append(_cm_pdk.Layer(
                    "ScatterplotLayer",
                    data=[{"lon": lon, "lat": lat, "label": "Subject Property"}],
                    get_position="[lon, lat]", get_fill_color=[26, 58, 107], get_radius=14,
                    pickable=True, radius_min_pixels=8,
                ))
                _cm_comp_rows = [
                    {"lon": c["lon"], "lat": c["lat"], "label": f"{c.get('address','—')} · ${c.get('price',0):,.0f}"}
                    for c in _cm_comps if c.get("lat") and c.get("lon")
                ]
                if _cm_comp_rows:
                    _cm_layers.append(_cm_pdk.Layer(
                        "ScatterplotLayer", data=_cm_comp_rows,
                        get_position="[lon, lat]", get_fill_color=[31, 107, 58], get_radius=9,
                        pickable=True, radius_min_pixels=5,
                    ))
                    _cm_fit_points += [[r["lon"], r["lat"]] for r in _cm_comp_rows]
                _cm_permit_rows = [
                    {"lon": p["lon"], "lat": p["lat"], "label": f"{p.get('address','—')} · {p.get('status','—')}"}
                    for p in _cm_permits if p.get("lat") and p.get("lon")
                ]
                if _cm_permit_rows:
                    _cm_layers.append(_cm_pdk.Layer(
                        "ScatterplotLayer", data=_cm_permit_rows,
                        get_position="[lon, lat]", get_fill_color=[139, 105, 20], get_radius=9,
                        pickable=True, radius_min_pixels=5,
                    ))
                    _cm_fit_points += [[r["lon"], r["lat"]] for r in _cm_permit_rows]
                _cm_asm_rows = [
                    {"lon": float(l["longitude"]), "lat": float(l["latitude"]), "label": l.get("address", "—")}
                    for l in _cm_assemblage if l.get("latitude") and l.get("longitude")
                ]
                if _cm_asm_rows:
                    _cm_layers.append(_cm_pdk.Layer(
                        "ScatterplotLayer", data=_cm_asm_rows,
                        get_position="[lon, lat]", get_fill_color=[122, 46, 46], get_radius=9,
                        pickable=True, radius_min_pixels=5,
                    ))
                    _cm_fit_points += [[r["lon"], r["lat"]] for r in _cm_asm_rows]

                st.pydeck_chart(
                    _cm_pdk.Deck(
                        layers=_cm_layers, initial_view_state=_cm_compute_view(_cm_fit_points),
                        map_style="light", tooltip={"html": "<b>{label}</b>"},
                    ),
                    width="stretch", height=420,
                )
                st.caption(
                    "🔵 Subject · 🟢 Comps "
                    f"({len(_cm_comp_rows)}) · 🟤 Nearby Permits/Pipeline ({len(_cm_permit_rows)}) · "
                    f"🔴 Assemblage Candidates ({len(_cm_asm_rows)})"
                )
                if not (_cm_comp_rows or _cm_permit_rows or _cm_asm_rows):
                    st.caption("ℹ️ Scroll through the Property Sales, Nearby Developments, and Assemblage "
                               "sections above to populate this map with their data.")
            except Exception as _cm_exc:
                st.caption(f"⚠️ Combined site map unavailable: {_cm_exc}")

            # ── Macro + Micro Risk Matrix ──────────────────────────────────────
            _section_header("⚠️", "Investment Risk Analysis")

            # ── Property-Specific Risk Signals (dynamic — from live data ────
            # already fetched earlier in this same render, not the static
            # macro/micro tables below) ──────────────────────────────────────
            _rk_bbl = (_zinfo or {}).get("bbl", "—")
            _rk_score_result = st.session_state.get("_ds_last_score_result")
            _rk_acris = st.session_state.get(f"_acris_{_rk_bbl}", {}) or {}
            _rk_acris_sum = _rk_acris.get("summary", {}) or {}
            _rk_pip = st.session_state.get(f"_pip_{_rk_bbl}", {}) or {}
            _rk_pip_sum = _rk_pip.get("summary", {}) or {}
            _rk_abate = st.session_state.get(f"_abate_{_rk_bbl}", {}) or {}
            _rk_rentstab = st.session_state.get(f"_rentstab_{_rk_bbl}", {}) or {}
            _rk_flood = st.session_state.get(f"_flood_{lat:.5f}_{lon:.5f}", {}) or {}

            _rk_flags: list[dict] = []
            if _rk_flood.get("in_special_flood_hazard_area"):
                _rk_flags.append({
                    "level": "high",
                    "text": f"FEMA Special Flood Hazard Area (Zone {_rk_flood.get('flood_zone','—')}) "
                            "— flood insurance likely required; factor into construction/insurance costs",
                })
            elif _rk_flood.get("flood_zone") == "X500":
                _rk_flags.append({"level": "med", "text": "500-year floodplain (FEMA Zone X500, 0.2% annual chance)"})
            _rk_liens = _rk_acris_sum.get("open_liens", 0) or 0
            _rk_forecl = _rk_acris_sum.get("foreclosure_count", 0) or 0
            if _rk_forecl > 0:
                _rk_flags.append({"level": "high", "text": f"{_rk_forecl} foreclosure/lis pendens filing(s) on ACRIS"})
            if _rk_liens >= 2:
                _rk_flags.append({"level": "high", "text": f"{_rk_liens} open liens/UCC filings"})
            elif _rk_liens == 1:
                _rk_flags.append({"level": "med", "text": "1 open lien/UCC filing"})

            _rk_open_dob = _rk_pip_sum.get("open_dob_viol", 0) or 0
            _rk_open_cx = _rk_pip_sum.get("open_complaints", 0) or 0
            if _rk_open_dob > 15:
                _rk_flags.append({"level": "high", "text": f"{_rk_open_dob} open DOB violations"})
            elif _rk_open_dob > 5:
                _rk_flags.append({"level": "med", "text": f"{_rk_open_dob} open DOB violations"})
            if _rk_open_cx > 10:
                _rk_flags.append({"level": "med", "text": f"{_rk_open_cx} open DOB complaints"})

            if _rk_rentstab.get("likely_stabilized"):
                _rk_flags.append({
                    "level": "med",
                    "text": f"Likely rent-stabilized ({_rk_rentstab.get('confidence', 0):.0%} conf., estimated) "
                            "— limits rent upside and may constrain conversion/demolition strategies",
                })
            if _rk_abate.get("currently_exempt"):
                _rk_flags.append({
                    "level": "low",
                    "text": f"Currently tax-exempt (${_rk_abate.get('exempt_value', 0):,.0f}) "
                            "— confirm exemption's expiration/phase-out schedule before underwriting stabilized taxes",
                })

            # ── Composite Risk Scorecard (Physical/Financial/Regulatory) ────────
            # Buckets the same live signals above (plus structural-vintage risk
            # and the composite distress score, when already fetched earlier in
            # this render) into 3 explicit 0-100 categories with a "needs
            # manual review" flag — complements, does not replace, the raw
            # signal flags below or the static macro/micro tables further down.
            _rk_oath = st.session_state.get(f"_oath_{_rk_bbl}", {}) or {}
            _rk_taxlien = st.session_state.get(f"_taxlien_{_rk_bbl}", {}) or {}
            _rk_lpc = st.session_state.get(f"_lpc_{_rk_bbl}", {}) or {}
            _rk_struct = compute_structural_vintage_risk(
                (_zinfo or {}).get("year_built"), num_floors=(_zinfo or {}).get("num_floors", 0),
                bldg_class=(_zinfo or {}).get("bldg_class", ""),
            )
            _rk_distress = compute_composite_distress_score(
                acris_summary=_rk_acris_sum,
                dob_open_violations=_rk_open_dob, dob_open_complaints=_rk_open_cx,
                hpd_open_violations=st.session_state.get(f"_ecb_{_rk_bbl}", {}).get("open_count", 0),
                oath_data=_rk_oath, tax_lien_data=_rk_taxlien,
            )
            _rk_data_gaps = []
            if _rk_acris.get("error"):
                _rk_data_gaps.append(f"ACRIS: {_rk_acris['error']}")
            if _rk_pip.get("error"):
                _rk_data_gaps.append(f"DOB/HPD: {_rk_pip['error']}")
            _rk_scorecard = compute_composite_risk_scorecard(
                dob_open_violations=_rk_open_dob, dob_open_complaints=_rk_open_cx,
                flood_data=_rk_flood, structural_risk_result=_rk_struct,
                acris_summary=_rk_acris_sum, distress_score_result=_rk_distress,
                tax_exempt=bool(_rk_abate.get("currently_exempt")),
                rent_stab_likely=bool(_rk_rentstab.get("likely_stabilized")),
                is_landmark=bool((_zinfo or {}).get("landmark")) or bool(_rk_lpc.get("is_individual_landmark")),
                is_historic_district=bool((_zinfo or {}).get("historic_dist")),
                data_gaps=_rk_data_gaps,
            )
            st.markdown("**Composite Risk Scorecard**")
            _rksc1, _rksc2, _rksc3, _rksc4 = st.columns(4)
            _rksc1.metric("Physical",   f"{_rk_scorecard['physical']['score']}/100",   _rk_scorecard['physical']['tier'])
            _rksc2.metric("Financial",  f"{_rk_scorecard['financial']['score']}/100",  _rk_scorecard['financial']['tier'])
            _rksc3.metric("Regulatory", f"{_rk_scorecard['regulatory']['score']}/100", _rk_scorecard['regulatory']['tier'])
            _rksc4.metric("Overall",    f"{_rk_scorecard['overall_score']}/100",       _rk_scorecard['overall_tier'])
            if _rk_scorecard["needs_manual_review"]:
                st.warning("⚠️ **Needs manual review:** " + " · ".join(_rk_scorecard["needs_manual_review_reasons"]))
            with st.expander("Scorecard factor detail", expanded=False):
                for _rksc_bucket in ("physical", "financial", "regulatory"):
                    _rksc_data = _rk_scorecard[_rksc_bucket]
                    st.markdown(f"**{_rksc_bucket.title()}** — {_rksc_data['score']}/100 ({_rksc_data['tier']})")
                    for _rksc_f in _rksc_data["factors"]:
                        st.caption(f"• {_rksc_f}")
                    if not _rksc_data["factors"]:
                        st.caption("• No elevated factors found.")
            st.markdown("---")

            if _rk_flags:
                st.markdown("**Property-Specific Risk Signals** *(from live data already fetched above — ACRIS, DOB/HPD, tax/rent-stab estimates)*")
                _rk_color = {"high": "#7A2E2E", "med": "#8B6914", "low": "#2A3E63"}
                _rk_bg    = {"high": "#F3E1DE", "med": "#F5EBD3", "low": "#E4E8F1"}
                _rk_cols = st.columns(min(3, len(_rk_flags)))
                for _rk_i, _rk_f in enumerate(_rk_flags):
                    with _rk_cols[_rk_i % len(_rk_cols)]:
                        st.markdown(
                            f"<div style='background:{_rk_bg[_rk_f['level']]};color:{_rk_color[_rk_f['level']]};"
                            f"padding:8px 12px;border-radius:8px;font-size:0.8rem;margin-bottom:8px'>"
                            f"{_rk_f['text']}</div>",
                            unsafe_allow_html=True,
                        )
                if _rk_score_result:
                    st.caption(
                        f"Deal Score already reflects these signals in its Distress component: "
                        f"{_rk_score_result['score']}/100 ({_rk_score_result['tier']})."
                    )
            elif _rk_bbl != "—" and (_rk_acris or _rk_pip):
                st.markdown("**Property-Specific Risk Signals**")
                st.success("✅ No elevated liens, foreclosures, DOB violations, or complaints found in the data already checked above.")
            st.markdown("---")

            _risk_c1, _risk_c2 = st.columns([3, 2])

            with _risk_c1:
                st.markdown("**Macro Risks — NYC Market**")

                def _prob_class(p: str) -> str:
                    pl = p.lower()
                    if "high" in pl: return "prob-high"
                    if "med"  in pl: return "prob-med"
                    return "prob-low"

                _macro_rows = "".join(
                    f"<tr>"
                    f"<td><b>{r['category']}</b></td>"
                    f"<td class='{_prob_class(r['probability'])}'>{r['probability']}</td>"
                    f"<td class='{_prob_class(r['impact'])}'>{r['impact']}</td>"
                    f"<td style='color:#3D4152;word-wrap:break-word'>{r['description']}</td>"
                    f"<td style='color:#6B7280;font-size:0.75rem;word-wrap:break-word'>{r['mitigation']}</td>"
                    f"</tr>"
                    for r in MACRO_RISKS
                )
                st.markdown(
                    f"<table class='risk-table'>"
                    f"<thead><tr><th>Risk Factor</th><th>Prob.</th><th>Impact</th>"
                    f"<th>Description</th><th>Mitigation</th></tr></thead>"
                    f"<tbody>{_macro_rows}</tbody></table>",
                    unsafe_allow_html=True,
                )

            with _risk_c2:
                st.markdown(f"**Micro Risks — {neighborhood}**")
                _micro_risks = get_micro_risks(neighborhood, borough)
                for _mr in _micro_risks:
                    _pc = _prob_class(_mr.get("probability", ""))
                    _ic = _prob_class(_mr.get("impact", ""))
                    st.markdown(
                        f"<div style='padding:10px;border:1px solid #DCD5C2;border-radius:8px;margin-bottom:8px;background:#FFFFFF'>"
                        f"<div style='display:flex;gap:8px;align-items:center;margin-bottom:4px'>"
                        f"<b style='font-size:0.83rem'>{_mr['category']}</b>"
                        f"&nbsp;<span class='{_pc}' style='padding:1px 7px;border-radius:10px;font-size:0.68rem;font-weight:700'>"
                        f"Prob: {_mr.get('probability','—')}</span>"
                        f"&nbsp;<span class='{_ic}' style='padding:1px 7px;border-radius:10px;font-size:0.68rem;font-weight:700'>"
                        f"Impact: {_mr.get('impact','—')}</span></div>"
                        f"<div style='font-size:0.78rem;color:#3D4152;margin-bottom:4px'>{_mr['description']}</div>"
                        f"<div style='font-size:0.74rem;color:#6B7280'><i>Mitigation:</i> {_mr['mitigation']}</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

            # ── Property Condition Assessment ──────────────────────────────────
            if _zinfo and "error" not in _zinfo:
                _section_header("🔧", "Property Condition Assessment")
                _yr_built   = _zinfo.get("year_built", "—")
                _yr_mod     = _zinfo.get("year_last_mod", "—")
                _bldg_cls   = _zinfo.get("bldg_class", "—")
                _floors_v   = _zinfo.get("num_floors", "—")
                _units_res_v= _zinfo.get("units_res", "—")
                _land_use_v = _zinfo.get("land_use", "—")

                # Derive condition estimate from year built
                _cond_bullets = []
                try:
                    _yb = int(str(_yr_built).replace(",",""))
                    if _yb < 1930:
                        _era = "Pre-War (pre-1930)"
                        _cond_bullets.append(f"**Era:** {_era} — likely masonry load-bearing construction; inspect for facade, plumbing, and wiring condition")
                    elif _yb < 1960:
                        _era = "Post-War (1930–1960)"
                        _cond_bullets.append(f"**Era:** {_era} — mixed concrete/steel frame; may require elevator, HVAC, and electrical upgrades")
                    elif _yb < 1990:
                        _era = "Modern (1960–1990)"
                        _cond_bullets.append(f"**Era:** {_era} — reinforced concrete or steel frame; likely mid-life condition if not recently renovated")
                    else:
                        _era = f"Contemporary (built {_yb})"
                        _cond_bullets.append(f"**Era:** {_era} — modern construction standards; lower deferred maintenance expected")
                except (ValueError, TypeError):
                    _cond_bullets.append("**Year Built:** Not available — verify via DOB BIS")

                _cond_bullets.append(f"**Building Class:** {_bldg_cls} · **Floors:** {_floors_v} · **Res. Units:** {_units_res_v}")
                _cond_bullets.append(f"**Land Use:** {_land_use_v}")

                try:
                    _ym = int(str(_yr_mod).replace(",",""))
                    _yr_built_int = int(str(_yr_built).replace(",","")) if _yr_built != "—" else 0
                    if _ym > _yr_built_int + 5:
                        _cond_bullets.append(f"**Last Modified:** {_ym} — suggests renovation or addition; review DOB permits for scope")
                    else:
                        _cond_bullets.append(f"**Last Modified:** {_ym} — no significant modification on record; full physical inspection recommended")
                except (ValueError, TypeError):
                    pass

                _cond_bullets.append("**Recommended:** Commission Phase I ESA, structural inspection, and DOB violation search before closing")

                _pc1, _pc2 = st.columns([3, 2])
                with _pc1:
                    st.markdown("**Condition Summary**")
                    for _cb in _cond_bullets:
                        st.markdown(f"- {_cb}")

                with _pc2:
                    st.markdown("**External Resources**")
                    # Google Street View
                    _gsv_url = f"https://www.google.com/maps?q={lat},{lon}&layer=c&cbll={lat},{lon}"
                    st.markdown(f"- [🗺️ Google Street View]({_gsv_url})")
                    # DOB BIS
                    _boro_code  = _zinfo.get("borough_code", "1")
                    _pluto_addr = _zinfo.get("address_pluto", "")
                    _bis_url = (
                        f"https://a810-bisweb.nyc.gov/bisweb/PropertyProfileOverviewServlet"
                        f"?selfborough={_boro_code}&requestid=0"
                    )
                    st.markdown(f"- [🏛️ NYC DOB BIS — Building Info]({_bis_url})")
                    # DOB NOW
                    st.markdown("- [⚠️ DOB NOW — Violations & Complaints](https://dobonline.nyc.gov/)")
                    # ACRIS
                    _acris_link = st.session_state.get("_acris_data_url", "")
                    if _acris_link:
                        st.markdown(f"- [📄 ACRIS — Document History]({_acris_link})")
                    st.caption(
                        "Data from PLUTO (NYC Open Data), DOB BIS, Google Maps. "
                        "Assessment is indicative only — verify via full physical inspection."
                    )

        # ── All Applicable Zoning Districts ───────────────────────────────────
        if "_zinfo" in dir() and _zinfo:
            _dist_entries = []
            for _dk in ["zoning_dist", "zoning_dist2", "zoning_dist3"]:
                _dv = _zinfo.get(_dk)
                if _dv and _dv != "—":
                    _dr = get_zoning_rules(_dv)
                    _dist_entries.append(("zone", _dv, _dr))
            for _ok in ["overlay", "overlay2"]:
                _ov = _zinfo.get(_ok)
                if _ov and _ov != "—":
                    _ov_info = COMMERCIAL_OVERLAYS.get(_ov)
                    _dist_entries.append(("overlay", _ov, _ov_info))
            for _sk in ["special_dist", "special_dist2", "special_dist3"]:
                _sv = _zinfo.get(_sk)
                if _sv and _sv != "—":
                    _sp_info = get_special_district_info(_sv)
                    _dist_entries.append(("special", _sv, _sp_info))
            _lh = _zinfo.get("ltd_height")
            if _lh and _lh != "—":
                _dist_entries.append(("limited_height", _lh, None))
            _hd = _zinfo.get("historic_dist")
            if _hd and _hd != "—":
                _dist_entries.append(("historic", _hd, None))

            if _dist_entries:
                st.markdown("---")
                st.markdown(
                    "<div style='font-size:0.72rem;font-weight:700;letter-spacing:0.08em;"
                    "text-transform:uppercase;color:#6B7280;margin-bottom:8px'>"
                    "🗂️ All Applicable Zoning Designations</div>",
                    unsafe_allow_html=True,
                )
                for _dtype, _dcode, _ddata in _dist_entries:
                    if _dtype == "zone" and _ddata:
                        with st.expander(f"📐 {_dcode} — {_ddata.get('description', '')[:60]}", expanded=False):
                            _zc1, _zc2 = st.columns(2)
                            with _zc1:
                                st.markdown(f"**Base FAR:** {_ddata.get('base_far')} · **Max FAR:** {_ddata.get('max_far')}")
                                st.markdown(f"**Res. FAR:** {_ddata.get('res_far')} · **Comm. FAR:** {_ddata.get('comm_far', 0)}")
                                st.markdown(f"**Base Height:** {_ddata.get('base_height_ft', 0)} ft · **Max Height:** {_ddata.get('max_height_ft', 0) or 'SEP'} ft")
                            with _zc2:
                                st.markdown(f"**Front Yard:** {_ddata.get('front_yard_ft', 0)} ft · **Rear Yard:** {_ddata.get('rear_yard_ft', 0)} ft · **Side Yard:** {_ddata.get('side_yard_ft', 0)} ft")
                                st.markdown(f"**Max Lot Coverage:** {_ddata.get('lot_coverage_pct', 0) or '—'}%")
                                st.markdown(f"**Contextual:** {'Yes' if _ddata.get('contextual') else 'No'} · **Sky Exp. Plane:** {'Yes' if _ddata.get('sky_exp_plane') else 'No'}")
                            _dcite = get_zoning_citations(_dcode)
                            st.markdown(
                                f"[NYC Zoning Text →]({_dcite.get('article_url','https://zoningresolution.planning.nyc.gov')}) · "
                                f"[View on ZOLA →]({_dcite.get('zola_url','https://zola.planning.nyc.gov')})"
                            )
                    elif _dtype == "overlay" and _ddata:
                        with st.expander(f"🏪 Commercial Overlay {_dcode}", expanded=False):
                            st.markdown(f"**Permitted Uses:** {_ddata.get('uses', 'local retail and service')}")
                            st.markdown(f"**Commercial FAR:** {_ddata.get('comm_far', '—')}")
                            _ocite = get_zoning_citations(_dcode)
                            st.markdown(f"[NYC Commercial Overlay Guide →]({_ocite.get('article_url','https://zoningresolution.planning.nyc.gov')})")
                    elif _dtype == "special" and _ddata:
                        with st.expander(f"⭐ Special District {_dcode} — {_ddata.get('name', '')}", expanded=False):
                            st.markdown(_ddata.get("description", ""))
                            st.markdown(f"[NYC Planning Special District Text →]({_ddata.get('url', 'https://zoningresolution.planning.nyc.gov')})")
                    elif _dtype == "limited_height":
                        with st.expander(f"📏 Limited Height District {_dcode}", expanded=False):
                            st.markdown(f"Limited height districts restrict building heights below the otherwise applicable zoning limits. Verify maximum height with NYC Planning for district **{_dcode}**.")
                            st.markdown("[NYC Planning →](https://zoningresolution.planning.nyc.gov)")
                    elif _dtype == "historic":
                        with st.expander(f"🏛️ Historic District — {_dcode}", expanded=False):
                            st.markdown(f"**{_dcode}** is a designated NYC Landmark or Historic District under LPC jurisdiction. All exterior alterations, demolitions, and new construction require a Certificate of Appropriateness (CofA) from the Landmarks Preservation Commission.")
                            st.markdown("[LPC Website →](https://www.nyc.gov/site/lpc/index.page) · [LPC Search →](https://www.nyc.gov/site/lpc/designations/designation-reports.page)")

        # ── Source section ─────────────────────────────────────────────────────
        st.markdown("---")
        st.markdown(
            "<div style='font-size:0.72rem;font-weight:700;letter-spacing:0.08em;"
            "text-transform:uppercase;color:#6B7280;margin-bottom:12px'>📌 Data Sources</div>",
            unsafe_allow_html=True,
        )
        sources_config = [
            {
                "name": "StreetEasy",
                "desc": (
                    "NYC's dominant rental marketplace — highest listing density of any NYC platform. "
                    "Scraped directly: no API key required."
                ),
                "url": "https://streeteasy.com",
                "url_label": "streeteasy.com",
                "status": data_status.get("streeteasy", "pending"),
                "primary": True,
            },
            {
                "name": "Apartments.com",
                "desc": (
                    "National multifamily platform with strong NYC coverage across all boroughs. "
                    "Scraped directly: no API key required."
                ),
                "url": "https://apartments.com",
                "url_label": "apartments.com",
                "status": data_status.get("apartments", "pending"),
                "primary": True,
            },
            {
                "name": "Craigslist",
                "desc": (
                    "High-volume NYC listings including private landlords, FSBO, and no-fee rentals "
                    "rarely found on other platforms. Scraped directly: no API key required."
                ),
                "url": "https://newyork.craigslist.org/search/apa",
                "url_label": "newyork.craigslist.org",
                "status": data_status.get("craigslist", "pending"),
                "primary": True,
            },
            {
                "name": "Zumper",
                "desc": (
                    "Real-time rental marketplace with strong NYC coverage and instant-apply listings. "
                    "Scraped directly via JSON API: no API key required."
                ),
                "url": "https://www.zumper.com",
                "url_label": "zumper.com",
                "status": data_status.get("zumper", "pending"),
                "primary": True,
            },
            {
                "name": "RentHop",
                "desc": (
                    "NYC-focused marketplace with broker and no-fee listings across all five boroughs. "
                    "Scraped directly: no API key required."
                ),
                "url": "https://www.renthop.com",
                "url_label": "renthop.com",
                "status": data_status.get("renthop", "pending"),
                "primary": True,
            },
            {
                "name": "Rentcast  *(optional)*",
                "desc": (
                    "Authorized aggregator: syndicates from StreetEasy, MLS, landlord-direct, "
                    "and other NYC feeds. Most reliable fallback when scraping is blocked."
                ),
                "url": "https://rentcast.io",
                "url_label": "rentcast.io — free tier available",
                "status": data_status.get("rentcast", "no_key"),
                "primary": False,
            },
            {
                "name": "Zillow  *(optional)*",
                "desc": (
                    "National portal with deep NYC rental inventory and price history, "
                    "accessed via RapidAPI (zillow-com1)."
                ),
                "url": "https://rapidapi.com/apimaker/api/zillow-com1/",
                "url_label": "rapidapi.com / zillow-com1",
                "status": data_status.get("zillow", "no_key"),
                "primary": False,
            },
        ]
        src_cols = st.columns(2)
        for idx, src in enumerate(sources_config):
            s = src["status"]
            pill = (
                '<span class="pill-live">✅ Live</span>'         if s == "live"      else
                '<span class="pill-partial">⚠️ Partial</span>'   if s == "partial"   else
                '<span class="pill-error">🛡️ Blocked</span>'     if s == "blocked"   else
                '<span class="pill-partial">📭 No Results</span>' if s == "no_results" else
                '<span class="pill-cached">➖ Optional</span>'    if s == "no_key"    else
                '<span class="pill-partial">⏱️ Timeout</span>'   if s == "timeout"   else
                '<span class="pill-error">❌ Error</span>'
            )
            with src_cols[idx % 2]:
                st.markdown(f"""
                <div class="source-card">
                  <div style="display:flex;justify-content:space-between;align-items:center">
                    <span class="source-name">{src['name']}</span>
                    {pill}
                  </div>
                  <div class="source-desc">{src['desc']}</div>
                  <div class="source-link">
                    <a href="{src['url']}" target="_blank">🔗 {src['url_label']}</a>
                  </div>
                </div>
                """, unsafe_allow_html=True)

        st.markdown(
            "<div style='font-size:0.70rem;color:#9CA3AF;margin-top:4px'>"
            "All listings are deduplicated across sources and IQR-filtered to remove outliers. "
            "Data is for informational purposes only — not a substitute for professional market analysis."
            "</div>",
            unsafe_allow_html=True,
        )

        # (Scraping always runs — no API key required for core data collection.
        #  Rentcast / Zillow keys in the sidebar add supplemental listings.)

    # ── Idle state ────────────────────────────────────────────────────────────────
    else:
        st.markdown("""
        <div style="text-align:center;padding:56px 24px;color:#9CA3AF">
          <div style="font-size:3.5rem;margin-bottom:12px">🏙️</div>
          <h3 style="color:#3D4152;margin:0 0 8px">Enter a NYC address to begin</h3>
          <p style="margin:0;max-width:460px;margin-inline:auto;line-height:1.6">
            Type any NYC street address in the form above, choose a search radius,
            and optionally filter by unit type or rental tier — then click
            <strong>Geocode Address</strong>.
          </p>
        </div>
        """, unsafe_allow_html=True)

with tab_sitefinder:
    from modules.site_finder_ui import render_site_finder
    render_site_finder(anthropic_key=anthropic_key)

with tab_portfolio:
    from modules.portfolio_ui import render_portfolio
    render_portfolio()

# ── Footer ─────────────────────────────────────────────────────────────────────
st.markdown("""
<hr style="margin-top:48px;border-color:#DCD5C2"/>
<div style="text-align:center;color:#9CA3AF;font-size:0.75rem;padding:12px 0">
  Real Estate Development &amp; Investment Analytics · NYC Planning, PLUTO, ACRIS &amp; Market Data ·
  For internal real estate diligence use only · Not financial advice
</div>
""", unsafe_allow_html=True)

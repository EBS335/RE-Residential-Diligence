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

from modules.data_fetcher import fetch_all_listings
from modules.analyzer import compute_summary, compute_insights
from modules.visualizer import build_map, build_bar_chart, build_range_chart
from modules.zola_fetcher import fetch_zoning_info
from modules.zoning_rules import get_zoning_rules, SPECIAL_DISTRICTS, COMMERCIAL_OVERLAYS, get_special_district_info
from modules.massing_viz import build_massing_options, floor_plate_fig
from modules.comps_research import search_competing_devs, generate_pipeline_summary
from modules.neighborhood_fetcher import fetch_neighborhood_data
from modules.acris_fetcher import fetch_acris
from modules.articles_fetcher import fetch_nearby_articles
from modules.ecb_fetcher import fetch_ecb_violations
from modules.deal_scorer import compute_deal_score
from modules.unit_mix import (
    get_avg_sf, optimize_unit_mix, compute_revenue,
    avg_rents_from_listings, NEIGHBORHOOD_AVG_SF, net_rentable_sf,
)
from modules.risk_matrix import MACRO_RISKS, get_micro_risks

load_dotenv()


# ── Section header helper ─────────────────────────────────────────────────────

def _section_header(icon: str, title: str, subtitle: str = "") -> None:
    """Render a consistent section divider + labeled header."""
    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    st.markdown(
        f'<div class="section-title">{icon} {title}</div>'
        + (f'<div class="section-subtitle">{subtitle}</div>' if subtitle else ""),
        unsafe_allow_html=True,
    )


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
/* ── Global ── */
html, body, [data-testid="stAppViewContainer"] {
    background-color: #F5F6FA;
    font-family: 'Inter', sans-serif;
}

/* ── Header banner ── */
.app-header {
    background: linear-gradient(135deg, #0D1B2A 0%, #1B2A4A 55%, #1A3A6B 100%);
    border-radius: 14px;
    padding: 32px 36px 28px;
    margin-bottom: 28px;
    color: white;
}
.app-header h1 {
    margin: 0 0 6px;
    font-size: 1.9rem;
    font-weight: 800;
    letter-spacing: -0.5px;
}
.app-header p {
    margin: 0;
    font-size: 0.92rem;
    opacity: 0.72;
    max-width: 560px;
    line-height: 1.5;
}

/* ── Section headers ── */
.section-label {
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #6B7280;
    margin-bottom: 10px;
}

/* ── Info card (geocoding result) ── */
.geo-card {
    background: white;
    border-radius: 12px;
    border: 1px solid #E5E7EB;
    padding: 20px 24px;
    margin-top: 20px;
}
.geo-card-title {
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #6B7280;
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
    background: #F0F4FF;
    color: #1A3A6B;
    border-radius: 20px;
    padding: 6px 14px;
    font-size: 0.83rem;
    font-weight: 600;
}
.geo-chip-label {
    color: #6B7280;
    font-weight: 400;
    font-size: 0.78rem;
}
.geo-address {
    font-size: 1.05rem;
    font-weight: 700;
    color: #111827;
    margin-bottom: 12px;
}
.geo-coords {
    font-size: 0.78rem;
    color: #9CA3AF;
    font-family: monospace;
    margin-top: 10px;
}
.geo-source {
    font-size: 0.72rem;
    color: #9CA3AF;
    margin-top: 6px;
}

/* ── Status badges ── */
.badge-live    { background:#DCFCE7; color:#15803D; padding:3px 10px; border-radius:20px; font-size:0.75rem; font-weight:700; }
.badge-partial { background:#FEF9C3; color:#854D0E; padding:3px 10px; border-radius:20px; font-size:0.75rem; font-weight:700; }
.badge-error   { background:#FEE2E2; color:#991B1B; padding:3px 10px; border-radius:20px; font-size:0.75rem; font-weight:700; }

/* ── Filter tags ── */
.filter-summary {
    background: white;
    border: 1px solid #E5E7EB;
    border-radius: 10px;
    padding: 14px 18px;
    margin-top: 16px;
    font-size: 0.84rem;
    color: #374151;
    line-height: 1.7;
}
.filter-tag {
    display: inline-block;
    background: #EFF6FF;
    color: #1D4ED8;
    border-radius: 6px;
    padding: 1px 8px;
    font-size: 0.78rem;
    font-weight: 600;
    margin: 0 2px;
}

/* ── Sidebar tweaks ── */
[data-testid="stSidebar"] > div:first-child {
    background: #0D1B2A;
    padding-top: 24px;
}
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stMarkdown,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span {
    color: #D1D5DB !important;
}
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
    color: #F9FAFB !important;
}

/* ── Next-step callout ── */
.next-step {
    background: #FFFBEB;
    border: 1px solid #FDE68A;
    border-radius: 10px;
    padding: 14px 18px;
    margin-top: 20px;
    font-size: 0.84rem;
    color: #78350F;
}

/* ── Data freshness pill ── */
.pill-live    { background:#DCFCE7; color:#166534; padding:4px 12px; border-radius:20px;
                font-size:0.74rem; font-weight:700; display:inline-block; }
.pill-partial { background:#FEF3C7; color:#92400E; padding:4px 12px; border-radius:20px;
                font-size:0.74rem; font-weight:700; display:inline-block; }
.pill-cached  { background:#E0E7FF; color:#3730A3; padding:4px 12px; border-radius:20px;
                font-size:0.74rem; font-weight:700; display:inline-block; }
.pill-error   { background:#FEE2E2; color:#991B1B; padding:4px 12px; border-radius:20px;
                font-size:0.74rem; font-weight:700; display:inline-block; }

/* ── Photo gallery (legacy grid) ── */
.photo-card {
    background: white;
    border: 1px solid #E5E7EB;
    border-radius: 10px;
    overflow: hidden;
    margin-bottom: 12px;
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
    color: #374151;
    line-height: 1.35;
}
.photo-caption b { color: #111827; }

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
    scrollbar-color: #D1D5DB transparent;
}
.gallery-scroll-row::-webkit-scrollbar { height: 5px; }
.gallery-scroll-row::-webkit-scrollbar-track { background: transparent; }
.gallery-scroll-row::-webkit-scrollbar-thumb { background: #D1D5DB; border-radius: 4px; }
.gallery-card {
    flex: 0 0 190px;
    min-width: 190px;
    background: white;
    border: 1px solid #E5E7EB;
    border-radius: 10px;
    overflow: hidden;
    text-decoration: none;
    color: inherit;
    transition: box-shadow 0.15s, transform 0.15s;
    display: block;
}
.gallery-card:hover {
    box-shadow: 0 4px 16px rgba(0,0,0,0.10);
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
    color: #374151;
    line-height: 1.35;
}
.gallery-card .gc-caption b { color: #111827; font-size: 0.82rem; }
.gallery-card .gc-badge {
    display: inline-block;
    background: #EFF6FF;
    color: #1D4ED8;
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 0.68rem;
    font-weight: 700;
    margin-top: 4px;
}

/* ── Risk badges ── */
.risk-low  { background:#DCFCE7; color:#15803D; padding:2px 9px; border-radius:20px; font-size:0.72rem; font-weight:700; }
.risk-med  { background:#FEF9C3; color:#854D0E; padding:2px 9px; border-radius:20px; font-size:0.72rem; font-weight:700; }
.risk-high { background:#FEE2E2; color:#991B1B; padding:2px 9px; border-radius:20px; font-size:0.72rem; font-weight:700; }

/* ── Massing tile ── */
.massing-tile {
    background: white;
    border: 1px solid #E5E7EB;
    border-radius: 12px;
    padding: 12px;
    margin-bottom: 10px;
}

/* ── Risk matrix table ── */
.risk-table { width:100%; border-collapse:collapse; font-size:0.80rem; }
.risk-table th { background:#F9FAFB; color:#6B7280; font-weight:700; padding:8px 10px;
                 text-align:left; border-bottom:2px solid #E5E7EB; }
.risk-table td { padding:8px 10px; border-bottom:1px solid #F3F4F6; color:#111827; vertical-align:top; }
.risk-table tr:last-child td { border-bottom:none; }
.prob-low  { color:#15803D; font-weight:700; }
.prob-med  { color:#B45309; font-weight:700; }
.prob-high { color:#B91C1C; font-weight:700; }

/* ── Borough comparison table ── */
.bcomp-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.83rem;
}
.bcomp-table th {
    background: #F9FAFB;
    color: #6B7280;
    font-weight: 700;
    padding: 8px 12px;
    text-align: left;
    border-bottom: 1px solid #E5E7EB;
}
.bcomp-table td {
    padding: 8px 12px;
    border-bottom: 1px solid #F3F4F6;
    color: #111827;
}
.bcomp-table tr:last-child td { border-bottom: none; }
.bcomp-above { color: #DC2626; font-weight: 700; }
.bcomp-below { color: #16A34A; font-weight: 700; }
.bcomp-at    { color: #6B7280; font-weight: 600; }

/* ── Source card ── */
.source-card {
    background: white;
    border: 1px solid #E5E7EB;
    border-radius: 10px;
    padding: 16px 20px;
    margin-bottom: 10px;
}
.source-name { font-weight: 700; color: #111827; font-size: 0.9rem; }
.source-desc { color: #6B7280; font-size: 0.80rem; margin-top: 3px; line-height: 1.4; }
.source-link { font-size: 0.78rem; margin-top: 5px; }
.source-link a { color: #1A3A6B; font-weight: 600; text-decoration: none; }

/* ── Neighborhood context banner ── */
.hood-banner {
    background: linear-gradient(90deg, #EFF6FF 0%, #F0FDF4 100%);
    border: 1px solid #BFDBFE;
    border-radius: 10px;
    padding: 14px 18px;
    margin-bottom: 16px;
    display: flex;
    gap: 20px;
    flex-wrap: wrap;
    align-items: center;
}
.hood-stat { text-align: center; min-width: 80px; }
.hood-stat-val { font-size: 1.1rem; font-weight: 800; color: #1A3A6B; }
.hood-stat-lbl { font-size: 0.70rem; color: #6B7280; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; }
/* ── Scraping status panel ────────────────────────────────────────────── */
.scrape-status-panel { background:white; border:1px solid #E5E7EB; border-radius:10px;
    padding:14px 18px; margin-top:10px; margin-bottom:6px; }
.scrape-status-panel table { width:100%; border-collapse:collapse; font-size:0.82rem; }
.scrape-status-panel th { background:#F9FAFB; color:#6B7280; font-weight:700;
    padding:6px 10px; text-align:left; border-bottom:1px solid #E5E7EB;
    font-size:0.74rem; text-transform:uppercase; letter-spacing:0.06em; }
.scrape-status-panel td { padding:6px 10px; border-bottom:1px solid #F3F4F6;
    color:#111827; vertical-align:middle; }
.scrape-status-panel tr:last-child td { border-bottom:none; }
.scrape-count-badge { background:#F3F4F6; color:#374151; border-radius:12px;
    padding:2px 9px; font-size:0.77rem; font-weight:700; font-family:monospace; }

/* ── Section dividers ── */
.section-divider {
    border: none;
    border-top: 2px solid #E5E7EB;
    margin: 32px 0 24px;
}
.section-title {
    font-size: 1.15rem;
    font-weight: 800;
    color: #111827;
    letter-spacing: -0.3px;
    margin-bottom: 4px;
}
.section-subtitle {
    font-size: 0.86rem;
    color: #6B7280;
    margin-bottom: 18px;
}

/* ── Deal score gauge ── */
.deal-score-num {
    font-size: 3.2rem;
    font-weight: 900;
    line-height: 1;
    margin-bottom: 4px;
}
.deal-tier-badge {
    display: inline-block;
    border-radius: 20px;
    padding: 4px 16px;
    font-size: 0.85rem;
    font-weight: 700;
    margin-bottom: 12px;
}
.distress-low    { background:#DCFCE7; color:#15803D; border-radius:20px; padding:3px 12px; font-size:0.82rem; font-weight:700; }
.distress-medium { background:#FEF9C3; color:#854D0E; border-radius:20px; padding:3px 12px; font-size:0.82rem; font-weight:700; }
.distress-high   { background:#FEE2E2; color:#991B1B; border-radius:20px; padding:3px 12px; font-size:0.82rem; font-weight:700; }
.opportunity-flag {
    background: #DCFCE7;
    border: 1px solid #86EFAC;
    border-radius: 10px;
    padding: 12px 16px;
    color: #15803D;
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
    "2 blocks  (~0.10 mi)":   0.10,
    "3 blocks  (~0.15 mi)":   0.15,
    "5 blocks  (~0.25 mi)":   0.25,
    "10 blocks (~0.50 mi)":   0.50,
    "15 blocks (~0.75 mi)":   0.75,
    "20 blocks (~1.00 mi)":   1.00,
    "25 blocks (~1.25 mi)":   1.25,
    "30 blocks (~1.50 mi)":   1.50,
    "35 blocks (~1.75 mi)":   1.75,
    "40 blocks (~2.00 mi)":   2.00,
    "45 blocks (~2.25 mi)":   2.25,
    "50 blocks (~2.50 mi)":   2.50,
    "55 blocks (~2.75 mi)":   2.75,
    "60 blocks (~3.00 mi)":   3.00,
    "65 blocks (~3.25 mi)":   3.25,
    "70 blocks (~3.50 mi)":   3.50,
    "75 blocks (~3.75 mi)":   3.75,
    "80 blocks (~4.00 mi)":   4.00,
    "85 blocks (~4.25 mi)":   4.25,
    "90 blocks (~4.50 mi)":   4.50,
    "95 blocks (~4.75 mi)":   4.75,
    "100 blocks (~5.00 mi)":  5.00,
    "Custom…":                None,
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
    folium.LayerControl(position="topright", collapsed=True).add_to(m)

    # ── Search radius ring ────────────────────────────────────────────────────
    folium.Circle(
        location=[lat, lon],
        radius=radius_miles * 1609.34,   # miles → metres
        color="#1A3A6B",
        weight=2,
        dash_array="6 4",
        fill=True,
        fill_color="#1A3A6B",
        fill_opacity=0.06,
        tooltip=f"Search radius: {radius_miles:.2f} mi",
    ).add_to(m)

    # Solid inner dot to mark the exact centre
    folium.CircleMarker(
        location=[lat, lon],
        radius=5,
        color="#1A3A6B",
        fill=True,
        fill_color="#1A3A6B",
        fill_opacity=0.9,
        weight=2,
    ).add_to(m)

    # ── Subject property pin ──────────────────────────────────────────────────
    hood_line = f"<br/><span style='color:#6B7280'>{neighborhood}</span>" if neighborhood and neighborhood != "—" else ""
    borough_line = f" · {borough}" if borough and borough != "—" else ""

    popup_html = f"""
    <div style="font-family:sans-serif;min-width:200px;padding:4px">
      <b style="font-size:1rem;color:#0D1B2A">📍 Subject Property</b>
      {hood_line}{borough_line}
      <hr style="margin:8px 0;border-color:#E5E7EB"/>
      <span style="font-size:0.82rem;color:#374151">{label}</span><br/>
      <span style="font-size:0.75rem;color:#9CA3AF;font-family:monospace">
        {lat:.6f}, {lon:.6f}
      </span><br/>
      <span style="font-size:0.75rem;color:#1A3A6B;font-weight:600">
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
    rentcast_key = st.text_input(
        "Rentcast API Key  *(optional)*",
        value=os.getenv("RENTCAST_API_KEY", ""),
        type="password",
        help="Supplements scraping with authorized API data. "
             "Free tier: 50 req/month at rentcast.io.",
    )
    rapidapi_key = st.text_input(
        "RapidAPI Key  *(optional)*",
        value=os.getenv("RAPIDAPI_KEY", ""),
        type="password",
        help="Adds Zillow listings via RapidAPI. "
             "Subscribe to 'Zillow Com1' at rapidapi.com.",
    )

    st.divider()
    st.markdown("### 📖 How to use")
    st.caption(
        "**No API keys needed** — the app scrapes 5 sources directly "
        "(StreetEasy, Apartments.com, Craigslist, Zumper, RentHop).\n\n"
        "Add a **ScrapingBee** key (free tier available) to route requests "
        "through residential proxies — this bypasses Cloudflare blocks that "
        "affect cloud-hosted apps.\n\n"
        "**Rentcast** / **RapidAPI** keys add supplemental API-sourced data."
    )
    st.divider()
    st.markdown("### 🔗 Get API keys")
    st.markdown(
        "- [ScrapingBee](https://scrapingbee.com) *(free tier — recommended)*\n"
        "- [Google Maps Platform](https://console.cloud.google.com) *(optional)*\n"
        "- [Rentcast.io](https://rentcast.io) *(optional)*\n"
        "- [RapidAPI](https://rapidapi.com) *(optional)*"
    )


# ═════════════════════════════════════════════════════════════════════════════
# HEADER
# ═════════════════════════════════════════════════════════════════════════════

st.markdown("""
<div class="app-header">
  <h1>🏗️ Real Estate Development &amp; Investment Analytics</h1>
  <p>
    Full-stack NYC development diligence — deal sourcing, rental comps, zoning &amp; ACRIS research,
    massing scenarios, risk analysis, and unit economics. Enter any NYC address to begin.
  </p>
</div>
""", unsafe_allow_html=True)


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
    )

    st.markdown("<br/>", unsafe_allow_html=True)

    col_radius, col_custom, col_spacer = st.columns([2, 1.2, 1.8])

    # ── Radius ───────────────────────────────────────────────────────────────
    with col_radius:
        st.markdown('<div class="section-label">📏 Search Radius</div>',
                    unsafe_allow_html=True)
        radius_choice = st.selectbox(
            label="radius",
            label_visibility="collapsed",
            options=list(RADIUS_OPTIONS.keys()),
            index=2,   # default: 5 blocks
        )

    with col_custom:
        st.markdown('<div class="section-label">Custom (miles)</div>',
                    unsafe_allow_html=True)
        custom_miles = st.number_input(
            label="custom_miles",
            label_visibility="collapsed",
            min_value=0.05,
            max_value=5.0,
            value=0.50,
            step=0.05,
            format="%.2f",
            disabled=(radius_choice != "Custom…"),
            help="Only active when 'Custom…' is selected above.",
        )

    # Resolve radius
    if radius_choice == "Custom…":
        radius_miles = custom_miles
    else:
        radius_miles = RADIUS_OPTIONS[radius_choice]

    st.markdown("<br/>", unsafe_allow_html=True)

    col_units, col_rental = st.columns(2)

    # ── Unit types ───────────────────────────────────────────────────────────
    with col_units:
        st.markdown('<div class="section-label">🏠 Unit Types  <span style="font-weight:400;text-transform:none;letter-spacing:0">(leave blank = all)</span></div>',
                    unsafe_allow_html=True)
        selected_units = st.multiselect(
            label="unit_types",
            label_visibility="collapsed",
            options=UNIT_TYPES,
            default=[],
            placeholder="All unit types",
            help="Filter comps by bedroom count. Leave empty to include all.",
        )

    # ── Rental type ──────────────────────────────────────────────────────────
    with col_rental:
        st.markdown('<div class="section-label">💎 Rental Type</div>',
                    unsafe_allow_html=True)
        rental_type = st.selectbox(
            label="rental_type",
            label_visibility="collapsed",
            options=RENTAL_TYPES,
            index=2,   # default: All
            help="Filter by market-rate vs luxury tier when data is available.",
        )

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
    st.session_state["unit_filter"]   = selected_units
    st.session_state["rental_type"]   = rental_type
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
    selected_units = st.session_state.get('unit_filter', [])
    rental_type   = st.session_state.get('rental_type', 'All (no filter)')

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
        demand_tag = ' &nbsp;<span style="background:#FEE2E2;color:#991B1B;border-radius:20px;padding:3px 10px;font-size:0.75rem;font-weight:700;">🔥 High-Demand</span>'
    transit_tag = ""
    if is_transit:
        transit_tag = ' &nbsp;<span style="background:#DBEAFE;color:#1D4ED8;border-radius:20px;padding:3px 10px;font-size:0.75rem;font-weight:700;">🚇 Transit Hub</span>'

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
    unit_display   = ", ".join(f'<span class="filter-tag">{u}</span>' for u in (selected_units or UNIT_TYPES))
    rental_display = f'<span class="filter-tag">{rental_type}</span>'
    radius_label   = radius_choice if radius_choice != "Custom…" else f"Custom {radius_miles:.2f} mi"

    st.markdown(f"""
    <div class="filter-summary">
      <b>Search confirmed.</b> The dashed ring on the map shows the exact area
      from which rental comps will be pulled.<br/>
      &nbsp;&nbsp;• <b>Radius:</b> {radius_miles:.2f} miles ({radius_label})<br/>
      &nbsp;&nbsp;• <b>Unit types:</b> {unit_display}<br/>
      &nbsp;&nbsp;• <b>Rental type:</b> {rental_display}
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
        {"".join(f'<span style="background:#DBEAFE;color:#1D4ED8;border-radius:20px;padding:4px 12px;font-size:0.74rem;font-weight:700">{f}</span>' for f in hood_flags)}
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Scraping always runs — API keys are optional supplements

    st.divider()

    # ── Fetch with loading indicator ──────────────────────────────────────────
    has_rentcast = bool(rentcast_key and rentcast_key.strip())
    has_rapidapi = bool(rapidapi_key and rapidapi_key.strip())
    has_proxy    = bool(scraping_key and scraping_key.strip())

    fetch_cache_key = (
        f"_listings_{lat:.5f}_{lon:.5f}_{radius_miles}_"
        f"{'_'.join(sorted(selected_units or []))}"
        f"_rc{int(has_rentcast)}_ra{int(has_rapidapi)}_pb{int(has_proxy)}"
    )
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
                rentcast_key=rentcast_key.strip() if has_rentcast else None,
                rapidapi_key=rapidapi_key.strip() if has_rapidapi else None,
                bed_filter=selected_units if selected_units else None,
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

    # ── Data status row ────────────────────────────────────────────────────────
    def _source_pill(source_name: str, status_val: str) -> str:
        if status_val == "live":
            return f'<span class="pill-live">✅ {source_name} · Live</span>'
        if status_val == "partial":
            return f'<span class="pill-partial">⚠️ {source_name} · Partial</span>'
        if status_val == "blocked":
            return f'<span class="pill-error">🛡️ {source_name} · Blocked</span>'
        if status_val == "no_results":
            return f'<span class="pill-partial">📭 {source_name} · No Results</span>'
        if status_val == "invalid_key":
            return f'<span class="pill-error">🔑 {source_name} · Invalid Key</span>'
        if status_val == "no_key":
            return f'<span class="pill-cached">➖ {source_name} · Optional</span>'
        if status_val == "timeout":
            return f'<span class="pill-partial">⏱️ {source_name} · Timeout</span>'
        if status_val in ("pending", "no_data"):
            return f'<span class="pill-error">⭕ {source_name} · No Data</span>'
        return f'<span class="pill-error">❌ {source_name} · Error</span>'

    freshness_cls = (
        "pill-live"    if data_freshness == "Live Data"    else
        "pill-partial" if data_freshness == "Partial Data" else
        "pill-cached"  if data_freshness == "Cached Data"  else
        "pill-error"
    )
    freshness_icon = (
        "🟢" if data_freshness == "Live Data" else
        "🟡" if data_freshness == "Partial Data" else
        "🔵" if data_freshness == "Cached Data" else "🔴"
    )

    pills_html = (
        f'<span class="{freshness_cls}">{freshness_icon} {data_freshness}</span> &nbsp; '
        + _source_pill("StreetEasy",    data_status.get("streeteasy", "pending"))
        + " &nbsp; "
        + _source_pill("Apartments.com", data_status.get("apartments", "pending"))
        + " &nbsp; "
        + _source_pill("Craigslist",    data_status.get("craigslist", "pending"))
        + " &nbsp; "
        + _source_pill("Zumper",        data_status.get("zumper", "pending"))
        + " &nbsp; "
        + _source_pill("RentHop",       data_status.get("renthop", "pending"))
        + " &nbsp; "
        + _source_pill("Rentcast", data_status.get("rentcast", "no_key"))
        + " &nbsp; "
        + _source_pill("Zillow", data_status.get("zillow", "no_key"))
    )
    st.markdown(pills_html, unsafe_allow_html=True)

    # ── Scraping status panel (source + status + raw counts) ───────────────
    _counts = data_status.get("_counts", {})
    _status_labels = {
        "live":        ("✅", "Live",        "pill-live"),
        "partial":     ("⚠️", "Partial",     "pill-partial"),
        "blocked":     ("🛡️", "Blocked",     "pill-error"),
        "no_results":  ("📭", "No Results",  "pill-partial"),
        "invalid_key": ("🔑", "Invalid Key", "pill-error"),
        "no_key":      ("➖", "Optional",    "pill-cached"),
        "timeout":     ("⏱️", "Timeout",     "pill-partial"),
        "pending":     ("⭕", "No Data",     "pill-error"),
        "no_data":     ("⭕", "No Data",     "pill-error"),
    }
    _sources_display = [
        ("StreetEasy",     "streeteasy"),
        ("Apartments.com", "apartments"),
        ("Craigslist",     "craigslist"),
        ("Zumper",         "zumper"),
        ("RentHop",        "renthop"),
        ("Rentcast",       "rentcast"),
        ("Zillow",         "zillow"),
    ]
    _status_rows = ""
    for _sname, _skey in _sources_display:
        _s = data_status.get(_skey, "pending")
        _icon, _label, _css = _status_labels.get(_s, ("❌", "Error", "pill-error"))
        _cnt = _counts.get(_skey, 0)
        _count_cell = (
            f'<span class="scrape-count-badge">{_cnt} found</span>'
            if _cnt > 0
            else '<span style="color:#9CA3AF;font-size:0.78rem">—</span>'
        )
        _opt = ' <span style="color:#9CA3AF;font-size:0.74rem">(optional)</span>' if _s == "no_key" else ""
        _status_rows += (
            f"<tr><td><b>{_sname}</b>{_opt}</td>"
            f'<td><span class="{_css}">{_icon} {_label}</span></td>'
            f"<td>{_count_cell}</td></tr>"
        )
    st.markdown(
        f"""<div class="scrape-status-panel">
          <div style="font-size:0.72rem;font-weight:700;letter-spacing:0.08em;
                      text-transform:uppercase;color:#6B7280;margin-bottom:10px">
            🔍 Live Scraping Status
          </div>
          <table><thead><tr>
            <th>Source</th><th>Status</th><th>Listings Found (pre-dedup)</th>
          </tr></thead><tbody>{_status_rows}</tbody></table>
        </div>""",
        unsafe_allow_html=True,
    )

    # ── No results / blocked state ─────────────────────────────────────────
    blocked_sources = [
        k for k in ("streeteasy", "apartments", "craigslist", "zumper", "renthop")
        if data_status.get(k) == "blocked"
    ]
    all_primary_blocked = len(blocked_sources) == 5

    if not listings:
        if all_primary_blocked:
            st.warning(
                "**All scraping sources were blocked** (bot/Cloudflare protection).\n\n"
                "To get live data add a **Rentcast** or **RapidAPI** key in the sidebar — "
                "those use authorized APIs that bypass bot detection. "
                "Rentcast has a free tier at rentcast.io."
            )
        elif blocked_sources:
            blocked_names = ", ".join(blocked_sources)
            st.warning(
                f"Some sources were blocked by bot protection ({blocked_names}). "
                "Try **expanding the radius** or add API keys in the sidebar for reliable data."
            )
        else:
            st.warning(
                "No rental listings found in this area.\n\n"
                "• Try **expanding the radius** (20–50 blocks captures more comps)\n"
                "• Check your internet connection\n"
                "• Add Rentcast / RapidAPI keys as backup sources"
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
        if _ds_zk not in st.session_state and _ds_addr:
            with st.spinner("Fetching parcel data from NYC Planning…"):
                st.session_state[_ds_zk] = fetch_zoning_info(_ds_addr, lat=lat, lon=lon)
        _ds_zi  = st.session_state.get(_ds_zk) or {}
        _ds_bbl = _ds_zi.get("bbl", "")

        # Pre-initialize shared variables used across tabs
        _ub_max_far      = 0.0
        _ub_lot_area     = 0.0
        _ub_unused_pct   = 0.0
        _ub_uplift_pct   = 0.0
        _ds_dist_level   = 0
        _nearby_listings = []

        def _sf(v, d: float = 0.0) -> float:
            """Safe float: handles None, '—', and comma-formatted strings like '5,000'."""
            try:
                return float(str(v or "").replace(",", "").strip())
            except (ValueError, TypeError):
                return d

        _ds_t1, _ds_t2, _ds_t3, _ds_t4, _ds_t5, _ds_t6 = st.tabs([
            "📋 Parcel Data",
            "📈 Underbuilt?",
            "🚨 Distress Signals",
            "🏷️ Listings",
            "🔗 Assemblage",
            "🏆 Deal Score",
        ])

        # ── Tab 1: Address + Parcel Auto-Enrichment ─────────────────────────
        with _ds_t1:
            if not _ds_zi or "error" in _ds_zi:
                st.info("Parcel data unavailable — zoning lookup may have failed.")
            else:
                _p_c1, _p_c2 = st.columns(2)
                with _p_c1:
                    st.markdown("**🏠 Parcel Identity**")
                    _p_left = [
                        ("Owner",       _ds_zi.get("owner", "—")),
                        ("Address",     _ds_zi.get("address_pluto", "—")),
                        ("Borough",     borough),
                        ("Zoning",      _ds_zi.get("zoning_dist", "—")),
                        ("Bldg Class",  _ds_zi.get("bldg_class", "—")),
                        ("Land Use",    _ds_zi.get("land_use", "—")),
                        ("Year Built",  _ds_zi.get("year_built", "—")),
                        ("Floors",      _ds_zi.get("num_floors", "—")),
                        ("Res Units",   _ds_zi.get("units_res", "—")),
                    ]
                    _p_html = "<table style='width:100%;font-size:0.83rem;border-collapse:collapse'>"
                    for _pk, _pv in _p_left:
                        _p_html += (
                            f"<tr><td style='color:#6B7280;padding:5px 10px 5px 0;white-space:nowrap'>{_pk}</td>"
                            f"<td style='font-weight:600;padding:5px 0;color:#111827'>{_pv}</td></tr>"
                        )
                    st.markdown(_p_html + "</table>", unsafe_allow_html=True)
                with _p_c2:
                    st.markdown("**📐 FAR & Financials**")
                    _la_v = int(_sf(_ds_zi.get("lot_area_sqft")))
                    _p_right = [
                        ("Lot Area",       f"{_la_v:,} SF" if _la_v else "—"),
                        ("Lot Frontage",   f"{_ds_zi.get('lot_frontage_ft', '—')} ft"),
                        ("Lot Depth",      f"{_ds_zi.get('lot_depth_ft', '—')} ft"),
                        ("FAR (Built)",    _ds_zi.get("far_built", "—")),
                        ("FAR (Res Max)",  _ds_zi.get("far_residential", "—")),
                        ("FAR (Comm Max)", _ds_zi.get("far_commercial", "—")),
                        ("Assessed Land",  _ds_zi.get("assess_land", "—")),
                        ("Assessed Total", _ds_zi.get("assess_total", "—")),
                        ("BBL",            _ds_bbl or "—"),
                    ]
                    _p_html2 = "<table style='width:100%;font-size:0.83rem;border-collapse:collapse'>"
                    for _pk, _pv in _p_right:
                        _p_html2 += (
                            f"<tr><td style='color:#6B7280;padding:5px 10px 5px 0;white-space:nowrap'>{_pk}</td>"
                            f"<td style='font-weight:600;padding:5px 0;color:#111827'>{_pv}</td></tr>"
                        )
                    st.markdown(_p_html2 + "</table>", unsafe_allow_html=True)
                st.caption("Source: NYC PLUTO via NYC Planning GeoSearch · No API key required")

        # ── Tab 2: Underbuilt / Value-Add Detection ──────────────────────────
        with _ds_t2:
            _ub_lot_area   = _sf(_ds_zi.get("lot_area_sqft"))
            _ub_max_far    = max(
                _sf(_ds_zi.get("far_residential")),
                _sf(_ds_zi.get("far_commercial")),
            )
            _ub_built_far  = _sf(_ds_zi.get("far_built"))
            _ub_unused_far = max(0.0, _ub_max_far - _ub_built_far)
            _ub_unused_pct = (_ub_unused_far / _ub_max_far * 100) if _ub_max_far > 0 else 0.0
            _ub_add_sf     = int(_ub_unused_far * _ub_lot_area)

            _um1, _um2, _um3, _um4 = st.columns(4)
            _um1.metric("Max FAR",             f"{_ub_max_far:.2f}")
            _um2.metric("Built FAR",           f"{_ub_built_far:.2f}")
            _um3.metric("Unused FAR",          f"{_ub_unused_pct:.0f}%")
            _um4.metric("Additional Build SF", f"{_ub_add_sf:,}")

            if _ub_unused_pct > 20:
                st.markdown(
                    f'<div class="opportunity-flag">🏗️ Underbuilt Opportunity — '
                    f'{_ub_unused_pct:.0f}% unused FAR · {_ub_add_sf:,} additional buildable SF</div>',
                    unsafe_allow_html=True,
                )
            elif _ub_max_far > 0:
                st.info(f"Site is near full buildout — {100 - _ub_unused_pct:.0f}% of max FAR utilized.")

            # Fetch nearby lots on same block
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
                            "$select": "lot,address,lotarea,builtfar,residfar,commfar,bldgclass,numfloors,latitude,longitude",
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
                        _ul_la      = float(_ul.get("lotarea") or 0)
                        _ul_built   = float(_ul.get("builtfar") or 0)
                        _ul_max_f   = max(float(_ul.get("residfar") or 0), float(_ul.get("commfar") or 0))
                        _ul_unused  = max(0.0, _ul_max_f - _ul_built)
                        _ul_pct     = (_ul_unused / _ul_max_f * 100) if _ul_max_f > 0 else 0.0
                        _ub_rows.append({
                            "Address":        _ul.get("address", "—"),
                            "Built FAR":      round(_ul_built, 2),
                            "Max FAR":        round(_ul_max_f, 2),
                            "Unused %":       f"{_ul_pct:.0f}%",
                            "Used SF":        f"{int(_ul_built * _ul_la):,}",
                            "Add'l Build SF": f"{int(_ul_unused * _ul_la):,}",
                            "Flag":           "🏗️ Underbuilt" if _ul_pct > 20 else "—",
                        })
                    except Exception:
                        continue

                if _ub_rows:
                    _ub_mc, _ub_tc = st.columns([1, 1])
                    with _ub_tc:
                        st.markdown("**Nearby Lots — Same Block**")
                        st.dataframe(pd.DataFrame(_ub_rows), use_container_width=True,
                                     height=min(len(_ub_rows) * 35 + 40, 340))
                    with _ub_mc:
                        st.markdown("**Lot Map**")
                        _ub_fmap = folium.Map(location=[lat, lon], zoom_start=17, tiles="CartoDB positron")
                        folium.Marker(
                            [lat, lon],
                            tooltip="Subject Property",
                            icon=folium.Icon(color="blue", icon="home"),
                        ).add_to(_ub_fmap)
                        for _ri, _ul in enumerate(_ub_lots[:15]):
                            try:
                                _ul_la   = float(_ul.get("lotarea") or 0)
                                _ul_built= float(_ul.get("builtfar") or 0)
                                _ul_max_f= max(float(_ul.get("residfar") or 0), float(_ul.get("commfar") or 0))
                                _ul_pct  = (max(0, _ul_max_f - _ul_built) / _ul_max_f * 100) if _ul_max_f > 0 else 0
                                _off_lat = lat + (_ri - 7) * 0.000065
                                _off_lon = lon + 0.00009
                                folium.CircleMarker(
                                    [_off_lat, _off_lon],
                                    radius=9,
                                    color="#15803D" if _ul_pct > 20 else "#9CA3AF",
                                    fill=True, fill_opacity=0.75,
                                    tooltip=f"{_ul.get('address', '?')} · {_ul_pct:.0f}% unused FAR",
                                ).add_to(_ub_fmap)
                            except Exception:
                                continue
                        st_folium(_ub_fmap, width="100%", height=340, returned_objects=[])
            st.caption("Green = underbuilt (>20% unused FAR) · Data: NYC PLUTO via Socrata")

        # ── Tab 3: Distress Signal Identification ────────────────────────────
        with _ds_t3:
            _ecb_key = f"_ecb_{_ds_bbl}"
            if _ecb_key not in st.session_state and _ds_bbl:
                with st.spinner("Checking ECB violations…"):
                    st.session_state[_ecb_key] = fetch_ecb_violations(_ds_bbl)
            _ecb_data = st.session_state.get(_ecb_key, {})

            # ACRIS lien count from session state (populated after Zoning section runs)
            _acris_ds   = st.session_state.get(f"_acris_{_ds_bbl}", {})
            _lien_count = sum(
                1 for d in _acris_ds.get("documents", [])
                if d.get("doc_type", "").upper() in ("UCC1", "LIEN", "LIEN2")
            )

            _ds_dist_level = _ecb_data.get("distress_level", 0)
            if _lien_count >= 3:
                _ds_dist_level = min(2, _ds_dist_level + 1)

            _dist_labels = ["Low", "Medium", "High"]
            _dist_css    = ["distress-low", "distress-medium", "distress-high"]

            _dm1, _dm2, _dm3 = st.columns(3)
            _dm1.metric("ECB Violations",          _ecb_data.get("count", "—"))
            _dm2.metric("Open / Unpaid",            _ecb_data.get("open_count", "—"))
            _dm3.metric("ACRIS Liens (UCC/LIEN)",   _lien_count)

            st.markdown(
                f'<div style="margin:10px 0 16px">'
                f'<span class="{_dist_css[_ds_dist_level]}">'
                f'⚡ Distress Score: {_dist_labels[_ds_dist_level]}</span></div>',
                unsafe_allow_html=True,
            )

            if _ecb_data.get("violations"):
                with st.expander(f"ECB Violations ({_ecb_data['count']} total)", expanded=True):
                    _vrows = [
                        {
                            "Date":        v.get("issue_date", "—"),
                            "Type":        v.get("violation_type", "—"),
                            "Description": v.get("description", "—")[:80],
                            "Penalty":     v.get("penalty", "—"),
                            "Balance Due": v.get("balance_due", "0"),
                        }
                        for v in _ecb_data["violations"]
                    ]
                    st.dataframe(pd.DataFrame(_vrows), use_container_width=True, height=240)
            elif _ecb_data and not _ecb_data.get("error"):
                st.success("No ECB violations found for this property.")

            if _ecb_data.get("error"):
                st.warning(f"ECB lookup: {_ecb_data['error']}")

            st.caption("ECB data: NYC Open Data (w9ak-ipjd) · ACRIS liens: NYC DOF · No API key required")

        # ── Tab 4: Listing + Broker Aggregation ─────────────────────────────
        with _ds_t4:
            _nearby_listings = [l for l in listings if float(l.get("distance_miles") or 99) < 0.15]
            if not _nearby_listings:
                st.info(
                    f"No active listings found within 0.15 miles. "
                    f"There are {len(listings)} listing(s) in the full search radius — see All Listings below."
                )
            else:
                _nl_rents   = [l.get("rent") or 0 for l in _nearby_listings if l.get("rent")]
                _nl_avg     = int(sum(_nl_rents) / len(_nl_rents)) if _nl_rents else 0
                _nl_min     = min(_nl_rents) if _nl_rents else 0
                _nl_max     = max(_nl_rents) if _nl_rents else 0
                _nl_psf_all = [
                    l["rent"] / l["sqft"]
                    for l in _nearby_listings
                    if l.get("sqft") and l["sqft"] > 0 and l.get("rent")
                ]
                _nl_avg_psf = round(sum(_nl_psf_all) / len(_nl_psf_all), 2) if _nl_psf_all else None

                _lm1, _lm2, _lm3, _lm4 = st.columns(4)
                _lm1.metric("Listings (0.15 mi)",  len(_nearby_listings))
                _lm2.metric("Avg Asking Rent",     f"${_nl_avg:,}/mo" if _nl_avg else "—")
                _lm3.metric("Rent Range",           f"${_nl_min:,}–${_nl_max:,}" if _nl_min else "—")
                _lm4.metric("Avg $/SF",             f"${_nl_avg_psf:.2f}" if _nl_avg_psf else "—")

                _nl_rows = []
                for _nl in _nearby_listings:
                    _sq = _nl.get("sqft") or 0
                    _rt = _nl.get("rent") or 0
                    _nl_rows.append({
                        "Address":   _nl.get("address", "—"),
                        "Unit Type": _nl.get("unit_type", "—"),
                        "Rent/mo":   f"${_rt:,}" if _rt else "—",
                        "$/SF":      f"${_rt/_sq:.2f}" if _sq > 0 and _rt else "—",
                        "Sqft":      f"{int(_sq):,}" if _sq else "—",
                        "Beds":      _nl.get("beds", "—"),
                        "Source":    _nl.get("source", "—"),
                        "Dist (mi)": f"{float(_nl.get('distance_miles') or 0):.3f}",
                    })
                st.dataframe(pd.DataFrame(_nl_rows), use_container_width=True,
                             height=min(len(_nl_rows) * 35 + 40, 320))
            st.caption("Listings sourced from comps search · Broker contact available via listing URL")

        # ── Tab 5: Assemblage Detection ──────────────────────────────────────
        with _ds_t5:
            _as_key = f"_assem_{_ds_bbl}"
            if _as_key not in st.session_state and _ds_bbl and len(str(_ds_bbl)) == 10:
                _as_bbl_s    = str(_ds_bbl)
                _as_boro_int = _as_bbl_s[0]
                _as_blk_int  = str(int(_as_bbl_s[1:6]))
                try:
                    _as_resp = requests.get(
                        "https://data.cityofnewyork.us/resource/64uk-42ks.json",
                        params={
                            "$where": f"block='{_as_blk_int}' AND borough='{_as_boro_int}'",
                            "$select": "lot,address,lotarea,lotfront,lotdepth,bldgclass,numfloors,residfar,commfar,builtfar",
                            "$limit": "30",
                        },
                        timeout=12,
                    )
                    st.session_state[_as_key] = _as_resp.json() if _as_resp.ok else []
                except Exception:
                    st.session_state[_as_key] = []
            _as_lots = st.session_state.get(_as_key, [])

            if _as_lots and _ds_bbl and len(str(_ds_bbl)) == 10:
                _subj_lot_num = int(str(_ds_bbl)[6:])
                _adj_lots_as  = [
                    l for l in _as_lots
                    if l.get("lot") and abs(int(l.get("lot", 0)) - _subj_lot_num) <= 3
                    and int(l.get("lot", 0)) != _subj_lot_num
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

                _am1, _am2, _am3 = st.columns(3)
                _am1.metric("Adjacent Lots",    len(_adj_lots_as))
                _am2.metric("Combined Lot Area", f"{int(_comb_la):,} SF")
                _am3.metric("Assemblage Uplift", f"{_ub_uplift_pct:.0f}%")

                if _ub_uplift_pct > 30:
                    st.markdown(
                        f'<div class="opportunity-flag">🔗 Assemblage Opportunity — '
                        f'{_ub_uplift_pct:.0f}% increase in buildable SF if assembled · '
                        f'Individual: {int(_indiv_sf):,} SF → Combined: {int(_comb_sf):,} SF</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.info(
                        f"Assemblage would increase buildable SF by {_ub_uplift_pct:.0f}% "
                        f"(flag threshold: >30%)."
                    )

                if _adj_lots_as:
                    _as_rows = []
                    for _al in _adj_lots_as:
                        _al_la = float(_al.get("lotarea") or 0)
                        _as_rows.append({
                            "Address":     _al.get("address", "—"),
                            "Lot #":       _al.get("lot", "—"),
                            "Lot Area SF": f"{int(_al_la):,}" if _al_la else "—",
                            "Floors":      _al.get("numfloors", "—"),
                            "Bldg Class":  _al.get("bldgclass", "—"),
                        })
                    st.markdown("**Adjacent Lots (±3 lot numbers, same block)**")
                    st.dataframe(pd.DataFrame(_as_rows), use_container_width=True,
                                 height=min(len(_as_rows) * 35 + 40, 260))
                else:
                    st.info("No directly adjacent lots found on this block.")
            else:
                st.info("BBL required for assemblage analysis. Enter a valid NYC address to begin.")
            st.caption("Assemblage data: NYC PLUTO via Socrata · Adjacent = lot number ±3 on same block")

        # ── Tab 6: Lead Scoring Engine ───────────────────────────────────────
        with _ds_t6:
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

            _sc_clr = "#15803D" if _sc_score >= 70 else ("#B45309" if _sc_score >= 40 else "#991B1B")
            _sc_tbg = "#DCFCE7" if _sc_score >= 70 else ("#FEF9C3" if _sc_score >= 40 else "#FEE2E2")
            _sc_tfg = "#15803D" if _sc_score >= 70 else ("#854D0E" if _sc_score >= 40 else "#991B1B")

            _sc_col1, _sc_col2 = st.columns([1, 2])
            with _sc_col1:
                st.markdown(
                    f'<div style="text-align:center;padding:28px 16px 16px">'
                    f'<div class="deal-score-num" style="color:{_sc_clr}">{_sc_score}</div>'
                    f'<div style="font-size:0.72rem;color:#6B7280;margin-bottom:10px">out of 100</div>'
                    f'<span class="deal-tier-badge" style="background:{_sc_tbg};color:{_sc_tfg}">'
                    f'{_sc_tier}</span></div>',
                    unsafe_allow_html=True,
                )
            with _sc_col2:
                st.markdown("**Score Breakdown**")
                for _cn, _cd in _sc_break.items():
                    _bar_pct = _cd["score"] / _cd["max"] if _cd["max"] > 0 else 0
                    st.markdown(
                        f"<div style='margin-bottom:10px'>"
                        f"<div style='display:flex;justify-content:space-between;font-size:0.82rem'>"
                        f"<span style='font-weight:600'>{_cn}</span>"
                        f"<span style='color:#6B7280'>{_cd['score']}/{_cd['max']}</span></div>"
                        f"<div style='background:#F3F4F6;border-radius:4px;height:7px;margin-top:4px'>"
                        f"<div style='background:{_sc_clr};width:{_bar_pct*100:.0f}%;"
                        f"height:7px;border-radius:4px'></div></div>"
                        f"<div style='font-size:0.72rem;color:#9CA3AF;margin-top:2px'>{_cd['reasoning']}</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
            st.caption(
                "Deal Score = weighted composite: unused FAR 30% · distress 25% · "
                "location demand 20% · zoning flexibility 15% · listing activity 10%"
            )

        # ── Market insights ────────────────────────────────────────────────
        _section_header("💡", "Market Insights")
        for insight in insights:
            st.markdown(f"• {insight}")

        # ── Borough comparison ─────────────────────────────────────────────
        if bench:
            st.markdown("---")
            st.markdown(
                "<div style='font-size:0.72rem;font-weight:700;letter-spacing:0.08em;"
                "text-transform:uppercase;color:#6B7280;margin-bottom:12px'>"
                f"🏙️ Comp vs {borough} Borough Median</div>",
                unsafe_allow_html=True,
            )
            bcomp_rows = ""
            for _, row in summary_df.iterrows():
                utype      = row["Unit Type"]
                comp_avg   = row["_avg"]
                bmark      = bench.get(utype)
                if bmark is None:
                    continue
                diff_pct   = (comp_avg - bmark) / bmark * 100
                diff_label = (
                    f'<span class="bcomp-above">▲ {abs(diff_pct):.1f}% above</span>'
                    if diff_pct > 3 else
                    f'<span class="bcomp-below">▼ {abs(diff_pct):.1f}% below</span>'
                    if diff_pct < -3 else
                    f'<span class="bcomp-at">≈ at median</span>'
                )
                bcomp_rows += (
                    f"<tr><td><b>{utype}</b></td>"
                    f"<td>${comp_avg:,.0f}</td>"
                    f"<td>${bmark:,}</td>"
                    f"<td>{diff_label}</td></tr>"
                )
            if bcomp_rows:
                st.markdown(f"""
                <table class="bcomp-table">
                  <thead><tr>
                    <th>Unit Type</th>
                    <th>Comp Avg Rent</th>
                    <th>{borough} Median*</th>
                    <th>vs. Borough</th>
                  </tr></thead>
                  <tbody>{bcomp_rows}</tbody>
                </table>
                <div style="font-size:0.70rem;color:#9CA3AF;margin-top:6px">
                  * Borough medians: <a href="https://streeteasy.com/blog/market-reports/" target="_blank" style="color:#6B7280">StreetEasy Market Reports Q4 2024</a> / NYC Rent Guidelines Board 2024.
                  Directional benchmark only — verify with current market data.
                </div>
                """, unsafe_allow_html=True)

        # ── Rent summary table ─────────────────────────────────────────────
        _section_header("📈", "Rent Summary by Unit Type")
        display_cols = ["Unit Type", "# Listings", "Avg Rent", "Median Rent",
                        "Min Rent", "Max Rent", "Rent Range", "Avg $/SF"]
        st.dataframe(
            summary_df[display_cols].set_index("Unit Type"),
            use_container_width=True,
            height=min(len(summary_df) * 35 + 38, 260),
        )

        # ── Listings map ───────────────────────────────────────────────────
        _section_header("🗺️", "Comparable Listings Map")
        st.caption(
            "Colored markers = rental listings by unit type.  "
            "Click any marker for rent, address, and source link.  "
            "Clusters expand on zoom."
        )
        listings_map = build_map(
            listings=listings,
            center_lat=lat,
            center_lon=lon,
            radius_miles=radius_miles,
            subject_label=geo["formatted_address"],
        )
        st_folium(listings_map, width="100%", height=540,
                  returned_objects=[], key="listings_map")

        # ── Charts ─────────────────────────────────────────────────────────
        st.markdown("---")
        st.markdown(
            "<div style='font-size:0.72rem;font-weight:700;letter-spacing:0.08em;"
            "text-transform:uppercase;color:#6B7280;margin-bottom:8px'>📊 Rent Charts</div>",
            unsafe_allow_html=True,
        )
        col_bar, col_range = st.columns(2)
        with col_bar:
            st.plotly_chart(build_bar_chart(summary_df),
                            use_container_width=True, config={"displayModeBar": False})
        with col_range:
            st.plotly_chart(build_range_chart(summary_df),
                            use_container_width=True, config={"displayModeBar": False})

        # ── All Listings Table (collapsible) ──────────────────────────────
        _section_header("📄", "All Listings")
        display_listings = []
        for listing in listings:
            sqft = listing.get("sqft") or 0
            rent = listing.get("rent") or 0
            psf  = f"${rent / sqft:.2f}" if sqft and sqft > 0 else "—"
            url  = listing.get("url") or ""
            link = (
                f'<a href="{url}" target="_blank" '
                f'style="color:#1A3A6B;text-decoration:none;font-weight:600">View →</a>'
                if url else "—"
            )
            display_listings.append({
                "Source":        listing.get("source", "—"),
                "Address":       listing.get("address", "N/A"),
                "Unit Type":     listing.get("unit_type", "—"),
                "Beds":          listing.get("bedrooms", "—"),
                "Rent/mo":       f"${rent:,.0f}",
                "$/SF":          psf,
                "Sqft":          listing.get("sqft") or "—",
                "Distance (mi)": f"{listing.get('distance_miles', 0):.2f}",
                "Link":          link,
            })
        df_display = pd.DataFrame(display_listings)
        with st.expander(f"📋 All Listings ({len(display_listings)} total)", expanded=False):
            st.write(df_display.to_html(escape=False, index=False), unsafe_allow_html=True)

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
                                f"padding:2px 0;border-bottom:1px solid #F3F4F6'>"
                                f"<span style='color:#6B7280'>{_label}</span>"
                                f"<b>{_vstr}</b></div>",
                                unsafe_allow_html=True,
                            )
                        if _res_d.get("condo_psf"):
                            st.caption(f"Condo: ${_res_d['condo_psf']:,}/SF")
                    else:
                        if _hb_res:
                            st.markdown(f"<div style='font-size:0.84rem;color:#374151;padding:4px 0'>{_hb_res[:200]}</div>", unsafe_allow_html=True)
                with _hc2:
                    st.markdown("**🏪 Retail Rents**")
                    if _ret_d.get("asking_rent_psf"):
                        st.markdown(
                            f"<div style='font-size:1.1rem;font-weight:700;color:#111827'>"
                            f"${_ret_d['asking_rent_psf']:,} <span style='font-size:0.75rem;font-weight:400;color:#6B7280'>/SF/yr asking</span></div>",
                            unsafe_allow_html=True,
                        )
                    if _ret_d.get("vacancy_pct"):
                        st.caption(f"Vacancy: {_ret_d['vacancy_pct']:.1f}%")
                    if _ret_d.get("tenant_types"):
                        st.markdown(
                            " ".join(f"<span style='background:#EEF2FF;color:#4338CA;border-radius:12px;padding:2px 8px;font-size:0.72rem;margin:2px'>{t}</span>" for t in _ret_d["tenant_types"]),
                            unsafe_allow_html=True,
                        )
                    if not _ret_d.get("asking_rent_psf") and _hb_com:
                        st.markdown(f"<div style='font-size:0.84rem;color:#374151;padding:4px 0'>{_hb_com[:200]}</div>", unsafe_allow_html=True)
                with _hc3:
                    st.markdown("**🏢 Commercial / Office**")
                    if _com_d.get("asking_rent_psf"):
                        st.markdown(
                            f"<div style='font-size:1.1rem;font-weight:700;color:#111827'>"
                            f"${_com_d['asking_rent_psf']:,} <span style='font-size:0.75rem;font-weight:400;color:#6B7280'>/SF/yr asking</span></div>",
                            unsafe_allow_html=True,
                        )
                    if _com_d.get("vacancy_pct"):
                        st.caption(f"Vacancy: {_com_d['vacancy_pct']:.1f}%")
                    if _com_d.get("tenant_types"):
                        st.markdown(
                            " ".join(f"<span style='background:#F0F9FF;color:#0369A1;border-radius:12px;padding:2px 8px;font-size:0.72rem;margin:2px'>{t}</span>" for t in _com_d["tenant_types"]),
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
            "sourced from public news and real estate databases."
        )

        _comps_key = f"_comps_{neighborhood.lower()}_{zip_code}"
        if _comps_key not in st.session_state:
            with st.spinner(f"Researching competing developments in {neighborhood}…"):
                st.session_state[_comps_key] = search_competing_devs(
                    neighborhood, borough, lat, lon, zip_code
                )
        _comp_devs = st.session_state.get(_comps_key, [])

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
        _articles_key = f"_articles_{address_input.strip()[:40].lower()}_{neighborhood.lower()}"
        if _articles_key not in st.session_state:
            with st.spinner("Searching real estate news…"):
                st.session_state[_articles_key] = fetch_nearby_articles(
                    address_input.strip(), neighborhood, borough
                )
        _articles = st.session_state.get(_articles_key, [])

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
                        f"<div style='background:white;border:1px solid #E5E7EB;"
                        f"border-radius:10px;padding:10px 14px;margin-bottom:8px'>"
                        f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:4px'>"
                        f"<span style='background:{_bg};color:{_fg};border-radius:10px;padding:2px 8px;font-size:0.68rem;font-weight:700'>{_lbl}</span>"
                        f"<span style='font-size:0.68rem;color:#9CA3AF'>{_dt}</span>"
                        f"</div>"
                        f"<div style='font-size:0.82rem;font-weight:600;color:#111827;margin-bottom:4px'>"
                        f"<a href='{_art['url']}' target='_blank' style='color:#111827;text-decoration:none'>"
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

        if _zola_subj_key not in st.session_state and _subject_addr:
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
            else:
                # ── Header: BBL + ZOLA link ──────────────────────────────
                _bbl_disp = _zinfo.get("bbl", "—")
                _zola_url = _zinfo.get("zola_url", "")
                _matched  = _zinfo.get("matched_label", "")
                _zola_link = (
                    f'&nbsp;&nbsp;<a href="{_zola_url}" target="_blank" '
                    f'style="color:#1A3A6B;font-weight:600">View on ZOLA →</a>'
                    if _zola_url else ""
                )
                st.markdown(
                    f"<div style='margin-bottom:12px;padding:8px 12px;"
                    f"background:#F0F4FF;border-radius:8px;border-left:3px solid #1A3A6B'>"
                    f"<b>BBL:</b> {_bbl_disp} &nbsp;·&nbsp; "
                    f"Borough {_zinfo.get('borough_code','—')} &nbsp;·&nbsp; "
                    f"Block {_zinfo.get('block','—')} &nbsp;·&nbsp; "
                    f"Lot {_zinfo.get('lot','—')}"
                    f"{_zola_link}"
                    f"<br><span style='color:#6B7280;font-size:0.82rem'>{_matched}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

                # ── ACRIS Property History ───────────────────────────────
                _acris_key = f"_acris_{_bbl_disp}"
                if _acris_key not in st.session_state and _bbl_disp != "—":
                    with st.spinner("Fetching ACRIS document history…"):
                        st.session_state[_acris_key] = fetch_acris(_bbl_disp)
                _acris = st.session_state.get(_acris_key, {})
                _acris_sum = _acris.get("summary", {}) if _acris else {}
                if _acris and _acris.get("acris_url"):
                    st.session_state["_acris_data_url"] = _acris["acris_url"]

                if _acris_sum:
                    _ac1, _ac2, _ac3, _ac4 = st.columns(4)
                    def _acris_card(col, icon, label, value, sub=""):
                        with col:
                            st.markdown(
                                f"<div style='background:white;border:1px solid #E5E7EB;"
                                f"border-radius:10px;padding:10px 14px;margin-bottom:8px'>"
                                f"<div style='font-size:0.68rem;color:#6B7280;font-weight:700;"
                                f"text-transform:uppercase;letter-spacing:0.06em'>{icon} {label}</div>"
                                f"<div style='font-size:1.05rem;font-weight:700;color:#111827;"
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
                                f"{_acris_sum.get('total_docs', 0)} total docs")

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
                            for _d in _all_docs[:60]:
                                _parties_str = "; ".join(
                                    f"{p['role']}: {p['name']}" for p in _d.get("parties", [])
                                )
                                _amt = _d.get("amount")
                                _doc_rows.append({
                                    "Date":      _d.get("date", "—"),
                                    "Doc Type":  _d.get("doc_type", "—"),
                                    "Amount":    f"${_amt:,.0f}" if _amt and _amt > 0 else "—",
                                    "Parties":   _parties_str[:60] or "—",
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
                                    f"background:#F9FAFB;border-radius:6px;border:1px solid #E5E7EB;margin-bottom:4px'>"
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
                    _bullets_html = "".join(f"<li style='margin-bottom:5px;font-size:0.82rem;color:#374151'>{b}</li>" for b in _bullets)
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
                        st.markdown(
                            _zrow("Community Board", zi.get("community_board")) +
                            _zrow("ZIP Code",        zi.get("zip_code")) +
                            _zrow("NTA",             zi.get("nta")) +
                            _zrow("PLUTO Address",   zi.get("address_pluto")),
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

                    _ec1, _ec2, _ec3 = st.columns(3)
                    def _erow(lbl, val, width="170px"):
                        v = str(val) if val not in (None, 0, "0", "") else None
                        body = f"<b>{v}</b>" if v else "<span style='color:#9CA3AF'>—</span>"
                        return (
                            f"<div style='display:flex;gap:8px;margin-bottom:5px'>"
                            f"<span style='color:#6B7280;min-width:{width}'>{lbl}</span>"
                            f"{body}</div>"
                        )

                    with _ec1:
                        st.markdown("**FAR Limits**")
                        st.markdown(
                            _erow("Base FAR",       _zrules.get("base_far")) +
                            _erow("Max FAR (bonus)", _zrules.get("max_far")) +
                            _erow("Residential FAR",_zrules.get("res_far")) +
                            _erow("Commercial FAR", _zrules.get("comm_far")),
                            unsafe_allow_html=True,
                        )
                    with _ec2:
                        st.markdown("**Height & Setbacks**")
                        _bh = _zrules.get("base_height_ft", 0)
                        _mh = _zrules.get("max_height_ft", 0)
                        st.markdown(
                            _erow("Base Height",    f"{_bh} ft" if _bh else "Sky exposure plane") +
                            _erow("Max Height",     f"{_mh} ft" if _mh else "No absolute limit") +
                            _erow("Front Yard",     f"{_zrules.get('front_yard_ft',0)} ft") +
                            _erow("Rear Yard",      f"{_zrules.get('rear_yard_ft',0)} ft") +
                            _erow("Side Yard",      f"{_zrules.get('side_yard_ft',0)} ft"),
                            unsafe_allow_html=True,
                        )
                    with _ec3:
                        st.markdown("**Rules & Controls**")
                        _lc = _zrules.get("lot_coverage_pct", 0)
                        st.markdown(
                            _erow("Max Lot Coverage",  f"{_lc}%" if _lc else "—") +
                            _erow("Contextual Rules",  "Yes" if _zrules.get("contextual") else "No") +
                            _erow("Tower Rules",       "Yes" if _zrules.get("tower_rules") else "No") +
                            _erow("Sky Exp. Plane",    "Yes" if _zrules.get("sky_exp_plane") else "No"),
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
                                f"<div style='background:#F0FDF4;border:1px solid #BBF7D0;"
                                f"border-radius:8px;padding:10px 14px;margin-bottom:12px'>"
                                f"<span style='font-size:0.72rem;font-weight:700;color:#15803D;"
                                f"text-transform:uppercase;letter-spacing:0.06em'>📦 Existing Structure</span>"
                                f"<div style='margin-top:4px;font-size:0.84rem;color:#374151'>"
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

                        _dev_focus  = st.session_state.get("dev_focus", "Residential")
                        _sub_comps  = st.session_state.get("dev_sub_comps", ["Ground Floor Retail"])
                        _show_nbrs  = st.session_state.get("show_nbr_toggle", False)
                        _sub_key    = "_".join(sorted(_sub_comps))

                        # Fetch neighbor lots from PLUTO if toggle enabled
                        _nbr_lots: list = []
                        if _show_nbrs and _zinfo.get("block") and _zinfo.get("borough_code"):
                            _nbr_cache_key = f"_nbr_{_zinfo.get('block')}_{_zinfo.get('borough_code')}"
                            if _nbr_cache_key not in st.session_state:
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
                                    _nbr_raw = _nbr_resp.json() if _nbr_resp.ok else []
                                    # Tag each with side relative to subject lot
                                    _subj_lot_int = int(re.sub(r"\D", "", str(_zinfo.get("lot", "0"))) or "0")
                                    for _nb in _nbr_raw:
                                        _nb_lot = int(re.sub(r"\D", "", str(_nb.get("lot", "0"))) or "0")
                                        if _nb_lot != _subj_lot_int:
                                            _nb["_side"] = "left" if _nb_lot < _subj_lot_int else "right"
                                    st.session_state[_nbr_cache_key] = [
                                        nb for nb in _nbr_raw if nb.get("_side")
                                    ]
                                except Exception:
                                    st.session_state[_nbr_cache_key] = []
                            _nbr_lots = st.session_state.get(_nbr_cache_key, [])

                        # Build / retrieve massing options
                        _mass_key = (
                            f"_massing_{_bbl_disp}_comb{len(_valid_adj)}"
                            f"_f{_dev_focus}_s{_sub_key}_n{int(_show_nbrs)}"
                            if _using_combined else
                            f"_massing_{_bbl_disp}"
                            f"_f{_dev_focus}_s{_sub_key}_n{int(_show_nbrs)}"
                        )
                        if _mass_key not in st.session_state:
                            st.session_state[_mass_key] = build_massing_options(
                                _lf_v, _ld_v, _la_v, _primary_zone, _zrules,
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

                        if _options:
                            # ── Summary Metrics Table ─────────────────────
                            _max_far_val = _zrules.get("max_far") or _zrules.get("base_far", 0)
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
                                _sum_rows.append({
                                    "#":           _o.get("number", ""),
                                    "Scenario":    _o.get("name", "—"),
                                    "Risk":        _o.get("risk_level", "—"),
                                    "Stories":     _o.get("floors", 0),
                                    "Height (ft)": _o.get("height_ft", 0),
                                    "Gross SF":    _gross_sf,
                                    "Max Bldg SF": _max_bldg_sf,
                                    "FAR Used":    _far_used_pct,
                                    "Net SF":      _net_sf,
                                    "Est. Units":  _units,
                                    "Loss %":      f"{int(_o.get('loss_factor',0.15)*100)}%",
                                })
                            _sum_df = pd.DataFrame(_sum_rows)
                            with st.expander("📊 All Scenarios — Summary Table", expanded=True):
                                st.dataframe(
                                    _sum_df,
                                    use_container_width=True,
                                    hide_index=True,
                                    column_config={
                                        "#":           st.column_config.NumberColumn("#", width="small"),
                                        "Gross SF":    st.column_config.NumberColumn("Gross SF", format="%d"),
                                        "Max Bldg SF": st.column_config.NumberColumn("Max Bldg SF", format="%d",
                                                        help=f"Max buildable SF = lot area × max FAR ({_max_far_val})"),
                                        "Net SF":      st.column_config.NumberColumn("Net SF",   format="%d"),
                                        "Est. Units":  st.column_config.NumberColumn("Est. Units", format="%d"),
                                        "Stories":     st.column_config.NumberColumn("Stories",  format="%d"),
                                        "Height (ft)": st.column_config.NumberColumn("Height (ft)", format="%d"),
                                    },
                                )

                        if _options:
                            # ── Risk badge helper ────────────────────────
                            def _risk_badge(rl: str) -> str:
                                if rl == "LOW":
                                    return "<span class='risk-low'>🟢 Low Risk</span>"
                                elif rl == "HIGH":
                                    return "<span class='risk-high'>🔴 High Risk</span>"
                                return "<span class='risk-med'>🟡 Med Risk</span>"

                            # ── Tile renderer ────────────────────────────
                            def _render_tile(opt: dict, key_suffix: str):
                                rl = opt.get("risk_level", "MED")
                                st.markdown(
                                    f"<div style='background:white;border:1px solid #E5E7EB;"
                                    f"border-radius:12px;padding:10px 10px 6px'>"
                                    f"{_risk_badge(rl)}"
                                    f"<div style='font-weight:700;font-size:0.85rem;margin:6px 0 2px'>"
                                    f"{opt['name']}</div></div>",
                                    unsafe_allow_html=True,
                                )
                                st.plotly_chart(
                                    opt["fig"],
                                    use_container_width=True,
                                    config={"displayModeBar": False},
                                    key=f"mass_{key_suffix}",
                                )
                                _ta1, _ta2 = st.columns(2)
                                with _ta1:
                                    st.metric("Gross Area",     f"{opt.get('total_sqft',0):,} SF")
                                    st.metric("Net Rentable",   f"{opt.get('net_rentable_sqft',0):,} SF")
                                with _ta2:
                                    st.metric("Height",         f"{opt.get('height_ft',0)} ft")
                                    st.metric("Floors",         str(opt.get("floors", 0)))

                                # Strategy + description (collapsible)
                                with st.expander("📋 Strategy & Description", expanded=True):
                                    st.markdown(f"**Strategy:** {opt.get('strategy','')}")
                                    st.markdown(opt.get('description',''))

                                # Unit mix + financials + floor plates
                                with st.expander("📊 Unit Mix, Financials & Floor Plans", expanded=False):
                                    _tab_mix, _tab_fp = st.tabs(["💰 Unit Mix & Financials", "🏢 Floor Plates"])
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

                            # ── Display tiles by risk tier ───────────────
                            for _tier, _tier_label, _tier_color in [
                                ("LOW",  "🟢 Low Risk Scenarios",    "#DCFCE7"),
                                ("MED",  "🟡 Medium Risk Scenarios", "#FEF9C3"),
                                ("HIGH", "🔴 High Risk Scenarios",   "#FEE2E2"),
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
                                _tcols = st.columns(len(_tier_opts))
                                for _tc, _topt in zip(_tcols, _tier_opts):
                                    with _tc:
                                        _render_tile(
                                            _topt,
                                            f"{_topt['name'].replace(' ','_').replace('/','_')}_{_bbl_disp}",
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
                                        for _ck, _cv in _cmp_data:
                                            st.markdown(
                                                f"<div style='display:flex;justify-content:space-between;"
                                                f"border-bottom:1px solid #F3F4F6;padding:4px 0;"
                                                f"font-size:0.79rem'>"
                                                f"<span style='color:#6B7280'>{_ck}</span>"
                                                f"<b>{_cv}</b></div>",
                                                unsafe_allow_html=True,
                                            )
                                        st.markdown(
                                            f"<div style='margin-top:8px;font-size:0.73rem;color:#374151'>"
                                            f"{_so.get('strategy','')}</div>",
                                            unsafe_allow_html=True,
                                        )
                            elif _selected_names:
                                st.caption("Select at least 2 scenarios to enable comparison.")
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

        # ── Macro + Micro Risk Matrix ──────────────────────────────────────
        _section_header("⚠️", "Investment Risk Analysis")

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
                f"<td style='color:#374151;word-wrap:break-word'>{r['description']}</td>"
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
                    f"<div style='padding:10px;border:1px solid #E5E7EB;border-radius:8px;margin-bottom:8px;background:white'>"
                    f"<div style='display:flex;gap:8px;align-items:center;margin-bottom:4px'>"
                    f"<b style='font-size:0.83rem'>{_mr['category']}</b>"
                    f"&nbsp;<span class='{_pc}' style='padding:1px 7px;border-radius:10px;font-size:0.68rem;font-weight:700'>"
                    f"Prob: {_mr.get('probability','—')}</span>"
                    f"&nbsp;<span class='{_ic}' style='padding:1px 7px;border-radius:10px;font-size:0.68rem;font-weight:700'>"
                    f"Impact: {_mr.get('impact','—')}</span></div>"
                    f"<div style='font-size:0.78rem;color:#374151;margin-bottom:4px'>{_mr['description']}</div>"
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
                        st.markdown(f"[NYC Zoning Text →](https://zoning.nyc.gov/) · [View on ZOLA →](https://zola.planning.nyc.gov/)")
                elif _dtype == "overlay" and _ddata:
                    with st.expander(f"🏪 Commercial Overlay {_dcode}", expanded=False):
                        st.markdown(f"**Permitted Uses:** {_ddata.get('uses', 'local retail and service')}")
                        st.markdown(f"**Commercial FAR:** {_ddata.get('comm_far', '—')}")
                        st.markdown("[NYC Commercial Overlay Guide →](https://zoning.nyc.gov/)")
                elif _dtype == "special" and _ddata:
                    with st.expander(f"⭐ Special District {_dcode} — {_ddata.get('name', '')}", expanded=False):
                        st.markdown(_ddata.get("description", ""))
                        st.markdown(f"[NYC Planning Special District Text →]({_ddata.get('url', 'https://zoning.nyc.gov/')})")
                elif _dtype == "limited_height":
                    with st.expander(f"📏 Limited Height District {_dcode}", expanded=False):
                        st.markdown(f"Limited height districts restrict building heights below the otherwise applicable zoning limits. Verify maximum height with NYC Planning for district **{_dcode}**.")
                        st.markdown("[NYC Planning →](https://zoning.nyc.gov/)")
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
      <h3 style="color:#374151;margin:0 0 8px">Enter a NYC address to begin</h3>
      <p style="margin:0;max-width:460px;margin-inline:auto;line-height:1.6">
        Type any NYC street address in the form above, choose a search radius,
        and optionally filter by unit type or rental tier — then click
        <strong>Geocode Address</strong>.
      </p>
    </div>
    """, unsafe_allow_html=True)

# ── Footer ─────────────────────────────────────────────────────────────────────
st.markdown("""
<hr style="margin-top:48px;border-color:#E5E7EB"/>
<div style="text-align:center;color:#9CA3AF;font-size:0.75rem;padding:12px 0">
  Real Estate Development &amp; Investment Analytics · NYC Planning, PLUTO, ACRIS &amp; Market Data ·
  For internal real estate diligence use only · Not financial advice
</div>
""", unsafe_allow_html=True)

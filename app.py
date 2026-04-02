"""
NYC Rent Comp Analyzer
Stages 1–6: Input collection + geocoding + NYC context + data collection + analysis + visualizations
"""

import os
import time
import requests
import streamlit as st
import folium
from folium.plugins import MiniMap
from streamlit_folium import st_folium
from dotenv import load_dotenv
import pandas as pd

from modules.data_fetcher import fetch_all_listings
from modules.analyzer import compute_summary, compute_insights
from modules.visualizer import (
    build_map, build_bar_chart, build_range_chart,
    build_box_chart, build_scatter_chart
)
from modules.zola_fetcher import fetch_zoning_info
from modules.zoning_rules import get_zoning_rules
from modules.massing_viz import build_massing_options

load_dotenv()

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="NYC Rent Comp Analyzer",
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

/* ── Photo gallery ── */
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
    "Manhattan": {"Studio": 3_200, "1 Bed": 4_200, "2 Bed": 5_800, "3 Bed": 7_500, "4+ Bed": 10_000},
    "Brooklyn":  {"Studio": 2_500, "1 Bed": 3_200, "2 Bed": 4_100, "3 Bed": 5_500, "4+ Bed":  7_200},
    "Queens":    {"Studio": 2_000, "1 Bed": 2_600, "2 Bed": 3_200, "3 Bed": 4_000, "4+ Bed":  5_500},
    "Bronx":     {"Studio": 1_700, "1 Bed": 2_100, "2 Bed": 2_600, "3 Bed": 3_200, "4+ Bed":  4_200},
    "Staten Island": {"Studio": 1_600, "1 Bed": 1_900, "2 Bed": 2_400, "3 Bed": 3_000, "4+ Bed": 3_800},
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
  <h1>🏙️ NYC Rent Comp Analyzer</h1>
  <p>
    Professional rental market intelligence for real estate development
    &amp; investment diligence — enter any NYC address to begin.
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
    st.markdown(f"""
    <div class="geo-card">
      <div class="geo-card-title">📍 Geocoding Result &nbsp; {badge}{demand_tag}{transit_tag}</div>
      <div class="geo-address">{geo['formatted_address']}</div>
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

        # ── Market insights ────────────────────────────────────────────────
        st.markdown("---")
        st.markdown(
            "<div style='font-size:0.72rem;font-weight:700;letter-spacing:0.08em;"
            "text-transform:uppercase;color:#6B7280;margin-bottom:12px'>💡 Market Insights</div>",
            unsafe_allow_html=True,
        )
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
                  * Borough medians from StreetEasy / NYC Rent Guidelines Board Q4 2024.
                  Use as directional benchmark only.
                </div>
                """, unsafe_allow_html=True)

        # ── Rent summary table ─────────────────────────────────────────────
        st.markdown("---")
        st.markdown(
            "<div style='font-size:0.72rem;font-weight:700;letter-spacing:0.08em;"
            "text-transform:uppercase;color:#6B7280;margin-bottom:12px'>📈 Rent Summary by Unit Type</div>",
            unsafe_allow_html=True,
        )
        display_cols = ["Unit Type", "# Listings", "Avg Rent", "Median Rent",
                        "Min Rent", "Max Rent", "Rent Range", "Avg $/SF"]
        st.dataframe(
            summary_df[display_cols].set_index("Unit Type"),
            use_container_width=True,
            height=min(len(summary_df) * 35 + 38, 260),
        )

        # ── Listings map ───────────────────────────────────────────────────
        st.markdown("---")
        st.markdown(
            "<div style='font-size:0.72rem;font-weight:700;letter-spacing:0.08em;"
            "text-transform:uppercase;color:#6B7280;margin-bottom:8px'>🗺️ Comparable Listings Map</div>",
            unsafe_allow_html=True,
        )
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

        st.plotly_chart(build_box_chart(listings),
                        use_container_width=True, config={"displayModeBar": False})
        st.plotly_chart(build_scatter_chart(listings),
                        use_container_width=True, config={"displayModeBar": False})

        # ── All Listings Table (collapsible) ──────────────────────────────
        st.markdown("---")
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

        # ── NYC Zoning Information (ZOLA / PLUTO) ─────────────────────────
        st.markdown("---")
        st.markdown(
            "<div style='font-size:0.72rem;font-weight:700;letter-spacing:0.08em;"
            "text-transform:uppercase;color:#6B7280;margin-bottom:8px'>"
            "🗺️ NYC Zoning Information (ZOLA)</div>",
            unsafe_allow_html=True,
        )

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

                def _zrow(label, val, width="160px"):
                    v = str(val) if val and str(val) != "—" else None
                    body = f"<b>{v}</b>" if v else "<span style='color:#9CA3AF'>—</span>"
                    return (
                        f"<div style='display:flex;gap:8px;margin-bottom:5px'>"
                        f"<span style='color:#6B7280;min-width:{width}'>{label}</span>"
                        f"{body}</div>"
                    )

                zc1, zc2, zc3 = st.columns(3)

                with zc1:
                    st.markdown("**🏙️ Zoning Districts**")
                    st.markdown(
                        _zrow("Primary District",  _zinfo.get("zoning_dist")) +
                        _zrow("Secondary District",_zinfo.get("zoning_dist2")) +
                        _zrow("Tertiary District", _zinfo.get("zoning_dist3")) +
                        _zrow("Commercial Overlay",_zinfo.get("overlay")) +
                        _zrow("Overlay 2",         _zinfo.get("overlay2")) +
                        _zrow("Special District",  _zinfo.get("special_dist")) +
                        _zrow("Special District 2",_zinfo.get("special_dist2")) +
                        _zrow("Limited Height",    _zinfo.get("ltd_height")) +
                        _zrow("Split Zone",        _zinfo.get("split_zone")) +
                        _zrow("Land Use",          _zinfo.get("land_use")) +
                        _zrow("Historic District", _zinfo.get("historic_dist")) +
                        _zrow("Landmark",          _zinfo.get("landmark")),
                        unsafe_allow_html=True,
                    )
                    st.markdown("**💰 Assessment & Ownership**")
                    st.markdown(
                        _zrow("Owner",           _zinfo.get("owner")) +
                        _zrow("Tax Class",       _zinfo.get("tax_class")) +
                        _zrow("Assessed Land",   _zinfo.get("assess_land")) +
                        _zrow("Assessed Total",  _zinfo.get("assess_total")) +
                        _zrow("Exemption Total", _zinfo.get("exempt_total")),
                        unsafe_allow_html=True,
                    )

                with zc2:
                    st.markdown("**📐 FAR — Development Rights**")
                    st.markdown(
                        _zrow("Residential FAR",  _zinfo.get("far_residential")) +
                        _zrow("Commercial FAR",   _zinfo.get("far_commercial")) +
                        _zrow("Facility FAR",     _zinfo.get("far_facility")) +
                        _zrow("Built FAR",        _zinfo.get("far_built")) +
                        _zrow("Existing FAR",     _zinfo.get("far_existing")),
                        unsafe_allow_html=True,
                    )
                    st.markdown("**📏 Lot Dimensions**")
                    _la = _zinfo.get("lot_area_sqft", "—")
                    _lf = _zinfo.get("lot_frontage_ft", "—")
                    _ld = _zinfo.get("lot_depth_ft", "—")
                    st.markdown(
                        _zrow("Lot Area",     f"{_la} SF" if _la != "—" else "—") +
                        _zrow("Lot Frontage", f"{_lf} ft" if _lf != "—" else "—") +
                        _zrow("Lot Depth",    f"{_ld} ft" if _ld != "—" else "—") +
                        _zrow("Lot Type",     _zinfo.get("lot_type")) +
                        _zrow("Irregular",    _zinfo.get("irr_lot")) +
                        _zrow("Easements",    _zinfo.get("easements")),
                        unsafe_allow_html=True,
                    )
                    st.markdown("**📍 Location**")
                    st.markdown(
                        _zrow("Community Board", _zinfo.get("community_board")) +
                        _zrow("ZIP Code",        _zinfo.get("zip_code")) +
                        _zrow("NTA",             _zinfo.get("nta")) +
                        _zrow("PLUTO Address",   _zinfo.get("address_pluto")),
                        unsafe_allow_html=True,
                    )

                with zc3:
                    st.markdown("**🏗️ Building**")
                    _ba  = _zinfo.get("bldg_area_sqft", "—")
                    _bfr = _zinfo.get("bldg_frontage_ft", "—")
                    _bdp = _zinfo.get("bldg_depth_ft", "—")
                    st.markdown(
                        _zrow("Building Area",    f"{_ba} SF"  if _ba  != "—" else "—") +
                        _zrow("Bldg Frontage",    f"{_bfr} ft" if _bfr != "—" else "—") +
                        _zrow("Bldg Depth",       f"{_bdp} ft" if _bdp != "—" else "—") +
                        _zrow("Floors",           _zinfo.get("num_floors")) +
                        _zrow("Num. Buildings",   _zinfo.get("num_buildings")) +
                        _zrow("Year Built",       _zinfo.get("year_built")) +
                        _zrow("Year Last Mod.",   _zinfo.get("year_last_mod")) +
                        _zrow("Building Class",   _zinfo.get("bldg_class")) +
                        _zrow("Basement",         _zinfo.get("basement")) +
                        _zrow("Extensions",       _zinfo.get("extensions")) +
                        _zrow("Condo Number",     _zinfo.get("condo_no")) +
                        _zrow("Res. Units",       _zinfo.get("units_res")) +
                        _zrow("Total Units",      _zinfo.get("units_total")),
                        unsafe_allow_html=True,
                    )

                # ── Zoning Envelope Rules ────────────────────────────────
                _primary_zone = _zinfo.get("zoning_dist", "")
                _zrules = get_zoning_rules(_primary_zone)

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

                    # ── 3D Massing Diagrams ──────────────────────────────
                    try:
                        _lf_raw  = _zinfo.get("lot_frontage_ft", "0").replace(",", "")
                        _ld_raw  = _zinfo.get("lot_depth_ft", "0").replace(",", "")
                        _la_raw  = _zinfo.get("lot_area_sqft", "0").replace(",", "")
                        _lf_v    = float(_lf_raw) if _lf_raw not in ("—","") else 0
                        _ld_v    = float(_ld_raw) if _ld_raw not in ("—","") else 0
                        _la_v    = float(_la_raw) if _la_raw not in ("—","") else 0
                        # Fall back to frontage×depth estimate if lot area missing
                        if _la_v <= 0 and _lf_v > 0 and _ld_v > 0:
                            _la_v = _lf_v * _ld_v
                        # Fall back to estimated lot dimensions if individual dims missing
                        if _lf_v <= 0 and _la_v > 0:
                            _lf_v = (_la_v ** 0.5) * 0.8
                        if _ld_v <= 0 and _la_v > 0:
                            _ld_v = _la_v / max(10, _lf_v)
                    except (ValueError, AttributeError):
                        _lf_v = _ld_v = _la_v = 0

                    if _lf_v > 0 and _ld_v > 0 and _la_v > 0:
                        st.markdown("---")
                        st.markdown(
                            "<div style='font-size:0.72rem;font-weight:700;letter-spacing:0.08em;"
                            "text-transform:uppercase;color:#6B7280;margin-bottom:8px'>"
                            "🏗️ Massing Options (Based on Zoning)</div>",
                            unsafe_allow_html=True,
                        )
                        st.caption(
                            f"Lot: {_lf_v:.0f}′ × {_ld_v:.0f}′ = {_la_v:,.0f} SF  ·  "
                            f"District: {_primary_zone}  ·  "
                            f"Max buildable: {_la_v * _zrules['base_far']:,.0f} SF "
                            f"(FAR {_zrules['base_far']})"
                        )

                        _mass_key = f"_massing_{_bbl_disp}"
                        if _mass_key not in st.session_state:
                            st.session_state[_mass_key] = build_massing_options(
                                _lf_v, _ld_v, _la_v, _primary_zone, _zrules
                            )
                        _options = st.session_state.get(_mass_key, [])

                        if _options:
                            _mcols = st.columns(len(_options))
                            for _mc, _opt in zip(_mcols, _options):
                                with _mc:
                                    st.markdown(f"**{_opt['name']}**")
                                    st.plotly_chart(
                                        _opt["fig"],
                                        use_container_width=True,
                                        config={"displayModeBar": False},
                                        key=f"mass_{_opt['name'].replace(' ','_')}",
                                    )
                                    _m1, _m2 = st.columns(2)
                                    with _m1:
                                        st.metric("Total Area",   f"{_opt['total_sqft']:,} SF")
                                        st.metric("Floors",        str(_opt["floors"]))
                                    with _m2:
                                        st.metric("Floor Plate",  f"{_opt['typical_floor_sqft']:,} SF")
                                        st.metric("Height",       f"{_opt['height_ft']} ft")
                                    st.caption(_opt["description"])
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

        # ── Photo Gallery ──────────────────────────────────────────────────
        photos_available = [l for l in listings if l.get("photos")]
        if photos_available:
            st.markdown("---")
            st.markdown(
                "<div style='font-size:0.72rem;font-weight:700;letter-spacing:0.08em;"
                "text-transform:uppercase;color:#6B7280;margin-bottom:12px'>🖼️ Photo Gallery</div>",
                unsafe_allow_html=True,
            )
            st.caption(f"{len(photos_available)} listings have photos available.")

            cols_per_row = 3
            rows = [
                photos_available[i : i + cols_per_row]
                for i in range(0, min(len(photos_available), 24), cols_per_row)
            ]
            for row_items in rows:
                cols = st.columns(cols_per_row)
                for col, listing in zip(cols, row_items):
                    photo_url = listing["photos"][0] if listing["photos"] else None
                    if not photo_url:
                        continue
                    rent_label = f"${listing.get('rent', 0):,.0f}/mo"
                    utype      = listing.get("unit_type", "")
                    addr       = listing.get("address", "")[:45]
                    src        = listing.get("source", "")
                    list_url   = listing.get("url", "")
                    with col:
                        st.markdown(f"""
                        <div class="photo-card">
                          <img src="{photo_url}" alt="{addr}"
                               onerror="this.style.display='none'"/>
                          <div class="photo-caption">
                            <b>{rent_label}</b> · {utype}<br>
                            {addr}<br>
                            <span style="color:#9CA3AF">{src}</span>
                            {"&nbsp;·&nbsp;<a href='" + list_url + "' target='_blank' style='color:#1A3A6B;font-weight:600'>View →</a>" if list_url else ""}
                          </div>
                        </div>
                        """, unsafe_allow_html=True)

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
  NYC Rent Comp Analyzer · Inputs, Geocoding &amp; Interactive Map ·
  For internal real estate diligence use only · Not financial advice
</div>
""", unsafe_allow_html=True)

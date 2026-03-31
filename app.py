"""
NYC Rent Comp Analyzer
Stage 1: Input collection + geocoding + NYC context
"""

import os
import time
import requests
import streamlit as st
import folium
from folium.plugins import MiniMap
from streamlit_folium import st_folium
from dotenv import load_dotenv

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
</style>
""", unsafe_allow_html=True)

# ═════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═════════════════════════════════════════════════════════════════════════════

RADIUS_OPTIONS = {
    "2 blocks  (~0.10 mi)": 0.10,
    "3 blocks  (~0.15 mi)": 0.15,
    "5 blocks  (~0.25 mi)": 0.25,
    "Custom…": None,
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
    rentcast_key = st.text_input(
        "Rentcast API Key  *(Stage 2)*",
        value=os.getenv("RENTCAST_API_KEY", ""),
        type="password",
        help="Required in Stage 2 to pull live NYC rental listings. "
             "Free tier at rentcast.io.",
    )
    rapidapi_key = st.text_input(
        "RapidAPI Key  *(Stage 2)*",
        value=os.getenv("RAPIDAPI_KEY", ""),
        type="password",
        help="Required in Stage 2 for supplemental Zillow data. "
             "Subscribe to 'Zillow Com1' at rapidapi.com.",
    )

    st.divider()
    st.markdown("### 📖 How to use")
    st.caption(
        "**Stage 1 (now):** Enter an address, pick a radius, set filters — "
        "the app geocodes the location and shows borough, neighborhood, ZIP.\n\n"
        "**Stage 2 (coming):** Live rental listings, rent stats, map, charts, "
        "photo gallery, and market insights."
    )
    st.divider()
    st.markdown("### 🔗 Get API keys")
    st.markdown(
        "- [Google Maps Platform](https://console.cloud.google.com) *(optional)*\n"
        "- [Rentcast.io](https://rentcast.io) *(Stage 2)*\n"
        "- [RapidAPI](https://rapidapi.com) *(Stage 2)*"
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

    # ── Persist result in session state (for Stage 2) ────────────────────────
    st.session_state["geo"]          = geo
    st.session_state["radius_miles"] = radius_miles
    st.session_state["unit_filter"]  = selected_units or UNIT_TYPES
    st.session_state["rental_type"]  = rental_type
    st.session_state["address_raw"]  = address_input.strip()

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

    # ── Next-step callout ─────────────────────────────────────────────────────
    st.markdown("""
    <div class="next-step">
      ⏳ <b>Data collection coming next:</b> live rental listings from Rentcast
      and Zillow will be plotted on this map once Stage 2 is wired in.
      Add your <b>Rentcast</b> and <b>RapidAPI</b> keys in the sidebar to be ready.
    </div>
    """, unsafe_allow_html=True)

# ── Idle state ────────────────────────────────────────────────────────────────
elif not submitted:
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

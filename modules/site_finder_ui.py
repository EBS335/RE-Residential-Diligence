"""
Site Finder — NYC Development Site Sourcing, Screening & Initial Diligence.

Renders the "🔍 Site Finder" tab: an Investment Criteria form that bulk-
searches NYC PLUTO for candidate development sites, scores/ranks them,
and lets the user drill into a lightweight preliminary diligence view for
any result — all without disturbing the existing single-property
"🏢 Property Analysis" tab.

This is an initial feasibility / sourcing tool, not a substitute for
legal, zoning, environmental, title, engineering, appraisal, or other
professional diligence.
"""

from __future__ import annotations
import pandas as pd
import streamlit as st
import pydeck as pdk
from pydeck.data_utils import compute_view

from modules.property_search import search_properties, BOROUGH_CODES, PROPERTY_TYPE_LANDUSE
from modules.site_sourcing import enrich_property, flag_assemblage_candidates, STRATEGY_VACANT, STRATEGY_DEMOLITION, STRATEGY_CONVERSION
from modules.deal_scorer import compute_bulk_deal_scores
from modules.zoning_rules import get_zoning_rules, get_zoning_citations
from modules.zola_fetcher import bbl_to_zola_url
from modules.acris_fetcher import fetch_acris
from modules.ownership_research import enrich_ownership_batch, DEFAULT_BATCH_SIZE
from modules.site_finder_market import enrich_market_data, fetch_market_comps
from modules.site_finder_valuation import estimate_acquisition_cost
from modules.underwriting_engine import (
    build_scenarios, build_cash_flows, simple_sponsor_returns, lp_gp_waterfall,
    run_sensitivity, DEFAULT_HOLD_YEARS_POST_STAB, DEFAULT_RENT_GROWTH_PCT,
    DEFAULT_EXPENSE_GROWTH_PCT, DEFAULT_EXIT_CAP_SPREAD_BPS, DEFAULT_SELLING_COST_PCT,
    DEFAULT_CONSTRUCTION_LTC, DEFAULT_CONSTRUCTION_RATE, DEFAULT_PERM_LTV,
    DEFAULT_PERM_DSCR_MIN, DEFAULT_PERM_RATE, DEFAULT_PERM_AMORT_YEARS,
    DEFAULT_PREFERRED_RETURN_PCT, DEFAULT_PROMOTE_TIERS, DEFAULT_GP_CO_INVEST_PCT,
)
from modules.report_exporter import build_excel_workbook, build_pdf_report, build_pptx_report
from modules.site_finder_agents import (
    run_all_agents, has_anthropic_key, AGENT_ORDER,
)

_SF_PREFIX = "_sf_"   # session-state key namespace, isolated from the existing tab


# ── Investment Criteria form ────────────────────────────────────────────────

def _render_criteria_form() -> dict | None:
    st.markdown("### 📋 Investment Criteria")
    st.caption(
        "Enter as many or as few criteria as you like — every field is optional. "
        "The search runs against live NYC PLUTO data (no API key required)."
    )

    with st.form("site_finder_criteria_form", border=False):
        with st.expander("📍 Geography", expanded=True):
            g1, g2 = st.columns(2)
            with g1:
                boroughs = st.multiselect(
                    "Boroughs", options=list(BOROUGH_CODES.keys()),
                    default=[], key=f"{_SF_PREFIX}boroughs",
                )
            with g2:
                zip_codes = st.text_input(
                    "ZIP codes (comma-separated)", value="",
                    key=f"{_SF_PREFIX}zips",
                    placeholder="e.g. 11201, 11238",
                )

        with st.expander("💰 Acquisition Parameters", expanded=False):
            a1, a2, a3 = st.columns(3)
            with a1:
                min_price = st.number_input("Min purchase price ($)", min_value=0, value=0, step=100_000, key=f"{_SF_PREFIX}minprice")
            with a2:
                max_price = st.number_input("Max purchase price ($)", min_value=0, value=0, step=100_000, key=f"{_SF_PREFIX}maxprice")
            with a3:
                target_psf = st.number_input("Target price/SF ($)", min_value=0, value=0, step=25, key=f"{_SF_PREFIX}targetpsf")

        with st.expander("🏗️ Development Parameters", expanded=False):
            d1, d2, d3 = st.columns(3)
            with d1:
                min_lot_sf = st.number_input("Min lot SF", min_value=0, value=0, step=500, key=f"{_SF_PREFIX}minlot")
                min_far = st.number_input("Min FAR", min_value=0.0, value=0.0, step=0.5, key=f"{_SF_PREFIX}minfar")
            with d2:
                max_lot_sf = st.number_input("Max lot SF", min_value=0, value=0, step=500, key=f"{_SF_PREFIX}maxlot")
                max_far = st.number_input("Max FAR", min_value=0.0, value=0.0, step=0.5, key=f"{_SF_PREFIX}maxfar")
            with d3:
                min_units = st.number_input("Min residential units", min_value=0, value=0, step=1, key=f"{_SF_PREFIX}minunits")
                max_units = st.number_input("Max residential units", min_value=0, value=0, step=1, key=f"{_SF_PREFIX}maxunits")

        with st.expander("🏢 Property Type & Strategy", expanded=False):
            p1, p2 = st.columns(2)
            with p1:
                property_types = st.multiselect(
                    "Property type", options=list(PROPERTY_TYPE_LANDUSE.keys()),
                    default=["Any"], key=f"{_SF_PREFIX}ptypes",
                )
            with p2:
                strategies = st.multiselect(
                    "Development strategy",
                    options=[STRATEGY_VACANT, STRATEGY_DEMOLITION, STRATEGY_CONVERSION],
                    default=[], key=f"{_SF_PREFIX}strategies",
                    help="Filter results to properties matching these sourcing heuristics. Leave blank for all.",
                )

        with st.expander("⚖️ Risk Tolerance", expanded=False):
            risk = st.select_slider(
                "Risk tolerance", options=["Low", "Moderate", "High"], value="Moderate",
                key=f"{_SF_PREFIX}risk",
            )

        sv1, sv2 = st.columns([1, 2])
        with sv1:
            save_this = st.checkbox("💾 Save this search", key=f"{_SF_PREFIX}save_search_cb")
        with sv2:
            search_name = st.text_input(
                "Search name", key=f"{_SF_PREFIX}save_search_name",
                placeholder="e.g. Brooklyn vacant lots, R6+",
                label_visibility="collapsed",
            )

        submitted = st.form_submit_button("🔎 Search NYC Development Sites", type="primary", use_container_width=True)

    if not submitted:
        return None

    criteria = {
        "boroughs":            boroughs,
        "zip_codes":           [z.strip() for z in zip_codes.split(",") if z.strip()],
        "min_price":           min_price or None,
        "max_price":           max_price or None,
        "target_psf":          target_psf or None,
        "min_lot_sf":          min_lot_sf or None,
        "max_lot_sf":          max_lot_sf or None,
        "min_far":             min_far or None,
        "max_far":             max_far or None,
        "min_units":           min_units or None,
        "max_units":           max_units or None,
        "property_types":      [p for p in property_types if p != "Any"],
        "strategies":          strategies,
        "risk":                risk,
    }

    if save_this and search_name.strip():
        from modules.portfolio_db import save_search
        save_search(search_name.strip(), criteria)
        st.toast(f"Saved search “{search_name.strip()}” — find it in the 📁 Portfolio tab.", icon="💾")

    return criteria


def load_saved_criteria_into_widgets(criteria: dict) -> None:
    """
    Pre-seed the Investment Criteria form's widget session_state from a
    saved-search criteria dict (the same shape _render_criteria_form()
    returns), so the form reflects the saved values the next time it
    renders. Called from the Portfolio tab's "▶ Re-run" action — Streamlit
    tabs can't be switched programmatically the way multipage apps can, so
    the realistic flow is: load criteria here, then the user clicks over
    to the 🔍 Site Finder tab themselves and the form is already populated.
    """
    criteria = criteria or {}
    st.session_state[f"{_SF_PREFIX}boroughs"] = criteria.get("boroughs") or []
    st.session_state[f"{_SF_PREFIX}zips"] = ", ".join(criteria.get("zip_codes") or [])
    st.session_state[f"{_SF_PREFIX}minprice"] = criteria.get("min_price") or 0
    st.session_state[f"{_SF_PREFIX}maxprice"] = criteria.get("max_price") or 0
    st.session_state[f"{_SF_PREFIX}targetpsf"] = criteria.get("target_psf") or 0
    st.session_state[f"{_SF_PREFIX}minlot"] = criteria.get("min_lot_sf") or 0
    st.session_state[f"{_SF_PREFIX}maxlot"] = criteria.get("max_lot_sf") or 0
    st.session_state[f"{_SF_PREFIX}minfar"] = criteria.get("min_far") or 0.0
    st.session_state[f"{_SF_PREFIX}maxfar"] = criteria.get("max_far") or 0.0
    st.session_state[f"{_SF_PREFIX}minunits"] = criteria.get("min_units") or 0
    st.session_state[f"{_SF_PREFIX}maxunits"] = criteria.get("max_units") or 0
    st.session_state[f"{_SF_PREFIX}ptypes"] = criteria.get("property_types") or ["Any"]
    st.session_state[f"{_SF_PREFIX}strategies"] = criteria.get("strategies") or []
    st.session_state[f"{_SF_PREFIX}risk"] = criteria.get("risk") or "Moderate"


# ── Search execution + scoring ──────────────────────────────────────────────

def _run_search(criteria: dict) -> tuple[list[dict], dict]:
    with st.spinner("Searching NYC PLUTO for matching parcels…"):
        raw_rows, status = search_properties(criteria)

    if status.get("error"):
        return [], status

    enriched = [enrich_property(r) for r in raw_rows]

    # Apply strategy filter (post-search, since it's a derived heuristic)
    if criteria.get("strategies"):
        wanted = set(criteria["strategies"])
        enriched = [p for p in enriched if wanted & set(p.get("strategies", []))]

    # Assessed value as a rough acquisition-price proxy for min/max price filters
    if criteria.get("min_price"):
        enriched = [p for p in enriched if p.get("assess_total", 0) >= criteria["min_price"]]
    if criteria.get("max_price"):
        enriched = [p for p in enriched if p.get("assess_total", 0) <= criteria["max_price"]]

    scored = compute_bulk_deal_scores(enriched)
    # Flag same-block/near-lot-number pairs WITHIN this result set as
    # assemblage candidates — run once over the full scored list here so
    # it's cached alongside `scored` itself (not recomputed on every rerun).
    scored = flag_assemblage_candidates(scored)
    return scored, status


# ── Summary cards ────────────────────────────────────────────────────────────

def _render_summary_cards(properties: list[dict]) -> None:
    n = len(properties)
    avg_far_gap = (
        sum(p.get("unused_far_pct", 0) for p in properties) / n if n else 0
    )
    vacant_count = sum(1 for p in properties if STRATEGY_VACANT in p.get("strategies", []))
    demo_count = sum(1 for p in properties if STRATEGY_DEMOLITION in p.get("strategies", []))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Properties Matched", f"{n:,}")
    c2.metric("Vacant/Underutilized Lots", f"{vacant_count:,}", f"{(vacant_count/n*100 if n else 0):.0f}% of results")
    c3.metric("Demolition Candidates", f"{demo_count:,}", f"{(demo_count/n*100 if n else 0):.0f}% of results")
    c4.metric("Avg. Unused FAR", f"{avg_far_gap:.0f}%")


# ── Results map ──────────────────────────────────────────────────────────────

_TIER_MARKER_COLOR = {
    "Strong Lead": [34, 197, 94],    # green
    "Watch":       [249, 115, 22],   # orange
    "Pass":        [156, 163, 175],  # gray
}
_DEFAULT_MARKER_COLOR = [59, 130, 246]  # blue fallback for an unrecognized tier


def _geojson_bounds(geojson: dict) -> list[list[float]] | None:
    """[[min_lat, min_lon], [max_lat, max_lon]] over every coordinate in a
    GeoJSON FeatureCollection (Polygon/MultiPolygon geometries — GeoJSON
    coordinate order is [lon, lat]). None if there are no usable coords."""
    lats: list[float] = []
    lons: list[float] = []

    def _walk(coords):
        if not coords:
            return
        # A coordinate pair is [number, number]; anything else is a nested list.
        if len(coords) == 2 and all(isinstance(c, (int, float)) for c in coords):
            lons.append(coords[0])
            lats.append(coords[1])
            return
        for c in coords:
            _walk(c)

    for feature in geojson.get("features", []):
        _walk((feature.get("geometry") or {}).get("coordinates"))

    if not lats or not lons:
        return None
    return [[min(lats), min(lons)], [max(lats), max(lons)]]


def _fetch_search_extent_boundary(criteria: dict | None) -> tuple[dict | None, bool]:
    """
    Fetch (and session_state-cache, since Streamlit reruns the whole
    script on every interaction) the boundary GeoJSON for the geographic
    filter in `criteria` — ZIP codes take priority over boroughs when
    both are set (a ZIP-level search is a tighter, more specific extent).
    Returns (geojson_or_None, ok) — see modules/nyc_boundaries.py for the
    exact contract. (None, True) means no geographic filter was set (an
    unfiltered citywide search has no single extent to draw), not a
    failure.
    """
    if not criteria:
        return None, True

    zip_codes = criteria.get("zip_codes") or []
    boroughs = criteria.get("boroughs") or []

    if zip_codes:
        cache_key = f"{_SF_PREFIX}boundary_zip_{tuple(sorted(zip_codes))}"
        kind, names = "zip", zip_codes
    elif boroughs:
        cache_key = f"{_SF_PREFIX}boundary_boro_{tuple(sorted(boroughs))}"
        kind, names = "borough", boroughs
    else:
        return None, True

    if cache_key in st.session_state:
        return st.session_state[cache_key]

    from modules.nyc_boundaries import fetch_zip_boundaries, fetch_borough_boundaries
    fetch_fn = fetch_zip_boundaries if kind == "zip" else fetch_borough_boundaries
    result = fetch_fn(names)
    st.session_state[cache_key] = result
    return result


def _render_results_map(properties: list[dict], criteria: dict | None = None) -> None:
    """
    Flag results via st.pydeck_chart() — a NATIVE Streamlit element (same
    rendering family as st.dataframe/st.line_chart), not a third-party
    custom component. This replaces a folium/streamlit_folium
    implementation that, across 6+ fix attempts (removing display caps,
    swapping st_folium<->folium_static, matching every kwarg convention
    used by this app's other working folium maps, reordering tabs so
    this map was first instead of second), consistently rendered ZERO
    visible footprint — not even a reserved blank area. Every one of
    those attempts stayed within the same technical family: folium
    rendered through Streamlit's custom-component/iframe bridge (whether
    st_folium's bidirectional component or folium_static's
    components.html() embed). Since swapping between every variant
    *within* that family made no difference, AND tab position (the one
    variable that had been unique to this map vs. the working Property
    Analysis maps) also made no difference once tested, the one thing
    shared across every failure — the custom-component/iframe bridge
    itself — is the best-evidenced remaining cause. st.pydeck_chart()
    sidesteps that whole class of failure rather than trying another
    variant within it; pydeck ships as a core Streamlit dependency
    (already installed, zero new dependency).

    Draws an outline of the actual borough/ZIP search extent
    (modules/nyc_boundaries.py, unchanged) as a GeoJsonLayer when
    `criteria` carries a geographic filter, and auto-fits the view to
    that extent (or to the markers themselves, if no boundary is
    available) via pydeck.data_utils.compute_view() — pydeck's own
    fit-to-bounds helper, replacing folium's fit_bounds().

    Plots every geolocated result — no display cap. deck.gl's
    ScatterplotLayer is GPU-rendered and handles thousands of points
    natively (unlike the old Leaflet/folium map, which is documented to
    fail entirely above ~3000 markers — the reason a cap existed at all
    previously; that risk doesn't apply to this rendering path).
    """
    located = [p for p in properties if p.get("latitude") and p.get("longitude")]
    missing = len(properties) - len(located)

    if not located:
        st.caption("No coordinates available to plot for these results.")
        return

    map_hdr, map_toggle = st.columns([3, 1])
    with map_hdr:
        st.markdown("#### 🗺️ Map View")
    with map_toggle:
        map_view_choice = st.radio(
            "View", ["Standard", "Satellite"], horizontal=True, label_visibility="collapsed",
            key=f"{_SF_PREFIX}map_style_choice",
        )
    map_style = "satellite" if map_view_choice == "Satellite" else "light"

    boundary_geojson, boundary_ok = _fetch_search_extent_boundary(criteria)
    boundary_requested = bool(criteria and (criteria.get("zip_codes") or criteria.get("boroughs")))

    layers = []
    if boundary_geojson:
        layers.append(pdk.Layer(
            "GeoJsonLayer",
            data=boundary_geojson,
            stroked=True, filled=True,
            get_fill_color=[29, 78, 216, 15],
            get_line_color=[29, 78, 216, 220],
            line_width_min_pixels=2,
        ))

    marker_rows = []
    for p in located:
        ds = p.get("deal_score", {})
        color = _TIER_MARKER_COLOR.get(ds.get("tier"), _DEFAULT_MARKER_COLOR)
        marker_rows.append({
            "lon": p["longitude"], "lat": p["latitude"],
            "color": color,
            "address": p.get("address", ""),
            "score": ds.get("score", "—"),
            "tier": ds.get("tier", "—"),
            "strategy": ", ".join(p.get("strategies", [])) or "—",
            "bbl": p.get("bbl", ""),
        })
    layers.append(pdk.Layer(
        "ScatterplotLayer",
        data=marker_rows,
        get_position="[lon, lat]",
        get_fill_color="color",
        get_radius=45, radius_min_pixels=5, radius_max_pixels=14,
        pickable=True, auto_highlight=True,
        stroked=True, get_line_color=[255, 255, 255], line_width_min_pixels=1,
    ))

    # Auto-fit the view to the actual extent instead of a fixed zoom level
    # — prefer the search-area boundary's own vertices so the view frames
    # the searched area, falling back to the plotted markers' positions
    # otherwise. compute_view() wants [lon, lat] points (deck.gl order);
    # _geojson_bounds() returns [lat, lon]-ordered corners, so swap here.
    fit_points = None
    if boundary_geojson:
        boundary_bounds = _geojson_bounds(boundary_geojson)
        if boundary_bounds:
            fit_points = [[lon, lat] for lat, lon in boundary_bounds]
    if not fit_points:
        fit_points = [[p["longitude"], p["latitude"]] for p in located]
    view_state = compute_view(fit_points)

    st.pydeck_chart(
        pdk.Deck(
            layers=layers,
            initial_view_state=view_state,
            map_style=map_style,
            tooltip={"html": "<b>{address}</b><br/>Deal Score: {score}/100 ({tier})<br/>Strategy: {strategy}"},
        ),
        width="stretch", height=420,
    )
    legend = " · ".join(
        f"🟢 {t}" if t == "Strong Lead" else (f"🟠 {t}" if t == "Watch" else f"⚪ {t}")
        for t in _TIER_MARKER_COLOR
    )
    caption = legend
    if boundary_geojson:
        caption += " · shaded outline = search area"
    elif boundary_requested and not boundary_ok:
        caption += " · search-area outline unavailable this time (boundary data source unreachable)"
    if missing:
        caption += f" · {missing:,} of {len(properties):,} results have no coordinates and are not plotted"
    st.caption(caption)


# ── Results table ────────────────────────────────────────────────────────────

def _apply_ownership_cache(top: list[dict]) -> list[dict]:
    """Overlay any previously-fetched ownership enrichment onto `top`."""
    cache = st.session_state.get(f"{_SF_PREFIX}ownership_cache", {})
    if not cache:
        return top
    return [cache.get(p["bbl"], p) for p in top]


def _current_conditions(p: dict) -> str:
    """Compose a 'what's currently on the site' summary from already-fetched
    PLUTO fields — no extra fetch. Primary signal is PLUTO's own official
    land-use category; unit count/year built are appended when present."""
    parts = [p.get("landuse_label") or "Unknown"]
    units = p.get("units_res", 0)
    if units:
        parts.append(f"{int(units)} units")
    yb = p.get("year_built", "")
    if yb:
        parts.append(f"built {yb}")
    return " · ".join(parts)


_LOT_POSITION_LABELS = {
    "Corner":   "Corner",
    "Through":  "Through Lot",
    "Interior": "Mid-Block",
}


def _lot_position_label(lot_type: str) -> str:
    return _LOT_POSITION_LABELS.get(lot_type, "—")


def _rent_stab_label(signal: dict) -> str:
    if not signal:
        return "—"
    if signal.get("verified") and signal.get("likely_stabilized"):
        return "✅ Confirmed"
    if signal.get("likely_stabilized"):
        return "🟡 Likely (est.)"
    return "—"


def _render_filter_panel(properties: list[dict]) -> list[dict]:
    """
    Client-side filter panel narrowing the already-fetched results list
    for display (summary cards, map, table, exports, row-selection) — no
    re-query against PLUTO. Deliberately does NOT affect assemblage
    flagging (computed once over the full unfiltered set in
    _run_search()) — two lots' physical adjacency is a fact independent
    of which filters happen to be applied for display right now.

    Options/ranges are computed dynamically from what's actually present
    in `properties` so an untouched filter never excludes anything.
    """
    if not properties:
        return properties

    landuse_options = sorted({p.get("landuse_label") or "Unknown" for p in properties})
    location_options = sorted({_lot_position_label(p.get("lot_type", "—")) for p in properties})
    strategy_options = sorted({s for p in properties for s in p.get("strategies", [])})

    lot_sf_vals = [p.get("lot_sf", 0) or 0 for p in properties]
    far_built_vals = [p.get("far_built", 0) or 0 for p in properties]
    far_max_vals = [p.get("far_max", 0) or 0 for p in properties]
    lot_sf_lo, lot_sf_hi = (min(lot_sf_vals), max(lot_sf_vals)) if lot_sf_vals else (0.0, 0.0)
    far_built_lo, far_built_hi = (min(far_built_vals), max(far_built_vals)) if far_built_vals else (0.0, 0.0)
    far_max_lo, far_max_hi = (min(far_max_vals), max(far_max_vals)) if far_max_vals else (0.0, 0.0)

    with st.expander("🔎 Filter Results", expanded=False):
        r1c1, r1c2, r1c3, r1c4 = st.columns(4)
        with r1c1:
            street_query = st.text_input(
                "Street/Avenue", key=f"{_SF_PREFIX}filter_street", placeholder="e.g. Broadway",
            )
        with r1c2:
            conditions_sel = st.multiselect(
                "Current Conditions", options=landuse_options, key=f"{_SF_PREFIX}filter_conditions",
            )
        with r1c3:
            location_sel = st.multiselect(
                "Location", options=location_options, key=f"{_SF_PREFIX}filter_location",
            )
        with r1c4:
            strategy_sel = st.multiselect(
                "Strategy", options=strategy_options, key=f"{_SF_PREFIX}filter_strategy",
            )

        r2c1, r2c2, r2c3, r2c4 = st.columns(4)
        with r2c1:
            lot_sf_min = st.number_input("Min Lot SF", min_value=0.0, value=float(lot_sf_lo), step=500.0, key=f"{_SF_PREFIX}filter_lotsf_min")
            lot_sf_max = st.number_input("Max Lot SF", min_value=0.0, value=float(lot_sf_hi), step=500.0, key=f"{_SF_PREFIX}filter_lotsf_max")
        with r2c2:
            far_built_min = st.number_input("Min Built FAR", min_value=0.0, value=float(far_built_lo), step=0.1, key=f"{_SF_PREFIX}filter_farbuilt_min")
            far_built_max = st.number_input("Max Built FAR", min_value=0.0, value=float(far_built_hi), step=0.1, key=f"{_SF_PREFIX}filter_farbuilt_max")
        with r2c3:
            far_max_min = st.number_input("Min Max FAR", min_value=0.0, value=float(far_max_lo), step=0.1, key=f"{_SF_PREFIX}filter_farmax_min")
            far_max_max = st.number_input("Max Max FAR", min_value=0.0, value=float(far_max_hi), step=0.1, key=f"{_SF_PREFIX}filter_farmax_max")
        with r2c4:
            rent_stab_sel = st.selectbox(
                "Rent Stabilized", options=["Any", "Confirmed only", "Confirmed or Likely"],
                key=f"{_SF_PREFIX}filter_rentstab",
            )

        filtered = []
        for p in properties:
            if street_query and street_query.strip().lower() not in (p.get("address", "") or "").lower():
                continue
            if conditions_sel and (p.get("landuse_label") or "Unknown") not in conditions_sel:
                continue
            if location_sel and _lot_position_label(p.get("lot_type", "—")) not in location_sel:
                continue
            if strategy_sel and not (set(p.get("strategies", [])) & set(strategy_sel)):
                continue
            lot_sf = p.get("lot_sf", 0) or 0
            if not (lot_sf_min <= lot_sf <= lot_sf_max):
                continue
            far_built = p.get("far_built", 0) or 0
            if not (far_built_min <= far_built <= far_built_max):
                continue
            far_max = p.get("far_max", 0) or 0
            if not (far_max_min <= far_max <= far_max_max):
                continue
            if rent_stab_sel != "Any":
                rs = p.get("rent_stab_signal") or {}
                if rent_stab_sel == "Confirmed only":
                    if not (rs.get("verified") and rs.get("likely_stabilized")):
                        continue
                elif rent_stab_sel == "Confirmed or Likely":
                    if not rs.get("likely_stabilized"):
                        continue
            filtered.append(p)

        st.caption(f"Showing {len(filtered):,} of {len(properties):,} results")

    return filtered


def _render_results_table(properties: list[dict], criteria: dict | None = None) -> None:
    if not properties:
        st.info("No properties matched your criteria. Try widening the search (fewer filters, larger area).")
        return

    # Full result set (no display cap) — Streamlit's dataframe/map both
    # handle large row counts natively; the upstream Socrata fetch already
    # caps at property_search._MAX_ROWS (3000) so this isn't unbounded.
    results_full = _apply_ownership_cache(properties)

    # Client-side filter panel narrows what's displayed everywhere below
    # (summary cards, map, table, exports, row-selection) — it does NOT
    # affect assemblage flagging, which stays computed over the full
    # unfiltered set (see _render_filter_panel()'s docstring).
    results_full = _render_filter_panel(results_full)

    _render_summary_cards(results_full)
    st.markdown("---")

    _render_results_map(results_full, criteria)
    st.markdown("---")

    has_ownership = any("owner_type" in p for p in results_full)

    oc1, oc2 = st.columns([3, 1])
    with oc1:
        st.caption(
            "Owner/ACRIS/DOB-HPD distress data is fetched live per property and is "
            f"limited to the top {DEFAULT_BATCH_SIZE} results (by Deal Score) to keep searches fast."
        )
    with oc2:
        if st.button("🔍 Enrich Top 25 with Ownership", use_container_width=True):
            progress = st.progress(0.0, text="Fetching ownership & ACRIS data…")

            def _cb(i, n):
                progress.progress(i / n, text=f"Fetching ownership & ACRIS data… ({i}/{n})")

            # enrich_ownership_batch() only live-fetches its own internal
            # batch_size (DEFAULT_BATCH_SIZE) slice and returns the rest of
            # results_full unchanged — safe to pass the full (unsliced) list.
            enriched_results = enrich_ownership_batch(results_full, progress_callback=_cb)
            progress.empty()
            cache = st.session_state.get(f"{_SF_PREFIX}ownership_cache", {})
            for p in enriched_results:
                cache[p["bbl"]] = p
            st.session_state[f"{_SF_PREFIX}ownership_cache"] = cache
            st.rerun()

    rows = []
    for i, p in enumerate(results_full, start=1):
        ds = p["deal_score"]
        row = {
            "Rank":        i,
            "Address":     p["address"],
            "Borough":     p["borough"],
            "Current Conditions": _current_conditions(p),
            "Lot SF":      f"{p['lot_sf']:,.0f}",
            "Built FAR":   f"{p['far_built']:.2f}",
            "Max FAR":     f"{p['far_max']:.2f}",
            "Unused FAR %": f"{p['unused_far_pct']:.0f}%",
            "Location":    _lot_position_label(p.get("lot_type", "—")),
            "Strategy":    ", ".join(p.get("strategies", [])) or "—",
        }
        if has_ownership:
            row["Owner"] = p.get("owner", "") or "—"
            row["Owner Type"] = p.get("owner_type", "—")
            sale = p.get("last_sale_price")
            row["Last Sale"] = f"${sale:,.0f}" if sale else "—"
        if p.get("owner_type"):
            # Truthiness, not key-presence: PLUTO's own `ownertype` field is
            # always present (usually blank) on every property, so a key
            # check would incorrectly read as "already enriched" for every
            # unenriched row too. ACRIS enrichment always sets a non-empty
            # classified value (detect_owner_type() never returns "").
            # Enriched — distinguish "checked cleanly" from "checked, but
            # the underlying ACRIS/DOB-HPD fetch had an issue" so a real
            # error doesn't look identical to a genuinely clean record.
            _err = p.get("acris_error") or p.get("pip_error")
            row["Distress"] = (
                f"⚠️ {p.get('distress_signal', 'No Signal')} (check error)" if _err
                else p.get("distress_signal", "No Signal")
            )
        else:
            row["Distress"] = f"{p.get('distress_signal', 'No Signal')} (not yet checked)"
        row["Rent Stab."] = _rent_stab_label(p.get("rent_stab_signal", {}))
        assemblage = p.get("assemblage_with") or []
        row["Assemblage"] = ("🔗 " + "; ".join(assemblage)) if assemblage else "—"
        row["Deal Score"] = ds["score"]
        row["Tier"] = ds["tier"]
        rows.append(row)

    df = pd.DataFrame(rows)
    st.markdown(f"**{len(results_full):,} results**, ranked by Deal Score")
    st.caption("🔬 Click a row to select it for Preliminary Diligence.")
    table_state = st.dataframe(
        df, width="stretch", hide_index=True,
        height=min(560, 60 + 35 * len(rows)),
        column_config={
            "Deal Score": st.column_config.ProgressColumn(
                "Deal Score", min_value=0, max_value=100, format="%d"
            ),
        },
        on_select="rerun",
        selection_mode="single-row",
        key=f"{_SF_PREFIX}results_table",
    )

    # Row-click selection replaces the old separate dropdown+button —
    # mirrors app.py's already-proven underbuilt-lots table pattern
    # (on_select="rerun", selection_mode="single-row", then
    # .selection.rows[0] as a positional index into the source list).
    selected_rows = getattr(getattr(table_state, "selection", None), "rows", [])
    if selected_rows:
        _sel_prop = results_full[selected_rows[0]]
        st.markdown(f"**Selected:** {_sel_prop['address']} (BBL {_sel_prop['bbl']})")
        if st.button("🔬 Open Preliminary Diligence →", type="primary", key=f"{_SF_PREFIX}open_diligence_btn"):
            st.session_state[f"{_SF_PREFIX}selected_bbl"] = _sel_prop["bbl"]
            st.session_state[f"{_SF_PREFIX}selected_prop"] = _sel_prop
            st.rerun()

    st.markdown("---")
    st.markdown("#### ☆ Save to Portfolio")
    options = ["— Select a property —"] + [
        f"{i}. {p['address']} (BBL {p['bbl']})" for i, p in enumerate(results_full, start=1)
    ]
    save_choice = st.selectbox("Choose a result to save", options=options, key=f"{_SF_PREFIX}save_choice")
    if save_choice != options[0]:
        save_idx = options.index(save_choice) - 1
        if st.button("☆ Save to Portfolio", key=f"{_SF_PREFIX}save_btn"):
            from modules.portfolio_db import save_property
            save_property(results_full[save_idx], status="Watching")
            st.success(f"Saved {results_full[save_idx]['address']} to Portfolio.")

    st.markdown("---")
    st.markdown("#### ⬇️ Export")
    ex1, ex2 = st.columns(2)
    with ex1:
        st.download_button(
            "⬇️ Export results to CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name="site_finder_results.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with ex2:
        if st.button("📊 Build Excel workbook", use_container_width=True):
            try:
                xlsx_bytes = build_excel_workbook(results_full)
                st.session_state[f"{_SF_PREFIX}xlsx_bytes"] = xlsx_bytes
            except ImportError as exc:
                st.error(str(exc))
        if st.session_state.get(f"{_SF_PREFIX}xlsx_bytes"):
            st.download_button(
                "Download Excel workbook",
                data=st.session_state[f"{_SF_PREFIX}xlsx_bytes"],
                file_name="site_finder_results.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )


# ── Property detail (lightweight, self-contained — does not call the ──────
# ── existing 4,000-line Property Analysis flow, to avoid any risk of ──────
# ── disturbing it) ──────────────────────────────────────────────────────────

def _render_site_building_summary(prop: dict) -> None:
    """Plain-language 'what is this site, right now' orientation block —
    every field here is already on `prop` from PLUTO/enrich_property(), no
    extra fetch. Sits above the score cards so a reader gets bearings on
    the physical site/building before diving into scores and expanders."""
    st.markdown("#### 🏠 Site & Building Summary")

    bcol, zcol = st.columns(2)

    with bcol:
        st.markdown("**Building**")
        st.markdown(f"- Current use: {_current_conditions(prop)}")
        bldg_class = prop.get("bldg_class")
        st.markdown(f"- Building class: {bldg_class or '—'}")
        floors = prop.get("num_floors") or 0
        st.markdown(f"- Floors: {int(floors) if floors else '—'}")
        bldg_sf = prop.get("bldg_sf") or 0
        st.markdown(f"- Building SF: {bldg_sf:,.0f}" if bldg_sf else "- Building SF: —")
        units_total = prop.get("units_total") or 0
        units_res = prop.get("units_res") or 0
        if units_total:
            st.markdown(f"- Units: {int(units_total)} total ({int(units_res)} residential)")
        else:
            st.markdown("- Units: —")

    with zcol:
        st.markdown("**Site & Zoning**")
        lot_sf = prop.get("lot_sf") or 0
        st.markdown(f"- Lot SF: {lot_sf:,.0f}" if lot_sf else "- Lot SF: —")
        st.markdown(f"- Lot position: {_lot_position_label(prop.get('lot_type', ''))}")
        st.markdown(f"- Zoning district: {prop.get('zoning_dist') or '—'}")
        st.markdown(
            f"- FAR: {prop.get('far_built', 0):.2f} built of "
            f"{prop.get('far_max', 0):.2f} max ({prop.get('unused_far_pct', 0):.0f}% unused)"
        )
        st.markdown(f"- Owner: {prop.get('owner') or '—'} ({prop.get('owner_type') or 'Unknown type'})")

def _render_property_detail(prop: dict) -> None:
    if st.button("← Back to Results"):
        st.session_state.pop(f"{_SF_PREFIX}selected_bbl", None)
        st.session_state.pop(f"{_SF_PREFIX}selected_prop", None)
        for k in ("pdf_bytes", "pptx_bytes"):
            st.session_state.pop(f"{_SF_PREFIX}{k}", None)
        st.rerun()

    st.markdown(f"## {prop['address']}")
    st.caption(f"BBL {prop['bbl']} · {prop['borough']} · Block {prop['block']} · Lot {prop['lot']}")
    st.caption(
        "⚠️ Preliminary screening output only — not a zoning opinion, appraisal, "
        "title report, or substitute for professional diligence."
    )

    zola_url = bbl_to_zola_url(prop["bbl"])
    if zola_url:
        st.markdown(f"🔗 [View on ZOLA ↗]({zola_url})")

    _render_site_building_summary(prop)

    ds = prop["deal_score"]
    opp = prop["opportunity"]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Deal Score", f"{ds['score']}/100", ds["tier"])
    m2.metric("Opportunity Score", f"{opp['score']}/100", opp["tier"])
    m3.metric("Lot SF", f"{prop['lot_sf']:,.0f}")
    m4.metric("Unused FAR", f"{prop['unused_far_pct']:.0f}%")

    st.markdown("#### 🎯 Development Strategy Signals")
    for s in prop.get("strategies", []):
        st.markdown(f"- {s}")
    if not prop.get("strategies"):
        st.caption("No strong strategy signal from PLUTO alone.")

    st.markdown("#### 📊 Opportunity Score Drivers")
    for d in opp.get("drivers", []):
        st.markdown(f"- {d}")

    with st.expander("🏗️ Zoning Summary (calculated — confirm with NYC Planning)", expanded=True):
        zdist = prop.get("zoning_dist", "")
        rules = get_zoning_rules(zdist) if zdist else None
        cite  = get_zoning_citations(zdist) if zdist else None
        st.markdown(f"**Zoning District:** {zdist or '—'}")
        if rules:
            z1, z2, z3 = st.columns(3)
            z1.metric("Max FAR (zoning)", f"{rules.get('max_far', '—')}")
            z2.metric("Max Height (ft)", f"{rules.get('max_height_ft') or 'N/A'}")
            z3.metric("Lot Coverage %", f"{rules.get('lot_coverage_pct', '—')}")
            st.caption(rules.get("description", ""))
        else:
            st.caption("No static zoning rule match found for this district code — confirm via ZOLA.")
        if cite:
            st.caption(
                f"ZR Citations — FAR: {cite.get('far_citation', '—')} · "
                f"Height/Setback: {cite.get('height_citation', '—')}"
            )
            if cite.get("mih_eligible"):
                st.caption("📋 Mandatory Inclusionary Housing (MIH) may apply — confirm with NYC Planning.")
        st.markdown(
            f"**Built FAR:** {prop['far_built']:.2f} &nbsp;·&nbsp; "
            f"**Max Residential FAR (PLUTO):** {prop['far_residential']:.2f} &nbsp;·&nbsp; "
            f"**Max Commercial FAR (PLUTO):** {prop['far_commercial']:.2f}"
        )
        if prop.get("historic_dist"):
            st.warning(f"🏛️ Historic District: {prop['historic_dist']} — Landmarks Preservation Commission approval likely required.")
        if prop.get("landmark"):
            st.warning(f"🏛️ Landmark status flagged: {prop['landmark']}")

    with st.expander("👤 Ownership, ACRIS & Distress Signal", expanded=bool(prop.get("owner_type"))):
        if prop.get("owner_type"):
            # Already enriched via ownership_research (bulk button or per-property fetch below)
            _fetch_err = prop.get("acris_error") or prop.get("pip_error")
            if _fetch_err:
                st.warning(f"⚠️ One or more data sources failed during enrichment — signal below may be incomplete: {_fetch_err}")
            o1, o2, o3 = st.columns(3)
            sale_price = prop.get("last_sale_price")
            o1.metric("Last Sale", f"${sale_price:,.0f}" if sale_price else "—", prop.get("last_sale_date") or "")
            mtge = prop.get("active_mortgage_amt")
            o2.metric("Active Mortgage", f"${mtge:,.0f}" if mtge else "—")
            o3.metric("Open Liens", str(prop.get("open_liens", 0)))
            st.markdown(
                f"**Owner:** {prop.get('owner') or '—'} &nbsp;·&nbsp; "
                f"**Owner Type:** {prop.get('owner_type', 'Unknown')}"
            )
            dist = prop.get("distress", {})
            level = dist.get("level", prop.get("distress_signal", "No Signal"))
            _dist_color = {"No Signal": "🟢", "Weak Signal": "🟡", "Moderate Signal": "🟠", "Strong Signal": "🔴"}.get(level, "⚪")
            st.markdown(f"**Distress Signal:** {_dist_color} {level}")
            for ev in dist.get("evidence", []):
                st.caption(f"• {ev}")
            if prop.get("acris_url"):
                st.caption(f"[Full ACRIS history ↗]({prop['acris_url']})")
            if prop.get("pip_url"):
                st.caption(f"[NYC Property Information Portal ↗]({prop['pip_url']})")
        else:
            st.markdown(f"**PLUTO Owner of Record:** {prop.get('owner') or '—'}")
            if st.button("Fetch ACRIS ownership & distress for this property", key=f"{_SF_PREFIX}fetch_own_{prop['bbl']}"):
                with st.spinner("Fetching ACRIS + DOB/HPD data…"):
                    enriched = enrich_ownership_batch([prop], batch_size=1)[0]
                st.session_state[f"{_SF_PREFIX}selected_prop"] = enriched
                cache = st.session_state.get(f"{_SF_PREFIX}ownership_cache", {})
                cache[enriched["bbl"]] = enriched
                st.session_state[f"{_SF_PREFIX}ownership_cache"] = cache
                st.rerun()
            _acris_key = f"{_SF_PREFIX}acris_{prop['bbl']}"
            if _acris_key not in st.session_state:
                with st.spinner("Fetching ACRIS document history…"):
                    st.session_state[_acris_key] = fetch_acris(prop["bbl"])
            acris = st.session_state.get(_acris_key, {})
            summ = acris.get("summary", {}) if acris else {}
            acris_err = acris.get("error")
            if acris_err:
                st.warning(f"⚠️ ACRIS fetch had an issue — data may be incomplete: {acris_err}")
            elif summ.get("total_docs", 0) == 0:
                st.info("✅ Checked — no ACRIS transaction history found for this BBL.")
            else:
                a1, a2, a3 = st.columns(3)
                sale_price = summ.get("latest_sale_price")
                a1.metric("Last Sale", f"${sale_price:,.0f}" if sale_price else "—", summ.get("latest_sale_date", "—"))
                mtge = summ.get("active_mortgage_amt")
                a2.metric("Active Mortgage", f"${mtge:,.0f}" if mtge else "—")
                a3.metric("Open Liens", str(summ.get("open_liens", 0)))
                if acris.get("acris_url"):
                    st.caption(f"[Full ACRIS history ↗]({acris['acris_url']})")

    with st.expander("📐 Assessment (PLUTO)", expanded=False):
        st.markdown(
            f"**Assessed Land Value:** ${prop.get('assess_land', 0):,.0f} &nbsp;·&nbsp; "
            f"**Assessed Total Value:** ${prop.get('assess_total', 0):,.0f}"
        )
        basis_psf = (prop["assess_land"] / prop["lot_sf"]) if prop.get("lot_sf") else None
        if basis_psf:
            st.markdown(f"**Assessed Land Basis:** ${basis_psf:,.0f} / lot SF")

    with st.expander("📈 Market Comps & Competitive Pipeline", expanded=False):
        st.caption(
            "📰 Pipeline press coverage draws from each outlet's current RSS feed "
            "(Google News, The Real Deal, Commercial Observer, Bisnow) — typically the "
            "last few weeks to a few months of posts, not a full historical archive. "
            "NYC DOB permit filings (36-month window) are the more reliable historical signal."
        )
        if st.button("Fetch market comps & nearby pipeline", key=f"{_SF_PREFIX}fetch_market_{prop['bbl']}"):
            with st.spinner("Fetching NYC Rolling Sales comps & nearby development pipeline…"):
                mkt = enrich_market_data(prop)
            st.session_state[f"{_SF_PREFIX}selected_prop"] = mkt
            st.rerun()

        mc = prop.get("market_comps")
        pipe = prop.get("pipeline")

        if mc is not None:
            st.markdown("**Nearby Sales Comps (NYC Rolling Sales, same ZIP, sorted by distance where available)**")
            mc_status = mc.get("status", "")
            if mc_status == "no_zip_code":
                st.warning("⚠️ No ZIP code on record for this property — can't pull sales comps.")
            elif mc_status.startswith("error"):
                st.error(f"⚠️ NYC Rolling Sales fetch failed: {mc_status.split(':', 1)[-1].strip()}")
            elif mc_status == "no_results":
                st.info("✅ Checked — no matching sales found in this ZIP.")
            else:  # "live"
                mc1, mc2, mc3 = st.columns(3)
                mc1.metric("Median $/SF", f"${mc['median_price_psf']:,.0f}" if mc.get("median_price_psf") else "—")
                mc2.metric("Median Price", f"${mc['median_price']:,.0f}" if mc.get("median_price") else "—")
                mc3.metric("Comp Count", mc.get("count", 0))
                if mc.get("comps"):
                    comp_rows = [{
                        "Address": c.get("address", ""), "Price": c.get("price"),
                        "SF": c.get("sqft"), "$/SF": c.get("price_psf"), "Date": c.get("date"),
                    } for c in mc["comps"][:15]]
                    st.dataframe(pd.DataFrame(comp_rows), use_container_width=True, hide_index=True)

        if pipe is not None:
            st.markdown("**Nearby Competitive Pipeline (0.5 mi)**")
            pipe_overall = pipe.get("status", {}).get("overall", "")
            if pipe_overall == "no_coordinates":
                st.warning("⚠️ No lat/lon on record — can't search nearby pipeline.")
            elif pipe_overall == "blocked":
                st.warning("⚠️ One or more pipeline sources rate-limited this request. Try again shortly.")
            elif pipe_overall == "error":
                st.error("⚠️ Pipeline sources failed to respond — results may be incomplete.")
            elif pipe_overall == "no_results":
                st.info("✅ Checked — no nearby DOB filings or press coverage found.")
            else:  # "live"
                p1, p2 = st.columns(2)
                p1.metric("Nearby Projects", pipe.get("count", 0))
                p2.metric("Total Units in Pipeline", pipe.get("total_units", 0))
                if pipe.get("developments"):
                    dev_rows = [{
                        "Address": d.get("address", ""), "Type": d.get("asset_type", ""),
                        "Units": d.get("units", ""), "Status": d.get("status", ""),
                        "Source": d.get("source", ""),
                    } for d in pipe["developments"][:15]]
                    st.dataframe(pd.DataFrame(dev_rows), use_container_width=True, hide_index=True)

        if mc is None and pipe is None:
            st.caption("Not yet fetched — click above to pull live market comps and nearby pipeline for this property.")

    _render_underwriting_section(prop)

    _render_ai_diligence_section(prop)

    with st.expander("⬇️ Export This Property", expanded=False):
        ic = prop.get("ic_summary")
        uw_for_export = st.session_state.get(f"{_SF_PREFIX}uw_export_{prop['bbl']}")
        prop_for_export = dict(prop)
        if uw_for_export:
            prop_for_export["underwriting"] = uw_for_export
        else:
            st.caption("Tip: generate a pro forma above to include it in these exports.")

        ex1, ex2 = st.columns(2)
        with ex1:
            if st.button("📄 Build PDF report", key=f"{_SF_PREFIX}pdf_{prop['bbl']}", use_container_width=True):
                try:
                    st.session_state[f"{_SF_PREFIX}pdf_bytes"] = build_pdf_report(prop_for_export, ic)
                except ImportError as exc:
                    st.error(str(exc))
            if st.session_state.get(f"{_SF_PREFIX}pdf_bytes"):
                st.download_button(
                    "Download PDF", data=st.session_state[f"{_SF_PREFIX}pdf_bytes"],
                    file_name=f"{prop['bbl']}_report.pdf", mime="application/pdf",
                    use_container_width=True,
                )
        with ex2:
            if st.button("📽️ Build PowerPoint pitch", key=f"{_SF_PREFIX}pptx_{prop['bbl']}", use_container_width=True):
                try:
                    st.session_state[f"{_SF_PREFIX}pptx_bytes"] = build_pptx_report(prop_for_export, ic)
                except ImportError as exc:
                    st.error(str(exc))
            if st.session_state.get(f"{_SF_PREFIX}pptx_bytes"):
                st.download_button(
                    "Download PowerPoint", data=st.session_state[f"{_SF_PREFIX}pptx_bytes"],
                    file_name=f"{prop['bbl']}_pitch.pptx",
                    mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    use_container_width=True,
                )

    st.info(
        "💡 For full comps, massing scenarios, ACRIS document tables, DOB/HPD "
        "records, risk analysis, and 3D massing visualizations, copy this "
        f"address into the **🏢 Property Analysis** tab: `{prop['address']}`"
    )


# ── Underwriting Engine: multi-year pro forma, financing, IRR, sensitivity ──
# (free/keyless, no LLM — deterministic arithmetic over already-collected data)

def _pct_input(label: str, value: float, key: str, step: float = 0.5, help: str | None = None) -> float:
    """A percentage-denominated number_input, stored/returned as a 0-1 fraction."""
    pct = st.number_input(label, min_value=-50.0, max_value=100.0, value=round(value * 100, 2),
                           step=step, key=key, help=help)
    return pct / 100.0


def _flatten_underwriting_for_export(scenario: dict, cf_result: dict, returns_result: dict, equity_structure: str) -> dict:
    """Small flat summary dict for report_exporter.py — decoupled from the
    engine's internal nested cash-flow/tier-breakdown shapes."""
    out = {
        "scenario_label": scenario["label"],
        "total_dev_cost": cf_result["total_dev_cost"],
        "year1_noi": cf_result["year1_noi"],
        "equity_structure": equity_structure,
    }
    if equity_structure == "waterfall":
        out["irr"] = returns_result.get("lp_irr")
        out["equity_multiple"] = returns_result.get("lp_equity_multiple")
        out["lp_irr"] = returns_result.get("lp_irr")
        out["gp_irr"] = returns_result.get("gp_irr")
        out["lp_equity_multiple"] = returns_result.get("lp_equity_multiple")
        out["gp_equity_multiple"] = returns_result.get("gp_equity_multiple")
        out["total_gp_promote"] = returns_result.get("total_gp_promote")
    else:
        out["irr"] = returns_result.get("irr")
        out["equity_multiple"] = returns_result.get("equity_multiple")
    return out


def _render_underwriting_section(prop: dict) -> None:
    st.markdown("---")
    st.markdown("#### 📊 Underwriting Pro Forma")
    st.caption(
        "Deterministic multi-year screening model — construction → stabilization → "
        "exit, with financing and a hand-computed IRR. Not a lender-grade or "
        "GP-facing underwriting package; assumptions are editable rules of thumb."
    )
    if not prop.get("borough"):
        st.caption("⚠️ Unit-size assumptions use a citywide default (no neighborhood-level SF data for this property).")

    bbl = prop["bbl"]
    scenarios_key = f"{_SF_PREFIX}uw_scenarios_{bbl}"

    if st.button("📊 Generate Development Scenarios & Pro Forma", key=f"{_SF_PREFIX}uw_gen_{bbl}"):
        working = prop
        if not prop.get("market_comps"):
            with st.spinner("Fetching neighborhood sales comps (NYC Rolling Sales, free)…"):
                working = dict(prop)
                working["market_comps"] = fetch_market_comps(prop)
                st.session_state[f"{_SF_PREFIX}selected_prop"] = working
        st.session_state[scenarios_key] = build_scenarios(working, working.get("market_comps"))
        st.rerun()

    scenarios = st.session_state.get(scenarios_key)
    if scenarios is None:
        st.caption("Not yet generated — click above to build 3-4 comparable development scenarios.")
        return
    if not scenarios:
        st.warning("No scenarios could be generated for this property (missing lot SF).")
        return

    market_comps = prop.get("market_comps")
    acq = estimate_acquisition_cost(prop)

    # ── Quick comparison table across all scenarios, default assumptions ──
    comp_rows = []
    for s in scenarios:
        cf = build_cash_flows(s, acq, market_comps=market_comps, borough=prop.get("borough", "Manhattan"))
        quick = simple_sponsor_returns(cf["annual_cash_flows"])
        comp_rows.append({
            "Scenario": s["label"], "Use Type": s["use_type"].replace("_", " ").title(),
            "FAR Basis": s["far_basis"].replace("_", " ").title(),
            "Dev Cost": f"${cf['total_dev_cost']:,.0f}",
            "Year 1 NOI": f"${cf['year1_noi']:,.0f}" if cf["year1_noi"] else "—",
            "Quick IRR": f"{quick['irr']:.1%}" if quick["irr"] is not None else "N/A",
        })
    st.dataframe(pd.DataFrame(comp_rows), use_container_width=True, hide_index=True)

    scenario_labels = [s["label"] for s in scenarios]
    chosen_label = st.selectbox("Drill into a scenario", options=scenario_labels, key=f"{_SF_PREFIX}uw_scenario_{bbl}")
    scenario = next(s for s in scenarios if s["label"] == chosen_label)
    if scenario["assumptions_note"]:
        st.caption(" · ".join(scenario["assumptions_note"]))

    # ── Financing & hold assumptions ───────────────────────────────────────
    with st.expander("⚙️ Financing & Hold Assumptions", expanded=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            hold_years = st.number_input("Hold period (yrs)", min_value=1, max_value=20,
                                          value=DEFAULT_HOLD_YEARS_POST_STAB, key=f"{_SF_PREFIX}uw_hold_{bbl}")
            rent_growth = _pct_input("Rent growth %/yr", DEFAULT_RENT_GROWTH_PCT, f"{_SF_PREFIX}uw_rentg_{bbl}")
            expense_growth = _pct_input("Expense growth %/yr", DEFAULT_EXPENSE_GROWTH_PCT, f"{_SF_PREFIX}uw_expg_{bbl}")
        with c2:
            exit_spread_bps = st.number_input("Exit cap spread (bps over going-in)", min_value=-200, max_value=500,
                                               value=DEFAULT_EXIT_CAP_SPREAD_BPS, step=10, key=f"{_SF_PREFIX}uw_exitspread_{bbl}")
            construction_ltc = _pct_input("Construction LTC %", DEFAULT_CONSTRUCTION_LTC, f"{_SF_PREFIX}uw_ltc_{bbl}")
            construction_rate = _pct_input("Construction rate %", DEFAULT_CONSTRUCTION_RATE, f"{_SF_PREFIX}uw_crate_{bbl}", step=0.125)
        with c3:
            perm_ltv = _pct_input("Perm loan LTV %", DEFAULT_PERM_LTV, f"{_SF_PREFIX}uw_ltv_{bbl}")
            perm_dscr_min = st.number_input("Perm loan min DSCR", min_value=1.0, max_value=2.0,
                                             value=DEFAULT_PERM_DSCR_MIN, step=0.05, key=f"{_SF_PREFIX}uw_dscr_{bbl}")
            perm_rate = _pct_input("Perm loan rate %", DEFAULT_PERM_RATE, f"{_SF_PREFIX}uw_prate_{bbl}", step=0.125)
        perm_amort_years = st.number_input("Perm loan amortization (yrs)", min_value=10, max_value=40,
                                            value=DEFAULT_PERM_AMORT_YEARS, key=f"{_SF_PREFIX}uw_amort_{bbl}")

    financing_kwargs = {
        "construction_ltc": construction_ltc, "construction_rate": construction_rate,
        "perm_ltv": perm_ltv, "perm_dscr_min": perm_dscr_min,
        "perm_rate": perm_rate, "perm_amort_years": perm_amort_years,
    }
    cf_kwargs = {
        "market_comps": market_comps, "borough": prop.get("borough", "Manhattan"),
        "hold_years": hold_years, "rent_growth_pct": rent_growth,
        "expense_growth_pct": expense_growth, "exit_cap_spread_bps": exit_spread_bps,
        "financing_kwargs": financing_kwargs,
    }

    # ── Equity structure ────────────────────────────────────────────────────
    equity_choice = st.radio(
        "Equity Structure", ["Simple Sponsor IRR", "LP/GP Waterfall"],
        key=f"{_SF_PREFIX}uw_equity_{bbl}", horizontal=True,
    )
    equity_structure = "waterfall" if equity_choice == "LP/GP Waterfall" else "simple"

    waterfall_kwargs = {}
    if equity_structure == "waterfall":
        with st.expander("💼 Waterfall Assumptions", expanded=True):
            w1, w2 = st.columns(2)
            with w1:
                pref_pct = _pct_input("Preferred return %", DEFAULT_PREFERRED_RETURN_PCT, f"{_SF_PREFIX}uw_pref_{bbl}")
            with w2:
                gp_co_invest = _pct_input("GP co-invest % of equity", DEFAULT_GP_CO_INVEST_PCT, f"{_SF_PREFIX}uw_gpco_{bbl}")
            st.caption("Promote tiers (GP % of cash above each IRR hurdle):")
            tiers = []
            for i, (lo, hi, default_pct) in enumerate(DEFAULT_PROMOTE_TIERS):
                hi_label = f"{hi:.0%}" if hi is not None else "∞"
                gp_pct = st.slider(f"{lo:.0%}–{hi_label} IRR", 0.0, 1.0, default_pct, step=0.05,
                                    key=f"{_SF_PREFIX}uw_tier{i}_{bbl}", format="%.0f%%")
                tiers.append((lo, hi, gp_pct))
            waterfall_kwargs = {"preferred_return_pct": pref_pct, "promote_tiers": tiers, "gp_co_invest_pct": gp_co_invest}

    # ── Compute & render the selected scenario's pro forma ─────────────────
    cf_result = build_cash_flows(scenario, acq, **cf_kwargs)

    if equity_structure == "waterfall":
        returns = lp_gp_waterfall(cf_result["annual_cash_flows"], **waterfall_kwargs)
        headline_irr, headline_em = returns["lp_irr"], returns["lp_equity_multiple"]
    else:
        returns = simple_sponsor_returns(cf_result["annual_cash_flows"])
        headline_irr, headline_em = returns["irr"], returns["equity_multiple"]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Levered IRR" + (" (LP)" if equity_structure == "waterfall" else ""),
              f"{headline_irr:.1%}" if headline_irr is not None else "N/A")
    m2.metric("Equity Multiple" + (" (LP)" if equity_structure == "waterfall" else ""),
              f"{headline_em:.2f}x" if headline_em is not None else "N/A")
    m3.metric("Total Dev. Cost", f"${cf_result['total_dev_cost']:,.0f}")
    m4.metric("Year 1 NOI", f"${cf_result['year1_noi']:,.0f}" if cf_result["year1_noi"] else "—")

    if equity_structure == "waterfall":
        g1, g2 = st.columns(2)
        g1.metric("GP IRR", f"{returns['gp_irr']:.1%}" if returns["gp_irr"] is not None else "N/A")
        g2.metric("GP Promote ($)", f"${returns['total_gp_promote']:,.0f}")
        st.caption(returns.get("note", ""))

    with st.expander("Annual Cash Flow Detail", expanded=False):
        cf_rows = [{
            "Year": c["year"], "Phase": c["phase"], "NOI": f"${c['noi']:,.0f}",
            "Debt Service": f"${c['debt_service']:,.0f}",
            "Reversion": f"${c['reversion_proceeds']:,.0f}" if c["reversion_proceeds"] else "—",
            "Equity CF": f"${c['equity_cf']:,.0f}",
        } for c in cf_result["annual_cash_flows"]]
        st.dataframe(pd.DataFrame(cf_rows), use_container_width=True, hide_index=True)

    with st.expander("Financing Detail", expanded=False):
        fin = cf_result["financing"]
        st.markdown(
            f"- Construction loan: ${fin['construction_loan_amount']:,.0f} "
            f"(interest accrued: ${fin['construction_interest_accrued']:,.0f})\n"
            f"- Permanent loan: ${fin['perm_loan_amount']:,.0f} "
            f"(binding constraint: {fin['binding_constraint']})\n"
            f"- Annual debt service: ${fin['annual_debt_service']:,.0f}\n"
            f"- {fin['note']}"
        )

    with st.expander("📉 Sensitivity / Stress Test", expanded=False):
        if st.button("Run Sensitivity", key=f"{_SF_PREFIX}uw_sens_{bbl}"):
            sens = run_sensitivity(
                scenario, acq, base_kwargs=cf_kwargs,
                equity_structure=equity_structure, waterfall_kwargs=waterfall_kwargs,
            )
            st.session_state[f"{_SF_PREFIX}uw_sens_result_{bbl}"] = sens

        sens = st.session_state.get(f"{_SF_PREFIX}uw_sens_result_{bbl}")
        if sens:
            try:
                import plotly.graph_objects as go
                tornado = sens["tornado_ranking"]
                fig = go.Figure(go.Bar(
                    x=[t["irr_range"] * 100 for t in tornado],
                    y=[t["lever"].replace("_", " ").title() for t in tornado],
                    orientation="h",
                ))
                fig.update_layout(
                    title="IRR Sensitivity (percentage-point swing)", xaxis_title="IRR range (pp)",
                    height=280, margin=dict(l=10, r=10, t=40, b=10),
                )
                st.plotly_chart(fig, use_container_width=True)
            except Exception:
                pass

            for lever, rows in sens["grid"].items():
                st.markdown(f"**{lever.replace('_', ' ').title()}**")
                grid_row = {f"{r['delta_pct']:+.0%}": (f"{r['irr']:.1%}" if r["irr"] is not None else "N/A") for r in rows}
                st.dataframe(pd.DataFrame([grid_row]), use_container_width=True, hide_index=True)
        else:
            st.caption("Not yet run — click above to stress-test rent, hard cost, exit cap rate, and interest rate.")

    # Stash a flattened summary for the export section below.
    st.session_state[f"{_SF_PREFIX}uw_export_{bbl}"] = _flatten_underwriting_for_export(
        scenario, cf_result, returns, equity_structure
    )


# ── Phase 4: AI Diligence Agents + Investment Committee ─────────────────────

def _render_ai_diligence_section(prop: dict) -> None:
    st.markdown("---")
    st.markdown("#### 🤖 AI Diligence Agents")

    anthropic_key = st.session_state.get(f"{_SF_PREFIX}anthropic_key", "")
    if not has_anthropic_key(anthropic_key):
        st.info(
            "Add an Anthropic API key in the sidebar (🏢 Property Analysis tab) to run "
            "AI diligence agents: Property, Zoning, Market, Development, Financial, "
            "Risk, and a final Investment Committee synthesis."
        )
        return

    ic = prop.get("ic_summary")
    if ic:
        rec = ic.get("recommendation", "—")
        _rec_color = {"GO": "#1F6B3A", "WATCH": "#8B6914", "REJECT": "#7A2E2E"}.get(rec, "#6B7280")
        st.markdown(
            f"<div style='background:{_rec_color};color:white;padding:10px 16px;"
            f"border-radius:8px;font-weight:700;font-size:1.1rem;text-align:center'>"
            f"Investment Committee Recommendation: {rec}</div>",
            unsafe_allow_html=True,
        )
        st.markdown("**Investment Thesis**")
        for t in ic.get("thesis", []):
            st.markdown(f"- {t}")
        st.markdown("**Key Risks**")
        for r in ic.get("key_risks", []):
            st.markdown(f"- {r}")
        st.markdown("**Key Unknowns**")
        for u in ic.get("key_unknowns", []):
            st.markdown(f"- {u}")
        st.markdown("**Recommended Next Steps**")
        for n in ic.get("next_steps", []):
            st.markdown(f"- {n}")

        agent_outputs = prop.get("agent_outputs", {})
        with st.expander("🔍 View individual specialist agent findings", expanded=False):
            for key in AGENT_ORDER:
                if key == "investment_committee":
                    continue
                out = agent_outputs.get(key, {})
                if out.get("error"):
                    st.warning(f"**{key.title()} Agent:** {out['error']}")
                    continue
                st.markdown(f"**{key.title()} Agent**")
                st.caption(out.get("summary", ""))
                for f in out.get("findings", []):
                    badge = "✅ verified" if f.get("verified") else "🔎 estimated"
                    st.markdown(
                        f"- {f.get('finding', '')} _(source: {f.get('source', '—')} · "
                        f"confidence {f.get('confidence', 0):.0%} · {badge})_"
                    )
        return

    st.caption(
        "Runs 6 specialist agents (Property, Zoning, Market, Development, Financial, "
        "Risk) over the data already collected for this property, then a final "
        "Investment Committee agent synthesizes a GO / WATCH / REJECT recommendation. "
        "Agents reason only over the structured data shown above — they flag gaps "
        "rather than inventing facts."
    )
    if st.button("🤖 Run AI Diligence", type="primary", key=f"{_SF_PREFIX}run_agents_{prop['bbl']}"):
        progress = st.progress(0.0, text="Running specialist agents…")

        def _cb(agent_key, i, n):
            progress.progress(i / n, text=f"Running {agent_key.replace('_', ' ').title()} Agent… ({i}/{n})")

        agent_input = prop
        uw_summary = st.session_state.get(f"{_SF_PREFIX}uw_export_{prop['bbl']}")
        if uw_summary:
            agent_input = dict(prop)
            agent_input["underwriting"] = uw_summary

        outputs = run_all_agents(agent_input, anthropic_key, progress_callback=_cb)
        progress.empty()

        updated = dict(prop)
        updated["agent_outputs"] = {k: v for k, v in outputs.items() if k != "investment_committee"}
        updated["ic_summary"] = outputs.get("investment_committee", {})
        st.session_state[f"{_SF_PREFIX}selected_prop"] = updated
        st.rerun()


# ── Main entry point ─────────────────────────────────────────────────────────

def render_site_finder(anthropic_key: str = "") -> None:
    st.session_state[f"{_SF_PREFIX}anthropic_key"] = anthropic_key
    st.markdown(
        "## 🔍 Site Finder — Development Site Sourcing & Screening"
    )
    st.caption(
        "Enter investment criteria to automatically search NYC properties, "
        "identify vacant/underutilized land, demolition candidates, and "
        "conversion/redevelopment opportunities, and rank them by a "
        "preliminary Deal Score. This is an initial screening tool only — "
        "not a substitute for legal, zoning, environmental, title, "
        "engineering, or appraisal diligence."
    )

    selected_prop = st.session_state.get(f"{_SF_PREFIX}selected_prop")
    if selected_prop:
        _render_property_detail(selected_prop)
        return

    criteria = _render_criteria_form()

    if criteria is not None:
        results, status = _run_search(criteria)
        st.session_state[f"{_SF_PREFIX}last_results"] = results
        st.session_state[f"{_SF_PREFIX}last_status"] = status
        st.session_state[f"{_SF_PREFIX}last_criteria"] = criteria
        # Reset any previous search's filter-panel widget state so numeric
        # filter bounds (Lot SF/FAR min-max) reset to this new result
        # set's actual range instead of silently carrying over stale
        # values from a prior search and excluding results the user never
        # meant to filter out.
        for _k in list(st.session_state.keys()):
            if _k.startswith(f"{_SF_PREFIX}filter_"):
                del st.session_state[_k]

    results = st.session_state.get(f"{_SF_PREFIX}last_results")
    status  = st.session_state.get(f"{_SF_PREFIX}last_status", {})
    last_criteria = st.session_state.get(f"{_SF_PREFIX}last_criteria")

    if status.get("error"):
        st.error(f"Search failed: {status['error']}")
        return

    if status.get("truncated"):
        st.warning(
            f"Results truncated at {status.get('total_fetched', 0):,} rows — "
            "narrow your search criteria for a complete match set."
        )

    if status.get("coords_missing_pct") == 100.0:
        raw_keys = status.get("raw_field_sample_if_no_coords") or []
        with st.expander("⚠️ Results map will be empty — no usable coordinates found", expanded=True):
            st.warning(
                "None of these results have usable latitude/longitude, so the map below "
                "won't show any markers. This usually means PLUTO's live field names for "
                "coordinates have drifted from what this app expects."
            )
            if raw_keys:
                st.caption(f"Raw PLUTO fields on a sample row (for diagnosis): {', '.join(raw_keys)}")
    elif status.get("coords_missing_pct"):
        st.caption(f"📍 {status['coords_missing_pct']:.0f}% of results have no usable coordinates and won't appear on the map.")

    if results is not None:
        st.markdown("---")
        _render_results_table(results, last_criteria)
    else:
        st.markdown("---")
        st.markdown(
            "<div style='text-align:center;padding:48px 24px;color:#6B7280'>"
            "<div style='font-size:3rem;margin-bottom:8px'>🏙️</div>"
            "<h4 style='color:#1A1D2E'>Enter investment criteria above and search to begin</h4>"
            "<p>Results are sourced live from NYC PLUTO — no API key required.</p>"
            "</div>",
            unsafe_allow_html=True,
        )

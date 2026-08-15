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
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import folium_static

from modules.visualizer import ESRI_SATELLITE_TILES, ESRI_SATELLITE_ATTR

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
    strong = sum(1 for p in properties if p["deal_score"]["score"] >= 65)
    avg_far_gap = (
        sum(p.get("unused_far_pct", 0) for p in properties) / n if n else 0
    )
    avg_score = (sum(p["deal_score"]["score"] for p in properties) / n) if n else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Properties Matched", f"{n:,}")
    c2.metric("Deal Score ≥ 65", f"{strong:,}", f"{(strong/n*100 if n else 0):.0f}% of results")
    c3.metric("Avg. Unused FAR", f"{avg_far_gap:.0f}%")
    c4.metric("Avg. Deal Score", f"{avg_score:.0f} / 100")


# ── Results map ──────────────────────────────────────────────────────────────

_TIER_MARKER_COLOR = {
    "Strong Lead": "green",
    "Watch":       "orange",
    "Pass":        "lightgray",
}


_MAX_MAP_MARKERS = 300  # see _render_results_map() docstring


def _render_results_map(properties: list[dict]) -> None:
    """
    Flag results on a free OpenStreetMap/CartoDB basemap (same tile
    provider already used in the Property Analysis tab's visualizer.py —
    no paid mapping API, no key required).

    Rendered via streamlit_folium.folium_static(), NOT st_folium():
    st_folium's custom bidirectional component has a documented bug where
    it silently fails to paint in Chrome when placed in a non-first
    st.tabs() tab (this map is tab 2 of 3) — see
    https://github.com/randyzwitch/streamlit-folium/issues/128. This map
    never consumed st_folium's bidirectional return value anyway (no
    click/zoom/bounds sync needed here), so folium_static's simpler
    components.html()-based static embed is a strictly safer fit, even
    though it's deprecated upstream in favor of st_folium. If a future
    streamlit-folium release removes folium_static entirely, this will
    need revisiting — not preemptively, since the suggested replacement
    is the specific thing suspected broken in this exact tab position.

    Also caps marker count at _MAX_MAP_MARKERS (by Deal Score, `properties`
    is already sorted) — separately from the results TABLE, which
    intentionally shows the full, uncapped result set. Folium/Leaflet maps
    are documented to fail to render at all above ~3000 markers
    (https://github.com/python-visualization/folium/issues/803), a real
    risk now that the table's own display cap was removed and a broad
    search can return up to property_search._MAX_ROWS (3000) rows.
    """
    located = [p for p in properties if p.get("latitude") and p.get("longitude")]
    missing = len(properties) - len(located)
    shown = located[:_MAX_MAP_MARKERS]
    map_truncated = len(located) - len(shown)

    if not located:
        st.caption("No coordinates available to plot for these results.")
        return

    st.markdown("#### 🗺️ Map View")
    center_lat = sum(p["latitude"] for p in shown) / len(shown)
    center_lon = sum(p["longitude"] for p in shown) / len(shown)

    m = folium.Map(location=[center_lat, center_lon], zoom_start=13, tiles="CartoDB positron")
    folium.TileLayer(
        tiles=ESRI_SATELLITE_TILES, attr=ESRI_SATELLITE_ATTR,
        name="Satellite", overlay=False, control=True,
    ).add_to(m)
    folium.LayerControl(position="topright", collapsed=True).add_to(m)
    # Wider pixel radius than visualizer.py's tight rental-comps map (40px)
    # since Site Finder results can legitimately include adjacent-lot
    # assemblage candidates worth grouping at a city-wide zoom; a higher
    # disableClusteringAtZoom (17 vs 16) defers full per-pin declustering
    # until the user has genuinely zoomed to a near-parcel view, avoiding a
    # cloud of overlapping individual pins on a wide borough-wide set.
    cluster = MarkerCluster(options={"maxClusterRadius": 50, "disableClusteringAtZoom": 17}).add_to(m)

    for p in shown:
        ds = p.get("deal_score", {})
        color = _TIER_MARKER_COLOR.get(ds.get("tier"), "blue")
        popup_html = (
            f"<b>{p.get('address', '')}</b><br>"
            f"BBL {p.get('bbl', '')}<br>"
            f"Deal Score: {ds.get('score', '—')}/100 ({ds.get('tier', '—')})<br>"
            f"Strategy: {', '.join(p.get('strategies', [])) or '—'}"
        )
        folium.Marker(
            location=[p["latitude"], p["longitude"]],
            icon=folium.Icon(color=color, icon="flag", prefix="fa"),
            tooltip=p.get("address", ""),
            popup=folium.Popup(popup_html, max_width=260),
        ).add_to(cluster)

    folium_static(m, width=1200, height=420)
    legend = " · ".join(f"🟢 {t}" if c == "green" else (f"🟠 {t}" if c == "orange" else f"⚪ {t}") for t, c in _TIER_MARKER_COLOR.items())
    caption = legend
    if map_truncated:
        caption += f" · showing the top {len(shown):,} of {len(located):,} geolocated results by Deal Score (full set is in the table below)"
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


def _render_results_table(properties: list[dict]) -> None:
    if not properties:
        st.info("No properties matched your criteria. Try widening the search (fewer filters, larger area).")
        return

    _render_summary_cards(properties)
    st.markdown("---")

    # Full result set (no display cap) — Streamlit's dataframe/map both
    # handle large row counts natively; the upstream Socrata fetch already
    # caps at property_search._MAX_ROWS (3000) so this isn't unbounded.
    results_full = _apply_ownership_cache(properties)

    _render_results_map(results_full)
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
    st.dataframe(
        df, use_container_width=True, hide_index=True,
        height=min(560, 60 + 35 * len(rows)),
        column_config={
            "Deal Score": st.column_config.ProgressColumn(
                "Deal Score", min_value=0, max_value=100, format="%d"
            ),
        },
    )

    st.markdown("---")
    st.markdown("#### 🔬 View Preliminary Diligence")
    options = ["— Select a property —"] + [
        f"{i}. {p['address']} (BBL {p['bbl']})" for i, p in enumerate(results_full, start=1)
    ]
    choice = st.selectbox("Choose a result to inspect", options=options, key=f"{_SF_PREFIX}detail_choice")
    if choice != options[0]:
        idx = options.index(choice) - 1
        if st.button("Open Preliminary Diligence →", type="primary"):
            st.session_state[f"{_SF_PREFIX}selected_bbl"] = results_full[idx]["bbl"]
            st.session_state[f"{_SF_PREFIX}selected_prop"] = results_full[idx]
            st.rerun()

    st.markdown("---")
    st.markdown("#### ☆ Save to Portfolio")
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

    results = st.session_state.get(f"{_SF_PREFIX}last_results")
    status  = st.session_state.get(f"{_SF_PREFIX}last_status", {})

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
        _render_results_table(results)
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

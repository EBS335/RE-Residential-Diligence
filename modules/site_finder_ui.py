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
from streamlit_folium import st_folium

from modules.property_search import search_properties, BOROUGH_CODES, PROPERTY_TYPE_LANDUSE
from modules.site_sourcing import enrich_property, STRATEGY_VACANT, STRATEGY_DEMOLITION, STRATEGY_CONVERSION
from modules.deal_scorer import compute_bulk_deal_scores
from modules.zoning_rules import get_zoning_rules, get_zoning_citations
from modules.zola_fetcher import bbl_to_zola_url
from modules.acris_fetcher import fetch_acris
from modules.ownership_research import enrich_ownership_batch, DEFAULT_BATCH_SIZE
from modules.site_finder_market import enrich_market_data, fetch_market_comps
from modules.site_finder_valuation import estimate_acquisition_cost, build_business_plan
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


def _render_results_map(properties: list[dict]) -> None:
    """
    Flag every result on a free OpenStreetMap/CartoDB basemap (same tile
    provider already used in the Property Analysis tab's visualizer.py —
    no paid mapping API, no key required).
    """
    located = [p for p in properties if p.get("latitude") and p.get("longitude")]
    missing = len(properties) - len(located)

    if not located:
        st.caption("No coordinates available to plot for these results.")
        return

    st.markdown("#### 🗺️ Map View")
    center_lat = sum(p["latitude"] for p in located) / len(located)
    center_lon = sum(p["longitude"] for p in located) / len(located)

    m = folium.Map(location=[center_lat, center_lon], zoom_start=13, tiles="CartoDB positron")
    cluster = MarkerCluster().add_to(m)

    for p in located:
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

    st_folium(m, use_container_width=True, height=420, key=f"{_SF_PREFIX}results_map")
    legend = " · ".join(f"🟢 {t}" if c == "green" else (f"🟠 {t}" if c == "orange" else f"⚪ {t}") for t, c in _TIER_MARKER_COLOR.items())
    st.caption(f"{legend}" + (f" · {missing} of {len(properties)} results have no coordinates and are not plotted" if missing else ""))


# ── Results table ────────────────────────────────────────────────────────────

def _apply_ownership_cache(top: list[dict]) -> list[dict]:
    """Overlay any previously-fetched ownership enrichment onto `top`."""
    cache = st.session_state.get(f"{_SF_PREFIX}ownership_cache", {})
    if not cache:
        return top
    return [cache.get(p["bbl"], p) for p in top]


def _render_results_table(properties: list[dict]) -> None:
    if not properties:
        st.info("No properties matched your criteria. Try widening the search (fewer filters, larger area).")
        return

    _render_summary_cards(properties)
    st.markdown("---")

    top = properties[:50]
    top = _apply_ownership_cache(top)

    _render_results_map(top)
    st.markdown("---")

    has_ownership = any("owner_type" in p for p in top)

    oc1, oc2 = st.columns([3, 1])
    with oc1:
        st.caption(
            "Owner/ACRIS/DOB-HPD distress data is fetched live per property and is "
            f"limited to the top {DEFAULT_BATCH_SIZE} results to keep searches fast."
        )
    with oc2:
        if st.button("🔍 Enrich Top 25 with Ownership", use_container_width=True):
            progress = st.progress(0.0, text="Fetching ownership & ACRIS data…")

            def _cb(i, n):
                progress.progress(i / n, text=f"Fetching ownership & ACRIS data… ({i}/{n})")

            enriched_top = enrich_ownership_batch(top, progress_callback=_cb)
            progress.empty()
            cache = st.session_state.get(f"{_SF_PREFIX}ownership_cache", {})
            for p in enriched_top:
                cache[p["bbl"]] = p
            st.session_state[f"{_SF_PREFIX}ownership_cache"] = cache
            st.rerun()

    rows = []
    for i, p in enumerate(top, start=1):
        ds = p["deal_score"]
        row = {
            "Rank":        i,
            "Address":     p["address"],
            "Borough":     p["borough"],
            "BBL":         p["bbl"],
            "Lot SF":      f"{p['lot_sf']:,.0f}",
            "Built FAR":   f"{p['far_built']:.2f}",
            "Max FAR":     f"{p['far_max']:.2f}",
            "Unused FAR %": f"{p['unused_far_pct']:.0f}%",
            "Strategy":    ", ".join(p.get("strategies", [])) or "—",
        }
        if has_ownership:
            row["Owner"] = p.get("owner", "") or "—"
            row["Owner Type"] = p.get("owner_type", "—")
            sale = p.get("last_sale_price")
            row["Last Sale"] = f"${sale:,.0f}" if sale else "—"
        row["Distress"] = p.get("distress_signal", "No Signal")
        row["Deal Score"] = ds["score"]
        row["Tier"] = ds["tier"]
        rows.append(row)

    df = pd.DataFrame(rows)
    st.markdown(f"**Top {len(top)} results** (of {len(properties):,} matched), ranked by Deal Score")
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
    options = ["— Select a property —"] + [f"{i}. {p['Address']} (BBL {p['BBL']})" for i, p in zip(range(1, len(rows) + 1), rows)]
    choice = st.selectbox("Choose a result to inspect", options=options, key=f"{_SF_PREFIX}detail_choice")
    if choice != options[0]:
        idx = options.index(choice) - 1
        if st.button("Open Preliminary Diligence →", type="primary"):
            st.session_state[f"{_SF_PREFIX}selected_bbl"] = top[idx]["bbl"]
            st.session_state[f"{_SF_PREFIX}selected_prop"] = top[idx]
            st.rerun()

    st.markdown("---")
    st.markdown("#### ☆ Save to Portfolio")
    save_choice = st.selectbox("Choose a result to save", options=options, key=f"{_SF_PREFIX}save_choice")
    if save_choice != options[0]:
        save_idx = options.index(save_choice) - 1
        if st.button("☆ Save to Portfolio", key=f"{_SF_PREFIX}save_btn"):
            from modules.portfolio_db import save_property
            save_property(top[save_idx], status="Watching")
            st.success(f"Saved {top[save_idx]['address']} to Portfolio.")

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
                xlsx_bytes = build_excel_workbook(top)
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
            if summ:
                a1, a2, a3 = st.columns(3)
                sale_price = summ.get("latest_sale_price")
                a1.metric("Last Sale", f"${sale_price:,.0f}" if sale_price else "—", summ.get("latest_sale_date", "—"))
                mtge = summ.get("active_mortgage_amt")
                a2.metric("Active Mortgage", f"${mtge:,.0f}" if mtge else "—")
                a3.metric("Open Liens", str(summ.get("open_liens", 0)))
                if acris.get("acris_url"):
                    st.caption(f"[Full ACRIS history ↗]({acris['acris_url']})")
            else:
                st.info("No ACRIS transaction history found for this BBL.")

    with st.expander("📐 Assessment (PLUTO)", expanded=False):
        st.markdown(
            f"**Assessed Land Value:** ${prop.get('assess_land', 0):,.0f} &nbsp;·&nbsp; "
            f"**Assessed Total Value:** ${prop.get('assess_total', 0):,.0f}"
        )
        basis_psf = (prop["assess_land"] / prop["lot_sf"]) if prop.get("lot_sf") else None
        if basis_psf:
            st.markdown(f"**Assessed Land Basis:** ${basis_psf:,.0f} / lot SF")

    with st.expander("📈 Market Comps & Competitive Pipeline", expanded=False):
        if st.button("Fetch market comps & nearby pipeline", key=f"{_SF_PREFIX}fetch_market_{prop['bbl']}"):
            with st.spinner("Fetching NYC Rolling Sales comps & nearby development pipeline…"):
                mkt = enrich_market_data(prop)
            st.session_state[f"{_SF_PREFIX}selected_prop"] = mkt
            st.rerun()

        mc = prop.get("market_comps")
        pipe = prop.get("pipeline")
        if mc:
            st.markdown("**Nearby Sales Comps (NYC Rolling Sales, by ZIP)**")
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
        if pipe:
            st.markdown("**Nearby Competitive Pipeline (0.5 mi)**")
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
        if not mc and not pipe:
            st.caption("Not yet fetched — click above to pull live market comps and nearby pipeline for this property.")

    _render_valuation_section(prop)

    _render_ai_diligence_section(prop)

    with st.expander("⬇️ Export This Property", expanded=False):
        ic = prop.get("ic_summary")
        plan_for_export = st.session_state.get(f"{_SF_PREFIX}bizplan_{prop['bbl']}")
        prop_for_export = dict(prop)
        if plan_for_export:
            prop_for_export["business_plan"] = plan_for_export
        else:
            st.caption("Tip: compute the Acquisition Estimate & Business Plan above to include it in these exports.")

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


# ── Preliminary Acquisition Estimate & Business Plan (free/keyless, no LLM) ─

def _render_valuation_section(prop: dict) -> None:
    st.markdown("---")
    st.markdown("#### 💰 Preliminary Acquisition Estimate & Business Plan")
    st.caption(
        "Deterministic screening math from free NYC Open Data only — prior sale, "
        "neighborhood comps, or assessed value; illustrative construction cost "
        "rules of thumb. Not an appraisal, broker opinion of value, or GC estimate."
    )

    plan_key = f"{_SF_PREFIX}bizplan_{prop['bbl']}"
    if st.button("📐 Compute Acquisition Estimate & Business Plan", key=f"{_SF_PREFIX}calc_plan_{prop['bbl']}"):
        working = prop
        if not prop.get("market_comps"):
            with st.spinner("Fetching neighborhood sales comps (NYC Rolling Sales, free)…"):
                working = dict(prop)
                working["market_comps"] = fetch_market_comps(prop)
                st.session_state[f"{_SF_PREFIX}selected_prop"] = working
        st.session_state[plan_key] = build_business_plan(working)
        st.rerun()

    plan = st.session_state.get(plan_key)
    if not plan:
        st.caption("Not yet computed — click above to generate a concise preliminary estimate.")
        return

    acq = plan["acquisition"]
    v1, v2, v3 = st.columns(3)
    v1.metric(
        "Est. Acquisition Cost",
        f"${acq['estimate']:,.0f}" if acq["estimate"] else "—",
        acq["confidence"] + " confidence",
    )
    v2.metric("Est. Total Dev. Cost", f"${plan['total_dev_cost']:,.0f}")
    v3.metric(
        "Est. Profit",
        f"${plan['profit']:,.0f}" if plan["profit"] is not None else "—",
        f"{plan['margin_pct']:.0f}% margin" if plan["margin_pct"] is not None else "no comps",
    )
    st.caption(f"**Acquisition basis:** {acq['basis']}")

    with st.expander("Cost & revenue breakdown", expanded=False):
        b1, b2 = st.columns(2)
        with b1:
            st.markdown("**Development Cost**")
            st.markdown(
                f"- Acquisition: ${acq['estimate']:,.0f}" if acq["estimate"] else "- Acquisition: —"
            )
            st.markdown(f"- Closing costs (~3%): ${plan['closing_cost']:,.0f}")
            st.markdown(f"- Hard cost ({plan['hard_cost_basis']} @ ${plan['hard_cost_psf']:,.0f}/GSF): ${plan['hard_cost']:,.0f}")
            st.markdown(f"- Soft costs (~20% of hard): ${plan['soft_cost']:,.0f}")
            st.markdown(f"- Contingency (~10%): ${plan['contingency']:,.0f}")
            st.markdown(f"- **Total: ${plan['total_dev_cost']:,.0f}**")
        with b2:
            st.markdown("**Buildable Area & Revenue**")
            st.markdown(f"- Gross buildable SF (max FAR × lot): {plan['gross_buildable_sf']:,.0f}")
            st.markdown(f"- Net buildable SF (~85% efficiency): {plan['net_buildable_sf']:,.0f}")
            if plan["revenue"] is not None:
                st.markdown(f"- Revenue @ ${plan['revenue_psf']:,.0f}/SF: ${plan['revenue']:,.0f}")
            else:
                st.markdown("- Revenue: — (no neighborhood comps found)")

    st.markdown("**Key Takeaways**")
    for b in plan["bullets"]:
        st.markdown(f"- {b}")


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
        _rec_color = {"GO": "#15803D", "WATCH": "#B45309", "REJECT": "#DC2626"}.get(rec, "#6B7280")
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

        outputs = run_all_agents(prop, anthropic_key, progress_callback=_cb)
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

    if results is not None:
        st.markdown("---")
        _render_results_table(results)
    else:
        st.markdown("---")
        st.markdown(
            "<div style='text-align:center;padding:48px 24px;color:#9CA3AF'>"
            "<div style='font-size:3rem;margin-bottom:8px'>🏙️</div>"
            "<h4 style='color:#374151'>Enter investment criteria above and search to begin</h4>"
            "<p>Results are sourced live from NYC PLUTO — no API key required.</p>"
            "</div>",
            unsafe_allow_html=True,
        )

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

from modules.property_search import search_properties, BOROUGH_CODES, PROPERTY_TYPE_LANDUSE
from modules.site_sourcing import enrich_property, STRATEGY_VACANT, STRATEGY_DEMOLITION, STRATEGY_CONVERSION
from modules.deal_scorer import compute_bulk_deal_scores
from modules.zoning_rules import get_zoning_rules, get_zoning_citations
from modules.zola_fetcher import bbl_to_zola_url
from modules.acris_fetcher import fetch_acris

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

        submitted = st.form_submit_button("🔎 Search NYC Development Sites", type="primary", use_container_width=True)

    if not submitted:
        return None

    return {
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


# ── Results table ────────────────────────────────────────────────────────────

def _render_results_table(properties: list[dict]) -> None:
    if not properties:
        st.info("No properties matched your criteria. Try widening the search (fewer filters, larger area).")
        return

    _render_summary_cards(properties)
    st.markdown("---")

    top = properties[:50]
    rows = []
    for i, p in enumerate(top, start=1):
        ds = p["deal_score"]
        rows.append({
            "Rank":        i,
            "Address":     p["address"],
            "Borough":     p["borough"],
            "BBL":         p["bbl"],
            "Lot SF":      f"{p['lot_sf']:,.0f}",
            "Built FAR":   f"{p['far_built']:.2f}",
            "Max FAR":     f"{p['far_max']:.2f}",
            "Unused FAR %": f"{p['unused_far_pct']:.0f}%",
            "Strategy":    ", ".join(p.get("strategies", [])) or "—",
            "Distress":    p.get("distress_signal", "No Signal"),
            "Deal Score":  ds["score"],
            "Tier":        ds["tier"],
        })

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

    st.download_button(
        "⬇️ Export results to CSV",
        data=df.to_csv(index=False).encode("utf-8"),
        file_name="site_finder_results.csv",
        mime="text/csv",
    )


# ── Property detail (lightweight, self-contained — does not call the ──────
# ── existing 4,000-line Property Analysis flow, to avoid any risk of ──────
# ── disturbing it) ──────────────────────────────────────────────────────────

def _render_property_detail(prop: dict) -> None:
    if st.button("← Back to Results"):
        st.session_state.pop(f"{_SF_PREFIX}selected_bbl", None)
        st.session_state.pop(f"{_SF_PREFIX}selected_prop", None)
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

    with st.expander("👤 Ownership & ACRIS History", expanded=False):
        st.markdown(f"**PLUTO Owner of Record:** {prop.get('owner') or '—'}")
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

    st.info(
        "💡 For full comps, massing scenarios, ACRIS document tables, DOB/HPD "
        "records, risk analysis, and 3D massing visualizations, copy this "
        f"address into the **🏢 Property Analysis** tab: `{prop['address']}`"
    )


# ── Main entry point ─────────────────────────────────────────────────────────

def render_site_finder() -> None:
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

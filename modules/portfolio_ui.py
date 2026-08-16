"""
Portfolio — Saved Properties, Deal Comparison & Saved Searches.

Renders the "📁 Portfolio" tab. This is the app's only cross-session view:
everywhere else, results live in `st.session_state` and vanish when the
browser tab closes. Properties land here via the "☆ Save to Portfolio"
buttons in the 🔍 Site Finder results table and the 🏢 Property Analysis
tab; searches land here via "💾 Save this search" in the Site Finder
Investment Criteria form.

Three sections:
  1. Pipeline table — every saved property, with an editable status column.
  2. Comparison view — up to 4 saved properties side by side.
  3. Saved searches — re-run a previously saved Site Finder search.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from modules.portfolio_db import (
    STATUSES,
    list_portfolio,
    update_status,
    remove_property,
    list_saved_searches,
    delete_saved_search,
    touch_search_last_run,
    seed_default_checklist,
    list_diligence_items,
    update_diligence_item,
    add_diligence_item,
    delete_diligence_item,
    diligence_progress,
)

_MAX_COMPARE = 4


def _render_pipeline_table() -> None:
    st.markdown("### 📋 Pipeline")
    rows = list_portfolio()
    if not rows:
        st.info(
            "Nothing saved yet. Use “☆ Save to Portfolio” in the 🔍 Site Finder results "
            "table or the 🏢 Property Analysis tab to start building a shortlist."
        )
        return

    df = pd.DataFrame([
        {
            "BBL":         r["bbl"],
            "Address":     r["address"],
            "Borough":     r.get("borough") or "—",
            "Status":      r.get("status") or "Watching",
            "Deal Score":  r.get("deal_score"),
            "Tier":        r.get("deal_tier") or "—",
            "Notes":       r.get("notes") or "",
            "Added":       (r.get("added_at") or "")[:10],
            "Updated":     (r.get("updated_at") or "")[:10],
        }
        for r in rows
    ])

    edited = st.data_editor(
        df, use_container_width=True, hide_index=True, key="_portfolio_pipeline_editor",
        column_config={
            "BBL":        st.column_config.TextColumn(disabled=True),
            "Address":    st.column_config.TextColumn(disabled=True),
            "Borough":    st.column_config.TextColumn(disabled=True),
            "Status":     st.column_config.SelectboxColumn(options=STATUSES, required=True),
            "Deal Score": st.column_config.NumberColumn(disabled=True, format="%.0f"),
            "Tier":       st.column_config.TextColumn(disabled=True),
            "Notes":      st.column_config.TextColumn(),
            "Added":      st.column_config.TextColumn(disabled=True),
            "Updated":    st.column_config.TextColumn(disabled=True),
        },
    )

    # Diff edited rows against the original snapshot and persist any changes.
    changed = 0
    for orig_row, edit_row in zip(df.itertuples(), edited.itertuples()):
        if orig_row.Status != edit_row.Status or orig_row.Notes != edit_row.Notes:
            update_status(
                edit_row.BBL,
                status=edit_row.Status if orig_row.Status != edit_row.Status else None,
                notes=edit_row.Notes if orig_row.Notes != edit_row.Notes else None,
            )
            changed += 1
    if changed:
        st.toast(f"Updated {changed} propert{'y' if changed == 1 else 'ies'}.", icon="✅")
        st.rerun()

    with st.expander("🗑️ Remove a property"):
        bbl_options = ["— Select —"] + [f"{r['bbl']} — {r['address']}" for r in rows]
        rm_choice = st.selectbox("Property to remove", options=bbl_options, key="_portfolio_rm_choice")
        if rm_choice != bbl_options[0] and st.button("Remove from Portfolio", key="_portfolio_rm_btn"):
            bbl = rm_choice.split(" — ")[0]
            remove_property(bbl)
            st.success("Removed.")
            st.rerun()


def _render_comparison(rows: list[dict]) -> None:
    st.markdown("### ⚖️ Compare Properties")
    if not rows:
        return

    labels = [f"{r['bbl']} — {r['address']}" for r in rows]
    chosen = st.multiselect(
        f"Select up to {_MAX_COMPARE} properties to compare", options=labels,
        key="_portfolio_compare_select",
    )
    if len(chosen) > _MAX_COMPARE:
        st.warning(f"Comparing more than {_MAX_COMPARE} properties gets hard to read — "
                   f"showing the first {_MAX_COMPARE} selected.")
        chosen = chosen[:_MAX_COMPARE]
    if not chosen:
        st.caption("Pick 2 or more properties above to see them side by side.")
        return

    by_label = {f"{r['bbl']} — {r['address']}": r for r in rows}
    selected = [by_label[c] for c in chosen if c in by_label]

    def _g(prop: dict, key, default="—"):
        v = prop.get(key)
        return v if v not in (None, "") else default

    fields = [
        ("Address", lambda r: r["address"]),
        ("BBL", lambda r: r["bbl"]),
        ("Borough", lambda r: r.get("borough") or "—"),
        ("Status", lambda r: r.get("status") or "—"),
        ("Deal Score", lambda r: r.get("deal_score") if r.get("deal_score") is not None else "—"),
        ("Tier", lambda r: r.get("deal_tier") or "—"),
        ("Lot SF", lambda r: _g(r["property"], "lot_sf")),
        ("Bldg SF", lambda r: _g(r["property"], "bldg_sf")),
        ("Built FAR", lambda r: _g(r["property"], "far_built")),
        ("Max FAR", lambda r: _g(r["property"], "far_max")),
        ("Unused FAR %", lambda r: _g(r["property"], "unused_far_pct")),
        ("Assessed Total", lambda r: _g(r["property"], "assess_total")),
        ("Year Built", lambda r: _g(r["property"], "year_built")),
        ("Res. Units", lambda r: _g(r["property"], "units_res")),
        ("Owner", lambda r: _g(r["property"], "owner")),
        ("Tax Abatement (est.)", lambda r: _fmt_abatement(r["property"])),
        ("Rent Stab. (est.)", lambda r: _fmt_rentstab(r["property"])),
    ]

    comp = {name: [fn(r) for r in selected] for name, fn in fields}
    comp_df = pd.DataFrame(comp, index=[c for c in chosen if c in by_label]).T
    st.dataframe(comp_df, use_container_width=True)


def _fmt_abatement(prop: dict) -> str:
    ab = prop.get("tax_abatement")
    if not ab or not isinstance(ab, dict):
        return "—"
    if ab.get("currently_exempt"):
        return "Currently exempt (verified)"
    programs = [p["program"] for p in ab.get("estimated_programs", []) if p.get("eligible_estimate")]
    return f"Est. eligible: {', '.join(programs)}" if programs else "—"


def _fmt_rentstab(prop: dict) -> str:
    rs = prop.get("rent_stab_signal")
    if not rs or not isinstance(rs, dict):
        return "—"
    return "Likely stabilized (est.)" if rs.get("likely_stabilized") else "Unlikely (est.)"


def _render_saved_searches() -> None:
    st.markdown("### 💾 Saved Searches")
    searches = list_saved_searches()
    if not searches:
        st.info(
            "No saved searches yet. Check “💾 Save this search” in the 🔍 Site Finder "
            "Investment Criteria form to save one."
        )
        return

    for s in searches:
        c1, c2, c3, c4 = st.columns([3, 2, 1, 1])
        with c1:
            st.markdown(f"**{s['name']}**")
            crit = s.get("criteria", {})
            summary_bits = []
            if crit.get("boroughs"):
                summary_bits.append(", ".join(crit["boroughs"]))
            if crit.get("min_far") or crit.get("max_far"):
                summary_bits.append(f"FAR {crit.get('min_far') or 0}–{crit.get('max_far') or '∞'}")
            if crit.get("strategies"):
                summary_bits.append(", ".join(crit["strategies"]))
            st.caption(" · ".join(summary_bits) or "No filters")
        with c2:
            st.caption(f"Saved {s.get('created_at', '')[:10]}")
            if s.get("last_run_at"):
                st.caption(f"Last run {s['last_run_at'][:10]}")
        with c3:
            if st.button("▶ Re-run", key=f"_portfolio_rerun_{s['id']}"):
                from modules.site_finder_ui import load_saved_criteria_into_widgets
                load_saved_criteria_into_widgets(s.get("criteria", {}))
                touch_search_last_run(s["id"])
                st.success("Loaded — switch to the 🔍 Site Finder tab to run it.")
        with c4:
            if st.button("🗑️", key=f"_portfolio_delsearch_{s['id']}"):
                delete_saved_search(s["id"])
                st.rerun()
        st.divider()


def _render_diligence_tracker(rows: list[dict]) -> None:
    st.markdown("### ✅ Diligence Checklist / Tracker")
    st.caption(
        "A categorized diligence checklist per saved property (Title, Zoning, Environmental, "
        "Structural, Financing, Legal) — distinct from the single Status pipeline-stage field "
        "in the Pipeline table above. Opening a property's tracker for the first time seeds a "
        "starter checklist you can freely add to or remove from."
    )
    if not rows:
        st.info("Save a property to the Portfolio first to start a diligence checklist for it.")
        return

    bbl_options = [f"{r['bbl']} — {r['address']}" for r in rows]
    dt_choice = st.selectbox("Property", options=bbl_options, key="_portfolio_dt_choice")
    bbl = dt_choice.split(" — ")[0]

    items = list_diligence_items(bbl)
    if not items:
        items = seed_default_checklist(bbl)

    progress = diligence_progress(bbl)
    st.progress(progress["pct"] / 100.0, text=f"{progress['complete']} / {progress['total']} complete ({progress['pct']:.0f}%)")

    df = pd.DataFrame([
        {
            "_id": i["id"], "Category": i["category"], "Item": i["item"],
            "Done": bool(i["is_complete"]), "Notes": i.get("notes") or "",
        }
        for i in items
    ])
    edited = st.data_editor(
        df.drop(columns=["_id"]), use_container_width=True, hide_index=True, key=f"_dt_editor_{bbl}",
        column_config={
            "Category": st.column_config.TextColumn(disabled=True),
            "Item":     st.column_config.TextColumn(disabled=True),
            "Done":     st.column_config.CheckboxColumn(),
            "Notes":    st.column_config.TextColumn(),
        },
    )

    changed = 0
    for (_, orig_row), (_, edit_row) in zip(df.iterrows(), edited.iterrows()):
        if orig_row["Done"] != edit_row["Done"] or orig_row["Notes"] != edit_row["Notes"]:
            update_diligence_item(
                int(orig_row["_id"]),
                is_complete=bool(edit_row["Done"]) if orig_row["Done"] != edit_row["Done"] else None,
                notes=edit_row["Notes"] if orig_row["Notes"] != edit_row["Notes"] else None,
            )
            changed += 1
    if changed:
        st.toast(f"Updated {changed} checklist item{'s' if changed != 1 else ''}.", icon="✅")
        st.rerun()

    with st.expander("➕ Add / 🗑️ remove a checklist item"):
        ac1, ac2, ac3 = st.columns([2, 3, 1])
        new_cat = ac1.text_input("Category", key=f"_dt_newcat_{bbl}")
        new_item = ac2.text_input("Item", key=f"_dt_newitem_{bbl}")
        if ac3.button("Add", key=f"_dt_addbtn_{bbl}") and new_cat.strip() and new_item.strip():
            add_diligence_item(bbl, new_cat.strip(), new_item.strip())
            st.rerun()

        rm_options = ["— Select —"] + [f"{i['id']} — {i['category']}: {i['item']}" for i in items]
        rm_choice = st.selectbox("Remove item", options=rm_options, key=f"_dt_rmchoice_{bbl}")
        if rm_choice != rm_options[0] and st.button("Remove", key=f"_dt_rmbtn_{bbl}"):
            delete_diligence_item(int(rm_choice.split(" — ")[0]))
            st.rerun()


def _render_proposal_comparer() -> None:
    st.markdown("### 📑 Consultant Proposal Comparer")
    st.caption(
        "Upload consultant proposal PDFs (structural, Phase I ESA, zoning, title, survey, "
        "geotechnical, etc.) to compare estimated fees and scope coverage side by side. "
        "Parsing runs entirely locally — nothing is uploaded anywhere except this session."
    )
    uploads = st.file_uploader(
        "Upload consultant proposals (PDF)", type="pdf", accept_multiple_files=True,
        key="_proposal_uploader",
    )
    if not uploads:
        st.info("Upload one or more consultant proposal PDFs to compare fees and scope coverage.")
        return

    try:
        from modules.proposal_parser import (
            extract_proposal_text, extract_fee_estimate, score_scope_keywords,
            SCOPE_KEYWORD_CATEGORIES,
        )
    except ImportError as exc:
        st.error(str(exc))
        return

    rows = []
    for f in uploads:
        parsed = extract_proposal_text(f.getvalue())
        if parsed["error"]:
            st.warning(f"⚠️ Could not parse **{f.name}**: {parsed['error']}")
            continue
        if not parsed["text"].strip():
            st.warning(f"⚠️ **{f.name}** yielded no extractable text (likely a scanned/image-only PDF) — skipped.")
            continue
        fee = extract_fee_estimate(parsed["text"])
        scores = score_scope_keywords(parsed["text"])
        matched = [cat for cat, count in scores.items() if count > 0]
        missing = [cat for cat in SCOPE_KEYWORD_CATEGORIES if cat not in matched]
        rows.append({
            "Consultant / File": f.name,
            "Total Fee": f"${fee:,.0f}" if fee is not None else "—",
            "Scope Categories Matched": ", ".join(matched) if matched else "—",
            "Categories Missing": ", ".join(missing) if missing else "—",
        })

    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("No proposals could be parsed from the uploaded files.")


def render_portfolio() -> None:
    st.markdown("## 📁 Portfolio")
    st.caption(
        "Your shortlist across sessions — saved properties and searches persist in a "
        "local database, unlike the rest of the app, which resets when your session ends."
    )

    _render_pipeline_table()
    st.markdown("---")
    _render_diligence_tracker(list_portfolio())
    st.markdown("---")
    _render_proposal_comparer()
    st.markdown("---")
    _render_comparison(list_portfolio())
    st.markdown("---")
    _render_saved_searches()

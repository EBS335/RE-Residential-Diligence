"""
Report Exporter — Site Finder Phase 3/4, upgraded to an institutional
export design (Property Analysis tab review pass).

Builds downloadable Excel (results workbook), PDF, and PowerPoint
(single-property investment summary) exports. All functions return raw
bytes so callers can hand them directly to st.download_button without
touching the filesystem.

Design note: these exports are a deliberately different visual language
from the app's live dashboard. The dashboard is a dark "trading-desk"
theme; these exports stay a light, print-friendly, institutional-memo
design (navy/white/gray) — the convention real IC memos, OMs, and pitch
decks actually use, and the one that prints/photocopies cleanly.

Optional dependencies (see requirements.txt): openpyxl, reportlab,
python-pptx. Each builder function raises ImportError with a clear
pip-install hint if its library is missing, so the calling UI can show
a friendly message instead of crashing.
"""

from __future__ import annotations
import io
from datetime import datetime

_NAVY_HEX = "1A3A6B"      # openpyxl/pptx use hex without '#'
_NAVY_DARK_HEX = "0D1B2A"
_GRAY_HEX = "6B7280"
_LIGHT_GRAY_HEX = "F3F4F6"
_BORDER_HEX = "D1D5DB"


def _generated_stamp() -> str:
    return datetime.now().strftime("%B %d, %Y")


# ── Excel: full results workbook ────────────────────────────────────────────

def build_excel_workbook(properties: list[dict], top_n_detail: int = 20,
                          included_sections: dict[str, bool] | None = None) -> bytes:
    """
    Build an Excel workbook with:
      - "Summary" sheet: a title/date banner, then all ranked properties
        (one row each), with borders and a tier-colored fill on the Tier
        column for quick visual scanning
      - One sheet per property (up to top_n_detail) with zoning/ownership/
        market detail, for whichever properties carry that enrichment data

    included_sections: optional dict of section-key -> bool controlling
        which optional sections render (keys: "ownership", "underwriting",
        "market_comps"). None (the default) means "include everything" —
        100% backward compatible with every existing caller that doesn't
        pass this argument (e.g. modules/site_finder_ui.py).

    Returns raw .xlsx bytes.
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError as exc:
        raise ImportError("Install `openpyxl` to enable Excel export: pip install openpyxl") from exc

    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"

    header_fill = PatternFill(start_color=_NAVY_HEX, end_color=_NAVY_HEX, fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)
    title_font = Font(color=_NAVY_HEX, bold=True, size=16)
    subtitle_font = Font(color=_GRAY_HEX, size=10, italic=True)
    thin = Side(style="thin", color="D1D5DB")
    body_border = Border(left=thin, right=thin, top=thin, bottom=thin)

    _TIER_FILL = {
        "Strong Lead": PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid"),
        "Watch":       PatternFill(start_color="FEF9C3", end_color="FEF9C3", fill_type="solid"),
        "Pass":        PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid"),
    }
    _TIER_FONT = {
        "Strong Lead": Font(color="15803D", bold=True),
        "Watch":       Font(color="854D0E", bold=True),
        "Pass":        Font(color="991B1B", bold=True),
    }

    headers = [
        "Rank", "Address", "Borough", "BBL", "Lot SF", "Built FAR", "Max FAR",
        "Unused FAR %", "Strategy", "Owner", "Owner Type", "Last Sale Price",
        "Last Sale Date", "Distress Signal", "Deal Score", "Tier",
    ]
    n_cols = len(headers)

    # ── Title / generated-date banner ───────────────────────────────────────
    ws.cell(row=1, column=1, value="Investment Screening Summary").font = title_font
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n_cols)
    ws.cell(row=2, column=1, value=(
        f"Generated {_generated_stamp()} · Preliminary screening output only — "
        f"not a zoning opinion, appraisal, or substitute for professional diligence."
    )).font = subtitle_font
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=n_cols)
    ws.row_dimensions[1].height = 24

    header_row = 4
    ws.append([])  # row 3 blank spacer
    ws.append(headers)  # row 4
    for c in range(1, n_cols + 1):
        cell = ws.cell(row=header_row, column=c)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")
        cell.border = body_border

    tier_col = headers.index("Tier") + 1
    for i, p in enumerate(properties, start=1):
        ds = p.get("deal_score", {})
        tier = ds.get("tier", "")
        row_vals = [
            i,
            p.get("address", ""),
            p.get("borough", ""),
            p.get("bbl", ""),
            p.get("lot_sf", 0),
            round(p.get("far_built", 0), 2),
            round(p.get("far_max", 0), 2),
            round(p.get("unused_far_pct", 0), 1),
            ", ".join(p.get("strategies", [])),
            p.get("owner", ""),
            p.get("owner_type", ""),
            p.get("last_sale_price") or "",
            p.get("last_sale_date") or "",
            p.get("distress_signal", "No Signal"),
            ds.get("score", ""),
            tier,
        ]
        ws.append(row_vals)
        r = header_row + i
        for c in range(1, n_cols + 1):
            cell = ws.cell(row=r, column=c)
            cell.border = body_border
            if c == tier_col and tier in _TIER_FILL:
                cell.fill = _TIER_FILL[tier]
                cell.font = _TIER_FONT[tier]

    for c in range(1, n_cols + 1):
        ws.column_dimensions[get_column_letter(c)].width = 18
    ws.freeze_panes = f"A{header_row + 1}"

    # Per-property detail sheets for the top N
    _uw_included = included_sections is None or included_sections.get("underwriting", True)
    _comps_included = included_sections is None or included_sections.get("market_comps", True)
    for i, p in enumerate(properties[:top_n_detail], start=1):
        sheet_name = f"{i}. {p.get('bbl', '')}"[:31]  # Excel sheet name limit
        sh = wb.create_sheet(sheet_name)
        _write_property_detail_sheet(sh, p, header_fill, header_font, included_sections)

        # Optional per-property sheets — only created when the source data
        # is actually present (underwriting/comps aren't always computed
        # for every property before export).
        uw = p.get("underwriting") or {}
        if uw.get("annual_cash_flows") and _uw_included:
            _write_pro_forma_sheet(wb, i, p, uw, header_fill, header_font)
        if uw.get("cost_breakdown") and _uw_included:
            _write_construction_budget_sheet(wb, i, p, uw, header_fill, header_font)
        comps = (p.get("market_comps") or {}).get("comps") or []
        if comps and _comps_included:
            _write_comps_sheet(wb, i, p, comps, header_fill, header_font)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _write_pro_forma_sheet(wb, i: int, p: dict, uw: dict, header_fill, header_font) -> None:
    """Year-by-year cash-flow rows from build_cash_flows()'s
    annual_cash_flows — a real Pro Forma sheet, not just headline numbers."""
    from openpyxl.styles import Alignment

    sh = wb.create_sheet(f"{i}. Pro Forma"[:31])
    sh.cell(row=1, column=1, value=f"{p.get('address', '')} — Pro Forma ({uw.get('scenario_label', '')})").font = header_font
    sh.merge_cells(start_row=1, start_column=1, end_row=1, end_column=7)

    headers = ["Year", "Phase", "NOI", "Debt Service", "Reversion", "Equity CF", "Unlevered CF"]
    for c, h in enumerate(headers, start=1):
        cell = sh.cell(row=3, column=c, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    for r, cf in enumerate(uw["annual_cash_flows"], start=4):
        sh.cell(row=r, column=1, value=cf.get("year", ""))
        sh.cell(row=r, column=2, value=cf.get("phase", ""))
        sh.cell(row=r, column=3, value=round(cf.get("noi", 0) or 0))
        sh.cell(row=r, column=4, value=round(cf.get("debt_service", 0) or 0))
        sh.cell(row=r, column=5, value=round(cf.get("reversion_proceeds", 0) or 0))
        sh.cell(row=r, column=6, value=round(cf.get("equity_cf", 0) or 0))
        sh.cell(row=r, column=7, value=round(cf.get("unlevered_cf", 0) or 0))

    for c in range(1, 8):
        sh.column_dimensions[chr(64 + c)].width = 16


def _write_construction_budget_sheet(wb, i: int, p: dict, uw: dict, header_fill, header_font) -> None:
    """Hard/soft/contingency/closing cost line items from
    build_cash_flows()'s cost_breakdown — a real budget breakdown, not
    just the single total_dev_cost figure. When a trade-level estimate
    (modules.construction_budget_estimator) is also present on `uw`, its
    per-trade line items are appended below — purely additive; the 5-line
    summary above is always written unchanged, trade-budget or not."""
    sh = wb.create_sheet(f"{i}. Construction Budget"[:31])
    cb = uw["cost_breakdown"]
    bold_rows = [
        ("Acquisition Cost", cb.get("acquisition_cost", 0)),
        ("Closing Cost", cb.get("closing_cost", 0)),
        ("Hard Cost", cb.get("hard_cost", 0)),
        ("Soft Cost", cb.get("soft_cost", 0)),
        ("Contingency", cb.get("contingency", 0)),
        ("Total Development Cost", cb.get("total_dev_cost", 0)),
    ]
    sh.cell(row=1, column=1, value=f"{p.get('address', '')} — Construction Budget").font = header_font
    sh.merge_cells(start_row=1, start_column=1, end_row=1, end_column=2)
    row = 3
    for label, value in bold_rows:
        sh.cell(row=row, column=1, value=label)
        sh.cell(row=row, column=2, value=round(value or 0))
        row += 1
    sh.column_dimensions["A"].width = 26
    sh.column_dimensions["B"].width = 20

    trade_budget = uw.get("trade_budget")
    if trade_budget and trade_budget.get("trade_breakdown"):
        row += 2
        sh.cell(row=row, column=1, value="Trade-Level Detail").font = header_font
        row += 1
        sh.cell(row=row, column=1, value="Trade").fill = header_fill
        sh.cell(row=row, column=1).font = header_font
        sh.cell(row=row, column=2, value="Total").fill = header_fill
        sh.cell(row=row, column=2).font = header_font
        row += 1
        for trade, detail in trade_budget["trade_breakdown"].items():
            sh.cell(row=row, column=1, value=trade)
            sh.cell(row=row, column=2, value=round(detail.get("total", 0) or 0))
            row += 1


def _write_comps_sheet(wb, i: int, p: dict, comps: list[dict], header_fill, header_font) -> None:
    """The actual comps table (not just aggregate median/avg numbers)."""
    from openpyxl.styles import Alignment

    sh = wb.create_sheet(f"{i}. Comps"[:31])
    sh.cell(row=1, column=1, value=f"{p.get('address', '')} — Market Comps").font = header_font
    sh.merge_cells(start_row=1, start_column=1, end_row=1, end_column=6)

    headers = ["Address", "Price", "SF", "$/SF", "Asset Type", "Date"]
    for c, h in enumerate(headers, start=1):
        cell = sh.cell(row=3, column=c, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    for r, comp in enumerate(comps, start=4):
        sh.cell(row=r, column=1, value=comp.get("address", ""))
        sh.cell(row=r, column=2, value=comp.get("price") or "")
        sh.cell(row=r, column=3, value=comp.get("sqft") or "")
        sh.cell(row=r, column=4, value=comp.get("price_psf") or "")
        sh.cell(row=r, column=5, value=comp.get("asset_type", ""))
        sh.cell(row=r, column=6, value=comp.get("date", ""))

    for c, w in zip(range(1, 7), (36, 14, 12, 12, 18, 14)):
        sh.column_dimensions[chr(64 + c)].width = w


def _write_property_detail_sheet(sh, p: dict, header_fill, header_font,
                                  included_sections: dict[str, bool] | None = None) -> None:
    from openpyxl.styles import Font as _Font

    bold = _Font(bold=True)
    row = 1

    def _kv(label, value):
        nonlocal row
        sh.cell(row=row, column=1, value=label).font = bold
        sh.cell(row=row, column=2, value=value)
        row += 1

    sh.cell(row=row, column=1, value=p.get("address", "")).font = _Font(bold=True, size=14, color=_NAVY_HEX)
    row += 2

    _kv("BBL", p.get("bbl", ""))
    _kv("Borough", p.get("borough", ""))
    _kv("Lot SF", p.get("lot_sf", 0))
    _kv("Zoning District", p.get("zoning_dist", ""))
    _kv("Built FAR", round(p.get("far_built", 0), 2))
    _kv("Max FAR", round(p.get("far_max", 0), 2))
    _kv("Unused FAR %", f"{p.get('unused_far_pct', 0):.1f}%")
    row += 1

    ds = p.get("deal_score", {})
    _kv("Deal Score", f"{ds.get('score', '—')} / 100")
    _kv("Deal Tier", ds.get("tier", ""))
    opp = p.get("opportunity", {})
    _kv("Opportunity Score", f"{opp.get('score', '—')} / 100")
    _kv("Strategies", ", ".join(p.get("strategies", [])))
    row += 1

    if p.get("owner") and (included_sections is None or included_sections.get("ownership", True)):
        _kv("Owner", p.get("owner", ""))
        _kv("Owner Type", p.get("owner_type", ""))
        _kv("Last Sale Price", p.get("last_sale_price") or "—")
        _kv("Last Sale Date", p.get("last_sale_date") or "—")
        _kv("Active Mortgage", p.get("active_mortgage_amt") or "—")
        _kv("Open Liens", p.get("open_liens", 0))
        _kv("Distress Signal", p.get("distress_signal", "No Signal"))
        row += 1

    mc = p.get("market_comps")
    if mc and (included_sections is None or included_sections.get("market_comps", True)):
        _kv("Market Median $/SF", mc.get("median_price_psf") or "—")
        _kv("Market Comp Count", mc.get("count", 0))
        row += 1

    pipe = p.get("pipeline")
    if pipe:
        _kv("Nearby Pipeline Projects", pipe.get("count", 0))
        _kv("Nearby Pipeline Units", pipe.get("total_units", 0))
        row += 1

    uw = p.get("underwriting")
    if uw and (included_sections is None or included_sections.get("underwriting", True)):
        _kv("Underwriting Scenario", uw.get("scenario_label", ""))
        _kv("Total Dev. Cost", uw.get("total_dev_cost", ""))
        _kv("Year 1 NOI", uw.get("year1_noi", ""))
        _kv("Levered IRR", f"{uw['irr']:.1%}" if uw.get("irr") is not None else "—")
        _kv("Equity Multiple", f"{uw['equity_multiple']:.2f}x" if uw.get("equity_multiple") is not None else "—")
        if uw.get("equity_structure") == "waterfall":
            _kv("LP IRR", f"{uw['lp_irr']:.1%}" if uw.get("lp_irr") is not None else "—")
            _kv("GP IRR", f"{uw['gp_irr']:.1%}" if uw.get("gp_irr") is not None else "—")
            _kv("GP Promote ($)", uw.get("total_gp_promote", ""))

    for col, width in (("A", 24), ("B", 40)):
        sh.column_dimensions[col].width = width


# ── Fallback IC summary (no LLM required) ────────────────────────────────────

def compose_fallback_ic_summary(prop: dict) -> dict:
    """
    Auto-compose an ic_summary dict from signals already computed on
    `prop` — no Anthropic API key required. Exists because
    modules.site_finder_agents.run_investment_committee() (the only other
    ic_summary source in the app) requires an LLM call and is wired only
    into Site Finder; the Property Analysis tab's own PDF/PPTX export call
    sites previously always passed ic_summary=None, so their exports never
    included a Thesis/Risks/Next-Steps section at all. Deliberately
    simpler and more conservative than the LLM version — same shape
    (recommendation/thesis/key_risks/next_steps) so build_pdf_report()/
    build_pptx_report() need no changes to consume it.

    Never raises; degrades to a minimal "insufficient data" summary if
    the property dict is too thin to say anything specific.
    """
    try:
        ds = prop.get("deal_score") or {}
        score = ds.get("score")
        tier = ds.get("tier", "")

        if tier == "Strong Lead":
            recommendation = "GO"
        elif tier == "Watch":
            recommendation = "WATCH"
        elif tier:
            recommendation = "REJECT"
        else:
            recommendation = "WATCH"

        thesis: list[str] = []
        unused_pct = prop.get("unused_far_pct")
        if unused_pct:
            thesis.append(f"{unused_pct:.0f}% unused FAR relative to zoning max — development upside on the existing basis.")
        for s in prop.get("strategies", []):
            thesis.append(f"Development signal: {s}.")
        opp = prop.get("opportunity") or {}
        for d in opp.get("drivers", [])[:2]:
            thesis.append(d)
        if not thesis:
            thesis.append("Limited standout signals from the data checked so far — screen further before committing.")

        key_risks: list[str] = []
        distress = prop.get("distress_signal")
        if distress and distress != "No Signal":
            key_risks.append(f"Distress signal on record: {distress} — review ACRIS/DOB history before underwriting.")
        rentstab = prop.get("rent_stab_signal") or {}
        if rentstab.get("likely_stabilized"):
            key_risks.append("Likely rent-stabilized — may constrain rent upside or conversion/demolition strategy.")
        if not key_risks:
            key_risks.append("No elevated distress or regulatory flags found in the data checked so far — confirm independently.")

        next_steps = [
            "Confirm zoning and buildable envelope directly with NYC Planning / ZOLA.",
            "Order a title report and full ACRIS ownership/lien history.",
        ]
        if not prop.get("underwriting"):
            next_steps.append("Run the Underwriting Pro Forma to size acquisition, financing, and target returns.")
        if rentstab.get("likely_stabilized") is None and not rentstab:
            next_steps.append("Confirm rent-stabilization status via the DHCR building list.")

        return {
            "recommendation": recommendation,
            "thesis": thesis,
            "key_risks": key_risks,
            "key_unknowns": [],
            "next_steps": next_steps,
            "source": "auto-composed (no LLM) — see modules.site_finder_agents for the AI-generated version",
        }
    except Exception:
        return {
            "recommendation": "WATCH",
            "thesis": ["Insufficient data to compose a thesis — screen further."],
            "key_risks": ["Insufficient data to identify risks — screen further."],
            "key_unknowns": [],
            "next_steps": ["Confirm zoning, ownership, and financial basis before proceeding."],
            "source": "auto-composed (no LLM) — fallback",
        }


# ── PDF: single-property investment report ──────────────────────────────────

def build_pdf_report(prop: dict, ic_summary: dict | None = None,
                      included_sections: dict[str, bool] | None = None) -> bytes:
    """
    Build a single-property PDF investment screening report with an
    institutional-memo layout: a letterhead-style header band repeated on
    every page, a cover metrics strip, ruled section dividers, and a
    running footer with page numbers and the generation date.

    included_sections: optional dict of section-key -> bool controlling
        which sections render (keys: "thesis", "zoning", "ownership",
        "business_plan", "underwriting", plus the newer "distress",
        "tax_abatement_rent_stab", "market_comps"). None (the default)
        means "include everything already present on `prop`" — 100%
        backward compatible with every existing caller that doesn't pass
        this argument (e.g. modules/site_finder_ui.py). The three newer
        section keys only ever render when included_sections is
        explicitly provided (not None), so callers that never opt into
        this parameter see byte-identical output to before this feature
        existed, regardless of what extra keys happen to be present on
        their `prop` dict.

    Returns raw .pdf bytes.
    """
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib.enums import TA_RIGHT
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
        )
    except ImportError as exc:
        raise ImportError("Install `reportlab` to enable PDF export: pip install reportlab") from exc

    NAVY = colors.HexColor(f"#{_NAVY_HEX}")
    NAVY_DARK = colors.HexColor(f"#{_NAVY_DARK_HEX}")
    GRAY = colors.HexColor(f"#{_GRAY_HEX}")
    LIGHT_GRAY = colors.HexColor(f"#{_LIGHT_GRAY_HEX}")
    BORDER = colors.HexColor(f"#{_BORDER_HEX}")

    address = prop.get("address", "Property")
    generated = _generated_stamp()

    def _header_footer(canvas, doc):
        canvas.saveState()
        page_w, page_h = letter
        # Letterhead band
        canvas.setFillColor(NAVY_DARK)
        canvas.rect(0, page_h - 0.42 * inch, page_w, 0.42 * inch, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawString(0.6 * inch, page_h - 0.29 * inch, "CONFIDENTIAL — INVESTMENT SCREENING MEMORANDUM")
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(page_w - 0.6 * inch, page_h - 0.29 * inch, address[:60])
        # Footer rule + page number
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(0.6 * inch, 0.55 * inch, page_w - 0.6 * inch, 0.55 * inch)
        canvas.setFillColor(GRAY)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(0.6 * inch, 0.38 * inch, f"Generated {generated}")
        canvas.drawRightString(page_w - 0.6 * inch, 0.38 * inch, f"Page {doc.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
        leftMargin=0.6 * inch, rightMargin=0.6 * inch,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleNavy", parent=styles["Title"], textColor=NAVY, spaceAfter=2)
    kicker = ParagraphStyle("Kicker", parent=styles["Normal"], textColor=GRAY,
                             fontSize=8, leading=10, spaceAfter=4,
                             fontName="Helvetica-Bold")
    h2 = ParagraphStyle("H2Navy", parent=styles["Heading2"], textColor=NAVY, spaceBefore=4)
    body = styles["Normal"]
    italic_caption = ParagraphStyle("ItalicCaption", parent=styles["Italic"], textColor=GRAY, fontSize=8.5)

    def _divider():
        return HRFlowable(width="100%", thickness=0.75, color=BORDER, spaceBefore=4, spaceAfter=12)

    story = []
    story.append(Paragraph("INVESTMENT SCREENING MEMORANDUM", kicker))
    story.append(Paragraph(address, title_style))
    story.append(Paragraph(
        f"BBL {prop.get('bbl', '—')} &nbsp;·&nbsp; {prop.get('borough', '—')} &nbsp;·&nbsp; "
        f"Block {prop.get('block', '—')} Lot {prop.get('lot', '—')} &nbsp;·&nbsp; Prepared {generated}",
        body,
    ))
    story.append(Spacer(1, 14))

    ds = prop.get("deal_score", {})
    rec = (ic_summary or {}).get("recommendation", "—")
    plan = prop.get("business_plan")
    acq_val = plan["acquisition"]["estimate"] if plan and plan.get("acquisition") else None
    headline_labels = ["DEAL SCORE", "RECOMMENDATION", "EST. ACQUISITION", "UNUSED FAR"]
    headline_values = [
        f"{ds.get('score', '—')}/100 ({ds.get('tier', '—')})", rec,
        f"${acq_val:,.0f}" if acq_val else "—", f"{prop.get('unused_far_pct', 0):.0f}%",
    ]
    t = Table([headline_labels, headline_values], colWidths=[1.68 * inch] * 4)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 1), (-1, 1), LIGHT_GRAY),
        ("TEXTCOLOR", (0, 1), (-1, 1), NAVY_DARK),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTSIZE", (0, 1), (-1, 1), 12),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("BOX", (0, 0), (-1, -1), 0.75, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 10),
        ("TOPPADDING", (0, 1), (-1, 1), 10),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))

    story.append(Paragraph(
        "⚠️ Preliminary screening output only — not a zoning opinion, appraisal, "
        "title report, environmental assessment, or substitute for professional "
        "diligence.", italic_caption,
    ))
    story.append(_divider())

    _sec = lambda key: included_sections is None or included_sections.get(key, True)

    if ic_summary and _sec("thesis"):
        story.append(Paragraph("INVESTMENT THESIS", kicker))
        story.append(Paragraph("Investment Thesis", h2))
        for bullet in ic_summary.get("thesis", []):
            story.append(Paragraph(f"• {bullet}", body))
        story.append(Spacer(1, 10))

        story.append(Paragraph("Key Risks", h2))
        for r in ic_summary.get("key_risks", []):
            story.append(Paragraph(f"• {r}", body))
        story.append(Spacer(1, 10))

        story.append(Paragraph("Key Unknowns / Next Diligence Steps", h2))
        for u in ic_summary.get("next_steps", []):
            story.append(Paragraph(f"• {u}", body))
        story.append(_divider())

    if _sec("zoning"):
        story.append(Paragraph("ZONING & ENTITLEMENT", kicker))
        story.append(Paragraph("Zoning Summary", h2))
        zdist = prop.get("zoning_dist", "—")
        story.append(Paragraph(
            f"District: {zdist} &nbsp;·&nbsp; Built FAR: {prop.get('far_built', 0):.2f} "
            f"&nbsp;·&nbsp; Max FAR (PLUTO): {prop.get('far_max', 0):.2f}",
            body,
        ))
        story.append(Spacer(1, 10))

    if prop.get("owner") and _sec("ownership"):
        story.append(Paragraph("Ownership", h2))
        story.append(Paragraph(
            f"Owner: {prop.get('owner', '—')} ({prop.get('owner_type', 'Unknown')}) &nbsp;·&nbsp; "
            f"Last Sale: {prop.get('last_sale_price') or '—'} on {prop.get('last_sale_date') or '—'} "
            f"&nbsp;·&nbsp; Distress Signal: {prop.get('distress_signal', 'No Signal')}",
            body,
        ))
        story.append(_divider())

    if plan and _sec("business_plan"):
        story.append(Paragraph("ACQUISITION & DEVELOPMENT ECONOMICS", kicker))
        profit_str = f"${plan['profit']:,.0f}" if plan["profit"] is not None else "—"
        margin_str = f"{plan['margin_pct']:.0f}%" if plan["margin_pct"] is not None else "—"
        story.append(Paragraph("Preliminary Acquisition Estimate & Business Plan", h2))
        story.append(Paragraph(f"Basis: {plan['acquisition']['basis']}", body))
        story.append(Paragraph(
            f"Est. total development cost: ${plan['total_dev_cost']:,.0f} &nbsp;·&nbsp; "
            f"Est. profit: {profit_str} &nbsp;·&nbsp; Margin: {margin_str}",
            body,
        ))
        for bullet in plan.get("bullets", []):
            story.append(Paragraph(f"• {bullet}", body))
        story.append(Paragraph(
            "Free-data screening estimate only — not underwriting, an appraisal, "
            "or a GC cost estimate.", italic_caption,
        ))
        story.append(_divider())

    uw = prop.get("underwriting")
    if uw and _sec("underwriting"):
        story.append(Paragraph("UNDERWRITING", kicker))
        story.append(Paragraph("Underwriting Pro Forma", h2))
        story.append(Paragraph(f"Scenario: {uw.get('scenario_label', '—')}", body))
        irr_str = f"{uw['irr']:.1%}" if uw.get("irr") is not None else "N/A"
        em_str = f"{uw['equity_multiple']:.2f}x" if uw.get("equity_multiple") is not None else "N/A"

        uw_labels = ["LEVERED IRR", "EQUITY MULTIPLE", "TOTAL DEV. COST", "YEAR 1 NOI"]
        uw_values = [irr_str, em_str, f"${uw.get('total_dev_cost', 0):,.0f}", f"${uw.get('year1_noi', 0):,.0f}"]
        uw_table = Table([uw_labels, uw_values], colWidths=[1.68 * inch] * 4)
        uw_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), LIGHT_GRAY),
            ("TEXTCOLOR", (0, 0), (-1, 0), GRAY),
            ("TEXTCOLOR", (0, 1), (-1, 1), NAVY_DARK),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 7.5),
            ("FONTSIZE", (0, 1), (-1, 1), 11),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("BOX", (0, 0), (-1, -1), 0.75, BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(uw_table)
        story.append(Spacer(1, 8))

        if uw.get("equity_structure") == "waterfall":
            lp_irr = f"{uw['lp_irr']:.1%}" if uw.get("lp_irr") is not None else "N/A"
            gp_irr = f"{uw['gp_irr']:.1%}" if uw.get("gp_irr") is not None else "N/A"
            story.append(Paragraph(
                f"LP/GP Waterfall — LP IRR: {lp_irr} &nbsp;·&nbsp; GP IRR: {gp_irr} &nbsp;·&nbsp; "
                f"GP Promote: ${uw.get('total_gp_promote', 0):,.0f}",
                body,
            ))
        story.append(Paragraph(
            "Preliminary underwriting model — a hand-rolled deterministic pro forma, "
            "not a lender-grade or GP-facing underwriting package.", italic_caption,
        ))

    # ── New sections below: only ever render when a caller explicitly opts
    # into included_sections (i.e. is not None) — this keeps every existing
    # caller's output byte-for-byte identical regardless of what extra keys
    # happen to be present on their `prop` dict (see build_pdf_report's
    # docstring for the full compatibility contract). ──────────────────────

    cd = prop.get("composite_distress")
    if cd and included_sections is not None and included_sections.get("distress", True):
        story.append(_divider())
        story.append(Paragraph("DISTRESS SIGNALS", kicker))
        story.append(Paragraph("Distress Signals", h2))
        story.append(Paragraph(
            f"Composite Distress Score: {cd.get('score', '—')}/100 ({cd.get('tier', '—')})", body,
        ))
        for comp, comp_detail in (cd.get("breakdown") or {}).items():
            story.append(Paragraph(f"• {comp.upper()}: {comp_detail.get('reasoning', '—')}", body))

    ta = prop.get("tax_abatement")
    rs = prop.get("rent_stab_signal")
    if (ta or rs) and included_sections is not None and included_sections.get("tax_abatement_rent_stab", True):
        story.append(_divider())
        story.append(Paragraph("TAX ABATEMENT & RENT STABILIZATION", kicker))
        story.append(Paragraph("Tax Abatement & Rent Stabilization", h2))
        if ta:
            story.append(Paragraph(
                f"Tax Abatement: {ta.get('program', ta.get('label', '—'))} "
                f"&nbsp;·&nbsp; {ta.get('summary', ta.get('notes', '—'))}", body,
            ))
        if rs:
            likely = "Likely Rent Stabilized" if rs.get("likely_stabilized") else "Unlikely Rent Stabilized"
            conf = rs.get("confidence")
            story.append(Paragraph(
                f"Rent Stabilization: {likely}" + (f" ({conf:.0%} confidence)" if conf is not None else ""),
                body,
            ))

    mkt = prop.get("market_comps")
    if mkt and included_sections is not None and included_sections.get("market_comps", True):
        story.append(_divider())
        story.append(Paragraph("MARKET COMPARABLES", kicker))
        story.append(Paragraph("Market Comps", h2))
        comps_list = mkt.get("comps") or []
        if comps_list:
            comp_rows = [["Address", "Price", "SF", "$/SF"]]
            for c in comps_list[:8]:
                comp_rows.append([
                    str(c.get("address", "—"))[:30],
                    f"${c['price']:,.0f}" if c.get("price") else "—",
                    f"{c['sqft']:,.0f}" if c.get("sqft") else "—",
                    f"${c['price_psf']:,.0f}" if c.get("price_psf") else "—",
                ])
            comp_table = Table(comp_rows, colWidths=[2.6 * inch, 1.2 * inch, 1.0 * inch, 1.0 * inch])
            comp_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GRAY]),
                ("BOX", (0, 0), (-1, -1), 0.75, BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(comp_table)
        else:
            story.append(Paragraph(
                f"{mkt.get('count', 0)} comparable(s) found &nbsp;·&nbsp; "
                f"Median $/SF: {mkt.get('median_price_psf', '—')}", body,
            ))

    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return buf.getvalue()


# ── PowerPoint: single-property pitch deck ──────────────────────────────────

def build_pptx_report(prop: dict, ic_summary: dict | None = None,
                       included_sections: dict[str, bool] | None = None) -> bytes:
    """
    Build a single-property PowerPoint investment pitch deck with an
    institutional design: a full-bleed navy cover band, rounded metric
    tiles, consistent footers/slide numbers on every slide, and a closing
    disclaimer slide.

    included_sections: same contract as build_pdf_report()'s parameter of
        the same name — None (default) means "include everything already
        present on `prop`," fully backward compatible with every existing
        caller. The newer "distress"/"tax_abatement_rent_stab"/
        "market_comps" slides only ever render when included_sections is
        explicitly provided (not None).

    Returns raw .pptx bytes.
    """
    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt, Emu
        from pptx.dml.color import RGBColor
        from pptx.enum.text import PP_ALIGN
        from pptx.enum.shapes import MSO_SHAPE
        from pptx.oxml.ns import qn
    except ImportError as exc:
        raise ImportError("Install `python-pptx` to enable PowerPoint export: pip install python-pptx") from exc

    NAVY = RGBColor.from_string(_NAVY_HEX)
    NAVY_DARK = RGBColor.from_string(_NAVY_DARK_HEX)
    GRAY = RGBColor.from_string(_GRAY_HEX)
    LIGHT_GRAY = RGBColor.from_string(_LIGHT_GRAY_HEX)
    BORDER = RGBColor.from_string(_BORDER_HEX)
    WHITE = RGBColor(0xFF, 0xFF, 0xFF)

    prs = Presentation()
    prs.slide_width = Inches(13.33)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]
    generated = _generated_stamp()
    address = prop.get("address", "Property")

    def _no_line(shape):
        shape.line.fill.background()

    def _add_footer(slide, label: str):
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(7.16), Inches(13.33), Inches(0.34))
        bar.fill.solid()
        bar.fill.fore_color.rgb = LIGHT_GRAY
        _no_line(bar)
        bar.shadow.inherit = False
        tf = bar.text_frame
        tf.margin_top = Emu(0)
        tf.margin_bottom = Emu(0)
        p = tf.paragraphs[0]
        p.text = f"CONFIDENTIAL — {label}  ·  Generated {generated}"
        p.font.size = Pt(8.5)
        p.font.color.rgb = GRAY
        p.alignment = PP_ALIGN.LEFT
        tf.margin_left = Inches(0.6)

    def _add_metric_tile(slide, x, y, w, h, label: str, value: str):
        tile = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h)
        tile.adjustments[0] = 0.08
        tile.fill.solid()
        tile.fill.fore_color.rgb = NAVY
        _no_line(tile)
        tile.shadow.inherit = False
        tf = tile.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = 3  # MSO_ANCHOR.MIDDLE would need enum import; 3 = middle
        p1 = tf.paragraphs[0]
        p1.text = value
        p1.font.size = Pt(26)
        p1.font.bold = True
        p1.font.color.rgb = WHITE
        p1.alignment = PP_ALIGN.CENTER
        p2 = tf.add_paragraph()
        p2.text = label
        p2.font.size = Pt(10.5)
        p2.font.color.rgb = RGBColor(0xBF, 0xDB, 0xFE)
        p2.alignment = PP_ALIGN.CENTER
        return tile

    # ── Slide 1: Cover ──────────────────────────────────────────────────────
    slide = prs.slides.add_slide(blank)
    band = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.33), Inches(2.35))
    band.fill.solid()
    band.fill.fore_color.rgb = NAVY_DARK
    _no_line(band)
    band.shadow.inherit = False
    accent = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(2.35), Inches(13.33), Inches(0.06))
    accent.fill.solid()
    accent.fill.fore_color.rgb = NAVY
    _no_line(accent)
    accent.shadow.inherit = False

    kicker = slide.shapes.add_textbox(Inches(0.6), Inches(0.35), Inches(12), Inches(0.4))
    kicker.text_frame.text = "INVESTMENT SCREENING MEMORANDUM"
    kicker.text_frame.paragraphs[0].font.size = Pt(12)
    kicker.text_frame.paragraphs[0].font.bold = True
    kicker.text_frame.paragraphs[0].font.color.rgb = RGBColor(0x93, 0xC5, 0xFD)

    tb = slide.shapes.add_textbox(Inches(0.6), Inches(0.75), Inches(12), Inches(1.0))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.text = address
    tf.paragraphs[0].font.size = Pt(34)
    tf.paragraphs[0].font.bold = True
    tf.paragraphs[0].font.color.rgb = WHITE

    sub = slide.shapes.add_textbox(Inches(0.6), Inches(1.62), Inches(12), Inches(0.5))
    sub.text_frame.text = f"BBL {prop.get('bbl', '—')}  ·  {prop.get('borough', '—')}  ·  Prepared {generated}"
    sub.text_frame.paragraphs[0].font.size = Pt(14)
    sub.text_frame.paragraphs[0].font.color.rgb = RGBColor(0xBF, 0xDB, 0xFE)

    ds = prop.get("deal_score", {})
    plan = prop.get("business_plan")
    acq_val = plan["acquisition"]["estimate"] if plan and plan.get("acquisition") else None
    metrics = [
        ("DEAL SCORE", f"{ds.get('score', '—')}/100"),
        ("TIER", ds.get("tier", "—")),
        ("EST. ACQUISITION", f"${acq_val:,.0f}" if acq_val else "—"),
        ("UNUSED FAR", f"{prop.get('unused_far_pct', 0):.0f}%"),
    ]
    x = Inches(0.6)
    for label, val in metrics:
        _add_metric_tile(slide, x, Inches(2.85), Inches(2.9), Inches(1.35), label, val)
        x += Inches(3.08)

    if ic_summary and ic_summary.get("recommendation"):
        rec = ic_summary["recommendation"]
        rec_color = {"GO": RGBColor(0x15, 0x80, 0x3D), "WATCH": RGBColor(0xB4, 0x53, 0x09),
                     "REJECT": RGBColor(0xDC, 0x26, 0x26)}.get(rec, GRAY)
        rec_box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.6), Inches(4.55), Inches(4.2), Inches(0.6))
        rec_box.adjustments[0] = 0.15
        rec_box.fill.solid()
        rec_box.fill.fore_color.rgb = rec_color
        _no_line(rec_box)
        rec_box.shadow.inherit = False
        rtf = rec_box.text_frame
        rtf.vertical_anchor = 3
        rp = rtf.paragraphs[0]
        rp.text = f"RECOMMENDATION: {rec}"
        rp.font.size = Pt(15)
        rp.font.bold = True
        rp.font.color.rgb = WHITE
        rp.alignment = PP_ALIGN.CENTER

    disclaimer = slide.shapes.add_textbox(Inches(0.6), Inches(6.6), Inches(12), Inches(0.5))
    disclaimer.text_frame.text = (
        "Preliminary screening output only — not a zoning opinion, appraisal, "
        "title report, or substitute for professional diligence."
    )
    disclaimer.text_frame.paragraphs[0].font.size = Pt(9.5)
    disclaimer.text_frame.paragraphs[0].font.italic = True
    disclaimer.text_frame.paragraphs[0].font.color.rgb = GRAY

    _sec = lambda key: included_sections is None or included_sections.get(key, True)

    # ── Slide 2: Investment thesis / risks / next steps ─────────────────────
    if ic_summary and _sec("thesis"):
        slide2 = prs.slides.add_slide(blank)
        title = slide2.shapes.add_textbox(Inches(0.6), Inches(0.35), Inches(12), Inches(0.6))
        title.text_frame.text = "Investment Thesis & Risks"
        title.text_frame.paragraphs[0].font.size = Pt(26)
        title.text_frame.paragraphs[0].font.bold = True
        title.text_frame.paragraphs[0].font.color.rgb = NAVY
        rule = slide2.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.6), Inches(0.98), Inches(2.2), Pt(3))
        rule.fill.solid(); rule.fill.fore_color.rgb = NAVY; _no_line(rule); rule.shadow.inherit = False

        col1 = slide2.shapes.add_textbox(Inches(0.6), Inches(1.35), Inches(5.8), Inches(5.5))
        f1 = col1.text_frame
        f1.word_wrap = True
        f1.text = "Investment Thesis"
        f1.paragraphs[0].font.bold = True
        f1.paragraphs[0].font.size = Pt(17)
        f1.paragraphs[0].font.color.rgb = NAVY
        for bullet in ic_summary.get("thesis", []):
            p = f1.add_paragraph()
            p.text = f"• {bullet}"
            p.font.size = Pt(13)

        col2 = slide2.shapes.add_textbox(Inches(6.8), Inches(1.35), Inches(5.8), Inches(5.5))
        f2 = col2.text_frame
        f2.word_wrap = True
        f2.text = "Key Risks"
        f2.paragraphs[0].font.bold = True
        f2.paragraphs[0].font.size = Pt(17)
        f2.paragraphs[0].font.color.rgb = NAVY
        for r in ic_summary.get("key_risks", []):
            p = f2.add_paragraph()
            p.text = f"• {r}"
            p.font.size = Pt(13)

        _add_footer(slide2, "INVESTMENT THESIS & RISKS")

    # ── Slide 3: Preliminary Acquisition Estimate & Business Plan ───────────
    if plan and _sec("business_plan"):
        slide3 = prs.slides.add_slide(blank)
        title3 = slide3.shapes.add_textbox(Inches(0.6), Inches(0.35), Inches(12), Inches(0.6))
        title3.text_frame.text = "Preliminary Acquisition Estimate & Business Plan"
        title3.text_frame.paragraphs[0].font.size = Pt(24)
        title3.text_frame.paragraphs[0].font.bold = True
        title3.text_frame.paragraphs[0].font.color.rgb = NAVY
        rule3 = slide3.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.6), Inches(0.98), Inches(2.2), Pt(3))
        rule3.fill.solid(); rule3.fill.fore_color.rgb = NAVY; _no_line(rule3); rule3.shadow.inherit = False

        profit_str = f"${plan['profit']:,.0f}" if plan["profit"] is not None else "—"
        margin_str = f"{plan['margin_pct']:.0f}%" if plan["margin_pct"] is not None else "—"
        bp_metrics = [
            ("EST. ACQUISITION", f"${acq_val:,.0f}" if acq_val else "—"),
            ("EST. TOTAL COST", f"${plan['total_dev_cost']:,.0f}"),
            ("EST. PROFIT", profit_str),
            ("EST. MARGIN", margin_str),
        ]
        x = Inches(0.6)
        for label, val in bp_metrics:
            _add_metric_tile(slide3, x, Inches(1.35), Inches(2.9), Inches(1.15), label, val)
            x += Inches(3.08)

        body = slide3.shapes.add_textbox(Inches(0.6), Inches(2.75), Inches(12), Inches(3.9))
        fb = body.text_frame
        fb.word_wrap = True
        fb.text = f"Basis: {plan['acquisition']['basis']}"
        fb.paragraphs[0].font.size = Pt(13)
        fb.paragraphs[0].font.italic = True
        fb.paragraphs[0].font.color.rgb = GRAY
        for bullet in plan.get("bullets", []):
            p = fb.add_paragraph()
            p.text = f"• {bullet}"
            p.font.size = Pt(14)

        note = slide3.shapes.add_textbox(Inches(0.6), Inches(6.55), Inches(12), Inches(0.4))
        note.text_frame.text = "Free-data screening estimate only — not underwriting, an appraisal, or a GC cost estimate."
        note.text_frame.paragraphs[0].font.size = Pt(9.5)
        note.text_frame.paragraphs[0].font.italic = True
        note.text_frame.paragraphs[0].font.color.rgb = GRAY

        _add_footer(slide3, "ACQUISITION & BUSINESS PLAN")

    # ── Slide 4: Underwriting Pro Forma ──────────────────────────────────────
    uw = prop.get("underwriting")
    if uw and _sec("underwriting"):
        slide4 = prs.slides.add_slide(blank)
        title4 = slide4.shapes.add_textbox(Inches(0.6), Inches(0.35), Inches(12), Inches(0.6))
        title4.text_frame.text = "Underwriting Pro Forma"
        title4.text_frame.paragraphs[0].font.size = Pt(24)
        title4.text_frame.paragraphs[0].font.bold = True
        title4.text_frame.paragraphs[0].font.color.rgb = NAVY
        rule4 = slide4.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.6), Inches(0.98), Inches(2.2), Pt(3))
        rule4.fill.solid(); rule4.fill.fore_color.rgb = NAVY; _no_line(rule4); rule4.shadow.inherit = False

        irr_str = f"{uw['irr']:.1%}" if uw.get("irr") is not None else "N/A"
        em_str = f"{uw['equity_multiple']:.2f}x" if uw.get("equity_multiple") is not None else "N/A"
        uw_metrics = [
            ("LEVERED IRR", irr_str),
            ("EQUITY MULTIPLE", em_str),
            ("TOTAL DEV. COST", f"${uw.get('total_dev_cost', 0):,.0f}"),
            ("SCENARIO", uw.get("scenario_label", "—")),
        ]
        x = Inches(0.6)
        for label, val in uw_metrics:
            _add_metric_tile(slide4, x, Inches(1.35), Inches(2.9), Inches(1.35), label, val)
            x += Inches(3.08)

        body4 = slide4.shapes.add_textbox(Inches(0.6), Inches(2.95), Inches(12), Inches(3.3))
        fb4 = body4.text_frame
        fb4.word_wrap = True
        if uw.get("equity_structure") == "waterfall":
            lp_irr = f"{uw['lp_irr']:.1%}" if uw.get("lp_irr") is not None else "N/A"
            gp_irr = f"{uw['gp_irr']:.1%}" if uw.get("gp_irr") is not None else "N/A"
            fb4.text = "LP/GP Waterfall"
            fb4.paragraphs[0].font.bold = True
            fb4.paragraphs[0].font.size = Pt(16)
            fb4.paragraphs[0].font.color.rgb = NAVY
            for line in (
                f"LP IRR: {lp_irr}  ·  GP IRR: {gp_irr}",
                f"GP Promote: ${uw.get('total_gp_promote', 0):,.0f}",
            ):
                p = fb4.add_paragraph()
                p.text = f"• {line}"
                p.font.size = Pt(14)
        else:
            fb4.text = "Simple Sponsor IRR — single all-equity-in/all-cash-out perspective."
            fb4.paragraphs[0].font.size = Pt(14)

        note4 = slide4.shapes.add_textbox(Inches(0.6), Inches(6.55), Inches(12), Inches(0.4))
        note4.text_frame.text = (
            "Preliminary underwriting model — a hand-rolled deterministic pro forma, "
            "not a lender-grade or GP-facing underwriting package."
        )
        note4.text_frame.paragraphs[0].font.size = Pt(9.5)
        note4.text_frame.paragraphs[0].font.italic = True
        note4.text_frame.paragraphs[0].font.color.rgb = GRAY

        _add_footer(slide4, "UNDERWRITING PRO FORMA")

    # ── New slides below: only ever render when a caller explicitly opts
    # into included_sections (i.e. is not None) — same compatibility
    # contract as the new PDF sections above. ───────────────────────────────

    def _add_bullet_slide(title_text: str, footer_label: str, lines: list[str]):
        """Shared layout for the three new slides below — title + navy
        rule (matching the existing slide2/3/4 pattern exactly) + a bullet
        list body + footer."""
        slide = prs.slides.add_slide(blank)
        title = slide.shapes.add_textbox(Inches(0.6), Inches(0.35), Inches(12), Inches(0.6))
        title.text_frame.text = title_text
        title.text_frame.paragraphs[0].font.size = Pt(24)
        title.text_frame.paragraphs[0].font.bold = True
        title.text_frame.paragraphs[0].font.color.rgb = NAVY
        rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.6), Inches(0.98), Inches(2.2), Pt(3))
        rule.fill.solid(); rule.fill.fore_color.rgb = NAVY; _no_line(rule); rule.shadow.inherit = False

        body_box = slide.shapes.add_textbox(Inches(0.6), Inches(1.35), Inches(12), Inches(5.5))
        fb = body_box.text_frame
        fb.word_wrap = True
        if lines:
            fb.text = f"• {lines[0]}"
            fb.paragraphs[0].font.size = Pt(14)
            for line in lines[1:]:
                p = fb.add_paragraph()
                p.text = f"• {line}"
                p.font.size = Pt(14)
        _add_footer(slide, footer_label)
        return slide

    cd = prop.get("composite_distress")
    if cd and included_sections is not None and included_sections.get("distress", True):
        lines = [f"Composite Distress Score: {cd.get('score', '—')}/100 ({cd.get('tier', '—')})"]
        for comp, comp_detail in (cd.get("breakdown") or {}).items():
            lines.append(f"{comp.upper()}: {comp_detail.get('reasoning', '—')}")
        _add_bullet_slide("Distress Signals", "DISTRESS SIGNALS", lines)

    ta = prop.get("tax_abatement")
    rs = prop.get("rent_stab_signal")
    if (ta or rs) and included_sections is not None and included_sections.get("tax_abatement_rent_stab", True):
        lines = []
        if ta:
            lines.append(f"Tax Abatement: {ta.get('program', ta.get('label', '—'))} — {ta.get('summary', ta.get('notes', '—'))}")
        if rs:
            likely = "Likely Rent Stabilized" if rs.get("likely_stabilized") else "Unlikely Rent Stabilized"
            conf = rs.get("confidence")
            lines.append(f"Rent Stabilization: {likely}" + (f" ({conf:.0%} confidence)" if conf is not None else ""))
        _add_bullet_slide("Tax Abatement & Rent Stabilization", "TAX ABATEMENT & RENT STABILIZATION", lines)

    mkt = prop.get("market_comps")
    if mkt and included_sections is not None and included_sections.get("market_comps", True):
        comps_list = mkt.get("comps") or []
        if comps_list:
            lines = [
                f"{c.get('address', '—')} — "
                f"{('$' + format(c['price'], ',.0f')) if c.get('price') else '—'} "
                f"({('$' + format(c['price_psf'], ',.0f') + '/SF') if c.get('price_psf') else '—'})"
                for c in comps_list[:8]
            ]
        else:
            lines = [f"{mkt.get('count', 0)} comparable(s) found", f"Median $/SF: {mkt.get('median_price_psf', '—')}"]
        _add_bullet_slide("Market Comps", "MARKET COMPARABLES", lines)

    # ── Closing slide ─────────────────────────────────────────────────────
    slide5 = prs.slides.add_slide(blank)
    band5 = slide5.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.33), Inches(7.5))
    band5.fill.solid()
    band5.fill.fore_color.rgb = NAVY_DARK
    _no_line(band5)
    band5.shadow.inherit = False
    close_tb = slide5.shapes.add_textbox(Inches(1.2), Inches(2.9), Inches(10.9), Inches(1.0))
    close_tb.text_frame.text = "Thank You"
    close_tb.text_frame.paragraphs[0].font.size = Pt(40)
    close_tb.text_frame.paragraphs[0].font.bold = True
    close_tb.text_frame.paragraphs[0].font.color.rgb = WHITE
    close_sub = slide5.shapes.add_textbox(Inches(1.2), Inches(3.75), Inches(10.9), Inches(2.0))
    csf = close_sub.text_frame
    csf.word_wrap = True
    csf.text = address
    csf.paragraphs[0].font.size = Pt(16)
    csf.paragraphs[0].font.color.rgb = RGBColor(0xBF, 0xDB, 0xFE)
    p_disc = csf.add_paragraph()
    p_disc.text = (
        "This document is a preliminary, free-public-data screening output prepared "
        "for internal discussion purposes only. It does not constitute a zoning "
        "opinion, appraisal, title report, environmental assessment, offering "
        "memorandum, or substitute for professional diligence. All figures are "
        "estimates and subject to change upon further underwriting."
    )
    p_disc.font.size = Pt(10.5)
    p_disc.font.italic = True
    p_disc.font.color.rgb = RGBColor(0x93, 0xA3, 0xB8)
    p_disc.space_before = Pt(18)

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()

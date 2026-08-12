"""
Report Exporter — Site Finder Phase 3/4.

Builds downloadable Excel (results workbook), PDF, and PowerPoint
(single-property investment summary) exports. All functions return raw
bytes so callers can hand them directly to st.download_button without
touching the filesystem.

Optional dependencies (see requirements.txt): openpyxl, reportlab,
python-pptx. Each builder function raises ImportError with a clear
pip-install hint if its library is missing, so the calling UI can show
a friendly message instead of crashing.
"""

from __future__ import annotations
import io


# ── Excel: full results workbook ────────────────────────────────────────────

def build_excel_workbook(properties: list[dict], top_n_detail: int = 20) -> bytes:
    """
    Build an Excel workbook with:
      - "Summary" sheet: all ranked properties, one row each
      - One sheet per property (up to top_n_detail) with zoning/ownership/
        market detail, for whichever properties carry that enrichment data

    Returns raw .xlsx bytes.
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter
    except ImportError as exc:
        raise ImportError("Install `openpyxl` to enable Excel export: pip install openpyxl") from exc

    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"

    header_fill = PatternFill(start_color="1A3A6B", end_color="1A3A6B", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)

    headers = [
        "Rank", "Address", "Borough", "BBL", "Lot SF", "Built FAR", "Max FAR",
        "Unused FAR %", "Strategy", "Owner", "Owner Type", "Last Sale Price",
        "Last Sale Date", "Distress Signal", "Deal Score", "Tier",
    ]
    ws.append(headers)
    for c in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    for i, p in enumerate(properties, start=1):
        ds = p.get("deal_score", {})
        ws.append([
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
            ds.get("tier", ""),
        ])

    for c in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(c)].width = 18
    ws.freeze_panes = "A2"

    # Per-property detail sheets for the top N
    for i, p in enumerate(properties[:top_n_detail], start=1):
        sheet_name = f"{i}. {p.get('bbl', '')}"[:31]  # Excel sheet name limit
        sh = wb.create_sheet(sheet_name)
        _write_property_detail_sheet(sh, p, header_fill, header_font)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _write_property_detail_sheet(sh, p: dict, header_fill, header_font) -> None:
    from openpyxl.styles import Font as _Font

    bold = _Font(bold=True)
    row = 1

    def _kv(label, value):
        nonlocal row
        sh.cell(row=row, column=1, value=label).font = bold
        sh.cell(row=row, column=2, value=value)
        row += 1

    sh.cell(row=row, column=1, value=p.get("address", "")).font = _Font(bold=True, size=14)
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

    if p.get("owner"):
        _kv("Owner", p.get("owner", ""))
        _kv("Owner Type", p.get("owner_type", ""))
        _kv("Last Sale Price", p.get("last_sale_price") or "—")
        _kv("Last Sale Date", p.get("last_sale_date") or "—")
        _kv("Active Mortgage", p.get("active_mortgage_amt") or "—")
        _kv("Open Liens", p.get("open_liens", 0))
        _kv("Distress Signal", p.get("distress_signal", "No Signal"))
        row += 1

    mc = p.get("market_comps")
    if mc:
        _kv("Market Median $/SF", mc.get("median_price_psf") or "—")
        _kv("Market Comp Count", mc.get("count", 0))
        row += 1

    pipe = p.get("pipeline")
    if pipe:
        _kv("Nearby Pipeline Projects", pipe.get("count", 0))
        _kv("Nearby Pipeline Units", pipe.get("total_units", 0))
        row += 1

    uw = p.get("underwriting")
    if uw:
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


# ── PDF: single-property investment report ──────────────────────────────────

def build_pdf_report(prop: dict, ic_summary: dict | None = None) -> bytes:
    """
    Build a single-property PDF investment screening report.
    Returns raw .pdf bytes.
    """
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
        )
    except ImportError as exc:
        raise ImportError("Install `reportlab` to enable PDF export: pip install reportlab") from exc

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.6 * inch, bottomMargin=0.6 * inch)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleNavy", parent=styles["Title"], textColor=colors.HexColor("#1A3A6B"))
    h2 = ParagraphStyle("H2Navy", parent=styles["Heading2"], textColor=colors.HexColor("#1A3A6B"))

    story = []
    story.append(Paragraph(prop.get("address", "Property"), title_style))
    story.append(Paragraph(
        f"BBL {prop.get('bbl', '—')} · {prop.get('borough', '—')} · "
        f"Block {prop.get('block', '—')} Lot {prop.get('lot', '—')}",
        styles["Normal"],
    ))
    story.append(Spacer(1, 12))

    ds = prop.get("deal_score", {})
    rec = (ic_summary or {}).get("recommendation", "—")
    plan = prop.get("business_plan")
    acq_val = plan["acquisition"]["estimate"] if plan and plan.get("acquisition") else None
    headline = [
        ["DEAL SCORE", "RECOMMENDATION", "EST. ACQUISITION", "UNUSED FAR"],
        [f"{ds.get('score', '—')}/100 ({ds.get('tier', '—')})", rec,
         f"${acq_val:,.0f}" if acq_val else "—", f"{prop.get('unused_far_pct', 0):.0f}%"],
    ]
    t = Table(headline, colWidths=[1.6 * inch] * 4)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A3A6B")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 18))

    story.append(Paragraph("⚠️ Preliminary screening output only — not a zoning opinion, appraisal, "
                            "title report, environmental assessment, or substitute for professional "
                            "diligence.", styles["Italic"]))
    story.append(Spacer(1, 12))

    if ic_summary:
        story.append(Paragraph("Investment Thesis", h2))
        for bullet in ic_summary.get("thesis", []):
            story.append(Paragraph(f"• {bullet}", styles["Normal"]))
        story.append(Spacer(1, 10))

        story.append(Paragraph("Key Risks", h2))
        for r in ic_summary.get("key_risks", []):
            story.append(Paragraph(f"• {r}", styles["Normal"]))
        story.append(Spacer(1, 10))

        story.append(Paragraph("Key Unknowns / Next Diligence Steps", h2))
        for u in ic_summary.get("next_steps", []):
            story.append(Paragraph(f"• {u}", styles["Normal"]))
        story.append(Spacer(1, 10))

    story.append(Paragraph("Zoning Summary", h2))
    zdist = prop.get("zoning_dist", "—")
    story.append(Paragraph(
        f"District: {zdist} &nbsp;·&nbsp; Built FAR: {prop.get('far_built', 0):.2f} "
        f"&nbsp;·&nbsp; Max FAR (PLUTO): {prop.get('far_max', 0):.2f}",
        styles["Normal"],
    ))
    story.append(Spacer(1, 10))

    if prop.get("owner"):
        story.append(Paragraph("Ownership", h2))
        story.append(Paragraph(
            f"Owner: {prop.get('owner', '—')} ({prop.get('owner_type', 'Unknown')}) &nbsp;·&nbsp; "
            f"Last Sale: {prop.get('last_sale_price') or '—'} on {prop.get('last_sale_date') or '—'} "
            f"&nbsp;·&nbsp; Distress Signal: {prop.get('distress_signal', 'No Signal')}",
            styles["Normal"],
        ))
        story.append(Spacer(1, 10))

    if plan:
        profit_str = f"${plan['profit']:,.0f}" if plan["profit"] is not None else "—"
        margin_str = f"{plan['margin_pct']:.0f}%" if plan["margin_pct"] is not None else "—"
        story.append(Paragraph("Preliminary Acquisition Estimate & Business Plan", h2))
        story.append(Paragraph(
            f"Basis: {plan['acquisition']['basis']}", styles["Normal"],
        ))
        story.append(Paragraph(
            f"Est. total development cost: ${plan['total_dev_cost']:,.0f} &nbsp;·&nbsp; "
            f"Est. profit: {profit_str} &nbsp;·&nbsp; Margin: {margin_str}",
            styles["Normal"],
        ))
        for bullet in plan.get("bullets", []):
            story.append(Paragraph(f"• {bullet}", styles["Normal"]))
        story.append(Paragraph(
            "Free-data screening estimate only — not underwriting, an appraisal, "
            "or a GC cost estimate.", styles["Italic"],
        ))
        story.append(Spacer(1, 10))

    uw = prop.get("underwriting")
    if uw:
        story.append(Paragraph("Underwriting Pro Forma", h2))
        story.append(Paragraph(f"Scenario: {uw.get('scenario_label', '—')}", styles["Normal"]))
        irr_str = f"{uw['irr']:.1%}" if uw.get("irr") is not None else "N/A"
        em_str = f"{uw['equity_multiple']:.2f}x" if uw.get("equity_multiple") is not None else "N/A"
        headline_line = (
            f"Levered IRR: {irr_str} &nbsp;·&nbsp; Equity Multiple: {em_str} &nbsp;·&nbsp; "
            f"Total Dev. Cost: ${uw.get('total_dev_cost', 0):,.0f} &nbsp;·&nbsp; "
            f"Year 1 NOI: ${uw.get('year1_noi', 0):,.0f}"
        )
        story.append(Paragraph(headline_line, styles["Normal"]))
        if uw.get("equity_structure") == "waterfall":
            lp_irr = f"{uw['lp_irr']:.1%}" if uw.get("lp_irr") is not None else "N/A"
            gp_irr = f"{uw['gp_irr']:.1%}" if uw.get("gp_irr") is not None else "N/A"
            story.append(Paragraph(
                f"LP/GP Waterfall — LP IRR: {lp_irr} &nbsp;·&nbsp; GP IRR: {gp_irr} &nbsp;·&nbsp; "
                f"GP Promote: ${uw.get('total_gp_promote', 0):,.0f}",
                styles["Normal"],
            ))
        story.append(Paragraph(
            "Preliminary underwriting model — a hand-rolled deterministic pro forma, "
            "not a lender-grade or GP-facing underwriting package.", styles["Italic"],
        ))
        story.append(Spacer(1, 10))

    doc.build(story)
    return buf.getvalue()


# ── PowerPoint: single-property pitch deck ──────────────────────────────────

def build_pptx_report(prop: dict, ic_summary: dict | None = None) -> bytes:
    """
    Build a single-property PowerPoint investment pitch deck.
    Returns raw .pptx bytes.
    """
    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt
        from pptx.dml.color import RGBColor
        from pptx.enum.text import PP_ALIGN
    except ImportError as exc:
        raise ImportError("Install `python-pptx` to enable PowerPoint export: pip install python-pptx") from exc

    NAVY = RGBColor(0x1A, 0x3A, 0x6B)
    prs = Presentation()
    prs.slide_width = Inches(13.33)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]

    # ── Slide 1: Cover / headline metrics ───────────────────────────────────
    slide = prs.slides.add_slide(blank)
    tb = slide.shapes.add_textbox(Inches(0.6), Inches(0.4), Inches(12), Inches(1.0))
    tf = tb.text_frame
    tf.text = prop.get("address", "Property")
    tf.paragraphs[0].font.size = Pt(36)
    tf.paragraphs[0].font.bold = True
    tf.paragraphs[0].font.color.rgb = NAVY

    sub = slide.shapes.add_textbox(Inches(0.6), Inches(1.25), Inches(12), Inches(0.5))
    sub.text_frame.text = (
        f"BBL {prop.get('bbl', '—')} · {prop.get('borough', '—')}"
    )
    sub.text_frame.paragraphs[0].font.size = Pt(16)

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
        box = slide.shapes.add_textbox(x, Inches(2.2), Inches(2.9), Inches(1.3))
        f = box.text_frame
        f.text = val
        f.paragraphs[0].font.size = Pt(28)
        f.paragraphs[0].font.bold = True
        f.paragraphs[0].font.color.rgb = NAVY
        p2 = f.add_paragraph()
        p2.text = label
        p2.font.size = Pt(12)
        x += Inches(3.1)

    if ic_summary and ic_summary.get("recommendation"):
        rec_box = slide.shapes.add_textbox(Inches(0.6), Inches(3.9), Inches(6), Inches(0.7))
        f = rec_box.text_frame
        f.text = f"Recommendation: {ic_summary['recommendation']}"
        f.paragraphs[0].font.size = Pt(20)
        f.paragraphs[0].font.bold = True

    footer = slide.shapes.add_textbox(Inches(0.6), Inches(6.8), Inches(12), Inches(0.5))
    footer.text_frame.text = (
        "Preliminary screening output only — not a zoning opinion, appraisal, "
        "title report, or substitute for professional diligence."
    )
    footer.text_frame.paragraphs[0].font.size = Pt(10)
    footer.text_frame.paragraphs[0].font.italic = True

    # ── Slide 2: Investment thesis / risks / next steps ─────────────────────
    if ic_summary:
        slide2 = prs.slides.add_slide(blank)
        title = slide2.shapes.add_textbox(Inches(0.6), Inches(0.4), Inches(12), Inches(0.7))
        title.text_frame.text = "Investment Thesis & Risks"
        title.text_frame.paragraphs[0].font.size = Pt(28)
        title.text_frame.paragraphs[0].font.bold = True
        title.text_frame.paragraphs[0].font.color.rgb = NAVY

        col1 = slide2.shapes.add_textbox(Inches(0.6), Inches(1.3), Inches(5.8), Inches(5.5))
        f1 = col1.text_frame
        f1.word_wrap = True
        f1.text = "Investment Thesis"
        f1.paragraphs[0].font.bold = True
        f1.paragraphs[0].font.size = Pt(18)
        for bullet in ic_summary.get("thesis", []):
            p = f1.add_paragraph()
            p.text = f"• {bullet}"
            p.font.size = Pt(13)

        col2 = slide2.shapes.add_textbox(Inches(6.8), Inches(1.3), Inches(5.8), Inches(5.5))
        f2 = col2.text_frame
        f2.word_wrap = True
        f2.text = "Key Risks"
        f2.paragraphs[0].font.bold = True
        f2.paragraphs[0].font.size = Pt(18)
        for r in ic_summary.get("key_risks", []):
            p = f2.add_paragraph()
            p.text = f"• {r}"
            p.font.size = Pt(13)

    # ── Slide 3: Preliminary Acquisition Estimate & Business Plan ───────────
    if plan:
        slide3 = prs.slides.add_slide(blank)
        title3 = slide3.shapes.add_textbox(Inches(0.6), Inches(0.4), Inches(12), Inches(0.7))
        title3.text_frame.text = "Preliminary Acquisition Estimate & Business Plan"
        title3.text_frame.paragraphs[0].font.size = Pt(26)
        title3.text_frame.paragraphs[0].font.bold = True
        title3.text_frame.paragraphs[0].font.color.rgb = NAVY

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
            box = slide3.shapes.add_textbox(x, Inches(1.3), Inches(2.9), Inches(1.1))
            f = box.text_frame
            f.text = val
            f.paragraphs[0].font.size = Pt(22)
            f.paragraphs[0].font.bold = True
            f.paragraphs[0].font.color.rgb = NAVY
            p2 = f.add_paragraph()
            p2.text = label
            p2.font.size = Pt(11)
            x += Inches(3.1)

        body = slide3.shapes.add_textbox(Inches(0.6), Inches(2.6), Inches(12), Inches(4.2))
        fb = body.text_frame
        fb.word_wrap = True
        fb.text = f"Basis: {plan['acquisition']['basis']}"
        fb.paragraphs[0].font.size = Pt(13)
        fb.paragraphs[0].font.italic = True
        for bullet in plan.get("bullets", []):
            p = fb.add_paragraph()
            p.text = f"• {bullet}"
            p.font.size = Pt(14)

        note = slide3.shapes.add_textbox(Inches(0.6), Inches(6.9), Inches(12), Inches(0.5))
        note.text_frame.text = (
            "Free-data screening estimate only — not underwriting, an appraisal, or a GC cost estimate."
        )
        note.text_frame.paragraphs[0].font.size = Pt(10)
        note.text_frame.paragraphs[0].font.italic = True

    # ── Slide 4: Underwriting Pro Forma ──────────────────────────────────────
    uw = prop.get("underwriting")
    if uw:
        slide4 = prs.slides.add_slide(blank)
        title4 = slide4.shapes.add_textbox(Inches(0.6), Inches(0.4), Inches(12), Inches(0.7))
        title4.text_frame.text = "Underwriting Pro Forma"
        title4.text_frame.paragraphs[0].font.size = Pt(26)
        title4.text_frame.paragraphs[0].font.bold = True
        title4.text_frame.paragraphs[0].font.color.rgb = NAVY

        irr_str = f"{uw['irr']:.1%}" if uw.get("irr") is not None else "N/A"
        em_str = f"{uw['equity_multiple']:.2f}x" if uw.get("equity_multiple") is not None else "N/A"
        uw_metrics = [
            ("LEVERED IRR", irr_str),
            ("EQUITY MULTIPLE", em_str),
            ("TOTAL DEV. COST", f"${uw.get('total_dev_cost', 0):,.0f}"),
            ("HOLD PERIOD", uw.get("scenario_label", "—")),
        ]
        x = Inches(0.6)
        for label, val in uw_metrics:
            box = slide4.shapes.add_textbox(x, Inches(1.3), Inches(2.9), Inches(1.3))
            f = box.text_frame
            f.word_wrap = True
            f.text = val
            f.paragraphs[0].font.size = Pt(20 if label != "HOLD PERIOD" else 14)
            f.paragraphs[0].font.bold = True
            f.paragraphs[0].font.color.rgb = NAVY
            p2 = f.add_paragraph()
            p2.text = label
            p2.font.size = Pt(11)
            x += Inches(3.1)

        body4 = slide4.shapes.add_textbox(Inches(0.6), Inches(2.9), Inches(12), Inches(3.5))
        fb4 = body4.text_frame
        fb4.word_wrap = True
        if uw.get("equity_structure") == "waterfall":
            lp_irr = f"{uw['lp_irr']:.1%}" if uw.get("lp_irr") is not None else "N/A"
            gp_irr = f"{uw['gp_irr']:.1%}" if uw.get("gp_irr") is not None else "N/A"
            fb4.text = "LP/GP Waterfall"
            fb4.paragraphs[0].font.bold = True
            fb4.paragraphs[0].font.size = Pt(16)
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

        note4 = slide4.shapes.add_textbox(Inches(0.6), Inches(6.9), Inches(12), Inches(0.5))
        note4.text_frame.text = (
            "Preliminary underwriting model — a hand-rolled deterministic pro forma, "
            "not a lender-grade or GP-facing underwriting package."
        )
        note4.text_frame.paragraphs[0].font.size = Pt(10)
        note4.text_frame.paragraphs[0].font.italic = True

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()

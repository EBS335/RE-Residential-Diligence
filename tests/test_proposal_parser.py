"""
Tests for modules/proposal_parser.py. Builds throwaway PDF fixtures with
reportlab (already a dependency, used for this app's own PDF export) at
test time rather than committing a binary PDF file to the repo.
"""

import io

import pytest

from modules.proposal_parser import (
    extract_proposal_text, extract_fee_estimate, score_scope_keywords,
    SCOPE_KEYWORD_CATEGORIES,
)


def _make_pdf(lines: list[str]) -> bytes:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    y = 750
    for line in lines:
        c.drawString(50, y, line)
        y -= 20
        if y < 50:
            c.showPage()
            y = 750
    c.save()
    return buf.getvalue()


# ── extract_proposal_text ─────────────────────────────────────────────────────

def test_extracts_text_from_generated_pdf():
    pdf_bytes = _make_pdf(["ACME Consulting Group", "Proposal for 123 Main St", "Total Fee: $45,000.00"])
    result = extract_proposal_text(pdf_bytes)
    assert result["error"] is None
    assert result["page_count"] == 1
    assert "ACME Consulting Group" in result["text"]
    assert "Total Fee" in result["text"]


def test_multi_page_pdf_counts_pages_correctly():
    pdf_bytes = _make_pdf([f"Line {i}" for i in range(60)])  # forces a 2nd page
    result = extract_proposal_text(pdf_bytes)
    assert result["page_count"] >= 2


def test_corrupt_bytes_never_raises():
    result = extract_proposal_text(b"not a real pdf at all")
    assert result["error"] is not None
    assert result["text"] == ""


def test_empty_bytes_never_raises():
    result = extract_proposal_text(b"")
    assert result["error"] is not None


# ── extract_fee_estimate ─────────────────────────────────────────────────────

def test_extracts_fee_near_keyword():
    text = "Scope of work includes structural survey. Total Fee: $45,000.00 due upon execution."
    assert extract_fee_estimate(text) == 45000.0


def test_extracts_fee_with_not_to_exceed_phrasing():
    text = "Professional services shall not to exceed $12,500 for the engagement."
    assert extract_fee_estimate(text) == 12500.0


def test_falls_back_to_largest_dollar_figure_when_no_keyword_match():
    text = "Line item A: $500. Line item B: $2,300. Line item C: $150."
    assert extract_fee_estimate(text) == 2300.0


def test_no_dollar_amounts_returns_none():
    assert extract_fee_estimate("This proposal has no pricing information at all.") is None


def test_empty_text_returns_none():
    assert extract_fee_estimate("") is None
    assert extract_fee_estimate(None) is None


# ── score_scope_keywords ─────────────────────────────────────────────────────

def test_counts_keyword_matches_per_category():
    text = (
        "This proposal covers a full structural survey and a Phase I "
        "Environmental Site Assessment. No zoning analysis is included."
    )
    result = score_scope_keywords(text)
    assert set(result.keys()) == set(SCOPE_KEYWORD_CATEGORIES.keys())
    assert result["Structural Survey"] > 0
    assert result["Phase I ESA"] > 0
    assert result["Zoning Analysis"] > 0  # "zoning analysis" phrase still matches even in a negation
    assert result["Geotechnical"] == 0


def test_case_insensitive_matching():
    text = "STRUCTURAL SURVEY will be performed by a licensed engineer."
    result = score_scope_keywords(text)
    assert result["Structural Survey"] > 0


def test_empty_text_returns_all_zero_never_raises():
    result = score_scope_keywords("")
    assert all(v == 0 for v in result.values())
    assert set(result.keys()) == set(SCOPE_KEYWORD_CATEGORIES.keys())


def test_custom_categories_respected():
    result = score_scope_keywords("appraisal report included", categories={"Appraisal": ["appraisal"]})
    assert result == {"Appraisal": 1}


# ── End-to-end: real generated PDF through the full pipeline ────────────────

def test_end_to_end_generated_proposal_pdf():
    pdf_bytes = _make_pdf([
        "Smith & Associates Engineering",
        "Re: Structural Survey and Geotechnical Investigation",
        "Scope: structural survey of existing building, geotechnical soil boring",
        "Total Fee: $28,750.00",
    ])
    parsed = extract_proposal_text(pdf_bytes)
    assert parsed["error"] is None
    fee = extract_fee_estimate(parsed["text"])
    assert fee == 28750.0
    scores = score_scope_keywords(parsed["text"])
    assert scores["Structural Survey"] > 0
    assert scores["Geotechnical"] > 0
    assert scores["Title Review"] == 0

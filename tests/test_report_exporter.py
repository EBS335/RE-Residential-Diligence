"""
Tests for the institutional-design PDF/PPTX/Excel export builders
(modules/report_exporter.py) — Property Analysis tab review pass.

These are smoke tests: given representative fixtures (including a full
underwriting block, an IC summary, and a business plan), each builder
must return non-empty, correctly-signed bytes without raising, across a
range of "missing optional data" shapes (no ic_summary, no plan, no
underwriting, waterfall vs. simple equity structure).
"""

import io

import pytest

from modules.report_exporter import (
    build_pdf_report, build_pptx_report, build_excel_workbook, compose_fallback_ic_summary,
)


def _prop(**overrides) -> dict:
    base = {
        "address": "123 Main St",
        "bbl": "1000010001",
        "borough": "Manhattan",
        "block": "1",
        "lot": "1",
        "lot_sf": 5000,
        "far_built": 2.0,
        "far_max": 6.0,
        "unused_far_pct": 66.7,
        "zoning_dist": "R7A",
        "strategies": ["Demolition"],
        "owner": "123 Main St LLC",
        "owner_type": "LLC",
        "last_sale_price": "$3,500,000",
        "last_sale_date": "2021-05-01",
        "distress_signal": "No Signal",
        "deal_score": {"score": 82, "tier": "Strong Lead"},
        "opportunity": {"score": 70},
        "market_comps": {"median_price_psf": 850, "count": 12},
        "pipeline": {"count": 3, "total_units": 240},
        "business_plan": {
            "acquisition": {"estimate": 3_500_000, "basis": "Comparable land sales"},
            "total_dev_cost": 12_000_000,
            "profit": 2_000_000,
            "margin_pct": 16.7,
            "bullets": ["Demolish existing 2-story building", "Build to max FAR"],
        },
        "underwriting": {
            "scenario_label": "Ground-Up Mixed-Use",
            "irr": 0.184,
            "equity_multiple": 2.1,
            "total_dev_cost": 12_000_000,
            "year1_noi": 780_000,
            "equity_structure": "simple",
        },
    }
    base.update(overrides)
    return base


def _ic_summary() -> dict:
    return {
        "recommendation": "GO",
        "thesis": ["Strong rezoning upside", "Below-market basis"],
        "key_risks": ["ULURP timeline risk", "Construction cost inflation"],
        "next_steps": ["Order title report", "Confirm zoning with DOB"],
    }


# ── Fallback IC summary ──────────────────────────────────────────────────────

def test_fallback_ic_summary_strong_lead_recommends_go():
    result = compose_fallback_ic_summary(_prop(deal_score={"score": 82, "tier": "Strong Lead"}))
    assert result["recommendation"] == "GO"
    assert result["thesis"]
    assert result["key_risks"]
    assert result["next_steps"]


def test_fallback_ic_summary_watch_tier_recommends_watch():
    result = compose_fallback_ic_summary(_prop(deal_score={"score": 55, "tier": "Watch"}))
    assert result["recommendation"] == "WATCH"


def test_fallback_ic_summary_pass_tier_recommends_reject():
    result = compose_fallback_ic_summary(_prop(deal_score={"score": 15, "tier": "Pass"}))
    assert result["recommendation"] == "REJECT"


def test_fallback_ic_summary_distress_signal_surfaces_as_risk():
    result = compose_fallback_ic_summary(_prop(distress_signal="Strong Signal"))
    assert any("Strong Signal" in r for r in result["key_risks"])


def test_fallback_ic_summary_no_underwriting_prompts_next_step():
    result = compose_fallback_ic_summary(_prop(underwriting=None))
    assert any("Underwriting" in s for s in result["next_steps"])


def test_fallback_ic_summary_never_raises_on_empty_prop():
    result = compose_fallback_ic_summary({})
    assert result["recommendation"] in ("GO", "WATCH", "REJECT")
    assert result["thesis"]
    assert result["key_risks"]
    assert result["next_steps"]


def test_fallback_ic_summary_consumable_by_pdf_and_pptx_builders():
    # The whole point: this dict must be a drop-in ic_summary for both
    # exporters, which previously always received None from app.py.
    ic = compose_fallback_ic_summary(_prop())
    pdf_bytes = build_pdf_report(_prop(), ic)
    pptx_bytes = build_pptx_report(_prop(), ic)
    assert pdf_bytes[:4] == b"%PDF"
    assert pptx_bytes[:2] == b"PK"


# ── PDF ──────────────────────────────────────────────────────────────────────

def test_pdf_report_full_fixture_returns_nonempty_bytes():
    pdf_bytes = build_pdf_report(_prop(), _ic_summary())
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 500
    assert pdf_bytes.startswith(b"%PDF")


def test_pdf_report_minimal_prop_no_ic_summary():
    minimal = {"address": "1 Test Ave", "bbl": "1", "borough": "Queens"}
    pdf_bytes = build_pdf_report(minimal, None)
    assert pdf_bytes.startswith(b"%PDF")


def test_pdf_report_waterfall_equity_structure():
    prop = _prop(underwriting={
        "scenario_label": "Ground-Up Mixed-Use", "equity_structure": "waterfall",
        "total_dev_cost": 12_000_000, "year1_noi": 780_000,
        "lp_irr": 0.15, "gp_irr": 0.28, "total_gp_promote": 500_000,
        "irr": None, "equity_multiple": None,
    })
    pdf_bytes = build_pdf_report(prop, _ic_summary())
    assert pdf_bytes.startswith(b"%PDF")


# ── PPTX ─────────────────────────────────────────────────────────────────────

def test_pptx_report_full_fixture_returns_nonempty_bytes():
    pptx_bytes = build_pptx_report(_prop(), _ic_summary())
    assert isinstance(pptx_bytes, bytes)
    assert len(pptx_bytes) > 500
    # .pptx is a zip container
    assert pptx_bytes[:2] == b"PK"


def test_pptx_report_minimal_prop_no_optional_sections():
    minimal = {"address": "1 Test Ave", "bbl": "1", "borough": "Queens"}
    pptx_bytes = build_pptx_report(minimal, None)
    assert pptx_bytes[:2] == b"PK"


def test_pptx_report_waterfall_equity_structure():
    prop = _prop(underwriting={
        "scenario_label": "Ground-Up Mixed-Use", "equity_structure": "waterfall",
        "total_dev_cost": 12_000_000, "year1_noi": 780_000,
        "lp_irr": 0.15, "gp_irr": 0.28, "total_gp_promote": 500_000,
        "irr": None, "equity_multiple": None,
    })
    pptx_bytes = build_pptx_report(prop, _ic_summary())
    assert pptx_bytes[:2] == b"PK"


def test_pptx_report_no_recommendation_still_builds():
    prop = _prop()
    pptx_bytes = build_pptx_report(prop, {"thesis": [], "key_risks": [], "next_steps": []})
    assert pptx_bytes[:2] == b"PK"


# ── Excel ────────────────────────────────────────────────────────────────────

def test_excel_workbook_returns_nonempty_bytes():
    xlsx_bytes = build_excel_workbook([_prop(), _prop(address="456 Elm St", deal_score={"score": 55, "tier": "Watch"})])
    assert isinstance(xlsx_bytes, bytes)
    assert len(xlsx_bytes) > 500
    assert xlsx_bytes[:2] == b"PK"


def test_excel_workbook_empty_properties_list():
    xlsx_bytes = build_excel_workbook([])
    assert xlsx_bytes[:2] == b"PK"


def test_excel_workbook_all_three_tiers_render():
    props = [
        _prop(address="A", deal_score={"score": 90, "tier": "Strong Lead"}),
        _prop(address="B", deal_score={"score": 60, "tier": "Watch"}),
        _prop(address="C", deal_score={"score": 20, "tier": "Pass"}),
    ]
    xlsx_bytes = build_excel_workbook(props)
    assert xlsx_bytes[:2] == b"PK"


def test_excel_workbook_no_pro_forma_comps_or_budget_sheets_without_data():
    # The base _prop() fixture's underwriting/market_comps have only
    # summary numbers, no annual_cash_flows/cost_breakdown/comps list.
    xlsx_bytes = build_excel_workbook([_prop()])
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(xlsx_bytes))
    assert not any("Pro Forma" in n for n in wb.sheetnames)
    assert not any("Comps" in n for n in wb.sheetnames)
    assert not any("Construction Budget" in n for n in wb.sheetnames)


def test_excel_workbook_pro_forma_and_budget_sheets_created_when_present():
    prop = _prop(underwriting={
        "scenario_label": "Ground-Up Mixed-Use",
        "irr": 0.184, "equity_multiple": 2.1,
        "total_dev_cost": 12_000_000, "year1_noi": 780_000,
        "equity_structure": "simple",
        "annual_cash_flows": [
            {"year": 0, "phase": "construction", "noi": 0, "debt_service": 0,
             "reversion_proceeds": 0, "equity_cf": -4_000_000, "unlevered_cf": -12_000_000},
            {"year": 1, "phase": "exit", "noi": 780_000, "debt_service": 400_000,
             "reversion_proceeds": 15_000_000, "equity_cf": 15_380_000, "unlevered_cf": 15_780_000},
        ],
        "cost_breakdown": {
            "acquisition_cost": 3_500_000, "closing_cost": 105_000,
            "hard_cost": 6_800_000, "soft_cost": 1_360_000,
            "contingency": 816_500, "total_dev_cost": 12_581_500,
        },
    })
    xlsx_bytes = build_excel_workbook([prop])
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(xlsx_bytes))
    assert any("Pro Forma" in n for n in wb.sheetnames)
    assert any("Construction Budget" in n for n in wb.sheetnames)
    pf_sheet = next(wb[n] for n in wb.sheetnames if "Pro Forma" in n)
    assert pf_sheet.cell(row=4, column=1).value == 0  # year 0
    assert pf_sheet.cell(row=5, column=1).value == 1  # year 1
    budget_sheet = next(wb[n] for n in wb.sheetnames if "Construction Budget" in n)
    assert budget_sheet.cell(row=3, column=2).value == 3_500_000  # acquisition cost


def test_excel_workbook_comps_sheet_created_when_present():
    prop = _prop(market_comps={
        "median_price_psf": 850, "count": 1,
        "comps": [{"address": "1 Test Ave", "price": 3_000_000, "sqft": 5000,
                    "price_psf": 600.0, "asset_type": "Residential Sale", "date": "2024-01-01"}],
    })
    xlsx_bytes = build_excel_workbook([prop])
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(xlsx_bytes))
    assert any("Comps" in n for n in wb.sheetnames)
    comps_sheet = next(wb[n] for n in wb.sheetnames if "Comps" in n)
    assert comps_sheet.cell(row=4, column=1).value == "1 Test Ave"

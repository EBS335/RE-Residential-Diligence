"""
Tests for the underwriting UI helper shared between the Site Finder and
Property Analysis tabs (modules/site_finder_ui.py::_flatten_underwriting_for_export).

Property Analysis's "Underwriting Pro Forma — Deep Dive" panel (app.py)
now imports this helper directly rather than re-implementing it, so its
correctness is pinned here rather than duplicated per call site.
"""

from modules.site_finder_ui import _flatten_underwriting_for_export


def _scenario():
    return {"label": "Ground-Up Mixed-Use", "scenario_id": "massing_1"}


def _cf_result():
    return {"total_dev_cost": 12_000_000, "year1_noi": 780_000}


def test_flatten_simple_equity_structure():
    returns = {"irr": 0.184, "equity_multiple": 2.1}
    out = _flatten_underwriting_for_export(_scenario(), _cf_result(), returns, "simple")
    assert out["scenario_label"] == "Ground-Up Mixed-Use"
    assert out["total_dev_cost"] == 12_000_000
    assert out["year1_noi"] == 780_000
    assert out["equity_structure"] == "simple"
    assert out["irr"] == 0.184
    assert out["equity_multiple"] == 2.1
    assert "lp_irr" not in out


def test_flatten_waterfall_equity_structure_uses_lp_as_headline():
    returns = {
        "lp_irr": 0.15, "gp_irr": 0.28, "lp_equity_multiple": 1.9,
        "gp_equity_multiple": 3.2, "total_gp_promote": 500_000,
    }
    out = _flatten_underwriting_for_export(_scenario(), _cf_result(), returns, "waterfall")
    assert out["equity_structure"] == "waterfall"
    # Headline irr/equity_multiple reflect the LP's perspective, not the GP's.
    assert out["irr"] == 0.15
    assert out["equity_multiple"] == 1.9
    assert out["gp_irr"] == 0.28
    assert out["total_gp_promote"] == 500_000


def test_flatten_missing_returns_values_degrade_to_none():
    out = _flatten_underwriting_for_export(_scenario(), _cf_result(), {}, "simple")
    assert out["irr"] is None
    assert out["equity_multiple"] is None

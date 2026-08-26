"""
AppTest-driven checks for the Site Finder overhaul:
  - summary cards show Vacant/Underutilized Lots + Demolition Candidates
    counts instead of Deal Score >=65 / Avg. Deal Score
  - the new filter panel narrows the map/table/summary-card view
  - row-click selection on the results table drives "Open Preliminary
    Diligence" (replacing the old separate dropdown+button)
"""

import os

from streamlit.testing.v1 import AppTest

from modules.site_sourcing import enrich_property, flag_assemblage_candidates
from modules.deal_scorer import compute_deal_score

_APP_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def _prop(i, **overrides):
    raw = {
        "bbl": f"301234{i:04d}", "borough": "Brooklyn", "borough_code": "3",
        "block": "1234", "lot": str(i + 1), "address": f"{100 + i} Test St",
        "zip_code": "11201", "community_district": "302",
        "zoning_dist": "R6A", "landuse_code": "02", "landuse_label": "Multi-Family Walk-Up",
        "bldg_class": "C1", "owner": "TEST OWNER", "owner_type": "",
        "lot_sf": 5000.0, "bldg_sf": 8000.0, "year_built": "1930", "num_floors": 4.0,
        "units_res": 12.0, "units_total": 12.0, "far_built": 1.6, "far_residential": 3.0,
        "far_commercial": 0.0, "far_max": 3.0, "unused_far": 1.4, "unused_far_pct": 46.7,
        "assess_land": 400000.0, "assess_total": 800000.0, "exempt_land": 0.0, "exempt_total": 0.0,
        "is_vacant": False, "historic_dist": "", "landmark": "",
        "latitude": 40.69 + i * 0.0001, "longitude": -73.99, "lot_type": "Interior",
    }
    raw.update(overrides)
    prop = enrich_property(raw)
    prop["deal_score"] = compute_deal_score(unused_far_pct=raw["unused_far_pct"], zoning_dist="R6A")
    return prop


def _run_with_results(results, extra_state=None):
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = results
    at.session_state["_sf_last_status"] = {"overall": "live"}
    if extra_state:
        for k, v in extra_state.items():
            at.session_state[k] = v
    at.run()
    return at


def _results_df(at):
    dataframes = [el.value for el in at.dataframe]
    return max(dataframes, key=lambda df: len(df))


# ── Summary cards ────────────────────────────────────────────────────────────

def test_summary_cards_show_vacant_and_demolition_counts():
    vacant = _prop(0, landuse_code="11", landuse_label="Vacant Land", bldg_class="V1",
                    bldg_sf=0.0, year_built="", num_floors=0.0, units_res=0.0, units_total=0.0,
                    far_built=0.0, unused_far_pct=100.0, is_vacant=True)
    demo = _prop(1)  # 1930-built, low-rise-on-large-lot etc. -> STRATEGY_DEMOLITION per classify_strategies()
    results = flag_assemblage_candidates([vacant, demo])

    at = _run_with_results(results)
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert "Deal Score ≥ 65" not in metrics
    assert "Avg. Deal Score" not in metrics
    assert "Vacant/Underutilized Lots" in metrics
    assert "Demolition Candidates" in metrics
    assert metrics["Vacant/Underutilized Lots"] == "1"
    assert metrics["Demolition Candidates"] == "1"


def test_summary_cards_keep_properties_matched_and_avg_far():
    results = flag_assemblage_candidates([_prop(0), _prop(1)])
    at = _run_with_results(results)
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Properties Matched"] == "2"
    assert "Avg. Unused FAR" in metrics


# ── Filter panel ─────────────────────────────────────────────────────────────

def test_filter_street_narrows_results():
    results = flag_assemblage_candidates([
        _prop(0, address="100 Broadway"),
        _prop(1, address="200 Main St"),
    ])
    at = _run_with_results(results, {"_sf_filter_street": "broadway"})
    df = _results_df(at)
    assert len(df) == 1
    assert df["Address"].iloc[0] == "100 Broadway"


def test_filter_current_conditions_narrows_results():
    results = flag_assemblage_candidates([
        _prop(0, landuse_label="Vacant Land"),
        _prop(1, landuse_label="Multi-Family Walk-Up"),
    ])
    at = _run_with_results(results, {"_sf_filter_conditions": ["Vacant Land"]})
    df = _results_df(at)
    assert len(df) == 1
    assert "Vacant Land" in df["Current Conditions"].iloc[0]


def test_filter_lot_sf_range_narrows_results():
    results = flag_assemblage_candidates([
        _prop(0, lot_sf=2000.0),
        _prop(1, lot_sf=10000.0),
    ])
    at = _run_with_results(results, {"_sf_filter_lotsf_min": 5000.0})
    df = _results_df(at)
    assert len(df) == 1


def test_filter_strategy_narrows_results():
    vacant = _prop(0, landuse_code="11", bldg_sf=0.0, year_built="", num_floors=0.0,
                    units_res=0.0, units_total=0.0, far_built=0.0, unused_far_pct=100.0, is_vacant=True)
    non_vacant = _prop(1)
    results = flag_assemblage_candidates([vacant, non_vacant])
    at = _run_with_results(results, {"_sf_filter_strategy": ["Vacant / Underutilized"]})
    df = _results_df(at)
    assert len(df) == 1


def test_filter_tag_narrows_results(monkeypatch):
    """Feature 9 — Tags/Labels: the new Tags multiselect filter narrows the
    table to rows carrying at least one of the chosen tags. Tags are joined
    onto each row via list_tags_bulk() (a portfolio_db.py bulk query),
    patched here to a fixed per-bbl mapping so this stays a pure UI test
    with no real DB touched."""
    from modules import site_finder_ui

    results = flag_assemblage_candidates([_prop(0), _prop(1)])
    tagged_bbl = results[0]["bbl"]

    def _fake_list_tags_bulk(bbls, conn=None):
        return {tagged_bbl: ["Hot"]} if tagged_bbl in bbls else {}

    monkeypatch.setattr(site_finder_ui, "list_tags_bulk", _fake_list_tags_bulk)

    at = _run_with_results(results, {"_sf_filter_tags": ["Hot"]})
    df = _results_df(at)
    assert len(df) == 1
    assert df["Tags"].iloc[0] == "Hot"


def test_no_filters_shows_all_results():
    results = flag_assemblage_candidates([_prop(0), _prop(1), _prop(2)])
    at = _run_with_results(results)
    df = _results_df(at)
    assert len(df) == 3


def test_filters_that_exclude_everything_show_empty_table_not_exception():
    results = flag_assemblage_candidates([_prop(0), _prop(1)])
    at = _run_with_results(results, {"_sf_filter_street": "nonexistent street xyz"})
    assert not at.exception
    df = _results_df(at)
    assert len(df) == 0


# ── Row-click selection for Preliminary Diligence ───────────────────────────

def test_row_selection_surfaces_diligence_button_for_correct_property():
    results = flag_assemblage_candidates([_prop(0, address="100 Test St"), _prop(1, address="101 Test St")])
    at = _run_with_results(results, {"_sf_results_table": {"selection": {"rows": [1]}}})
    assert not at.exception
    mds = [el.value for el in at.markdown]
    assert any("101 Test St" in m for m in mds if "Selected:" in m)
    buttons = [b.label for b in at.button]
    assert any("Open Preliminary Diligence" in b for b in buttons)


def test_no_row_selected_shows_no_diligence_button():
    results = flag_assemblage_candidates([_prop(0)])
    at = _run_with_results(results)
    buttons = [b.label for b in at.button]
    assert not any("Open Preliminary Diligence" in b for b in buttons)


def test_view_preliminary_diligence_dropdown_removed():
    # The old selectbox-driven flow is gone — only "Save to Portfolio" still
    # uses a selectbox on this page.
    results = flag_assemblage_candidates([_prop(0)])
    at = _run_with_results(results)
    selectbox_labels = [sb.label for sb in at.selectbox]
    assert "Choose a result to inspect" not in selectbox_labels
    assert "Choose a result to save" in selectbox_labels


# ── Preliminary Diligence: site/building summary ────────────────────────────

def test_property_detail_shows_site_building_summary():
    prop = _prop(0, address="100 Test St", bldg_class="C1", num_floors=4.0,
                 bldg_sf=8000.0, units_total=12.0, units_res=12.0, lot_sf=5000.0,
                 zoning_dist="R6A", far_built=1.6, far_max=3.0, unused_far_pct=46.7,
                 owner="TEST OWNER")
    at = _run_with_results([prop], {"_sf_selected_bbl": prop["bbl"], "_sf_selected_prop": prop})
    assert not at.exception
    mds = " ".join(el.value for el in at.markdown)
    assert "Site & Building Summary" in mds
    assert "Multi-Family Walk-Up" in mds  # _current_conditions() reused
    assert "C1" in mds
    assert "8,000" in mds
    assert "12 total (12 residential)" in mds
    assert "5,000" in mds
    assert "R6A" in mds
    assert "1.60 built of 3.00 max" in mds
    assert "TEST OWNER" in mds

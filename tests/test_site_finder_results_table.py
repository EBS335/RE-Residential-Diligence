"""
AppTest-driven checks for the Site Finder results-table changes:
  - the BBL column is no longer shown
  - "Current Conditions", "Location", "Assemblage", "Rent Stab.", "Landmark"
    columns are present
  - the full (unsliced) result set reaches the table — no more hardcoded
    top-50 display cap
"""

import os

from streamlit.testing.v1 import AppTest

from modules.site_sourcing import enrich_property, flag_assemblage_candidates
from modules.deal_scorer import compute_deal_score, compute_seller_propensity
from modules.site_finder_ui import _landmark_label, _rent_stab_label

_APP_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def _synthetic_results(n: int, landmark_overrides: dict | None = None) -> list[dict]:
    landmark_overrides = landmark_overrides or {}
    props = []
    for i in range(n):
        overrides = landmark_overrides.get(i, {})
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
            "latitude": 40.69 + i * 0.0001, "longitude": -73.99, "lot_type": "Corner" if i == 0 else "Interior",
        }
        raw.update(overrides)
        prop = enrich_property(raw)
        prop["deal_score"] = compute_deal_score(unused_far_pct=46.7, zoning_dist="R6A")
        props.append(prop)
    return flag_assemblage_candidates(props)


def test_results_table_full_set_no_bbl_column_new_columns_present():
    n = 75  # deliberately > the old 50-row cap
    results = _synthetic_results(n)

    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = results
    at.session_state["_sf_last_status"] = {"overall": "live"}
    at.run()

    assert not at.exception

    dataframes = [el.value for el in at.dataframe]
    # The results table is the largest dataframe rendered on this run.
    results_df = max(dataframes, key=lambda df: len(df))

    assert "BBL" not in results_df.columns
    assert "Current Conditions" in results_df.columns
    assert "Location" in results_df.columns
    assert "Assemblage" in results_df.columns
    assert "Rent Stab." in results_df.columns
    assert "Landmark" in results_df.columns
    assert len(results_df) == n  # full set, not capped at 50


def test_current_conditions_column_formatted():
    results = _synthetic_results(3)
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = results
    at.session_state["_sf_last_status"] = {"overall": "live"}
    at.run()

    dataframes = [el.value for el in at.dataframe]
    results_df = max(dataframes, key=lambda df: len(df))
    assert "Multi-Family Walk-Up" in results_df["Current Conditions"].iloc[0]
    assert "12 units" in results_df["Current Conditions"].iloc[0]
    assert "built 1930" in results_df["Current Conditions"].iloc[0]


def test_corner_and_mid_block_labels():
    results = _synthetic_results(2)  # index 0 -> Corner, index 1 -> Interior
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = results
    at.session_state["_sf_last_status"] = {"overall": "live"}
    at.run()

    dataframes = [el.value for el in at.dataframe]
    results_df = max(dataframes, key=lambda df: len(df))
    assert results_df["Location"].iloc[0] == "Corner"
    assert results_df["Location"].iloc[1] == "Mid-Block"


def test_landmark_column_labels_all_four_cases():
    # index 0: landmark only, 1: historic district only, 2: both, 3: neither
    overrides = {
        0: {"landmark": "Individual Landmark"},
        1: {"historic_dist": "Brooklyn Heights"},
        2: {"landmark": "Individual Landmark", "historic_dist": "Brooklyn Heights"},
        3: {},
    }
    results = _synthetic_results(4, overrides)
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = results
    at.session_state["_sf_last_status"] = {"overall": "live"}
    at.run()

    assert not at.exception
    dataframes = [el.value for el in at.dataframe]
    results_df = max(dataframes, key=lambda df: len(df))
    assert results_df["Landmark"].iloc[0] == "🏛️ Landmark"
    assert results_df["Landmark"].iloc[1] == "🏛️ Brooklyn Heights District"
    assert results_df["Landmark"].iloc[2] == "🏛️ Landmark + Brooklyn Heights"
    assert results_df["Landmark"].iloc[3] == "—"


def test_landmark_label_pure_unit():
    assert _landmark_label({"landmark": "", "historic_dist": ""}) == "—"
    assert _landmark_label({"landmark": "X", "historic_dist": ""}) == "🏛️ Landmark"
    assert _landmark_label({"landmark": "", "historic_dist": "SoHo"}) == "🏛️ SoHo District"
    assert _landmark_label({"landmark": "X", "historic_dist": "SoHo"}) == "🏛️ Landmark + SoHo"
    assert _landmark_label({}) == "—"


def test_rent_stab_label_pure_unit():
    assert _rent_stab_label({}) == "—"
    assert _rent_stab_label(None) == "—"
    assert _rent_stab_label({"likely_stabilized": True, "verified": True}) == "✅ Confirmed"
    assert _rent_stab_label({"likely_stabilized": True, "verified": False}) == "🟡 Likely (est.)"
    assert _rent_stab_label({"likely_stabilized": False}) == "—"


# ── Batch A: "Bring Your Own List" + Owner Portfolio expansion ─────────────
# AppTest-based coverage proving the new session-state-driven UI blocks
# render without exceptions — no live network calls (nothing is triggered
# here except a seeded st.session_state and a plain rerun; the "Run My
# List"/"Search ACRIS..."/"Load these..." buttons are not clicked, since
# clicking them would exercise the live-fetch code paths this sandbox
# has no network access for).

def test_bring_your_own_list_expander_renders_without_exception():
    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    assert not at.exception

    button_labels = [b.label for b in at.button]
    assert "▶ Run My List" in button_labels
    assert len(at.file_uploader) >= 1


def test_owner_portfolio_expander_renders_without_exception_no_results_yet():
    results = _synthetic_results(1)
    prop = results[0]

    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = results
    at.session_state["_sf_last_status"] = {"overall": "live"}
    at.session_state["_sf_selected_bbl"] = prop["bbl"]
    at.session_state["_sf_selected_prop"] = prop
    at.run()

    assert not at.exception
    button_labels = [b.label for b in at.button]
    assert "Search ACRIS for other properties by this owner" in button_labels


def test_owner_portfolio_expander_renders_seeded_results_table_and_load_button():
    results = _synthetic_results(2)
    prop = results[0]
    other = results[1]

    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = results
    at.session_state["_sf_last_status"] = {"overall": "live"}
    at.session_state["_sf_selected_bbl"] = prop["bbl"]
    at.session_state["_sf_selected_prop"] = prop
    at.session_state[f"_sf_ownerport_results_{prop['bbl']}"] = {
        "error": None,
        "results": [other],
        "status": {"total_fetched": 1, "truncated": False, "error": None},
    }
    at.run()

    assert not at.exception
    button_labels = [b.label for b in at.button]
    assert "Load these as new search results" in button_labels

    dataframes = [el.value for el in at.dataframe]
    op_dfs = [df for df in dataframes if "Deal Score" in df.columns and "Borough" in df.columns and len(df) == 1]
    assert op_dfs, "expected the owner-portfolio results dataframe to be rendered"
    assert op_dfs[0]["Address"].iloc[0] == other["address"]


def test_owner_portfolio_expander_renders_error_state_without_exception():
    results = _synthetic_results(1)
    prop = results[0]

    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = results
    at.session_state["_sf_last_status"] = {"overall": "live"}
    at.session_state["_sf_selected_bbl"] = prop["bbl"]
    at.session_state["_sf_selected_prop"] = prop
    at.session_state[f"_sf_ownerport_results_{prop['bbl']}"] = {
        "error": "One or more ACRIS requests failed or timed out — this result may be incomplete.",
        "results": [],
        "status": None,
    }
    at.run()

    assert not at.exception
    errors = [e.value for e in at.error]
    assert any("Owner portfolio search failed" in e for e in errors)


# ── Batch B: "More Like This" similarity search ─────────────────────────────
# AppTest-based coverage proving the new session-state-driven UI block
# renders without exceptions — no live network calls (mirrors the Owner
# Portfolio AppTest cases above; the "Find similar properties"/"Load
# these..." buttons are not clicked, since clicking them would exercise
# the live-fetch code path this sandbox has no network access for).

def test_more_like_this_expander_renders_without_exception_no_results_yet():
    results = _synthetic_results(1)
    prop = results[0]

    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = results
    at.session_state["_sf_last_status"] = {"overall": "live"}
    at.session_state["_sf_selected_bbl"] = prop["bbl"]
    at.session_state["_sf_selected_prop"] = prop
    at.run()

    assert not at.exception
    button_labels = [b.label for b in at.button]
    assert "Find similar properties" in button_labels


def test_more_like_this_expander_renders_seeded_results_table_and_load_button():
    results = _synthetic_results(2)
    prop = results[0]
    other = results[1]

    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = results
    at.session_state["_sf_last_status"] = {"overall": "live"}
    at.session_state["_sf_selected_bbl"] = prop["bbl"]
    at.session_state["_sf_selected_prop"] = prop
    at.session_state[f"_sf_similar_results_{prop['bbl']}"] = {
        "error": None,
        "results": [other],
        "status": {"total_fetched": 1, "truncated": False, "error": None},
    }
    at.run()

    assert not at.exception
    button_labels = [b.label for b in at.button]
    assert "Load these as new search results" in button_labels

    dataframes = [el.value for el in at.dataframe]
    sim_dfs = [df for df in dataframes if "Deal Score" in df.columns and "Borough" in df.columns and len(df) == 1]
    assert sim_dfs, "expected the more-like-this results dataframe to be rendered"
    assert sim_dfs[0]["Address"].iloc[0] == other["address"]


def test_more_like_this_expander_renders_error_state_without_exception():
    results = _synthetic_results(1)
    prop = results[0]

    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = results
    at.session_state["_sf_last_status"] = {"overall": "live"}
    at.session_state["_sf_selected_bbl"] = prop["bbl"]
    at.session_state["_sf_selected_prop"] = prop
    at.session_state[f"_sf_similar_results_{prop['bbl']}"] = {
        "error": "One or more PLUTO requests failed or timed out — this result may be incomplete.",
        "results": [],
        "status": None,
    }
    at.run()

    assert not at.exception
    errors = [e.value for e in at.error]
    assert any("Similarity search failed" in e for e in errors)


# ── Batch C: tax-lien + composite distress score fusion ────────────────────

def test_tax_lien_column_appears_and_shows_on_lien_list_when_present():
    overrides = {
        0: {
            "owner_type": "Corporate Entity",
            "tax_lien": {"on_lien_list": True, "verified": True, "count": 1},
        },
    }
    results = _synthetic_results(2, overrides)

    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = results
    at.session_state["_sf_last_status"] = {"overall": "live"}
    at.run()

    assert not at.exception
    dataframes = [el.value for el in at.dataframe]
    results_df = max(dataframes, key=lambda df: len(df))

    assert "Tax Lien" in results_df.columns
    assert results_df["Tax Lien"].iloc[0] == "⚠️ On DOF list"


def test_tax_lien_absent_row_renders_fine_without_error():
    # No property carries a "tax_lien" key at all — a normal un-enriched
    # search result — the table must still render without exception.
    results = _synthetic_results(3)

    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = results
    at.session_state["_sf_last_status"] = {"overall": "live"}
    at.run()

    assert not at.exception
    dataframes = [el.value for el in at.dataframe]
    results_df = max(dataframes, key=lambda df: len(df))
    # None of the synthetic rows have tax_lien set, so the column is never
    # added for this render (row-dict builder only adds it conditionally).
    assert "Tax Lien" not in results_df.columns
    assert len(results_df) == 3


# ── Batch D: seller propensity + adjustable Deal Score weights ─────────────

def _synthetic_results_varied_scores(n: int) -> list[dict]:
    """Like _synthetic_results(), but each property gets a DISTINCT
    unused_far_pct (and thus a distinct real deal_score, in descending
    order as constructed) so table-order regressions are actually
    detectable, plus a real compute_seller_propensity() result."""
    props = []
    for i in range(n):
        unused_far_pct = 90.0 - i * 20.0
        raw = {
            "bbl": f"301234{i:04d}", "borough": "Brooklyn", "borough_code": "3",
            "block": "1234", "lot": str(i + 1), "address": f"{100 + i} Test St",
            "zip_code": "11201", "community_district": "302",
            "zoning_dist": "R6A", "landuse_code": "02", "landuse_label": "Multi-Family Walk-Up",
            "bldg_class": "C1", "owner": "TEST OWNER", "owner_type": "",
            "lot_sf": 5000.0, "bldg_sf": 8000.0, "year_built": "1930", "num_floors": 4.0,
            "units_res": 12.0, "units_total": 12.0, "far_built": 1.6, "far_residential": 3.0,
            "far_commercial": 0.0, "far_max": 3.0, "unused_far": 1.4, "unused_far_pct": unused_far_pct,
            "assess_land": 400000.0, "assess_total": 800000.0, "exempt_land": 0.0, "exempt_total": 0.0,
            "is_vacant": (i % 2 == 0), "historic_dist": "", "landmark": "",
            "latitude": 40.69 + i * 0.0001, "longitude": -73.99, "lot_type": "Interior",
        }
        prop = enrich_property(raw)
        prop["deal_score"] = compute_deal_score(unused_far_pct=unused_far_pct, zoning_dist="R6A")
        prop["seller_propensity"] = compute_seller_propensity(
            tenure_years=5.0 + i, distress_level=0, is_vacant=prop["is_vacant"],
        )
        props.append(prop)
    return flag_assemblage_candidates(props)


def test_default_weight_sliders_are_a_no_op_row_order_and_deal_score_unchanged():
    """The single most important regression guard for Feature 13: with the
    weight-adjuster expander present but its sliders left untouched (all at
    the default 1.0), the table's row order and "Deal Score" column values
    must be byte-identical to what they'd be if the expander did not exist
    at all — i.e. still exactly the order/values compute_deal_score()
    produced, descending by score, with no re-sort by any "_display_score"."""
    n = 5
    results = _synthetic_results_varied_scores(n)
    expected_addresses = [p["address"] for p in results]
    expected_scores = [p["deal_score"]["score"] for p in results]
    # Sanity: the synthetic fixture really does produce distinct, already-
    # descending scores, otherwise this test couldn't catch a reordering bug.
    assert expected_scores == sorted(expected_scores, reverse=True)
    assert len(set(expected_scores)) == n

    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = results
    at.session_state["_sf_last_status"] = {"overall": "live"}
    at.run()

    assert not at.exception

    dataframes = [el.value for el in at.dataframe]
    results_df = max(dataframes, key=lambda df: len(df))

    assert list(results_df["Address"]) == expected_addresses
    assert list(results_df["Deal Score"]) == expected_scores


def test_seller_propensity_column_appears_and_is_populated():
    results = _synthetic_results_varied_scores(3)
    expected = [p["seller_propensity"]["score"] for p in results]

    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = results
    at.session_state["_sf_last_status"] = {"overall": "live"}
    at.run()

    assert not at.exception
    dataframes = [el.value for el in at.dataframe]
    results_df = max(dataframes, key=lambda df: len(df))

    assert "Seller Propensity" in results_df.columns
    assert list(results_df["Seller Propensity"]) == expected
    assert all(isinstance(v, int) for v in results_df["Seller Propensity"])


def test_weight_adjuster_expander_and_sliders_render_without_exception():
    results = _synthetic_results_varied_scores(3)

    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = results
    at.session_state["_sf_last_status"] = {"overall": "live"}
    at.run()

    assert not at.exception
    slider_labels = [s.label for s in at.slider]
    for component in ("Unused FAR", "Distress Signals", "Location Demand",
                       "Zoning Flexibility", "Listing Activity"):
        assert component in slider_labels
    button_labels = [b.label for b in at.button]
    assert "↺ Reset weights" in button_labels


def test_weight_adjuster_boosting_a_slider_resorts_display_only():
    """Moving one weight slider away from 1.0 re-sorts the table by the
    adjusted score, but must NOT change the underlying deal_score values
    shown in the "Deal Score" column (still the original, unweighted score)."""
    results = _synthetic_results_varied_scores(3)
    original_scores_by_address = {p["address"]: p["deal_score"]["score"] for p in results}

    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_sf_last_results"] = results
    at.session_state["_sf_last_status"] = {"overall": "live"}
    at.run()
    assert not at.exception

    # Push one component's weight away from 1.0.
    at.slider(key="_sf_weight_Distress Signals").set_value(2.0)
    at.run()
    assert not at.exception

    dataframes = [el.value for el in at.dataframe]
    results_df = max(dataframes, key=lambda df: len(df))

    # Deal Score column always reflects the ORIGINAL, unweighted score —
    # never the reweighted display score — regardless of row order.
    for _, row in results_df.iterrows():
        assert row["Deal Score"] == original_scores_by_address[row["Address"]]

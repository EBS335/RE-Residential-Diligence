"""
AppTest-driven checks for the Site Finder results-table changes:
  - the BBL column is no longer shown
  - "Current Conditions", "Location", "Assemblage", "Rent Stab." columns
    are present
  - the full (unsliced) result set reaches the table — no more hardcoded
    top-50 display cap
"""

import os

from streamlit.testing.v1 import AppTest

from modules.site_sourcing import enrich_property, flag_assemblage_candidates
from modules.deal_scorer import compute_deal_score

_APP_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def _synthetic_results(n: int) -> list[dict]:
    props = []
    for i in range(n):
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

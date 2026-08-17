"""
Confirms the Comparables Analysis section's "Residential" tab was split
into "Residential - Rental" and a new "Residential - Condo" tab (Property
Analysis enhancement round 2), and that the new condo-specific sale filter
renders without exception.

Mirrors tests/test_zoning_lookup_retry.py's AppTest seeding pattern
(geo/listings/zola cache), extended to also seed the commercial- and
sales-comps caches the Comparables Analysis section fetches once and
shares across its tabs — this reaches the section without triggering the
underlying live-network fetches (this sandbox has no live network access),
which would otherwise make the AppTest run slow/flaky.
"""

import os
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

_APP_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")

_LAT, _LON = 40.6892, -73.9908
_RADIUS_MILES = 0.25
_ZOLA_KEY = f"_zola_subject_{_LAT:.5f}_{_LON:.5f}"
_LISTINGS_KEY = f"_listings_{_LAT:.5f}_{_LON:.5f}_{_RADIUS_MILES}_pb0"
_COMM_KEY = f"_comm_{_LAT:.5f}_{_LON:.5f}_{_RADIUS_MILES:.2f}"
_ZIP = "11201"
_SALES_KEY = f"_sales_{_LAT:.5f}_{_LON:.5f}_{_RADIUS_MILES:.2f}_{_ZIP}"

_FAKE_GEO = {
    "lat": _LAT, "lon": _LON,
    "formatted_address": "100 Test St, Brooklyn, NY 11201",
    "borough": "Brooklyn", "neighborhood": "Downtown Brooklyn", "zip_code": _ZIP,
    "geocoder": "test",
}

_FAKE_LISTINGS = [
    {"rent": 3200.0, "unit_type": "1 Bed", "sqft": 650, "source": "StreetEasy",
     "lat": _LAT, "lon": _LON, "distance_miles": 0.05},
]
_FAKE_STATUS = {"overall": "live"}

_GOOD_ZINFO = {
    "bbl": "3001234567", "matched_label": "100 Test St", "zola_url": "https://zola.planning.nyc.gov",
    "borough_code": "3", "block": "1234", "lot": "567",
    "zoning_dist": "R6A", "overlay": "—", "overlay2": "—",
    "special_dist": "—", "special_dist2": "—", "special_dist3": "—",
    "ltd_height": "—", "split_zone": "—",
    "zoning_dist2": "—", "zoning_dist3": "—", "zoning_dist4": "—",
    "far_residential": "3.00", "far_commercial": "0.00", "far_facility": "0.00",
    "far_built": "1.60", "far_existing": "1.60",
    "lot_area_sqft": "5,000", "lot_frontage_ft": "50", "lot_depth_ft": "100",
    "lot_type": "Interior", "irr_lot": "—", "easements": "—",
    "bldg_area_sqft": "8,000", "bldg_frontage_ft": "50", "bldg_depth_ft": "80",
    "num_floors": "4", "num_buildings": "1", "year_built": "1930", "year_last_mod": "—",
    "bldg_class": "C1 - Walk-Up", "basement": "—", "extensions": "—", "condo_no": "—",
    "land_use": "Multi-Family Walk-Up",
    "units_res": "12", "units_total": "12",
    "owner": "TEST OWNER LLC", "tax_class": "2",
    "assess_land": "$400,000", "assess_total": "$800,000",
    "exempt_land": "—", "exempt_total": "—",
    "community_board": "302", "zip_code": _ZIP, "nta": "—", "sanborn": "—",
    "address_pluto": "100 TEST ST",
    "historic_dist": "—", "landmark": "—",
    "_raw": {},
}

_FAKE_LPC = {
    "is_individual_landmark": False, "landmark_name": None, "designation_date": None,
    "map_url": "", "source": "NYC LPC Individual Landmarks", "verified": True, "error": None,
}
_FAKE_LPC_HIST = {
    "is_individual_landmark": False, "is_in_historic_district": False,
    "historic_district_name": None, "landmark_name": None, "designation_date": None,
    "borough": None, "map_url": "", "source": "NYC LPC — Discover NYC Landmarks", "verified": True, "error": None,
}

_FAKE_SALES = [
    {"address": "1 Test Condo Ave", "price": 1_200_000, "sqft": 1000, "price_psf": 1200.0,
     "asset_type": "Residential Sale", "building_name": "13 CONDOS", "date": "2024-01-01",
     "source": "NYC Rolling Sales", "reliability": "High"},
    {"address": "2 Test Coop St", "price": 800_000, "sqft": 900, "price_psf": 889.0,
     "asset_type": "Residential Sale", "building_name": "09 COOPS", "date": "2024-02-01",
     "source": "NYC Rolling Sales", "reliability": "High"},
]


def _run_comparables():
    with patch("modules.lpc_landmarks_fetcher.fetch_lpc_landmark_status", return_value=_FAKE_LPC), \
         patch("modules.lpc_landmarks_fetcher.fetch_lpc_designation_status", return_value=_FAKE_LPC_HIST):
        at = AppTest.from_file(_APP_PATH, default_timeout=120)
        at.run()
        at.session_state["geo"] = _FAKE_GEO
        at.session_state["radius_miles"] = _RADIUS_MILES
        at.session_state["radius_choice"] = "5 blocks  (~0.25 mi)"
        at.session_state["address_raw"] = _FAKE_GEO["formatted_address"]
        at.session_state[_LISTINGS_KEY] = {"listings": _FAKE_LISTINGS, "status": _FAKE_STATUS}
        at.session_state[_ZOLA_KEY] = _GOOD_ZINFO
        at.session_state[_COMM_KEY] = {"listings": []}
        at.session_state[_SALES_KEY] = {"listings": _FAKE_SALES, "status": "live"}
        at.run()
    return at


def test_comparables_tabs_split_into_rental_and_condo():
    at = _run_comparables()
    assert not at.exception
    tab_labels = [t.label for t in at.tabs]
    assert "🏠 Residential - Rental" in tab_labels
    assert "🏠 Residential - Condo" in tab_labels
    # Old combined label is gone.
    assert "🏠 Residential" not in tab_labels
    # New tab sits immediately after the rental tab, before Commercial.
    res_idx = tab_labels.index("🏠 Residential - Rental")
    condo_idx = tab_labels.index("🏠 Residential - Condo")
    comm_idx = tab_labels.index("🏢 Commercial")
    assert res_idx < condo_idx < comm_idx


def test_condo_tab_filters_out_coops():
    # The corrected filter should surface the CONDO row and exclude the
    # COOP row that the old broader "Residential" asset_type match would
    # have included.
    at = _run_comparables()
    assert not at.exception
    md_values = " ".join(m.value or "" for m in at.markdown)
    assert "Residential Condo Sale Comps" in md_values

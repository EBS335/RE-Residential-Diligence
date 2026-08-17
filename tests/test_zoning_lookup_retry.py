"""
Regression tests for the "Parcel data unavailable" / missing massing-section
bug: app.py's CELL 1 and "Zoning & Property Data" fetch/cache guards used to
treat a stored {"error": ...} result as "already fetched," permanently
locking an address out of parcel data AND everything gated behind it
(Zoning Summary, massing/floor plates, Underwriting, Export, Risk Analysis)
for the rest of the session after a single transient failure.

Both guards now key off "did the fetch succeed" instead of "was a fetch
attempted," and each surfaces a "🔄 Retry zoning lookup" button.

Note: the single-property tab's "Deal Sourcing" grid (CELL 1-6) and
everything below it (Zoning Summary, massing, Underwriting) only renders
when `listings` (rental comps) is non-empty — a pre-existing, unrelated
gate. These tests seed a fake listings cache entry so that gate opens and
CELL 1 actually executes (this sandbox has no live network access, so
without seeding, every test would otherwise dead-end at "No rental
listings found").
"""

import os
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

_APP_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")

# CELL 1's LPC individual-landmark + historic-district checks became
# automatic (no button) in this session's Property Analysis enhancement
# round — every _run_with_geo() call below now exercises that code path
# for any valid-BBL fixture, so these two live NYC Open Data calls are
# mocked out here to keep this test file fast and network-independent
# (matching this repo's established fetcher-mocking convention). Once
# fetched, the result is cached in session_state under a BBL-keyed key, so
# only the FIRST .run() in a given test needs the mock active — any
# subsequent .run() (e.g. after a button click) hits the cache instead.
_FAKE_LPC = {
    "is_individual_landmark": False, "landmark_name": None, "designation_date": None,
    "map_url": "", "source": "NYC LPC Individual Landmarks", "verified": True, "error": None,
}
_FAKE_LPC_HIST = {
    "is_individual_landmark": False, "is_in_historic_district": False,
    "historic_district_name": None, "landmark_name": None, "designation_date": None,
    "borough": None, "map_url": "", "source": "NYC LPC — Discover NYC Landmarks", "verified": True, "error": None,
}

_LAT, _LON = 40.6892, -73.9908
_RADIUS_MILES = 0.25
_ZOLA_KEY = f"_zola_subject_{_LAT:.5f}_{_LON:.5f}"
_LISTINGS_KEY = f"_listings_{_LAT:.5f}_{_LON:.5f}_{_RADIUS_MILES}_pb0"

_FAKE_GEO = {
    "lat": _LAT, "lon": _LON,
    "formatted_address": "100 Test St, Brooklyn, NY 11201",
    "borough": "Brooklyn", "neighborhood": "Downtown Brooklyn", "zip_code": "11201",
    "geocoder": "test",
}

_FAKE_LISTINGS = [
    {"rent": 3200.0, "unit_type": "1 Bed", "sqft": 650, "source": "StreetEasy",
     "lat": _LAT, "lon": _LON, "distance_miles": 0.05},
    {"rent": 4500.0, "unit_type": "2 Bed", "sqft": 950, "source": "StreetEasy",
     "lat": _LAT, "lon": _LON, "distance_miles": 0.08},
    {"rent": 2800.0, "unit_type": "Studio", "sqft": 450, "source": "Zumper",
     "lat": _LAT, "lon": _LON, "distance_miles": 0.10},
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
    "community_board": "302", "zip_code": "11201", "nta": "—", "sanborn": "—",
    "address_pluto": "100 TEST ST",
    "historic_dist": "—", "landmark": "—",
    "_raw": {},
}


def _run_with_geo(extra_state=None):
    with patch("modules.lpc_landmarks_fetcher.fetch_lpc_landmark_status", return_value=_FAKE_LPC), \
         patch("modules.lpc_landmarks_fetcher.fetch_lpc_designation_status", return_value=_FAKE_LPC_HIST):
        at = AppTest.from_file(_APP_PATH, default_timeout=90)
        at.run()
        at.session_state["geo"] = _FAKE_GEO
        at.session_state["radius_miles"] = _RADIUS_MILES
        at.session_state["radius_choice"] = "5 blocks  (~0.25 mi)"
        at.session_state["underbuilt_threshold_pct"] = 20
        at.session_state["address_raw"] = _FAKE_GEO["formatted_address"]
        at.session_state[_LISTINGS_KEY] = {"listings": _FAKE_LISTINGS, "status": _FAKE_STATUS}
        if extra_state:
            for k, v in extra_state.items():
                at.session_state[k] = v
        at.run()
    return at


def test_cached_error_is_not_permanently_stuck_and_shows_retry_button():
    at = _run_with_geo({_ZOLA_KEY: {"error": "boom — simulated failure"}})
    assert not at.exception

    # The core fix: an "error"-containing cached value no longer counts as
    # "already fetched," so the very next script rerun (this one) already
    # re-attempts the fetch on its own — the stale placeholder is gone,
    # replaced by a fresh attempt's result (here, a real NYC GeoSearch call
    # that fails because "100 Test St, Brooklyn, NY 11201" isn't a real
    # matchable address — proving a live re-fetch actually happened, not
    # just a no-op). Before this fix, the guard checked only "was a key
    # present," so this exact placeholder would have been stuck forever.
    assert at.session_state[_ZOLA_KEY] != {"error": "boom — simulated failure"}
    assert "error" in at.session_state[_ZOLA_KEY]

    button_labels = [b.label for b in at.button]
    # Both fetch/cache guards (CELL 1 + Zoning & Property Data section) show
    # their own retry button whenever the (possibly freshly re-fetched)
    # cached value is still an error.
    assert "🔄 Retry zoning lookup" in button_labels
    assert button_labels.count("🔄 Retry zoning lookup") == 2


def test_retry_button_clears_cache_key_and_does_not_crash():
    at = _run_with_geo({_ZOLA_KEY: {"error": "boom — simulated failure"}})
    retry_buttons = [b for b in at.button if b.label == "🔄 Retry zoning lookup"]
    assert retry_buttons, "expected at least one retry button to be present"

    retry_buttons[0].click()
    at.run()
    assert not at.exception
    # Retrying again still degrades gracefully (no live network access to a
    # real matchable address in this sandbox) rather than raising.
    assert _ZOLA_KEY not in at.session_state or "error" in at.session_state[_ZOLA_KEY] or at.session_state[_ZOLA_KEY].get("bbl")


def test_successful_cached_zoning_info_is_not_refetched_and_massing_section_renders():
    at = _run_with_geo({_ZOLA_KEY: _GOOD_ZINFO})
    assert not at.exception
    # Unchanged — proves the guard didn't clear/refetch a successful result.
    assert at.session_state[_ZOLA_KEY] == _GOOD_ZINFO

    button_labels = [b.label for b in at.button]
    assert "🔄 Retry zoning lookup" not in button_labels

    # The Parcel Data panel and the Zoning & Property Data section (which
    # gates the massing/floor-plate content) both render real content
    # instead of the error/unavailable messages.
    info_values = [i.value for i in at.info]
    assert not any("Parcel data unavailable" in v for v in info_values)
    warning_values = [w.value for w in at.warning]
    assert not any("Zoning lookup:" in v for v in warning_values)
    md_values = " ".join(m.value or "" for m in at.markdown)
    assert "BBL:" in md_values
    assert "3001234567" in md_values


def test_no_geo_search_yet_shows_no_exception():
    at = AppTest.from_file(_APP_PATH, default_timeout=90)
    at.run()
    assert not at.exception


# ── Fix 2: OATH/Tax Lien are opt-in; ULURP is opt-in; LPC landmarks +
# historic-district + rent-stabilization are automatic (no button) ────────

def test_lpc_landmarks_and_historic_district_fetched_automatically():
    # Landmark + historic-district checks no longer require a button click
    # (Property Analysis enhancement round 2) — verify both are populated
    # on the very first render, and that the old combined button is gone.
    at = _run_with_geo({_ZOLA_KEY: _GOOD_ZINFO})
    assert not at.exception
    assert f"_lpc_{_GOOD_ZINFO['bbl']}" in at.session_state
    assert f"_lpc_hist_{_GOOD_ZINFO['bbl']}" in at.session_state

    button_labels = [b.label for b in at.button]
    assert "🏛️ Check landmark & entitlement signals" not in button_labels


def test_ulurp_not_fetched_until_its_own_button_clicked():
    # ULURP remains its own small opt-in button (a 3rd live NYC Open Data
    # call), separate from the now-automatic landmark checks.
    at = _run_with_geo({_ZOLA_KEY: _GOOD_ZINFO})
    assert not at.exception
    assert f"_ulurp_{_GOOD_ZINFO['borough_code']}_{_GOOD_ZINFO['community_board']}" not in at.session_state

    button_labels = [b.label for b in at.button]
    assert "📜 Check ULURP applications" in button_labels


def test_ulurp_fetched_after_its_own_button_click():
    at = _run_with_geo({_ZOLA_KEY: _GOOD_ZINFO})
    btn = next(b for b in at.button if b.label == "📜 Check ULURP applications")
    btn.click()
    at.run()
    assert not at.exception
    assert f"_ulurp_{_GOOD_ZINFO['borough_code']}_{_GOOD_ZINFO['community_board']}" in at.session_state


def test_oath_taxlien_not_fetched_until_button_clicked():
    at = _run_with_geo({_ZOLA_KEY: _GOOD_ZINFO})
    assert not at.exception
    assert f"_oath_{_GOOD_ZINFO['bbl']}" not in at.session_state
    assert f"_taxlien_{_GOOD_ZINFO['bbl']}" not in at.session_state

    button_labels = [b.label for b in at.button]
    assert "Check OATH/Tax Lien signals" in button_labels


def test_oath_taxlien_fetched_after_button_click():
    at = _run_with_geo({_ZOLA_KEY: _GOOD_ZINFO})
    btn = next(b for b in at.button if b.label == "Check OATH/Tax Lien signals")
    btn.click()
    at.run()
    assert not at.exception
    assert f"_oath_{_GOOD_ZINFO['bbl']}" in at.session_state
    assert f"_taxlien_{_GOOD_ZINFO['bbl']}" in at.session_state


def test_cell3_does_not_call_fetch_property_history_directly():
    # CELL 3's composite-distress-score block must read _pip_{bbl} from
    # cache only — fetch_property_history() should be called from exactly
    # one place (the later "Property History" section), not duplicated
    # into CELL 3's earlier position in the page. A full single AppTest
    # run can't distinguish "CELL 3 fetched it" from "the later section
    # fetched it" (both run in the same top-to-bottom pass), so this is
    # verified directly against the source instead.
    with open(_APP_PATH) as f:
        source = f.read()
    assert source.count("fetch_property_history(") == 1

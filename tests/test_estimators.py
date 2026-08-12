from modules.abatement_estimator import estimate_tax_abatement
from modules.rent_stab_estimator import estimate_rent_stabilization


# ── Tax abatement estimator ─────────────────────────────────────────────────

def test_abatement_currently_exempt_from_verified_pluto_field():
    result = estimate_tax_abatement({"exempt_total": 500_000, "year_built": "1990", "units_res": 4})
    assert result["currently_exempt"] is True
    assert result["exempt_value"] == 500_000
    assert result["error"] is None


def test_abatement_not_exempt_when_zero():
    result = estimate_tax_abatement({"exempt_total": 0, "year_built": "1990", "units_res": 4})
    assert result["currently_exempt"] is False


def test_abatement_unknown_when_field_missing():
    result = estimate_tax_abatement({"year_built": "1990", "units_res": 4})
    assert result["currently_exempt"] is None


def test_abatement_never_raises_on_empty_or_none_input():
    assert estimate_tax_abatement({})["error"] is None
    assert estimate_tax_abatement(None)["error"] is None


def test_abatement_programs_are_all_marked_unverified():
    result = estimate_tax_abatement({"year_built": "1920", "units_res": 12})
    assert len(result["estimated_programs"]) == 3
    for p in result["estimated_programs"]:
        assert p["verified"] is False
        assert 0.0 <= p["confidence"] <= 1.0


def test_abatement_handles_display_formatted_strings():
    # zola_fetcher._zinfo shape: "$500,000" instead of a raw float
    result = estimate_tax_abatement({"exempt_total": "$500,000", "year_built": "1920", "units_res": "12"})
    assert result["currently_exempt"] is True


def test_abatement_handles_em_dash_placeholder():
    result = estimate_tax_abatement({"exempt_total": "—", "year_built": "—", "units_res": "—"})
    assert result["currently_exempt"] is None
    assert result["error"] is None


# ── Rent stabilization estimator ────────────────────────────────────────────

def test_rentstab_pre1974_6plus_units_flags_true():
    result = estimate_rent_stabilization({"year_built": "1930", "units_res": 20})
    assert result["likely_stabilized"] is True
    assert result["verified"] is False


def test_rentstab_new_construction_not_flagged():
    result = estimate_rent_stabilization({"year_built": "2015", "units_res": 20, "exempt_total": 0})
    assert result["likely_stabilized"] is False


def test_rentstab_small_pre1974_building_not_flagged_on_age_alone():
    result = estimate_rent_stabilization({"year_built": "1930", "units_res": 2, "exempt_total": 0})
    assert result["likely_stabilized"] is False


def test_rentstab_verified_always_false():
    for prop in ({}, {"year_built": "1900", "units_res": 100}, None):
        assert estimate_rent_stabilization(prop)["verified"] is False


def test_rentstab_never_raises_on_malformed_input():
    result = estimate_rent_stabilization({"year_built": "not a year", "units_res": "many"})
    assert result["error"] is None
    assert result["likely_stabilized"] is False


def test_rentstab_confidence_in_range():
    result = estimate_rent_stabilization({"year_built": "1950", "units_res": 8})
    assert 0.0 <= result["confidence"] <= 1.0


def test_rentstab_includes_dhcr_lookup_url():
    result = estimate_rent_stabilization({})
    assert result["dhcr_lookup_url"].startswith("https://")

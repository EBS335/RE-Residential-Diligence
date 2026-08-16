from modules.carbon_compliance import (
    compute_ll97_compliance, map_landuse_to_occupancy_group,
    LL97_EMISSIONS_LIMITS_KGCO2E_PER_SF, PENALTY_PER_TON_OVER,
)


def test_no_emissions_supplied_returns_limit_only_unknown_status():
    result = compute_ll97_compliance(50_000, "Multifamily Residential")
    assert result["error"] is None
    assert result["emissions_limit_tons"] is not None
    assert result["compliance_status"] == "unknown — no reported emissions data"
    assert result["verified"] is False
    assert result["over_limit_tons"] is None


def test_emissions_under_limit_is_compliant():
    limit = LL97_EMISSIONS_LIMITS_KGCO2E_PER_SF["Multifamily Residential"]["2024-2029"]
    sf = 50_000
    exact_limit_tons = limit * sf / 1000.0
    result = compute_ll97_compliance(sf, "Multifamily Residential", annual_emissions_tons_co2e=exact_limit_tons - 10)
    assert result["compliance_status"] == "compliant"
    assert result["over_limit_tons"] == 0.0
    assert result["estimated_annual_penalty"] == 0.0
    assert result["verified"] is True


def test_emissions_over_limit_computes_penalty():
    limit = LL97_EMISSIONS_LIMITS_KGCO2E_PER_SF["Office"]["2024-2029"]
    sf = 30_000
    exact_limit_tons = limit * sf / 1000.0
    over_by = 25.0
    result = compute_ll97_compliance(sf, "Office", annual_emissions_tons_co2e=exact_limit_tons + over_by)
    assert result["compliance_status"] == "over_limit"
    assert abs(result["over_limit_tons"] - over_by) < 0.5
    assert abs(result["estimated_annual_penalty"] - over_by * PENALTY_PER_TON_OVER) < 200


def test_later_period_has_stricter_limit():
    early = compute_ll97_compliance(50_000, "Office", period="2024-2029")
    late = compute_ll97_compliance(50_000, "Office", period="2030-2034")
    assert late["emissions_limit_tons"] < early["emissions_limit_tons"]


def test_unrecognized_occupancy_group_returns_error_never_raises():
    result = compute_ll97_compliance(50_000, "Not A Real Group")
    assert result["error"] is not None
    assert result["emissions_limit_tons"] is None


def test_unrecognized_period_returns_error_never_raises():
    result = compute_ll97_compliance(50_000, "Office", period="1999-2000")
    assert result["error"] is not None


def test_zero_or_negative_sf_returns_error_never_raises():
    assert compute_ll97_compliance(0, "Office")["error"] is not None
    assert compute_ll97_compliance(-100, "Office")["error"] is not None


def test_garbage_input_never_raises():
    result = compute_ll97_compliance("not a number", "Office")  # type: ignore
    assert result["error"] is not None
    assert "emissions_limit_tons" in result


def test_map_landuse_to_occupancy_group_known_and_unknown():
    assert map_landuse_to_occupancy_group("Multi-Family Walk-Up") == "Multifamily Residential"
    assert map_landuse_to_occupancy_group("Some Unrecognized Land Use") is None
    assert map_landuse_to_occupancy_group("") is None
    assert map_landuse_to_occupancy_group(None) is None

from modules.unit_mix import (
    net_rentable_sf, optimize_unit_mix, compute_revenue, get_avg_sf,
    LOSS_FACTOR_NEW, LOSS_FACTOR_CONVERSION,
)


def test_net_rentable_sf_new_construction_vs_conversion():
    gross = 10_000.0
    new_construction = net_rentable_sf(gross, is_conversion=False)
    conversion = net_rentable_sf(gross, is_conversion=True)

    assert new_construction == gross * (1 - LOSS_FACTOR_NEW)
    assert conversion == gross * (1 - LOSS_FACTOR_CONVERSION)
    # Conversion has a larger loss factor, so less net rentable SF
    assert conversion < new_construction


def test_net_rentable_sf_never_negative():
    assert net_rentable_sf(0.0) == 0.0
    assert net_rentable_sf(-500.0) == 0.0


def test_optimize_unit_mix_totals_within_rounding_of_input():
    net_sf = 50_000.0
    mix = optimize_unit_mix(net_sf, "Manhattan")
    assert "_totals" in mix
    # Floor-division allocation means used SF is <= input, never more
    assert mix["_totals"]["total_sf"] <= net_sf
    assert mix["_totals"]["total_units"] > 0


def test_get_avg_sf_unknown_neighborhood_falls_back_to_default():
    from modules.unit_mix import NEIGHBORHOOD_AVG_SF
    result = get_avg_sf("Nonexistent Neighborhood XYZ")
    assert result == NEIGHBORHOOD_AVG_SF["_default"]


def test_compute_revenue_risk_tier_ordering():
    unit_mix = optimize_unit_mix(50_000.0, "Manhattan")
    avg_rents = {"Studio": 2800, "1 Bed": 3500, "2 Bed": 5000, "3 Bed": 7500, "4+ Bed": 11000}

    low = compute_revenue(unit_mix, avg_rents, risk_level="LOW")
    med = compute_revenue(unit_mix, avg_rents, risk_level="MED")
    high = compute_revenue(unit_mix, avg_rents, risk_level="HIGH")

    # HIGH's larger rent multiplier (1.08) outweighs its lower occupancy
    # (0.88) relative to LOW (0.95 rent mult, 0.94 occ) -- net effective
    # revenue factor: HIGH (0.9504) > MED (0.92) > LOW (0.893)
    assert high["egi"] > med["egi"] > low["egi"]


def test_compute_revenue_shape():
    unit_mix = optimize_unit_mix(30_000.0, "Manhattan")
    result = compute_revenue(unit_mix, {}, risk_level="MED")
    for key in ("line_items", "gross_annual_rent", "egi", "opex", "noi",
                "cap_rate_used", "est_cap_value", "risk_level", "borough"):
        assert key in result
    assert result["noi"] == result["egi"] - result["opex"]

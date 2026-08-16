from modules.structural_risk import compute_structural_vintage_risk, recommend_structural_system


# ── compute_structural_vintage_risk ──────────────────────────────────────────

def test_pre_1901_scores_highest():
    result = compute_structural_vintage_risk(1895)
    assert result["tier"] == "High"
    assert result["score"] >= 70
    assert "Pre-1901" in result["era_label"]


def test_modern_construction_scores_lowest():
    result = compute_structural_vintage_risk(2015)
    assert result["tier"] == "Low"
    assert result["score"] <= 20


def test_risk_decreases_monotonically_with_era():
    scores = [compute_structural_vintage_risk(yb)["score"] for yb in (1895, 1920, 1945, 1965, 1985, 2015)]
    assert scores == sorted(scores, reverse=True)


def test_tall_pre_1968_building_gets_height_bump():
    low_rise = compute_structural_vintage_risk(1950, num_floors=3)
    high_rise = compute_structural_vintage_risk(1950, num_floors=10)
    assert high_rise["score"] > low_rise["score"]


def test_missing_year_built_never_raises():
    result = compute_structural_vintage_risk(None)
    assert result["score"] is None
    assert result["notes"] is not None


def test_malformed_year_built_never_raises():
    result = compute_structural_vintage_risk("not a year")
    assert result["score"] is None


def test_never_claims_verified():
    result = compute_structural_vintage_risk(1930)
    assert result["verified"] is False


# ── recommend_structural_system ──────────────────────────────────────────────

def test_narrow_frontage_recommends_wood_or_light_steel():
    result = recommend_structural_system(16)
    assert "Wood" in result["recommended_system"] or "light" in result["recommended_system"].lower()


def test_wide_frontage_recommends_concrete_or_composite():
    result = recommend_structural_system(120)
    assert "concrete" in result["recommended_system"].lower()


def test_height_flag_set_when_target_exceeds_typical_for_frontage():
    result = recommend_structural_system(16, target_floors=20)
    assert result["height_flag"] is not None


def test_no_height_flag_when_within_typical_range():
    result = recommend_structural_system(60, target_floors=10)
    assert result["height_flag"] is None


def test_zero_frontage_never_raises():
    result = recommend_structural_system(0)
    assert result["recommended_system"] is None
    assert result["rationale"] is not None

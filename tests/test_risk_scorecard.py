from modules.risk_scorecard import compute_composite_risk_scorecard


def test_all_clean_signals_scores_low_no_review_needed():
    result = compute_composite_risk_scorecard()
    assert result["physical"]["score"] == 0
    assert result["financial"]["score"] == 0
    assert result["regulatory"]["score"] == 0
    assert result["overall_tier"] == "Low"
    assert result["needs_manual_review"] is False


def test_flood_zone_drives_physical_bucket():
    result = compute_composite_risk_scorecard(flood_data={"in_special_flood_hazard_area": True, "flood_zone": "AE"})
    assert result["physical"]["score"] > 0
    assert any("Flood Hazard" in f for f in result["physical"]["factors"])


def test_foreclosure_drives_financial_bucket():
    result = compute_composite_risk_scorecard(acris_summary={"foreclosure_count": 1, "open_liens": 0})
    assert result["financial"]["score"] > 0
    assert any("foreclosure" in f.lower() for f in result["financial"]["factors"])


def test_landmark_and_rent_stab_drive_regulatory_bucket():
    result = compute_composite_risk_scorecard(is_landmark=True, rent_stab_likely=True)
    assert result["regulatory"]["score"] > 0
    assert len(result["regulatory"]["factors"]) == 2


def test_high_bucket_score_triggers_manual_review():
    result = compute_composite_risk_scorecard(
        acris_summary={"foreclosure_count": 2, "open_liens": 3},
    )
    assert result["financial"]["score"] >= 70
    assert result["needs_manual_review"] is True
    assert result["needs_manual_review_reasons"]


def test_data_gaps_trigger_manual_review_even_with_low_scores():
    result = compute_composite_risk_scorecard(data_gaps=["ACRIS request failed"])
    assert result["needs_manual_review"] is True
    assert "ACRIS request failed" in result["needs_manual_review_reasons"]


def test_overall_score_is_average_of_three_buckets():
    result = compute_composite_risk_scorecard(
        flood_data={"in_special_flood_hazard_area": True},
        acris_summary={"foreclosure_count": 1},
        is_landmark=True,
    )
    expected = round((result["physical"]["score"] + result["financial"]["score"] + result["regulatory"]["score"]) / 3)
    assert result["overall_score"] == expected


def test_never_raises_on_garbage_input():
    result = compute_composite_risk_scorecard(
        flood_data="not a dict", acris_summary=None, structural_risk_result=[],  # type: ignore
    )
    assert "overall_score" in result
    assert 0 <= result["overall_score"] <= 100


def test_structural_risk_result_feeds_physical_bucket():
    result = compute_composite_risk_scorecard(
        structural_risk_result={"score": 90, "era_label": "Pre-1901 (pre-code)"},
    )
    assert result["physical"]["score"] > 0
    assert any("Structural-vintage" in f for f in result["physical"]["factors"])


def test_distress_score_feeds_financial_bucket():
    result = compute_composite_risk_scorecard(
        distress_score_result={"score": 80, "tier": "Severe"},
    )
    assert result["financial"]["score"] > 0
    assert any("distress" in f.lower() for f in result["financial"]["factors"])

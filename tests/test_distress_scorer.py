from modules.distress_scorer import compute_composite_distress_score, DEFAULT_WEIGHTS


def test_all_clean_signals_score_zero_minimal():
    result = compute_composite_distress_score()
    assert result["score"] == 0
    assert result["tier"] == "Minimal"
    assert result["components_with_data"] == []


def test_foreclosure_and_liens_drive_acris_component():
    result = compute_composite_distress_score(acris_summary={"foreclosure_count": 1, "open_liens": 2})
    assert result["breakdown"]["acris"]["score"] > 0
    assert "acris" in result["components_with_data"]
    assert result["score"] > 0


def test_all_components_maxed_scores_100_severe():
    result = compute_composite_distress_score(
        acris_summary={"foreclosure_count": 5, "open_liens": 5},
        dob_open_violations=20, dob_open_complaints=20,
        hpd_open_violations=20,
        oath_data={"open_balance_count": 10, "verified": True},
        tax_lien_data={"on_lien_list": True, "verified": True},
    )
    assert result["score"] == 100
    assert result["tier"] == "Severe"
    assert set(result["components_with_data"]) == {"acris", "dob", "hpd", "oath", "tax_lien"}


def test_tier_thresholds_ordered_correctly():
    low = compute_composite_distress_score(dob_open_violations=1)
    high = compute_composite_distress_score(
        acris_summary={"foreclosure_count": 5, "open_liens": 5}, dob_open_violations=20,
    )
    assert low["score"] < high["score"]


def test_custom_weights_normalized_and_change_outcome():
    # All weight on tax_lien: a lien-list hit alone should now score ~100.
    result = compute_composite_distress_score(
        tax_lien_data={"on_lien_list": True, "verified": True},
        weights={"acris": 0, "dob": 0, "hpd": 0, "oath": 0, "tax_lien": 1.0},
    )
    assert result["score"] == 100


def test_weights_that_sum_to_zero_fall_back_to_defaults():
    result = compute_composite_distress_score(
        acris_summary={"foreclosure_count": 1},
        weights={"acris": 0, "dob": 0, "hpd": 0, "oath": 0, "tax_lien": 0},
    )
    # Falls back to DEFAULT_WEIGHTS rather than dividing by zero.
    assert result["breakdown"]["acris"]["weight"] == DEFAULT_WEIGHTS["acris"]


def test_never_raises_on_garbage_input():
    result = compute_composite_distress_score(
        acris_summary="not a dict", oath_data=None, tax_lien_data=None,  # type: ignore
    )
    assert "score" in result
    assert 0 <= result["score"] <= 100


def test_breakdown_scores_sum_to_total():
    result = compute_composite_distress_score(
        acris_summary={"foreclosure_count": 1, "open_liens": 1},
        dob_open_violations=3, hpd_open_violations=2,
        oath_data={"open_balance_count": 1, "verified": True},
        tax_lien_data={"on_lien_list": False, "verified": True},
    )
    assert sum(c["score"] for c in result["breakdown"].values()) == result["score"]

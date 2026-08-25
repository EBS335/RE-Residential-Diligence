import copy

from modules.deal_scorer import (
    compute_deal_score,
    compute_bulk_deal_scores,
    _zoning_flexibility,
    compute_seller_propensity,
    compute_bulk_seller_propensity,
    recompute_display_score,
)


def test_score_bounds_extreme_inputs():
    result = compute_deal_score(
        unused_far_pct=500.0, distress_level=2, neighborhood_rent_premium=1000.0,
        zoning_dist="M1-1", listings_nearby=1000, has_overlay=True,
    )
    assert 0 <= result["score"] <= 100

    result_min = compute_deal_score(
        unused_far_pct=-50.0, distress_level=0, neighborhood_rent_premium=-100.0,
        zoning_dist="", listings_nearby=0,
    )
    assert 0 <= result_min["score"] <= 100


def test_score_has_tier_and_breakdown():
    result = compute_deal_score(unused_far_pct=50.0, distress_level=1)
    assert result["tier"] in ("Strong Lead", "Watch", "Pass")
    assert set(result["breakdown"].keys()) == {
        "Unused FAR", "Distress Signals", "Location Demand",
        "Zoning Flexibility", "Listing Activity",
    }


def test_zoning_flexibility_tier_ordering():
    # M (manufacturing) > C (commercial) > high-density R > low-density R
    m_score = _zoning_flexibility("M1-1")
    c_score = _zoning_flexibility("C6-2")
    r_high = _zoning_flexibility("R8")
    r_low = _zoning_flexibility("R3")
    assert m_score > c_score > r_high > r_low


def test_zoning_flexibility_empty_defaults_low():
    assert _zoning_flexibility("") == 5
    assert _zoning_flexibility(None) == 5


def test_compute_bulk_deal_scores_non_mutating_and_adds_deal_score():
    properties = [
        {"bbl": "1001", "unused_far_pct": 30.0, "distress_signal": "No Signal"},
        {"bbl": "1002", "unused_far_pct": 80.0, "distress_signal": "Strong Signal"},
    ]
    original = [dict(p) for p in properties]

    scored = compute_bulk_deal_scores(properties)

    # Input list/dicts must be unchanged
    assert properties == original

    # Output has deal_score added, all original keys preserved
    for p in scored:
        assert "deal_score" in p
        assert "score" in p["deal_score"]
        assert "tier" in p["deal_score"]

    # Sorted descending by score
    scores = [p["deal_score"]["score"] for p in scored]
    assert scores == sorted(scores, reverse=True)


def test_compute_bulk_deal_scores_infers_distress_from_signal_string():
    properties = [
        {"bbl": "2001", "distress_signal": "Strong Signal"},
        {"bbl": "2002", "distress_signal": "No Signal"},
    ]
    scored = compute_bulk_deal_scores(properties)
    by_bbl = {p["bbl"]: p for p in scored}
    # Strong Signal (distress_level=2) should score at least as high on the
    # Distress Signals component as No Signal (distress_level=0)
    assert (by_bbl["2001"]["deal_score"]["breakdown"]["Distress Signals"]["score"]
            > by_bbl["2002"]["deal_score"]["breakdown"]["Distress Signals"]["score"])


def test_compute_bulk_deal_scores_explicit_distress_level_takes_precedence():
    properties = [{"bbl": "3001", "distress_level": 2, "distress_signal": "No Signal"}]
    scored = compute_bulk_deal_scores(properties)
    assert scored[0]["deal_score"]["breakdown"]["Distress Signals"]["score"] == 25


# ── Feature 6: Seller Propensity Score ────────────────────────────────────────

def test_seller_propensity_unknown_tenure_gets_neutral_partial_credit():
    unknown = compute_seller_propensity(tenure_years=None)
    zero_tenure_equivalent = compute_seller_propensity(tenure_years=0.0)
    # Unknown tenure must NOT be treated as zero — it gets partial credit
    # strictly between the <5yr bucket's score and the >10yr bucket's score.
    assert unknown["breakdown"]["Tenure"]["score"] == 20
    assert unknown["breakdown"]["Tenure"]["score"] > 0
    assert unknown["breakdown"]["Tenure"]["score"] != zero_tenure_equivalent["breakdown"]["Tenure"]["score"]


def test_seller_propensity_long_tenure_scores_higher_than_short_tenure():
    long_tenure = compute_seller_propensity(tenure_years=15.0)
    short_tenure = compute_seller_propensity(tenure_years=2.0)
    assert long_tenure["breakdown"]["Tenure"]["score"] > short_tenure["breakdown"]["Tenure"]["score"]
    assert long_tenure["score"] > short_tenure["score"]


def test_seller_propensity_vacancy_adds_flat_bonus():
    vacant = compute_seller_propensity(tenure_years=5.0, is_vacant=True)
    occupied = compute_seller_propensity(tenure_years=5.0, is_vacant=False)
    assert vacant["breakdown"]["Vacancy"]["score"] == 25
    assert occupied["breakdown"]["Vacancy"]["score"] == 0
    assert vacant["score"] == occupied["score"] + 25


def test_seller_propensity_higher_distress_scores_higher():
    high_distress = compute_seller_propensity(distress_level=2)
    low_distress = compute_seller_propensity(distress_level=0)
    assert high_distress["breakdown"]["Distress"]["score"] > low_distress["breakdown"]["Distress"]["score"]


def test_seller_propensity_score_bounded_0_100():
    best = compute_seller_propensity(tenure_years=50.0, distress_level=2, is_vacant=True)
    worst = compute_seller_propensity(tenure_years=0.0, distress_level=0, is_vacant=False)
    assert 0 <= worst["score"] <= 100
    assert 0 <= best["score"] <= 100


def test_seller_propensity_tier_thresholds_match_deal_score_convention():
    # Mirrors compute_deal_score()'s >=70 / >=40 / else convention, with the
    # distinct propensity-appropriate vocabulary.
    high = compute_seller_propensity(tenure_years=15.0, distress_level=2, is_vacant=True)
    assert high["score"] >= 70
    assert high["tier"] == "High"

    low = compute_seller_propensity(tenure_years=2.0, distress_level=0, is_vacant=False)
    assert low["score"] < 40
    assert low["tier"] == "Low"

    for result in (
        compute_seller_propensity(),
        compute_seller_propensity(tenure_years=7.0, distress_level=1),
    ):
        if result["score"] >= 70:
            assert result["tier"] == "High"
        elif result["score"] >= 40:
            assert result["tier"] == "Moderate"
        else:
            assert result["tier"] == "Low"


def test_seller_propensity_shape():
    result = compute_seller_propensity(tenure_years=5.0, distress_level=1, is_vacant=True)
    assert set(result.keys()) == {"score", "tier", "breakdown"}
    assert set(result["breakdown"].keys()) == {"Tenure", "Distress", "Vacancy"}
    for detail in result["breakdown"].values():
        assert set(detail.keys()) == {"score", "max", "reasoning"}


def test_compute_bulk_seller_propensity_returns_new_list_non_mutating():
    properties = [
        {"bbl": "4001", "distress_signal": "No Signal", "is_vacant": False},
        {"bbl": "4002", "distress_signal": "Strong Signal", "is_vacant": True, "last_sale_date": "2010-01-01"},
    ]
    original = copy.deepcopy(properties)

    scored = compute_bulk_seller_propensity(properties)

    # Input list/dicts must be entirely unchanged.
    assert properties == original
    assert scored is not properties

    for p in scored:
        assert "seller_propensity" in p
        assert "score" in p["seller_propensity"]
        assert "deal_score" not in p  # this function never touches deal_score


def test_compute_bulk_seller_propensity_does_not_reorder():
    properties = [
        {"bbl": "5001", "distress_signal": "No Signal"},
        {"bbl": "5002", "distress_signal": "Strong Signal", "is_vacant": True},
        {"bbl": "5003", "distress_signal": "Weak Signal"},
    ]
    scored = compute_bulk_seller_propensity(properties)
    assert [p["bbl"] for p in scored] == ["5001", "5002", "5003"]


def test_compute_bulk_seller_propensity_derives_tenure_from_last_sale_date():
    properties = [{"bbl": "6001", "last_sale_date": "2005-03-01"}]  # long tenure
    scored = compute_bulk_seller_propensity(properties)
    assert scored[0]["seller_propensity"]["breakdown"]["Tenure"]["score"] == 40


def test_compute_bulk_seller_propensity_leaves_deal_score_untouched_when_present():
    properties = [
        {"bbl": "7001", "unused_far_pct": 40.0, "distress_signal": "No Signal"},
    ]
    with_deal_score = compute_bulk_deal_scores(properties)
    with_both = compute_bulk_seller_propensity(with_deal_score)
    assert with_both[0]["deal_score"] == with_deal_score[0]["deal_score"]
    assert "seller_propensity" in with_both[0]


# ── Feature 13: Adjustable Deal Score Weights (recompute_display_score) ──────

def test_recompute_display_score_default_multipliers_reproduce_original_score():
    for kwargs in (
        dict(unused_far_pct=40.0, distress_level=1, neighborhood_rent_premium=5.0,
             zoning_dist="R6", listings_nearby=3),
        dict(unused_far_pct=90.0, distress_level=2, neighborhood_rent_premium=25.0,
             zoning_dist="C6-2", listings_nearby=0, has_overlay=True),
        dict(unused_far_pct=0.0, distress_level=0, neighborhood_rent_premium=-10.0,
             zoning_dist="", listings_nearby=10),
    ):
        original = compute_deal_score(**kwargs)
        recomputed_none = recompute_display_score(original["breakdown"], None)
        recomputed_ones = recompute_display_score(
            original["breakdown"],
            {k: 1.0 for k in original["breakdown"]},
        )
        assert recomputed_none["score"] == original["score"]
        assert recomputed_ones["score"] == original["score"]
        assert recomputed_none["tier"] == original["tier"]


def test_recompute_display_score_boosting_component_increases_relative_score():
    original = compute_deal_score(
        unused_far_pct=50.0, distress_level=1, neighborhood_rent_premium=5.0,
        zoning_dist="R6", listings_nearby=2,
    )
    baseline = recompute_display_score(original["breakdown"])
    # Renormalization is a weighted average of each component's own
    # (score/max) fraction — boosting a component's multiplier only pulls
    # the combined score UP relative to baseline when that component's own
    # fraction is already above the current weighted average (here,
    # "Distress Signals" scores 17/25 = 0.68, well above the ~0.55 overall
    # average), and pulls it down when boosting a below-average component.
    # This is the correct, non-naive behavior for a true reweighting.
    boosted = recompute_display_score(original["breakdown"], {"Distress Signals": 2.0})
    assert boosted["score"] > baseline["score"]

    below_average_component = "Unused FAR"
    assert (
        original["breakdown"][below_average_component]["score"] / original["breakdown"][below_average_component]["max"]
        < baseline["score"] / 100
    )
    dampened = recompute_display_score(original["breakdown"], {below_average_component: 2.0})
    assert dampened["score"] < baseline["score"]


def test_recompute_display_score_never_mutates_input_breakdown():
    original = compute_deal_score(unused_far_pct=60.0, distress_level=2, listings_nearby=4)
    breakdown_before = copy.deepcopy(original["breakdown"])
    recompute_display_score(original["breakdown"], {"Unused FAR": 1.7, "Distress Signals": 0.6})
    assert original["breakdown"] == breakdown_before


def test_recompute_display_score_bounded_0_100():
    original = compute_deal_score(unused_far_pct=80.0, distress_level=2, listings_nearby=10)
    result = recompute_display_score(original["breakdown"], {c: 2.0 for c in original["breakdown"]})
    assert 0 <= result["score"] <= 100
    result_low = recompute_display_score(original["breakdown"], {c: 0.5 for c in original["breakdown"]})
    assert 0 <= result_low["score"] <= 100


def test_recompute_display_score_returns_shape():
    original = compute_deal_score(unused_far_pct=30.0, distress_level=1)
    result = recompute_display_score(original["breakdown"])
    assert set(result.keys()) == {"score", "tier"}
    assert result["tier"] in ("Strong Lead", "Watch", "Pass")

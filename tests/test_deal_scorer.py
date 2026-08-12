from modules.deal_scorer import compute_deal_score, compute_bulk_deal_scores, _zoning_flexibility


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

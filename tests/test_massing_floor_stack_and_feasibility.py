from modules.massing_viz import build_massing_options, build_floor_stack, _calc_massing
from modules.massing_feasibility import compute_massing_feasibility_score
from modules.zoning_rules import get_zoning_rules


def _scenarios():
    rules = get_zoning_rules("R6A")
    return build_massing_options(50.0, 100.0, 5000.0, "R6A", rules), rules


def _m(rules):
    return _calc_massing(50.0, 100.0, 5000.0, rules)


# ── build_floor_stack ────────────────────────────────────────────────────────

def test_build_floor_stack_returns_one_row_per_floor():
    scenarios, rules = _scenarios()
    m = _m(rules)
    scenario = scenarios[0]
    stack = build_floor_stack(scenario, m)
    assert len(stack) == scenario["floors"]
    assert [f["floor_num"] for f in stack] == list(range(1, scenario["floors"] + 1))


def test_build_floor_stack_ground_floor_is_retail_for_mixed_use_scenario():
    scenarios, rules = _scenarios()
    m = _m(rules)
    mixed = next((s for s in scenarios if "mixed" in s["name"].lower()), None)
    assert mixed is not None, "expected a Mixed-Use scenario among the 10 options"
    stack = build_floor_stack(mixed, m)
    assert stack[0]["use"] == "Retail/Commercial"
    assert stack[0]["program_label"] == "Ground Floor Retail"


def test_build_floor_stack_ground_floor_is_residential_for_non_mixed_scenario():
    scenarios, rules = _scenarios()
    m = _m(rules)
    non_mixed = next(s for s in scenarios if "mixed" not in s["name"].lower())
    stack = build_floor_stack(non_mixed, m)
    assert stack[0]["use"] == "Residential"


def test_build_floor_stack_flags_setback_zone_above_floors_at_base():
    scenarios, rules = _scenarios()
    m = _m(rules)
    # Find a scenario tall enough to exceed floors_at_base.
    tall = max(scenarios, key=lambda s: s["floors"])
    stack = build_floor_stack(tall, m)
    if tall["floors"] > m["floors_at_base"]:
        assert any(f["is_in_setback_zone"] for f in stack)
        assert not stack[0]["is_in_setback_zone"]
    else:
        assert all(not f["is_in_setback_zone"] for f in stack)


def test_build_floor_stack_never_raises_on_malformed_scenario():
    # An empty scenario dict degrades to a sane 1-floor default rather than
    # raising — never an exception, always a list.
    empty_result = build_floor_stack({}, {})
    assert isinstance(empty_result, list)
    assert len(empty_result) == 1
    # A genuinely unparsable "floors" value hits the except branch -> [].
    assert build_floor_stack({"floors": "not a number"}, {}) == []


def test_build_floor_stack_does_not_mutate_scenario_or_massing_options():
    scenarios, rules = _scenarios()
    m = _m(rules)
    original_floors = scenarios[0]["floors"]
    build_floor_stack(scenarios[0], m)
    assert scenarios[0]["floors"] == original_floors  # unchanged


# ── compute_massing_feasibility_score ────────────────────────────────────────

def test_feasibility_score_higher_far_utilization_scores_higher():
    scenarios, rules = _scenarios()
    max_far = rules["max_far"]
    low_util = compute_massing_feasibility_score(
        {"total_sqft": 1000, "floors": 4}, lot_frontage_ft=50, lot_area_sqft=5000,
        lot_depth_ft=100, zoning_dist="R6A", max_far=max_far,
    )
    high_util = compute_massing_feasibility_score(
        {"total_sqft": 5000 * max_far, "floors": 6}, lot_frontage_ft=50, lot_area_sqft=5000,
        lot_depth_ft=100, zoning_dist="R6A", max_far=max_far,
    )
    assert high_util["score"] > low_util["score"]


def test_feasibility_score_landmark_penalty_reduces_score():
    kwargs = dict(
        scenario={"total_sqft": 10000, "floors": 5}, lot_frontage_ft=50,
        lot_area_sqft=5000, lot_depth_ft=100, zoning_dist="R6A", max_far=3.6,
    )
    clean = compute_massing_feasibility_score(**kwargs)
    landmarked = compute_massing_feasibility_score(**kwargs, is_landmark=True)
    assert landmarked["score"] < clean["score"]


def test_feasibility_score_historic_district_penalty_less_severe_than_landmark():
    kwargs = dict(
        scenario={"total_sqft": 10000, "floors": 5}, lot_frontage_ft=50,
        lot_area_sqft=5000, lot_depth_ft=100, zoning_dist="R6A", max_far=3.6,
    )
    landmarked = compute_massing_feasibility_score(**kwargs, is_landmark=True)
    historic = compute_massing_feasibility_score(**kwargs, is_historic_district=True)
    assert historic["score"] > landmarked["score"]


def test_feasibility_score_narrow_frontage_flags_height_concern():
    result = compute_massing_feasibility_score(
        {"total_sqft": 10000, "floors": 20}, lot_frontage_ft=16, lot_area_sqft=5000,
        lot_depth_ft=100, zoning_dist="R6A", max_far=3.6,
    )
    assert result["structural_system_note"]["height_flag"] is not None
    assert any("concern" in f.lower() for f in result["factors"])


def test_feasibility_score_shallow_lot_depth_penalized():
    kwargs = dict(scenario={"total_sqft": 10000, "floors": 5}, lot_frontage_ft=50,
                   lot_area_sqft=5000, zoning_dist="R6A", max_far=3.6)
    shallow = compute_massing_feasibility_score(lot_depth_ft=40, **kwargs)
    deep = compute_massing_feasibility_score(lot_depth_ft=100, **kwargs)
    assert shallow["score"] < deep["score"]


def test_feasibility_score_manufacturing_zone_more_flexible_than_low_density_residential():
    kwargs = dict(scenario={"total_sqft": 10000, "floors": 5}, lot_frontage_ft=50,
                   lot_area_sqft=5000, lot_depth_ft=100, max_far=3.6)
    m_zone = compute_massing_feasibility_score(zoning_dist="M1-1", **kwargs)
    r_zone = compute_massing_feasibility_score(zoning_dist="R2", **kwargs)
    assert m_zone["score"] > r_zone["score"]


def test_feasibility_score_never_raises_on_garbage_input():
    result = compute_massing_feasibility_score(
        "not a dict", lot_frontage_ft="x", lot_area_sqft=None,  # type: ignore
        lot_depth_ft=None, zoning_dist=None,
    )
    assert "score" in result
    assert 0 <= result["score"] <= 100


def test_feasibility_score_bounded_0_to_100():
    result = compute_massing_feasibility_score(
        {"total_sqft": 999999, "floors": 50}, lot_frontage_ft=200, lot_area_sqft=5000,
        lot_depth_ft=200, zoning_dist="M1-1", max_far=10.0,
    )
    assert 0 <= result["score"] <= 100
    assert result["verified"] is False

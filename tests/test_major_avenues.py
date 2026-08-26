"""
Tests for modules/major_avenues.py — the "Major Avenue" corridor filter,
a sibling to modules/transit_fetcher.py's subway-line filter, backed by
pure static waypoint data (no network calls, so no mocking needed).
"""

from modules.major_avenues import MAJOR_AVENUES, list_available_avenues, is_near_avenue


def test_list_available_avenues_returns_sorted_names():
    result = list_available_avenues()
    assert result == sorted(result)
    assert "Broadway (Manhattan)" in result
    assert "Flatbush Avenue" in result
    assert "Queens Boulevard" in result
    assert "Grand Concourse" in result
    assert "Hylan Boulevard" in result


def test_every_avenue_has_at_least_two_waypoints():
    for name, waypoints in MAJOR_AVENUES.items():
        assert len(waypoints) >= 2, name
        for lat, lon in waypoints:
            assert 40.0 <= lat <= 41.5, f"{name}: implausible lat {lat}"
            assert -74.5 <= lon <= -73.4, f"{name}: implausible lon {lon}"


def test_is_near_avenue_true_at_a_waypoint():
    # Broadway (Manhattan)'s first waypoint is (40.7038, -74.0132).
    assert is_near_avenue(40.7038, -74.0132, "Broadway (Manhattan)", buffer_miles=0.1) is True


def test_is_near_avenue_false_far_from_any_waypoint():
    # Staten Island coordinates are far from every Manhattan avenue waypoint.
    assert is_near_avenue(40.5013, -74.2140, "Broadway (Manhattan)", buffer_miles=0.5) is False


def test_is_near_avenue_false_for_unknown_avenue_name_no_raise():
    assert is_near_avenue(40.7038, -74.0132, "Not A Real Avenue", buffer_miles=0.5) is False


def test_is_near_avenue_false_on_missing_coordinates_no_raise():
    assert is_near_avenue(None, None, "Broadway (Manhattan)") is False


def test_is_near_avenue_respects_buffer_size():
    # A point ~0.3 miles from Flatbush Ave's downtown-Brooklyn waypoint
    # (40.6935, -73.9800) — inside a 0.5mi buffer, outside a 0.05mi one.
    lat, lon = 40.6975, -73.9800
    assert is_near_avenue(lat, lon, "Flatbush Avenue", buffer_miles=0.5) is True
    assert is_near_avenue(lat, lon, "Flatbush Avenue", buffer_miles=0.05) is False

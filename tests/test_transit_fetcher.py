"""
Tests for modules/transit_fetcher.py's "Transit Corridor Search"
functions: stations_for_line(), is_near_line(), and list_available_lines().
fetch_transit_proximity()'s existing behavior is untouched and not
re-tested here.

All cases patch the module-level `_station_cache` directly with a small
fixed fake station index — zero network access required. `_empty_cache()`
ALSO patches `_get()` to a no-op, since the "cache empty" state is no
longer terminal (see the retry-on-empty-cache tests below) — without
that, `_load_station_index()` would attempt a real network call whenever
`_station_cache` is falsy.
"""

from unittest.mock import patch

import modules.transit_fetcher as transit_fetcher
from modules.transit_fetcher import stations_for_line, is_near_line, list_available_lines, _load_station_index

_FAKE_STATIONS = [
    {"name": "Times Sq-42 St", "line": "N-Q-R-W-S-1-2-3-7", "lat": 40.7557, "lon": -73.9866},
    {"name": "34 St-Herald Sq", "line": "B/D/F/M-N/Q/R/W", "lat": 40.7497, "lon": -73.9880},
    {"name": "Grand Central-42 St", "line": "4-5-6-7-S", "lat": 40.7527, "lon": -73.9772},
    {"name": "Far Rockaway", "line": "A", "lat": 40.6035, "lon": -73.7554},
]


def _patched_cache():
    return patch.object(transit_fetcher, "_station_cache", _FAKE_STATIONS)


def _empty_cache():
    return patch.multiple(transit_fetcher, _station_cache=None, _get=lambda *a, **k: [])


# ── stations_for_line() ─────────────────────────────────────────────────────

def test_stations_for_line_matches_token_within_dash_split_field():
    with _patched_cache():
        result = stations_for_line("7")
    names = {s["name"] for s in result}
    assert names == {"Times Sq-42 St", "Grand Central-42 St"}


def test_stations_for_line_matches_token_within_slash_split_field():
    with _patched_cache():
        result = stations_for_line("N")
    names = {s["name"] for s in result}
    assert names == {"Times Sq-42 St", "34 St-Herald Sq"}


def test_stations_for_line_is_case_insensitive():
    with _patched_cache():
        result = stations_for_line("a")
    assert [s["name"] for s in result] == ["Far Rockaway"]


def test_stations_for_line_no_match_returns_empty_list():
    with _patched_cache():
        result = stations_for_line("Z")
    assert result == []


def test_stations_for_line_blank_line_returns_empty_list():
    with _patched_cache():
        assert stations_for_line("") == []
        assert stations_for_line(None) == []


def test_stations_for_line_empty_station_index_returns_empty_list_no_raise():
    with _empty_cache():
        assert stations_for_line("7") == []


# ── is_near_line() ───────────────────────────────────────────────────────────

def test_is_near_line_true_within_buffer():
    with _patched_cache():
        # Right at Times Sq-42 St itself
        assert is_near_line(40.7557, -73.9866, "7", buffer_miles=0.5) is True


def test_is_near_line_false_outside_buffer():
    with _patched_cache():
        # Far from every "7" station (Times Sq / Grand Central), well
        # outside a 0.5-mile buffer.
        assert is_near_line(40.6035, -73.7554, "7", buffer_miles=0.5) is False


def test_is_near_line_false_for_line_with_no_stations():
    with _patched_cache():
        assert is_near_line(40.7557, -73.9866, "Z", buffer_miles=0.5) is False


def test_is_near_line_false_on_missing_coordinates_no_raise():
    with _patched_cache():
        assert is_near_line(None, None, "7") is False


def test_is_near_line_empty_station_index_returns_false_no_raise():
    with _empty_cache():
        assert is_near_line(40.7557, -73.9866, "7") is False


def test_is_near_line_respects_larger_buffer():
    with _patched_cache():
        # 34 St-Herald Sq is close to Times Sq/Grand Central's "N" line
        # stations, but pick a buffer wide enough to include Far Rockaway's
        # "A" only when explicitly searching for A.
        assert is_near_line(40.6035, -73.7554, "A", buffer_miles=0.1) is True


# ── list_available_lines() ──────────────────────────────────────────────────

def test_list_available_lines_returns_sorted_distinct_tokens():
    with _patched_cache():
        result = list_available_lines()
    assert result == sorted(set(result))  # sorted
    for expected in ["1", "2", "3", "4", "5", "6", "7", "A", "B", "D", "F", "M", "N", "Q", "R", "S", "W"]:
        assert expected in result


def test_list_available_lines_empty_station_index_returns_empty_list_no_raise():
    with _empty_cache():
        assert list_available_lines() == []


# ── Caching-bug fix: a failed fetch must NOT be cached forever ─────────────

def test_load_station_index_does_not_permanently_cache_an_empty_result():
    """The bug this guards against: a transient fetch failure sets
    _station_cache to [] (an empty list, not None); the OLD
    `if _station_cache is not None: return _station_cache` guard would
    then short-circuit forever, since [] is not None. The fix: only a
    non-empty result is cached; an empty result is retried next call."""
    call_count = {"n": 0}

    def _flaky_get(url, params):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return []  # first call: simulated transient failure
        return [
            {"the_geom": {"type": "Point", "coordinates": [-73.9866, 40.7557]},
             "name": "Times Sq-42 St", "line": "N-Q-R-W-S-1-2-3-7"},
        ]

    with patch.multiple(transit_fetcher, _station_cache=None, _get=_flaky_get):
        first = _load_station_index()
        assert first == []
        assert call_count["n"] == 1

        # A second call must RETRY (not return the stale empty cache) —
        # this is the exact behavior the bug fix guarantees.
        second = _load_station_index()
        assert len(second) == 1
        assert call_count["n"] == 2

        # Once populated, the cache is now sticky — a third call must NOT
        # hit _get() again.
        third = _load_station_index()
        assert third == second
        assert call_count["n"] == 2


def test_load_station_index_records_source_status_on_failure_and_success():
    with patch.multiple(transit_fetcher, _station_cache=None, _get=lambda *a, **k: []), \
         patch.object(transit_fetcher, "record_source_status") as mock_record:
        _load_station_index()
    mock_record.assert_called_once()
    args, kwargs = mock_record.call_args
    assert args[0] == "NYC Subway Stations"
    assert kwargs.get("ok") is False

    def _good_get(url, params):
        return [{"the_geom": {"type": "Point", "coordinates": [-73.9866, 40.7557]},
                  "name": "Times Sq-42 St", "line": "7"}]

    with patch.multiple(transit_fetcher, _station_cache=None, _get=_good_get), \
         patch.object(transit_fetcher, "record_source_status") as mock_record2:
        _load_station_index()
    mock_record2.assert_called_once()
    args2, kwargs2 = mock_record2.call_args
    assert args2[0] == "NYC Subway Stations"
    assert kwargs2.get("ok") is True

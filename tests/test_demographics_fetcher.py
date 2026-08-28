"""
Tests for modules/demographics_fetcher.py — the Census ACS demographics
fetcher, and specifically the new per-ZCTA process cache added to make
Search Area Intelligence's parallel per-ZIP fetch cheap on repeat/
overlapping searches within a session.
"""

from unittest.mock import patch, MagicMock

from modules import demographics_fetcher as df


def _fake_response(json_data, status_code=200):
    r = MagicMock()
    r.status_code = status_code
    r.json = lambda: json_data
    return r


_ACS_ROWS = [
    ["B01003_001E", "B19013_001E", "zip code tabulation area"],
    ["50000", "75000", "11201"],
]


def setup_function(_fn):
    # Reset the module-level cache before every test so tests don't leak
    # state into each other.
    df._demo_cache.clear()


def test_fetch_demographics_parses_population_and_income():
    with patch.object(df.requests, "get", return_value=_fake_response(_ACS_ROWS)):
        result = df.fetch_demographics("11201")
    assert result["population"] == 50000
    assert result["median_household_income"] == 75000
    assert result["verified"] is True
    assert result["error"] is None


def test_second_call_for_same_zip_hits_cache_no_second_network_call():
    with patch.object(df.requests, "get", return_value=_fake_response(_ACS_ROWS)) as mock_get:
        first = df.fetch_demographics("11201")
        assert mock_get.call_count == 1

    # Second call: network mocked to raise if it were actually invoked —
    # a cache hit must never reach it.
    with patch.object(df.requests, "get", side_effect=Exception("network should not be called")):
        second = df.fetch_demographics("11201")

    assert second == first
    assert second["population"] == 50000


def test_different_zip_is_not_a_cache_hit():
    with patch.object(df.requests, "get", return_value=_fake_response(_ACS_ROWS)) as mock_get:
        df.fetch_demographics("11201")
        df.fetch_demographics("10001")
    assert mock_get.call_count == 2


def test_error_result_is_never_cached():
    with patch.object(df.requests, "get", return_value=_fake_response(None, status_code=500)):
        first = df.fetch_demographics("11201")
    assert first["error"] is not None
    assert "11201" not in df._demo_cache

    # A subsequent call must retry the network, not reuse the failed result.
    with patch.object(df.requests, "get", return_value=_fake_response(_ACS_ROWS)) as mock_get:
        second = df.fetch_demographics("11201")
    assert mock_get.call_count == 1
    assert second["population"] == 50000


def test_no_data_result_is_never_cached():
    # ACS returns just a header row (< 2 rows) — treated as "no data,"
    # same as a request failure for caching purposes.
    with patch.object(df.requests, "get", return_value=_fake_response([_ACS_ROWS[0]])):
        first = df.fetch_demographics("11201")
    assert first["error"] is not None
    assert "11201" not in df._demo_cache


def test_missing_zip_returns_error_never_raises():
    result = df.fetch_demographics("")
    assert result["error"] is not None
    assert result["verified"] is True

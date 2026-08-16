from unittest.mock import patch, MagicMock

import requests

from modules import oath_fetcher as of


def _fake_response(json_data, ok=True):
    r = MagicMock()
    if ok:
        r.raise_for_status = lambda: None
    else:
        r.raise_for_status = MagicMock(side_effect=requests.HTTPError("error"))
    r.json = lambda: json_data
    return r


def test_hearings_parsed_with_open_balance_count():
    rows = [
        {"ticket_number": "1", "hearing_date": "2023-01-01T00:00:00.000",
         "hearing_result": "IN VIOLATION", "charge_1_code_description": "Failure to maintain",
         "balance_due": "500"},
        {"ticket_number": "2", "hearing_date": "2022-06-01T00:00:00.000",
         "hearing_result": "DISMISSED", "charge_1_code_description": "Noise",
         "balance_due": "0"},
    ]
    with patch.object(of.requests, "get", return_value=_fake_response(rows)):
        result = of.fetch_oath_hearings("3", "1234", "56")
    assert result["verified"] is True
    assert result["count"] == 2
    assert result["open_balance_count"] == 1


def test_unrecognized_borough_code_returns_error():
    result = of.fetch_oath_hearings("9", "1234", "56")
    assert result["error"] is not None
    assert result["verified"] is False


def test_request_failure_never_raises():
    with patch.object(of.requests, "get", return_value=_fake_response(None, ok=False)):
        result = of.fetch_oath_hearings("3", "1234", "56")
    assert result["verified"] is False
    assert result["hearings"] == []
    assert result["error"] is not None


def test_no_hearings_found():
    with patch.object(of.requests, "get", return_value=_fake_response([])):
        result = of.fetch_oath_hearings("3", "1234", "56")
    assert result["verified"] is True
    assert result["count"] == 0
    assert result["open_balance_count"] == 0

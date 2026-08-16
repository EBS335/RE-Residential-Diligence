from unittest.mock import patch, MagicMock

import requests

from modules import ceqr_fetcher as cf


def _fake_response(json_data, ok=True):
    r = MagicMock()
    if ok:
        r.raise_for_status = lambda: None
    else:
        r.raise_for_status = MagicMock(side_effect=requests.HTTPError("error"))
    r.json = lambda: json_data
    return r


def test_applications_parsed():
    rows = [{"ulurp_no": "N 230123 ZRK", "project_name": "Test Rezoning",
             "certified_referred_date": "2023-05-01T00:00:00.000", "status": "Certified"}]
    with patch.object(cf.requests, "get", return_value=_fake_response(rows)):
        result = cf.fetch_ulurp_applications("3", "302")
    assert result["verified"] is True
    assert result["count"] == 1
    assert result["applications"][0]["ulurp_no"] == "N 230123 ZRK"


def test_unrecognized_borough_returns_error():
    result = cf.fetch_ulurp_applications("9", "302")
    assert result["error"] is not None
    assert result["verified"] is False


def test_missing_community_district_returns_error():
    result = cf.fetch_ulurp_applications("3", "")
    assert result["error"] is not None


def test_request_failure_never_raises():
    with patch.object(cf.requests, "get", return_value=_fake_response(None, ok=False)):
        result = cf.fetch_ulurp_applications("3", "302")
    assert result["verified"] is False
    assert result["applications"] == []
    assert result["error"] is not None

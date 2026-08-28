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


# ── fetch_ulurp_applications_by_cds (batched) ────────────────────────────────

def test_batched_builds_in_clause_with_all_normalized_districts():
    captured = {}

    def _capture_get(url, params=None, timeout=None):
        captured["where"] = params["$where"]
        return _fake_response([])

    with patch.object(cf.requests, "get", side_effect=_capture_get):
        cf.fetch_ulurp_applications_by_cds("3", ["302", "305", "310"])

    assert "community_district IN(" in captured["where"]
    for n in ("'2'", "'5'", "'10'"):
        assert n in captured["where"]


def test_batched_groups_rows_back_to_original_cd_keys():
    rows = [
        {"ulurp_no": "N1", "project_name": "Rezoning A", "community_district": "2",
         "certified_referred_date": "2024-01-01T00:00:00.000", "status": "Certified"},
        {"ulurp_no": "N2", "project_name": "Rezoning B", "community_district": "5",
         "certified_referred_date": "2024-02-01T00:00:00.000", "status": "Certified"},
    ]
    with patch.object(cf.requests, "get", return_value=_fake_response(rows)):
        result = cf.fetch_ulurp_applications_by_cds("3", ["302", "305"])

    assert result["302"]["verified"] is True
    assert result["302"]["count"] == 1
    assert result["302"]["applications"][0]["project_name"] == "Rezoning A"
    assert result["305"]["count"] == 1
    assert result["305"]["applications"][0]["project_name"] == "Rezoning B"


def test_batched_district_with_zero_matches_still_verified():
    with patch.object(cf.requests, "get", return_value=_fake_response([])):
        result = cf.fetch_ulurp_applications_by_cds("3", ["302", "305"])
    assert result["302"] == {**result["302"], "verified": True, "count": 0, "applications": []}
    assert result["305"]["verified"] is True
    assert result["305"]["count"] == 0


def test_batched_request_failure_marks_every_requested_cd_unverified():
    with patch.object(cf.requests, "get", return_value=_fake_response(None, ok=False)):
        result = cf.fetch_ulurp_applications_by_cds("3", ["302", "305"])
    assert set(result.keys()) == {"302", "305"}
    assert all(v["verified"] is False and v["error"] for v in result.values())


def test_batched_unrecognized_borough_no_network_call():
    with patch.object(cf.requests, "get") as mock_get:
        result = cf.fetch_ulurp_applications_by_cds("9", ["302", "305"])
    mock_get.assert_not_called()
    assert all(v["verified"] is False and v["error"] for v in result.values())


def test_batched_empty_cd_list_returns_empty_dict():
    result = cf.fetch_ulurp_applications_by_cds("3", [])
    assert result == {}

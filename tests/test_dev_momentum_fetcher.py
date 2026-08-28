"""
Tests for modules/dev_momentum_fetcher.py — the DOB Permit Issuance
(ipu4-2q9a) aggregate "development momentum" fetcher, following the same
house pattern (and test conventions) as tests/test_tax_lien_fetcher.py.
"""

from unittest.mock import patch, MagicMock

import requests

from modules import dev_momentum_fetcher as dmf


def _fake_response(json_data, ok=True):
    r = MagicMock()
    if ok:
        r.raise_for_status = lambda: None
    else:
        r.raise_for_status = MagicMock(side_effect=requests.HTTPError("error"))
    r.json = lambda: json_data
    return r


def test_returns_permit_count_on_success():
    with patch.object(dmf.requests, "get", return_value=_fake_response([{"cnt": "7"}])):
        result = dmf.fetch_dev_momentum("1", "105")
    assert result["verified"] is True
    assert result["nb_permit_count"] == 7
    assert result["error"] is None
    assert result["community_district"] == "105"


def test_zero_permits_still_verified():
    with patch.object(dmf.requests, "get", return_value=_fake_response([{"cnt": "0"}])):
        result = dmf.fetch_dev_momentum("1", "105")
    assert result["verified"] is True
    assert result["nb_permit_count"] == 0


def test_empty_response_list_defaults_to_zero():
    with patch.object(dmf.requests, "get", return_value=_fake_response([])):
        result = dmf.fetch_dev_momentum("1", "105")
    assert result["verified"] is True
    assert result["nb_permit_count"] == 0


def test_request_failure_never_raises_and_reports_unverified():
    with patch.object(dmf.requests, "get", return_value=_fake_response(None, ok=False)):
        result = dmf.fetch_dev_momentum("1", "105")
    assert result["verified"] is False
    assert result["error"] is not None
    assert result["nb_permit_count"] == 0


def test_missing_borough_or_cd_returns_error_never_raises():
    result = dmf.fetch_dev_momentum("", "")
    assert result["error"] is not None
    assert result["verified"] is False

    result2 = dmf.fetch_dev_momentum("1", "")
    assert result2["error"] is not None


def test_unrecognized_borough_code_returns_error():
    result = dmf.fetch_dev_momentum("9", "105")
    assert result["error"] is not None
    assert "unrecognized borough" in result["error"]


def test_where_clause_uses_full_borough_name_and_nb_job_type():
    captured = {}

    def _capture_get(url, params=None, timeout=None):
        captured["where"] = params["$where"]
        return _fake_response([{"cnt": "3"}])

    with patch.object(dmf.requests, "get", side_effect=_capture_get):
        dmf.fetch_dev_momentum("1", "105")

    assert "MANHATTAN" in captured["where"]
    assert "job_type='NB'" in captured["where"]


def test_community_district_normalized_to_district_number():
    captured = {}

    def _capture_get(url, params=None, timeout=None):
        captured["where"] = params["$where"]
        return _fake_response([{"cnt": "1"}])

    with patch.object(dmf.requests, "get", side_effect=_capture_get):
        # "302" = Brooklyn CD 3 -> district number "2" per the same
        # normalization convention modules/ceqr_fetcher.py already uses.
        dmf.fetch_dev_momentum("3", "302")

    assert "community_board='2'" in captured["where"]


# ── fetch_dev_momentum_by_cds (batched) ──────────────────────────────────────

def test_batched_builds_group_by_and_in_clause():
    captured = {}

    def _capture_get(url, params=None, timeout=None):
        captured["where"] = params["$where"]
        captured["select"] = params["$select"]
        captured["group"] = params["$group"]
        return _fake_response([])

    with patch.object(dmf.requests, "get", side_effect=_capture_get):
        dmf.fetch_dev_momentum_by_cds("1", ["105", "108"])

    assert "community_board IN(" in captured["where"]
    assert "'5'" in captured["where"] and "'8'" in captured["where"]
    assert "job_type='NB'" in captured["where"]
    assert "count(*)" in captured["select"]
    assert captured["group"] == "community_board"


def test_batched_maps_grouped_counts_back_to_original_cds():
    rows = [{"community_board": "5", "cnt": "12"}, {"community_board": "8", "cnt": "3"}]
    with patch.object(dmf.requests, "get", return_value=_fake_response(rows)):
        result = dmf.fetch_dev_momentum_by_cds("1", ["105", "108"])
    assert result["105"]["verified"] is True
    assert result["105"]["nb_permit_count"] == 12
    assert result["108"]["nb_permit_count"] == 3


def test_batched_cd_absent_from_grouped_response_defaults_to_zero():
    rows = [{"community_board": "5", "cnt": "12"}]  # "108" never appears
    with patch.object(dmf.requests, "get", return_value=_fake_response(rows)):
        result = dmf.fetch_dev_momentum_by_cds("1", ["105", "108"])
    assert result["108"]["verified"] is True
    assert result["108"]["nb_permit_count"] == 0


def test_batched_request_failure_marks_every_requested_cd_unverified():
    with patch.object(dmf.requests, "get", return_value=_fake_response(None, ok=False)):
        result = dmf.fetch_dev_momentum_by_cds("1", ["105", "108"])
    assert set(result.keys()) == {"105", "108"}
    assert all(v["verified"] is False and v["error"] for v in result.values())


def test_batched_unrecognized_borough_no_network_call():
    with patch.object(dmf.requests, "get") as mock_get:
        result = dmf.fetch_dev_momentum_by_cds("9", ["105", "108"])
    mock_get.assert_not_called()
    assert all(v["verified"] is False and v["error"] for v in result.values())


def test_batched_empty_cd_list_returns_empty_dict():
    result = dmf.fetch_dev_momentum_by_cds("1", [])
    assert result == {}

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

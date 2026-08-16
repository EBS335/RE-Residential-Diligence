from unittest.mock import patch, MagicMock

import requests

from modules import lpc_landmarks_fetcher as lpc


def _fake_response(json_data, ok=True):
    r = MagicMock()
    if ok:
        r.raise_for_status = lambda: None
    else:
        r.raise_for_status = MagicMock(side_effect=requests.HTTPError("error"))
    r.json = lambda: json_data
    return r


def test_is_landmark_true_with_details():
    with patch.object(lpc.requests, "get", return_value=_fake_response(
        [{"lm_name": "Test Building", "designated": "1985-03-12T00:00:00.000"}]
    )):
        result = lpc.fetch_lpc_landmark_status("3012340056")
    assert result["verified"] is True
    assert result["is_individual_landmark"] is True
    assert result["landmark_name"] == "Test Building"
    assert result["designation_date"] == "1985-03-12"


def test_is_landmark_false_when_no_match():
    with patch.object(lpc.requests, "get", return_value=_fake_response([])):
        result = lpc.fetch_lpc_landmark_status("3012340056")
    assert result["verified"] is True
    assert result["is_individual_landmark"] is False
    assert result["landmark_name"] is None


def test_malformed_bbl_returns_error_never_raises():
    result = lpc.fetch_lpc_landmark_status("123")
    assert result["error"] is not None
    assert result["is_individual_landmark"] is None


def test_request_failure_does_not_claim_not_a_landmark():
    with patch.object(lpc.requests, "get", return_value=_fake_response(None, ok=False)):
        result = lpc.fetch_lpc_landmark_status("3012340056")
    assert result["verified"] is False
    assert result["is_individual_landmark"] is None  # not a false negative


# ── fetch_lpc_designation_status (dataset 7mgd-s57w: individual landmark +
# historic district building database, backs LPC's "Discover NYC Landmarks" map) ──

def test_designation_status_individual_landmark_true():
    with patch.object(lpc.requests, "get", return_value=_fake_response(
        [{"lpc_name": "Test Building", "lp_number": "LP-1234", "desig_date": "1985-03-12T00:00:00.000",
          "borough": "Manhattan"}]
    )):
        result = lpc.fetch_lpc_designation_status("1012340056")
    assert result["verified"] is True
    assert result["is_individual_landmark"] is True
    assert result["is_in_historic_district"] is False
    assert result["landmark_name"] == "Test Building"
    assert result["designation_date"] == "1985-03-12"
    assert result["borough"] == "Manhattan"


def test_designation_status_historic_district_true_with_name():
    with patch.object(lpc.requests, "get", return_value=_fake_response(
        [{"hist_dist": "Greenwich Village Historic District", "borough": "Manhattan"}]
    )):
        result = lpc.fetch_lpc_designation_status("1012340056")
    assert result["verified"] is True
    assert result["is_in_historic_district"] is True
    assert result["historic_district_name"] == "Greenwich Village Historic District"
    assert result["is_individual_landmark"] is False


def test_designation_status_neither():
    with patch.object(lpc.requests, "get", return_value=_fake_response([])):
        result = lpc.fetch_lpc_designation_status("1012340056")
    assert result["verified"] is True
    assert result["is_individual_landmark"] is False
    assert result["is_in_historic_district"] is False
    assert result["historic_district_name"] is None


def test_designation_status_malformed_bbl_returns_error_never_raises():
    result = lpc.fetch_lpc_designation_status("123")
    assert result["error"] is not None
    assert result["is_individual_landmark"] is None
    assert result["is_in_historic_district"] is None


def test_designation_status_request_failure_does_not_claim_negative():
    with patch.object(lpc.requests, "get", return_value=_fake_response(None, ok=False)):
        result = lpc.fetch_lpc_designation_status("1012340056")
    assert result["verified"] is False
    assert result["is_individual_landmark"] is None  # not a false negative
    assert result["is_in_historic_district"] is None  # not a false negative

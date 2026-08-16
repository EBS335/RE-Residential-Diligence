from unittest.mock import patch, MagicMock

import requests

from modules import ll84_fetcher as ll84


def _fake_response(json_data, ok=True):
    r = MagicMock()
    if ok:
        r.raise_for_status = lambda: None
    else:
        r.raise_for_status = MagicMock(side_effect=requests.HTTPError("error"))
    r.json = lambda: json_data
    return r


def test_reported_true_with_emissions_data():
    with patch.object(ll84.requests, "get", return_value=_fake_response(
        [{"total_ghg_emissions_metric": "450.5", "ghg_intensity_kgco2e_ft": "6.2", "reporting_year": "2023"}]
    )):
        result = ll84.fetch_ll84_emissions("3012340056")
    assert result["verified"] is True
    assert result["reported"] is True
    assert result["total_ghg_emissions_metric_tons"] == 450.5
    assert result["ghg_intensity"] == 6.2
    assert result["reporting_year"] == "2023"


def test_reported_false_when_no_filing_found():
    with patch.object(ll84.requests, "get", return_value=_fake_response([])):
        result = ll84.fetch_ll84_emissions("3012340056")
    assert result["verified"] is True
    assert result["reported"] is False
    assert result["error"] is None  # not an error — common/expected


def test_request_failure_does_not_claim_not_reported():
    with patch.object(ll84.requests, "get", return_value=_fake_response(None, ok=False)):
        result = ll84.fetch_ll84_emissions("3012340056")
    assert result["verified"] is False
    assert result["reported"] is None  # not a false negative
    assert result["error"] is not None


def test_malformed_bbl_returns_error_never_raises():
    result = ll84.fetch_ll84_emissions("123")
    assert result["error"] is not None
    assert result["reported"] is None

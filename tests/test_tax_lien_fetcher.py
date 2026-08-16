from unittest.mock import patch, MagicMock

import requests

from modules import tax_lien_fetcher as tlf


def _fake_response(json_data, ok=True):
    r = MagicMock()
    if ok:
        r.raise_for_status = lambda: None
    else:
        r.raise_for_status = MagicMock(side_effect=requests.HTTPError("error"))
    r.json = lambda: json_data
    return r


def test_on_lien_list_true_when_records_found():
    with patch.object(tlf.requests, "get", return_value=_fake_response(
        [{"owner_name": "TEST LLC", "total_amount_due": "5000", "class": "1"}]
    )):
        result = tlf.fetch_tax_lien_status("3", "1234", "56")
    assert result["verified"] is True
    assert result["on_lien_list"] is True
    assert result["count"] == 1
    assert result["error"] is None


def test_on_lien_list_false_when_no_records():
    with patch.object(tlf.requests, "get", return_value=_fake_response([])):
        result = tlf.fetch_tax_lien_status("3", "1234", "56")
    assert result["verified"] is True
    assert result["on_lien_list"] is False
    assert result["count"] == 0


def test_request_failure_does_not_claim_off_list():
    with patch.object(tlf.requests, "get", return_value=_fake_response(None, ok=False)):
        result = tlf.fetch_tax_lien_status("3", "1234", "56")
    assert result["verified"] is False
    assert result["on_lien_list"] is None  # not a false negative
    assert result["error"] is not None


def test_missing_block_lot_returns_error_never_raises():
    result = tlf.fetch_tax_lien_status("3", "", "")
    assert result["error"] is not None
    assert result["on_lien_list"] is None

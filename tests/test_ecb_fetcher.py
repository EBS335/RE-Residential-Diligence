from unittest.mock import patch, MagicMock

import requests

from modules import ecb_fetcher as ecb


def _fake_response(json_data, ok=True):
    r = MagicMock()
    if ok:
        r.raise_for_status = lambda: None
    else:
        r.raise_for_status = MagicMock(side_effect=requests.HTTPError("error"))
    r.json = lambda: json_data
    return r


def test_hpd_url_present_in_empty_template():
    assert ecb._EMPTY["hpd_url"] == ecb._HPD_VIOLATIONS_PORTAL_URL


def test_hpd_url_present_on_invalid_bbl():
    result = ecb.fetch_ecb_violations("")
    assert result["error"] == "Invalid BBL"
    assert result["hpd_url"] == ecb._HPD_VIOLATIONS_PORTAL_URL


def test_hpd_url_present_on_request_failure():
    with patch.object(ecb.requests, "get", side_effect=requests.ConnectionError("boom")):
        result = ecb.fetch_ecb_violations("3012340056")
    assert result["error"] is not None
    assert result["hpd_url"] == ecb._HPD_VIOLATIONS_PORTAL_URL


def test_hpd_url_present_on_success():
    rows = [
        {"inspectiondate": "2023-01-01T00:00:00.000", "class": "C",
         "novdescription": "No heat", "apartment": "3B", "violationstatus": "Open"},
    ]
    with patch.object(ecb.requests, "get", return_value=_fake_response(rows)):
        result = ecb.fetch_ecb_violations("3012340056")
    assert result["error"] is None
    assert result["count"] == 1
    assert result["hpd_url"] == ecb._HPD_VIOLATIONS_PORTAL_URL

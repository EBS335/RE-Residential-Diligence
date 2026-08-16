from unittest.mock import patch, MagicMock

import requests

from modules import zola_fetcher as zf


def _fake_response(json_data, ok=True):
    r = MagicMock()
    if ok:
        r.raise_for_status = lambda: None
    else:
        r.raise_for_status = MagicMock(side_effect=requests.HTTPError("error"))
    r.json = lambda: json_data
    return r


_FEATURE_COLLECTION = {
    "features": [
        {
            "properties": {"label": "120 Broadway, Manhattan, New York, NY", "pad_bbl": "1000160001"},
            "geometry": {"coordinates": [-74.0110, 40.7075]},
        },
        {
            "properties": {"label": "120 Broadway, Brooklyn, New York, NY", "pad_bbl": "3012340001"},
            "geometry": {"coordinates": [-73.9500, 40.6900]},
        },
    ]
}


def test_returns_multiple_suggestions():
    with patch.object(zf.requests, "get", return_value=_fake_response(_FEATURE_COLLECTION)):
        result = zf.geosearch_autocomplete("120 Broa")
    assert len(result) == 2
    assert result[0]["label"] == "120 Broadway, Manhattan, New York, NY"
    assert result[0]["bbl"] == "1000160001"
    assert result[0]["lat"] == 40.7075
    assert result[0]["lon"] == -74.0110


def test_respects_size_cap():
    with patch.object(zf.requests, "get", return_value=_fake_response(_FEATURE_COLLECTION)):
        result = zf.geosearch_autocomplete("120 Broa", size=1)
    assert len(result) == 1


def test_too_short_text_returns_empty_without_request():
    with patch.object(zf.requests, "get") as mock_get:
        result = zf.geosearch_autocomplete("12")
    mock_get.assert_not_called()
    assert result == []


def test_no_features_returns_empty():
    with patch.object(zf.requests, "get", return_value=_fake_response({"features": []})):
        result = zf.geosearch_autocomplete("nonexistent address xyz")
    assert result == []


def test_request_failure_returns_empty_never_raises():
    with patch.object(zf.requests, "get", return_value=_fake_response(None, ok=False)):
        result = zf.geosearch_autocomplete("120 Broadway")
    assert result == []


def test_feature_missing_bbl_still_returns_label_with_none_bbl():
    fc = {"features": [{"properties": {"label": "Some Place, NY"}, "geometry": {"coordinates": [-73.9, 40.7]}}]}
    with patch.object(zf.requests, "get", return_value=_fake_response(fc)):
        result = zf.geosearch_autocomplete("Some Place")
    assert result[0]["bbl"] is None
    assert result[0]["label"] == "Some Place, NY"


def test_geosearch_bbl_unaffected_still_single_result():
    # geosearch_bbl() itself must be completely untouched by this addition.
    with patch.object(zf.requests, "get", return_value=_fake_response(_FEATURE_COLLECTION)):
        result = zf.geosearch_bbl("120 Broadway")
    assert isinstance(result, dict)
    assert result["bbl"] == "1000160001"

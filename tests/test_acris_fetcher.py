"""
Tests for modules/acris_fetcher.py::fetch_owner_portfolio() — the
owner-portfolio-expansion query (Batch A, Feature 2): a new query shape
that searches ACRIS Parties by owner NAME (rather than by BBL/document_id)
and joins to Legals to resolve BBLs.
"""

from unittest.mock import MagicMock, patch

from modules.acris_fetcher import fetch_owner_portfolio, _PARTY_URL, _LEGALS_URL


def _resp(json_data):
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = json_data
    m.raise_for_status = MagicMock()
    return m


def test_fetch_owner_portfolio_builds_dedups_bbls():
    def _fake_get(url, params=None, timeout=None):
        if url == _PARTY_URL:
            assert params["$where"] == "party_type='2' AND UPPER(name) LIKE UPPER('%ACME LLC%')"
            return _resp([
                {"document_id": "DOC1"},
                {"document_id": "DOC2"},
                {"document_id": "DOC1"},  # duplicate document_id from the party query itself
            ])
        if url == _LEGALS_URL:
            return _resp([
                {"borough": "3", "block": "123", "lot": "45"},
                {"borough": "3", "block": "123", "lot": "45"},  # dup row -> same BBL, deduped
                {"borough": "1", "block": "7", "lot": "1001"},
            ])
        raise AssertionError(f"unexpected url {url}")

    with patch("modules.acris_fetcher.requests.get", side_effect=_fake_get):
        result = fetch_owner_portfolio("ACME LLC")

    assert result["error"] is None
    assert result["verified"] is True
    assert result["owner_name"] == "ACME LLC"
    assert set(result["bbls"]) == {"3001230045", "1000071001"}
    assert result["count"] == 2


def test_fetch_owner_portfolio_excludes_given_bbl():
    def _fake_get(url, params=None, timeout=None):
        if url == _PARTY_URL:
            return _resp([{"document_id": "DOC1"}])
        if url == _LEGALS_URL:
            return _resp([{"borough": "3", "block": "123", "lot": "45"}])
        raise AssertionError(f"unexpected url {url}")

    with patch("modules.acris_fetcher.requests.get", side_effect=_fake_get):
        result = fetch_owner_portfolio("ACME LLC", exclude_bbl="3-00123-0045")

    assert result["bbls"] == []
    assert result["count"] == 0
    assert result["error"] is None


def test_fetch_owner_portfolio_no_matching_documents():
    def _fake_get(url, params=None, timeout=None):
        if url == _PARTY_URL:
            return _resp([])
        raise AssertionError(f"unexpected url {url}")  # Legals should never be queried

    with patch("modules.acris_fetcher.requests.get", side_effect=_fake_get):
        result = fetch_owner_portfolio("NOBODY OWNS THIS LLC")

    assert result["bbls"] == []
    assert result["count"] == 0
    assert result["error"] is None
    assert result["verified"] is True


def test_fetch_owner_portfolio_escapes_single_quotes_in_owner_name():
    seen = {}

    def _fake_get(url, params=None, timeout=None):
        if url == _PARTY_URL:
            seen["where"] = params["$where"]
            return _resp([])
        raise AssertionError(f"unexpected url {url}")

    with patch("modules.acris_fetcher.requests.get", side_effect=_fake_get):
        fetch_owner_portfolio("O'BRIEN REALTY")

    assert "O''BRIEN REALTY" in seen["where"]


def test_fetch_owner_portfolio_network_failure_sets_error_never_raises():
    with patch("modules.acris_fetcher.requests.get", side_effect=RuntimeError("boom")):
        result = fetch_owner_portfolio("ACME LLC")

    assert result["error"] is not None
    assert result["bbls"] == []
    assert result["count"] == 0
    assert result["verified"] is False


def test_fetch_owner_portfolio_legals_failure_still_returns_without_raising():
    def _fake_get(url, params=None, timeout=None):
        if url == _PARTY_URL:
            return _resp([{"document_id": "DOC1"}])
        if url == _LEGALS_URL:
            raise RuntimeError("legals down")
        raise AssertionError(f"unexpected url {url}")

    with patch("modules.acris_fetcher.requests.get", side_effect=_fake_get):
        result = fetch_owner_portfolio("ACME LLC")

    assert result["error"] is not None
    assert result["verified"] is False
    assert result["bbls"] == []


def test_fetch_owner_portfolio_blank_owner_name_returns_error_no_fetch():
    with patch("modules.acris_fetcher.requests.get") as mock_get:
        result = fetch_owner_portfolio("")
    mock_get.assert_not_called()
    assert result["error"]
    assert result["bbls"] == []


def test_fetch_owner_portfolio_max_docs_passed_as_limit():
    seen = {}

    def _fake_get(url, params=None, timeout=None):
        if url == _PARTY_URL:
            seen["limit"] = params["$limit"]
            return _resp([])
        raise AssertionError(f"unexpected url {url}")

    with patch("modules.acris_fetcher.requests.get", side_effect=_fake_get):
        fetch_owner_portfolio("ACME LLC", max_docs=50)

    assert seen["limit"] == 50

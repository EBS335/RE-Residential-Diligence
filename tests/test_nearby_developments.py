from unittest.mock import patch

from modules import nearby_developments as nd


def _fake_fetch_rss(url, params=None, timeout=15):
    # No matching items — we only care about which queries were issued.
    return "<rss><channel></channel></rss>", "ok"


def test_google_news_builds_zip_code_query_when_provided():
    calls = []

    def _capture(url, params=None, timeout=15):
        calls.append(params)
        return _fake_fetch_rss(url, params, timeout)

    with patch.object(nd, "fetch_rss_content", side_effect=_capture):
        nd._fetch_google_news(
            40.75, -73.98, 0.25,
            address="123 Main St, New York, NY", neighborhood="Midtown", zip_code="10018",
        )

    queries = [c["q"] for c in calls]
    assert any("10018" in q for q in queries), queries
    assert any("123 Main St" in q for q in queries), queries
    assert any("Midtown" in q for q in queries), queries


def test_google_news_omits_zip_code_query_when_not_provided():
    calls = []

    def _capture(url, params=None, timeout=15):
        calls.append(params)
        return _fake_fetch_rss(url, params, timeout)

    with patch.object(nd, "fetch_rss_content", side_effect=_capture):
        nd._fetch_google_news(40.75, -73.98, 0.25, address="123 Main St", neighborhood="Midtown")

    queries = [c["q"] for c in calls]
    assert len(queries) == 2
    assert not any("zip" in q.lower() for q in queries)


def test_google_news_query_count_caps_at_three():
    calls = []

    def _capture(url, params=None, timeout=15):
        calls.append(params)
        return _fake_fetch_rss(url, params, timeout)

    with patch.object(nd, "fetch_rss_content", side_effect=_capture):
        nd._fetch_google_news(
            40.75, -73.98, 0.25,
            address="123 Main St, New York, NY", neighborhood="Midtown", zip_code="10018",
        )

    assert len(calls) == 3


def test_fetch_nearby_developments_accepts_zip_code_kwarg_without_raising():
    # Smoke test: the public entrypoint's new zip_code kwarg must thread
    # through without raising, even with every underlying source mocked out.
    with patch.object(nd, "_fetch_dob", return_value=([], "no_results")), \
         patch.object(nd, "_fetch_google_news", return_value=([], "no_results")), \
         patch.object(nd, "_fetch_trd", return_value=([], "no_results")), \
         patch.object(nd, "_fetch_commercial_observer", return_value=([], "no_results")), \
         patch.object(nd, "_fetch_bisnow", return_value=([], "no_results")):
        devs, status = nd.fetch_nearby_developments(
            40.75, -73.98, 0.25, address="123 Main St", neighborhood="Midtown", zip_code="10018",
        )
    assert devs == []
    assert status["overall"] == "no_results"

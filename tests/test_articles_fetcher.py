"""
Tests for modules/articles_fetcher.py's RSS-first fetch_nearby_articles()
(Property Analysis tab news/comps reliability fix — replaces the previous
DuckDuckGo-only approach with the more robust RSS pattern proven in
modules/nearby_developments.py, keeping DDG only as a last-resort
fallback).
"""

from unittest.mock import patch

from modules import articles_fetcher as af


_RELEVANT_FEED = """<rss><channel>
<item>
  <title>Bushwick Tower Breaks Ground</title>
  <link>https://therealdeal.com/article-1</link>
  <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
  <description>A new residential tower in Bushwick, NYC broke ground this week.</description>
</item>
</channel></rss>"""

_EMPTY_FEED = "<rss><channel></channel></rss>"


def _patch_all_rss_ok(monkeypatch_content=_RELEVANT_FEED):
    return patch.object(af, "fetch_rss_content", return_value=(monkeypatch_content, "ok"))


def test_no_address_or_neighborhood_returns_no_results():
    articles, status = af.fetch_nearby_articles("", "", "Brooklyn")
    assert articles == []
    assert status == "no_results"


def test_rss_sources_all_relevant_returns_live():
    with patch.object(af, "fetch_rss_content", return_value=(_RELEVANT_FEED, "ok")):
        articles, status = af.fetch_nearby_articles("123 Main St, Bushwick", "Bushwick", "Brooklyn", max_results=8)
    assert status == "live"
    assert len(articles) > 0
    assert articles[0]["title"] == "Bushwick Tower Breaks Ground"
    assert articles[0]["date_approx"] == "2024-01-01"
    assert "label" in articles[0]["source"]


def test_rss_sources_empty_and_ddg_disabled_reports_no_results():
    with patch.object(af, "fetch_rss_content", return_value=(_EMPTY_FEED, "ok")), \
         patch.object(af, "_ddg_search", return_value=([], True)), \
         patch.object(af.time, "sleep"):
        articles, status = af.fetch_nearby_articles("1 Test Ave, Nowhere", "Nowhere", "Queens")
    assert articles == []
    assert status == "no_results"


def test_all_sources_fail_reports_error():
    with patch.object(af, "fetch_rss_content", return_value=(None, "error: boom")), \
         patch.object(af, "_ddg_search", return_value=([], False)), \
         patch.object(af.time, "sleep"):
        articles, status = af.fetch_nearby_articles("1 Test Ave, Nowhere", "Nowhere", "Queens")
    assert articles == []
    assert status == "error"


def test_ddg_fallback_used_when_rss_finds_nothing():
    ddg_result = [{"title": "Fallback Article", "url": "https://yimbynewyork.com/x", "snippet": "A story about Nowhere NYC."}]
    with patch.object(af, "fetch_rss_content", return_value=(_EMPTY_FEED, "ok")), \
         patch.object(af, "_ddg_search", return_value=(ddg_result, True)), \
         patch.object(af.time, "sleep"):
        articles, status = af.fetch_nearby_articles("1 Test Ave, Nowhere", "Nowhere", "Queens")
    assert status == "live"
    assert any(a["title"] == "Fallback Article" for a in articles)


def test_irrelevant_feed_items_filtered_out():
    irrelevant_feed = """<rss><channel>
    <item>
      <title>Unrelated Miami Story</title>
      <link>https://therealdeal.com/miami</link>
      <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
      <description>A story about Miami real estate, unrelated to the area in question.</description>
    </item>
    </channel></rss>"""
    with patch.object(af, "fetch_rss_content", return_value=(irrelevant_feed, "ok")), \
         patch.object(af, "_ddg_search", return_value=([], True)), \
         patch.object(af.time, "sleep"):
        articles, status = af.fetch_nearby_articles("1 Test Ave, Bushwick", "Bushwick", "Brooklyn")
    assert articles == []
    assert status == "no_results"


def test_source_badge_lookup_never_raises_on_unknown_domain():
    info = af._source_info("https://some-random-outlet.example/x")
    assert "label" in info and "bg" in info and "fg" in info

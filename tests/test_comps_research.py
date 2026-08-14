"""
Tests for modules/comps_research.py's RSS-first search_competing_devs()
(Property Analysis tab news/comps reliability fix — same RSS-first,
DDG-fallback pattern as modules/articles_fetcher.py, reusing the
existing _parse_dev()/_dedupe()/_geocode_dev() pipeline unchanged).
"""

from unittest.mock import patch

from modules import comps_research as cr


_RELEVANT_FEED = """<rss><channel>
<item>
  <title>100 West 42nd Street Tower Breaks Ground in Bushwick</title>
  <link>https://therealdeal.com/article-1</link>
  <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
  <description>A new 250-unit residential building in Bushwick broke ground this week.</description>
</item>
</channel></rss>"""

_EMPTY_FEED = "<rss><channel></channel></rss>"


def _no_geocoder(dev, neighborhood, borough):
    # Skip real geocoding — just tag centroid-style, matching the
    # geosearch_bbl-unavailable code path.
    dev["lat"], dev["lon"], dev["geocoded"] = 40.7, -73.9, "centroid"
    return dev


def test_rss_pass_finds_relevant_development():
    with patch.object(cr, "fetch_rss_content", return_value=(_RELEVANT_FEED, "ok")), \
         patch.object(cr, "_geocode_dev", side_effect=_no_geocoder), \
         patch.object(cr, "cutoff_date", return_value="2000-01-01"):
        devs, status = cr.search_competing_devs("Bushwick", "Brooklyn", 40.7, -73.9)
    assert status == "live"
    assert len(devs) > 0
    assert devs[0]["address"]


def test_rss_empty_falls_back_to_ddg():
    ddg_result = [{
        "title": "100 West 42nd Street Rental Tower", "snippet": "250 units in Bushwick.",
        "url": "https://yimbynewyork.com/x",
    }]
    with patch.object(cr, "fetch_rss_content", return_value=(_EMPTY_FEED, "ok")), \
         patch.object(cr, "_ddg_search", return_value=(ddg_result, True)), \
         patch.object(cr, "_geocode_dev", side_effect=_no_geocoder), \
         patch.object(cr.time, "sleep"):
        devs, status = cr.search_competing_devs("Bushwick", "Brooklyn", 40.7, -73.9)
    assert status == "live"
    assert len(devs) > 0


def test_all_sources_fail_reports_error():
    with patch.object(cr, "fetch_rss_content", return_value=(None, "error: boom")), \
         patch.object(cr, "_ddg_search", return_value=([], False)), \
         patch.object(cr.time, "sleep"):
        devs, status = cr.search_competing_devs("Bushwick", "Brooklyn", 40.7, -73.9)
    assert devs == []
    assert status == "error"


def test_genuinely_no_results_reports_no_results():
    with patch.object(cr, "fetch_rss_content", return_value=(_EMPTY_FEED, "ok")), \
         patch.object(cr, "_ddg_search", return_value=([], True)), \
         patch.object(cr.time, "sleep"):
        devs, status = cr.search_competing_devs("Bushwick", "Brooklyn", 40.7, -73.9)
    assert devs == []
    assert status == "no_results"


def test_rss_results_helper_filters_by_location():
    with patch.object(cr, "fetch_rss_content", return_value=(_RELEVANT_FEED, "ok")), \
         patch.object(cr, "cutoff_date", return_value="2000-01-01"):
        rows, any_ok = cr._rss_results("Bushwick")
    assert any_ok is True
    # The mock returns the same relevant item for every configured RSS
    # source — search_competing_devs()'s later _dedupe() step (not
    # _rss_results() itself) is what collapses duplicates across sources.
    assert len(rows) == len(cr._RSS_SOURCES)

    with patch.object(cr, "fetch_rss_content", return_value=(_RELEVANT_FEED, "ok")), \
         patch.object(cr, "cutoff_date", return_value="2000-01-01"):
        rows_miami, _ = cr._rss_results("Miami Beach")
    # "Bushwick" feed item doesn't mention Miami Beach or NYC generically —
    # should be filtered out.
    assert rows_miami == []

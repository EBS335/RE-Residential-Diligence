"""
Tests for modules/rss_fetcher.py — the shared RSS fetch/parse primitives
now reused by modules/nearby_developments.py, modules/articles_fetcher.py,
and modules/comps_research.py (Property Analysis tab news/comps
reliability fix).
"""

from unittest.mock import patch, MagicMock

import requests

from modules import rss_fetcher as rf


def _fake_response(text: str, status_code: int = 200, raise_exc=None):
    r = MagicMock()
    r.status_code = status_code
    if raise_exc:
        r.raise_for_status = MagicMock(side_effect=raise_exc)
    else:
        r.raise_for_status = lambda: None
    r.content = text.encode("utf-8")
    return r


_SAMPLE_FEED = """<rss><channel>
<item>
  <title>New Tower Approved in Bushwick</title>
  <link>https://example.com/article-1</link>
  <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
  <description>A 12-story residential tower with 200 units was approved.</description>
</item>
<item>
  <title>Old News From Elsewhere</title>
  <link>https://example.com/article-2</link>
  <pubDate>Mon, 01 Jan 2018 12:00:00 GMT</pubDate>
  <description>Unrelated story.</description>
</item>
</channel></rss>"""


# ── fetch_rss_content ────────────────────────────────────────────────────────

def test_fetch_rss_content_ok():
    with patch.object(rf.requests, "get", return_value=_fake_response(_SAMPLE_FEED)):
        content, status = rf.fetch_rss_content("https://example.com/feed/")
    assert status == "ok"
    assert "New Tower Approved" in content


def test_fetch_rss_content_blocked():
    with patch.object(rf.requests, "get", return_value=_fake_response("", status_code=403)):
        content, status = rf.fetch_rss_content("https://example.com/feed/")
    assert status == "blocked"
    assert content is None


def test_fetch_rss_content_error_never_raises():
    with patch.object(rf.requests, "get", side_effect=requests.exceptions.Timeout("simulated")):
        content, status = rf.fetch_rss_content("https://example.com/feed/")
    assert status.startswith("error")
    assert content is None


# ── parse_rss_items ──────────────────────────────────────────────────────────

def test_parse_rss_items_extracts_fields():
    items = rf.parse_rss_items(_SAMPLE_FEED)
    assert len(items) == 2
    first = items[0]
    assert first["title"] == "New Tower Approved in Bushwick"
    assert first["url"] == "https://example.com/article-1"
    assert first["pub_date"] == "2024-01-01"
    assert "200 units" in first["description"]


def test_parse_rss_items_malformed_feed_degrades_gracefully():
    assert rf.parse_rss_items("<not-xml-at-all") == []


def test_parse_rss_items_empty_string():
    assert rf.parse_rss_items("") == []


# ── parse_pub_date / cutoff_date ─────────────────────────────────────────────

def test_parse_pub_date_valid():
    assert rf.parse_pub_date("Mon, 01 Jan 2024 12:00:00 GMT") == "2024-01-01"


def test_parse_pub_date_unparseable_falls_back_to_prefix():
    assert rf.parse_pub_date("2024-01-01 garbage") == "2024-01-01"


def test_parse_pub_date_empty():
    assert rf.parse_pub_date("") == ""


def test_cutoff_date_is_iso_format():
    d = rf.cutoff_date(12)
    assert len(d) == 10
    assert d.count("-") == 2


# ── location_relevant ────────────────────────────────────────────────────────

def test_location_relevant_matches_loc_filter():
    assert rf.location_relevant("A new tower in Bushwick is rising", "Bushwick") is True


def test_location_relevant_matches_generic_nyc():
    assert rf.location_relevant("A new tower in New York is rising", "Greenpoint") is True


def test_location_relevant_no_match():
    assert rf.location_relevant("A new tower in Miami is rising", "Bushwick") is False


def test_location_relevant_empty_loc_filter_still_requires_nyc_mention():
    assert rf.location_relevant("A story about Miami", "") is False
    assert rf.location_relevant("A story about NYC", "") is True

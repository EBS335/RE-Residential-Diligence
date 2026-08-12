from modules.zoning_rules import get_zoning_rules, get_zoning_citations, all_districts


def test_exact_match():
    assert get_zoning_rules("R6") is not None
    assert get_zoning_rules("C6-2") is not None


def test_modifier_stripped_match():
    # "C4-4X" isn't itself a key, but stripping the trailing letter modifier
    # (A/B/D/X/H) should resolve to "C4-4"
    rules = get_zoning_rules("C4-4X")
    assert rules is not None
    assert rules == get_zoning_rules("C4-4")


def test_letter_digit_prefix_fallback_match():
    # "R6A-1" has no modifier-letter suffix ("1" isn't A/B/D/X/H), so it
    # falls through to strategy 4: truncate to the base letter+digit
    # prefix ("R6A-1" -> "R6")
    rules = get_zoning_rules("R6A-1")
    assert rules is not None
    assert rules == get_zoning_rules("R6")


def test_split_zone_notation_uses_first_district():
    rules = get_zoning_rules("R7A/C1-4")
    assert rules is not None


def test_unknown_district_returns_none():
    assert get_zoning_rules("ZZ99") is None
    assert get_zoning_rules("") is None
    assert get_zoning_rules(None) is None


def test_case_insensitive():
    assert get_zoning_rules("r6") == get_zoning_rules("R6")


def test_all_districts_sorted_and_nonempty():
    ds = all_districts()
    assert len(ds) > 0
    assert ds == sorted(ds)


def test_get_zoning_citations_required_keys():
    citations = get_zoning_citations("R6A")
    required = {
        "far_citation", "far_url", "height_citation", "height_url",
        "lot_cov_citation", "use_citation", "use_url", "parking_citation",
        "parking_url", "article_url", "zr_main_url", "quality_housing",
        "mih_eligible", "mih_url", "ih_url", "zola_url",
    }
    assert required.issubset(citations.keys())


def test_get_zoning_citations_empty_district():
    assert get_zoning_citations("") == {}
    assert get_zoning_citations(None) == {}

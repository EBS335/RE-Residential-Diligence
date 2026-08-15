"""
Tests for the Site Finder tab improvements added to modules/site_sourcing.py:
  - flag_assemblage_candidates(): flags near-lot-number pairs WITHIN a
    results set as assemblage candidates (no extra network calls).
  - enrich_property()'s rent_stab_signal: ground-truth registry match
    (modules/rent_stab_registry.py) takes priority over the pre-existing
    PLUTO-only heuristic estimate.
"""

from unittest.mock import patch

from modules.site_sourcing import flag_assemblage_candidates, enrich_property, _lot_number


def _prop(address, borough_code="3", block="100", lot="10", **overrides):
    base = {
        "bbl": f"3{block.zfill(5)}{lot.zfill(4)}", "borough": "Brooklyn",
        "borough_code": borough_code, "block": block, "lot": lot,
        "address": address, "lot_sf": 5000.0, "bldg_sf": 0.0,
        "far_max": 3.0, "far_built": 0.0, "unused_far_pct": 100.0,
        "assess_land": 100000.0, "is_vacant": True,
        "year_built": "", "num_floors": 0.0, "units_res": 0.0,
    }
    base.update(overrides)
    return base


# ── flag_assemblage_candidates ──────────────────────────────────────────────

def test_adjacent_lots_on_same_block_flagged():
    props = [_prop("A", lot="10"), _prop("B", lot="11")]
    out = flag_assemblage_candidates(props)
    assert out[0]["assemblage_with"] == ["B"]
    assert out[1]["assemblage_with"] == ["A"]


def test_non_adjacent_lot_number_not_flagged():
    props = [_prop("A", lot="10"), _prop("C", lot="50")]
    out = flag_assemblage_candidates(props)
    assert out[0]["assemblage_with"] == []
    assert out[1]["assemblage_with"] == []


def test_different_block_not_flagged_even_with_adjacent_lot_numbers():
    props = [_prop("A", block="100", lot="10"), _prop("B", block="200", lot="11")]
    out = flag_assemblage_candidates(props)
    assert out[0]["assemblage_with"] == []
    assert out[1]["assemblage_with"] == []


def test_different_borough_not_flagged():
    props = [
        _prop("A", borough_code="3", block="100", lot="10"),
        _prop("B", borough_code="4", block="100", lot="11"),
    ]
    out = flag_assemblage_candidates(props)
    assert out[0]["assemblage_with"] == []
    assert out[1]["assemblage_with"] == []


def test_chain_of_three_adjacent_lots():
    props = [_prop("A", lot="10"), _prop("B", lot="11"), _prop("C", lot="12")]
    out = flag_assemblage_candidates(props)
    assert out[0]["assemblage_with"] == ["B"]
    assert set(out[1]["assemblage_with"]) == {"A", "C"}
    assert out[2]["assemblage_with"] == ["B"]


def test_single_property_never_flagged():
    props = [_prop("A", lot="10")]
    out = flag_assemblage_candidates(props)
    assert out[0]["assemblage_with"] == []


def test_missing_block_or_lot_does_not_raise():
    props = [_prop("A", lot=""), _prop("B", block="")]
    out = flag_assemblage_candidates(props)
    assert out[0]["assemblage_with"] == []
    assert out[1]["assemblage_with"] == []


def test_does_not_mutate_input():
    props = [_prop("A", lot="10"), _prop("B", lot="11")]
    flag_assemblage_candidates(props)
    assert "assemblage_with" not in props[0]


def test_lot_number_parses_digits_from_string():
    assert _lot_number({"lot": "42"}) == 42
    assert _lot_number({"lot": ""}) is None
    assert _lot_number({"lot": "7501"}) == 7501


# ── enrich_property() rent-stab registry wiring ─────────────────────────────

def test_enrich_property_uses_confirmed_registry_match():
    prop = _prop("246 10th Avenue", borough_code="1", block="722", lot="3")
    with patch(
        "modules.rent_stab_registry.check_rent_stabilized",
        return_value={"status": "confirmed", "match_type": "bbl", "notes": ["MULTIPLE DWELLING A"], "error": None},
    ):
        out = enrich_property(prop)
    rs = out["rent_stab_signal"]
    assert rs["likely_stabilized"] is True
    assert rs["verified"] is True
    assert rs["match_type"] == "bbl"
    assert "MULTIPLE DWELLING A" in rs["registry_notes"]


def test_enrich_property_falls_back_to_heuristic_when_not_on_list():
    prop = _prop("1 Nonexistent Ave", year_built="1920", units_res=10.0, is_vacant=False)
    with patch(
        "modules.rent_stab_registry.check_rent_stabilized",
        return_value={"status": "not_found", "match_type": None, "notes": [], "error": None},
    ):
        out = enrich_property(prop)
    rs = out["rent_stab_signal"]
    assert rs["verified"] is False
    assert rs["match_type"] is None
    assert rs["registry_notes"] == []
    # Heuristic estimate keys still present (backward-compatible shape)
    assert "likely_stabilized" in rs
    assert "confidence" in rs

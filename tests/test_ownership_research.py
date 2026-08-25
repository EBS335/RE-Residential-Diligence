"""
Tests for modules/ownership_research.py.

Batch C adds two new appended fetch calls + two new output keys
(`tax_lien`, `composite_distress`) to enrich_ownership() — this file
pins the pre-existing output shape (so a future change can't silently
alter it) and covers the new fields.
"""

from unittest.mock import patch

from modules import ownership_research as own


_PROP = {
    "bbl": "3012340001",
    "borough": "Brooklyn",
    "borough_code": "3",
    "block": "1234",
    "lot": "1",
    "address": "100 Test St",
    "owner": "TEST OWNER LLC",
    "year_built": "1930",
}

_ACRIS_RESULT = {
    "summary": {
        "latest_buyer": "TEST OWNER LLC",
        "latest_sale_price": 1_000_000.0,
        "latest_sale_date": "2020-01-01",
        "active_mortgage_amt": 500_000.0,
        "active_lender": "TEST BANK",
        "open_liens": 1,
        "foreclosure_count": 0,
    },
    "acris_url": "https://example.com/acris",
    "error": None,
}

_PIP_RESULT = {
    "summary": {
        "open_dob_viol": 3,
        "total_dob_viol": 5,
        "open_complaints": 2,
    },
    "hpd_building": {"dwelling_units": "12"},
    "pip_url": "https://example.com/pip",
    "error": None,
}

_TAX_LIEN_RESULT = {
    "on_lien_list": True,
    "records": [{"owner_name": "TEST OWNER LLC", "total_due": "5000", "class": "1"}],
    "count": 1,
    "info_url": "https://www.nyc.gov/site/finance/property/property-tax-lien-sale.page",
    "source": "NYC DOF Tax Lien Sale List",
    "verified": True,
    "error": None,
}


def _patched():
    return patch.multiple(
        own,
        fetch_acris=lambda bbl: dict(_ACRIS_RESULT),
        fetch_property_history=lambda bbl, borough_name="", address="": dict(_PIP_RESULT),
        fetch_tax_lien_status=lambda boro, block, lot: dict(_TAX_LIEN_RESULT),
    )


def test_enrich_ownership_preserves_all_pre_existing_keys_and_values():
    with _patched():
        out = own.enrich_ownership(_PROP, borough_name="Brooklyn")

    # Every pre-existing key from the function's original docstring/contract.
    assert out["owner_type"] == "Corporate Entity"
    assert out["last_sale_price"] == 1_000_000.0
    assert out["last_sale_date"] == "2020-01-01"
    assert out["active_mortgage_amt"] == 500_000.0
    assert out["active_lender"] == "TEST BANK"
    assert out["open_liens"] == 1
    assert out["foreclosure_count"] == 0
    assert out["dob_open_violations"] == 3
    assert out["hpd_dwelling_units"] == "12"
    assert out["distress"]["level"] in ("No Signal", "Weak Signal", "Moderate Signal", "Strong Signal")
    assert out["distress_signal"] == out["distress"]["level"]
    assert out["acris_url"] == "https://example.com/acris"
    assert out["pip_url"] == "https://example.com/pip"
    assert out["acris_error"] is None
    assert out["pip_error"] is None
    # Original input fields carried through untouched.
    assert out["bbl"] == _PROP["bbl"]
    assert out["address"] == _PROP["address"]


def test_enrich_ownership_adds_tax_lien_and_composite_distress_keys():
    with _patched():
        out = own.enrich_ownership(_PROP, borough_name="Brooklyn")

    assert out["tax_lien"] == _TAX_LIEN_RESULT
    assert "composite_distress" in out
    cd = out["composite_distress"]
    assert set(cd.keys()) == {"score", "tier", "breakdown", "components_with_data"}
    assert isinstance(cd["score"], int)
    assert cd["tier"] in ("Minimal", "Moderate", "Elevated", "Severe")
    # tax_lien component should reflect on_lien_list=True in its breakdown.
    assert cd["breakdown"]["tax_lien"]["score"] > 0
    assert "tax_lien" in cd["components_with_data"]
    # dob component fed from p_summ's open_dob_viol/open_complaints.
    assert cd["breakdown"]["dob"]["score"] > 0


def test_enrich_ownership_never_raises_when_tax_lien_fetch_raises():
    def _boom(boro, block, lot):
        raise RuntimeError("network exploded")

    with patch.multiple(
        own,
        fetch_acris=lambda bbl: dict(_ACRIS_RESULT),
        fetch_property_history=lambda bbl, borough_name="", address="": dict(_PIP_RESULT),
        fetch_tax_lien_status=_boom,
    ):
        out = own.enrich_ownership(_PROP, borough_name="Brooklyn")

    # Never raises — tax_lien degrades to a captured-error dict, and
    # composite_distress still computes off whatever signal is available.
    assert "error" in out["tax_lien"]
    assert "composite_distress" in out
    # Pre-existing keys are still present and correct even when the new
    # fetch call blows up.
    assert out["owner_type"] == "Corporate Entity"
    assert out["last_sale_price"] == 1_000_000.0


def test_enrich_ownership_never_raises_when_tax_lien_returns_error_dict():
    error_result = {
        "on_lien_list": None, "records": [], "count": 0,
        "info_url": "", "source": "NYC DOF Tax Lien Sale List",
        "verified": False, "error": "tax lien list request failed",
    }
    with patch.multiple(
        own,
        fetch_acris=lambda bbl: dict(_ACRIS_RESULT),
        fetch_property_history=lambda bbl, borough_name="", address="": dict(_PIP_RESULT),
        fetch_tax_lien_status=lambda boro, block, lot: dict(error_result),
    ):
        out = own.enrich_ownership(_PROP, borough_name="Brooklyn")

    assert out["tax_lien"]["on_lien_list"] is None
    assert out["tax_lien"]["error"] == "tax lien list request failed"
    assert out["composite_distress"]["breakdown"]["tax_lien"]["score"] == 0


def test_enrich_ownership_skips_tax_lien_fetch_when_bbl_fields_missing():
    prop = dict(_PROP)
    prop["borough_code"] = ""
    prop["block"] = ""
    prop["lot"] = ""

    calls = []

    def _tracked(boro, block, lot):
        calls.append((boro, block, lot))
        return dict(_TAX_LIEN_RESULT)

    with patch.multiple(
        own,
        fetch_acris=lambda bbl: dict(_ACRIS_RESULT),
        fetch_property_history=lambda bbl, borough_name="", address="": dict(_PIP_RESULT),
        fetch_tax_lien_status=_tracked,
    ):
        out = own.enrich_ownership(prop, borough_name="Brooklyn")

    assert calls == []  # never called — defensive guard on usable bbl fields
    assert out["tax_lien"] == {}
    assert "composite_distress" in out  # still computes (defaults tax_lien component to 0)


def test_enrich_ownership_batch_still_works_unchanged_with_new_fields():
    with _patched():
        results = own.enrich_ownership_batch([_PROP], batch_size=1)

    assert len(results) == 1
    assert results[0]["tax_lien"] == _TAX_LIEN_RESULT
    assert "composite_distress" in results[0]
    assert results[0]["owner_type"] == "Corporate Entity"

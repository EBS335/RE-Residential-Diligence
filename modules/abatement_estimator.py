"""
Tax Abatement Signal — Estimator (485-x / J-51 / ICAP).

There is no free, keyless, building-level public API for tax-abatement
program status/eligibility in NYC. This module surfaces two different
kinds of signal and is explicit about which is which:

  1. `currently_exempt` / `exempt_value` — VERIFIED, taken directly from
     PLUTO's own exemption fields (`exemptland`/`exempttot`), which are
     already fetched by property_search.py / zola_fetcher.py and simply
     weren't being surfaced. This tells you the property currently
     receives *some* tax exemption, but not which program.

  2. `estimated_programs` — a rough, rules-of-thumb ESTIMATE of which
     major NYC incentive program(s) the property might be eligible for
     (485-x successor to 421-a, J-51, ICAP), based on building age and
     unit count. Every entry is explicitly labeled unverified per the
     confidence convention used by the AI diligence agents
     (modules/site_finder_agents.py): {source, confidence, verified}.
     These thresholds are simplified rules of thumb, not legal/tax advice
     — always confirm with NYC Dept of Finance / a tax attorney.

Follows the house fetcher-module contract even though it makes no network
call: a public function that never raises, always returns the same fixed
dict shape (with `error` set on the rare malformed-input case).
"""

from __future__ import annotations

from modules.app_logging import get_logger

log = get_logger(__name__)

_485X_MIN_UNITS = 6      # 485-x (421-a successor) targets multifamily rental buildings
_J51_MAX_YEAR_BUILT = 1974  # J-51 targets renovation of older existing buildings
_ICAP_MIN_UNITS = 0      # ICAP is broad — any Class 1/2/4 new construction or major reno


def _to_float(v, default=None):
    """Coerce raw PLUTO numerics (Site Finder's _normalize_row) as well as
    zola_fetcher's pre-formatted display strings (e.g. "$500,000", "—")
    into a float, since this estimator is called from both flows."""
    try:
        if v is None or v == "":
            return default
        if isinstance(v, str):
            v = v.strip()
            if v in ("", "—", "-"):
                return default
            v = v.replace("$", "").replace(",", "")
        return float(v)
    except (TypeError, ValueError):
        return default


def _to_int(v, default=None):
    f = _to_float(v, None)
    return int(f) if f is not None else default


def estimate_tax_abatement(prop: dict) -> dict:
    """
    Rules-based estimate of tax abatement status/eligibility.

    Args:
        prop: a normalized property dict (Site Finder shape or ZoLA shape) —
            expects 'year_built', 'units_res', and optionally 'exempt_land'/
            'exempt_total' (added to _normalize_row/fetch_zoning_info).

    Returns (always this shape, never raises):
        {
          "currently_exempt": bool | None,
          "exempt_value": float | None,
          "estimated_programs": [
              {"program": str, "eligible_estimate": bool, "confidence": float,
               "verified": False, "source": str},
              ...
          ],
          "error": str | None,
        }
    """
    try:
        prop = prop or {}
        exempt_total = _to_float(prop.get("exempt_total"))
        currently_exempt = (exempt_total is not None and exempt_total > 0) if exempt_total is not None else None

        year_built = _to_int(prop.get("year_built"))
        units_res = _to_int(prop.get("units_res"), 0) or 0

        programs = []

        eligible_485x = units_res >= _485X_MIN_UNITS
        programs.append({
            "program": "485-x",
            "eligible_estimate": eligible_485x,
            "confidence": 0.4 if eligible_485x else 0.55,
            "verified": False,
            "source": f"model inference: {units_res} residential units "
                      f"({'meets' if eligible_485x else 'below'} the ~{_485X_MIN_UNITS}-unit "
                      "multifamily-rental threshold typical of 421-a/485-x successor programs)",
        })

        eligible_j51 = bool(year_built and year_built < _J51_MAX_YEAR_BUILT)
        programs.append({
            "program": "J-51",
            "eligible_estimate": eligible_j51,
            "confidence": 0.35 if eligible_j51 else 0.5,
            "verified": False,
            "source": f"model inference: built {year_built or 'unknown'} "
                      f"({'pre' if eligible_j51 else 'post'}-{_J51_MAX_YEAR_BUILT}, "
                      "J-51 targets renovation of older existing buildings)",
        })

        eligible_icap = True  # broad program; flag as "worth checking" rather than a hard filter
        programs.append({
            "program": "ICAP",
            "eligible_estimate": eligible_icap,
            "confidence": 0.3,
            "verified": False,
            "source": "model inference: ICAP eligibility is broad (Class 1/2/4 new "
                      "construction or major renovation) — worth checking regardless of "
                      "the above signals",
        })

        return {
            "currently_exempt": currently_exempt,
            "exempt_value": exempt_total if exempt_total else None,
            "estimated_programs": programs,
            "error": None,
        }
    except Exception as exc:
        log.debug("estimate_tax_abatement failed on malformed input: %s", exc)
        return {
            "currently_exempt": None,
            "exempt_value": None,
            "estimated_programs": [],
            "error": str(exc),
        }

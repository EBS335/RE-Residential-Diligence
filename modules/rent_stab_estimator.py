"""
Rent Stabilization Signal — Estimator.

NYS Homes & Community Renewal (DHCR) does not publish a clean, free,
building-level bulk API for rent-stabilization status — the official tool
is a manual per-building lookup. This module surfaces the standard
practitioner heuristic instead, clearly and permanently labeled as an
estimate (never `verified: True`), with a link out to the official DHCR
tool for confirmation.

Heuristic (the common rule of thumb used in NYC acquisition diligence):
  6+ residential units AND built before 1974
  OR currently/previously received a J-51 or 421-a/485-x exemption
  => "likely rent stabilized"

This is a screening signal only. It will both over- and under-flag
buildings relative to the true DHCR registration (e.g. it can't see
post-vacancy deregulation, individual apartment improvement decontrol
history prior to 2019 rule changes, or co-op/condo conversions that
exited stabilization) — the UI must always present it as "estimated,
confirm via DHCR," never as fact.
"""

from __future__ import annotations

from modules.app_logging import get_logger

log = get_logger(__name__)

_MIN_UNITS = 6
_MAX_YEAR_BUILT = 1974
DHCR_LOOKUP_URL = "https://hcr.ny.gov/rent-stabilized-building-list"


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


def estimate_rent_stabilization(prop: dict) -> dict:
    """
    Args:
        prop: normalized property dict — expects 'year_built', 'units_res',
            and optionally 'exempt_total' (>0 signals a currently-active
            tax exemption, one common path into stabilization coverage).

    Returns (always this shape, never raises):
        {
          "likely_stabilized": bool,
          "confidence": float,
          "verified": False,
          "source": str,
          "dhcr_lookup_url": str,
          "error": str | None,
        }
    """
    try:
        prop = prop or {}
        year_built = _to_int(prop.get("year_built"))
        units_res = _to_int(prop.get("units_res"), 0) or 0
        exempt_total = _to_float(prop.get("exempt_total"), 0.0) or 0.0

        age_signal = bool(year_built and year_built < _MAX_YEAR_BUILT and units_res >= _MIN_UNITS)
        exemption_signal = exempt_total > 0 and units_res >= _MIN_UNITS

        likely = age_signal or exemption_signal

        if age_signal and exemption_signal:
            confidence, reason = 0.6, (
                f"{units_res} units built {year_built} (pre-{_MAX_YEAR_BUILT}) AND "
                "currently receiving a tax exemption — both classic stabilization signals"
            )
        elif age_signal:
            confidence, reason = 0.5, (
                f"{units_res} units built {year_built} (pre-{_MAX_YEAR_BUILT}, "
                f"meets the {_MIN_UNITS}+ unit / pre-1974 rule of thumb)"
            )
        elif exemption_signal:
            confidence, reason = 0.4, (
                f"{units_res} units currently receiving a tax exemption — a common path "
                "into stabilization coverage, though program-dependent"
            )
        else:
            confidence, reason = 0.55, (
                f"{units_res} units, built {year_built or 'unknown'} — does not meet the "
                f"{_MIN_UNITS}+ unit / pre-{_MAX_YEAR_BUILT} rule of thumb, no active exemption detected"
            )

        return {
            "likely_stabilized": likely,
            "confidence": confidence,
            "verified": False,
            "source": f"heuristic: unit count + year built + exemption status ({reason})",
            "dhcr_lookup_url": DHCR_LOOKUP_URL,
            "error": None,
        }
    except Exception as exc:
        log.debug("estimate_rent_stabilization failed on malformed input: %s", exc)
        return {
            "likely_stabilized": False,
            "confidence": 0.0,
            "verified": False,
            "source": "",
            "dhcr_lookup_url": DHCR_LOOKUP_URL,
            "error": str(exc),
        }

"""
OATH/ECB Hearings Fetcher — NYC OATH Hearings Division Case Status
(Socrata 6bgk-3dad).

One free, keyless public data source: the Office of Administrative Trials
and Hearings' Environmental Control Board (ECB) hearing case records —
distinct from (and a genuine gap alongside) modules/ecb_fetcher.py, which
despite its name only queries HPD violations, not actual ECB/OATH hearing
data. This module is the real thing: hearing dates/results, violation
charges, and balance-due amounts for ECB summonses that went to a
hearing.

Same house pattern as modules/environmental_fetcher.py: a private
_get_json() wrapper, a fixed-shape dict return that never raises, and
record_source_status() wiring for the sidebar Data Health panel.

This sandbox cannot verify the live 6bgk-3dad schema against a real
request (network egress to data.cityofnewyork.us is blocked here) — the
violation_location_* field-name guesses below are drawn from the
dataset's publicly documented column list, but a wrong guess is caught
by the same graceful-degradation pattern environmental_fetcher.py uses
for its own unverifiable DEC-spills query: Socrata 400s on an unknown
$where column, which is treated as "couldn't confirm," never as a false
"zero hearings" negative.
"""

from __future__ import annotations

import requests

from modules.app_logging import get_logger, record_source_status

log = get_logger(__name__)

_OATH_URL = "https://data.cityofnewyork.us/resource/6bgk-3dad.json"
_TIMEOUT = 15

_BOROUGH_NAME = {
    "1": "MANHATTAN", "2": "BRONX", "3": "BROOKLYN", "4": "QUEENS", "5": "STATEN ISLAND",
}


def _get_json(url: str, params: dict) -> tuple[list | None, bool]:
    try:
        r = requests.get(url, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json(), True
    except Exception as exc:
        log.warning("oath_fetcher request to %s failed: %s", url, exc)
        return None, False


def fetch_oath_hearings(borough_code: str, block: str, lot: str, limit: int = 25) -> dict:
    """
    Look up OATH/ECB hearing case records for a parcel.

    Returns (always this shape, never raises):
        {
          "hearings": list[dict],   # ticket_number, hearing_date, result, charge, balance_due
          "count": int,
          "open_balance_count": int,   # hearings with a nonzero balance still due
          "source": "NYC OATH Hearings Division Case Status",
          "verified": bool,             # True only when the query itself succeeded
          "error": str | None,
        }
    """
    base = {
        "hearings": [],
        "count": 0,
        "open_balance_count": 0,
        "source": "NYC OATH Hearings Division Case Status",
        "verified": False,
        "error": None,
    }
    try:
        if not borough_code or not block or not lot:
            return {**base, "error": "missing borough/block/lot"}
        boro_name = _BOROUGH_NAME.get(str(borough_code))
        if not boro_name:
            return {**base, "error": f"unrecognized borough code: {borough_code}"}

        params = {
            "$where": (
                f"violation_location_borough='{boro_name}' AND "
                f"violation_location_block_no='{int(block)}' AND "
                f"violation_location_lot_no='{int(lot)}'"
            ),
            "$order": "hearing_date DESC",
            "$limit": str(limit),
        }
        data, ok = _get_json(_OATH_URL, params)
        record_source_status("OATH/ECB Hearings", ok=ok, detail="" if ok else "OATH hearings request failed")
        if not ok:
            return {**base, "error": "OATH hearings request failed, timed out, or field names have changed"}
        if not isinstance(data, list):
            return {**base, "error": "unexpected response shape"}

        hearings = []
        open_balance = 0
        for r in data:
            balance_raw = r.get("balance_due") or "0"
            try:
                balance = float(str(balance_raw).replace(",", ""))
            except ValueError:
                balance = 0.0
            if balance > 0:
                open_balance += 1
            hearings.append({
                "ticket_number": r.get("ticket_number", ""),
                "hearing_date": (r.get("hearing_date") or "")[:10],
                "result": r.get("hearing_result", r.get("hearing_status", "")),
                "charge": r.get("charge_1_code_description", r.get("violation_details", "")),
                "balance_due": balance,
            })

        return {
            **base, "verified": True, "hearings": hearings, "count": len(hearings),
            "open_balance_count": open_balance,
        }
    except Exception as exc:
        log.warning("fetch_oath_hearings failed: %s", exc)
        record_source_status("OATH/ECB Hearings", ok=False, detail=str(exc))
        return {**base, "error": str(exc)}

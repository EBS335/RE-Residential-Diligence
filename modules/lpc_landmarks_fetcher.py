"""
LPC Individual Landmarks Fetcher — NYC Landmarks Preservation Commission
Individual Landmarks (Socrata px3f-pupb).

One free, keyless public data source: LPC's own authoritative list of
individually-designated landmarks (distinct from historic-district status,
which PLUTO's own histdist/landmark fields already surface reasonably
well). PLUTO's landmark flag is not always complete/current, so this is a
corroborating, authoritative second source — not a replacement for the
existing PLUTO-derived flag.

Same house pattern as modules/environmental_fetcher.py: a private
_get_json() wrapper, a fixed-shape dict return that never raises, and
record_source_status() wiring for the sidebar Data Health panel.

This sandbox cannot verify the live px3f-pupb schema against a real
request (network egress to data.cityofnewyork.us is blocked here) — the
"bbl" field-name guess below matches the dataset's publicly documented
primary key column. A wrong guess is caught the same way
environmental_fetcher.py's DEC-spills fallback is: Socrata 400s on an
unknown $where column, treated as "couldn't confirm," never as a false
"not a landmark" negative.
"""

from __future__ import annotations

import requests

from modules.app_logging import get_logger, record_source_status

log = get_logger(__name__)

_LPC_URL = "https://data.cityofnewyork.us/resource/px3f-pupb.json"
_LPC_MAP_URL = "https://a002-ci.nyc.gov/lpc/lpc_public/"
_TIMEOUT = 15


def _get_json(url: str, params: dict) -> tuple[list | None, bool]:
    try:
        r = requests.get(url, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json(), True
    except Exception as exc:
        log.warning("lpc_landmarks_fetcher request to %s failed: %s", url, exc)
        return None, False


def fetch_lpc_landmark_status(bbl: str) -> dict:
    """
    Look up whether a parcel is an LPC-designated individual landmark.

    Returns (always this shape, never raises):
        {
          "is_individual_landmark": bool | None,   # None = could not confirm either way
          "landmark_name": str | None,
          "designation_date": str | None,
          "map_url": str,
          "source": "NYC LPC Individual Landmarks",
          "verified": bool,     # True only when the query itself succeeded
          "error": str | None,
        }
    """
    base = {
        "is_individual_landmark": None,
        "landmark_name": None,
        "designation_date": None,
        "map_url": _LPC_MAP_URL,
        "source": "NYC LPC Individual Landmarks",
        "verified": False,
        "error": None,
    }
    try:
        if not bbl or len(str(bbl)) < 10:
            return {**base, "error": "missing or malformed BBL"}

        params = {"$where": f"bbl='{bbl}'", "$limit": "5"}
        data, ok = _get_json(_LPC_URL, params)
        record_source_status("LPC Individual Landmarks", ok=ok, detail="" if ok else "LPC landmarks request failed")
        if not ok:
            return {**base, "error": "LPC landmarks request failed, timed out, or field names have changed"}
        if not isinstance(data, list):
            return {**base, "error": "unexpected response shape"}

        if not data:
            return {**base, "verified": True, "is_individual_landmark": False}

        rec = data[0]
        return {
            **base, "verified": True, "is_individual_landmark": True,
            "landmark_name": rec.get("lm_name", rec.get("name", "")) or None,
            "designation_date": (rec.get("designated", rec.get("designation_date", "")) or "")[:10] or None,
        }
    except Exception as exc:
        log.warning("fetch_lpc_landmark_status failed: %s", exc)
        record_source_status("LPC Individual Landmarks", ok=False, detail=str(exc))
        return {**base, "error": str(exc)}

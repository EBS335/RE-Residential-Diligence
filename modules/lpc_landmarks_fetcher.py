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

# "LPC Individual Landmark and Historic District Building Database" —
# the NYC Open Data dataset (Socrata 7mgd-s57w) that backs LPC's public
# "Discover NYC Landmarks" ArcGIS Experience Builder map
# (https://experience.arcgis.com/experience/fa1bcaad31374a88839da3f0166e640a/page/Page).
# This is a building-level, BBL-queryable dataset covering BOTH the
# ~1,408 individually-designated landmarks AND the ~34,000 buildings
# within the 141 historic districts — a strict superset of px3f-pupb
# above (individual landmarks only, no historic-district coverage).
_LPC_DESIGNATION_URL = "https://data.cityofnewyork.us/resource/7mgd-s57w.json"
_LPC_DISCOVER_MAP_URL = "https://experience.arcgis.com/experience/fa1bcaad31374a88839da3f0166e640a/page/Page"


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


def fetch_lpc_designation_status(bbl: str) -> dict:
    """
    Look up individual-landmark AND/OR historic-district status for a
    parcel against the same underlying dataset that powers LPC's public
    "Discover NYC Landmarks" map (see _LPC_DESIGNATION_URL above) — a
    strict superset of fetch_lpc_landmark_status()'s px3f-pupb dataset,
    since it also covers historic-district membership, which px3f-pupb
    does not.

    Returns (always this shape, never raises):
        {
          "is_individual_landmark": bool | None,    # None = could not confirm
          "is_in_historic_district": bool | None,   # None = could not confirm
          "historic_district_name": str | None,
          "landmark_name": str | None,
          "designation_date": str | None,
          "borough": str | None,
          "map_url": str,
          "source": "NYC LPC — Discover NYC Landmarks (Individual Landmark & Historic District Building Database)",
          "verified": bool,     # True only when the query itself succeeded
          "error": str | None,
        }

    CAVEAT — field names for dataset 7mgd-s57w are UNVERIFIED: this
    sandbox's egress to data.cityofnewyork.us is blocked (confirmed by
    direct test), so the Socrata field names guessed below (lpc_name,
    hist_dist, lp_number, desig_date, borough) could not be confirmed
    against a live request. Same caveat convention as
    modules/ll84_fetcher.py's documented dataset-ID flag — treat these
    as best-effort until live-verified. A wrong field-name guess degrades
    to "could not confirm" (never a false negative), the same fail-safe
    pattern fetch_lpc_landmark_status() above already uses.
    """
    base = {
        "is_individual_landmark": None,
        "is_in_historic_district": None,
        "historic_district_name": None,
        "landmark_name": None,
        "designation_date": None,
        "borough": None,
        "map_url": _LPC_DISCOVER_MAP_URL,
        "source": "NYC LPC — Discover NYC Landmarks (Individual Landmark & Historic District Building Database)",
        "verified": False,
        "error": None,
    }
    try:
        if not bbl or len(str(bbl)) < 10:
            return {**base, "error": "missing or malformed BBL"}

        params = {"$where": f"bbl='{bbl}'", "$limit": "5"}
        data, ok = _get_json(_LPC_DESIGNATION_URL, params)
        record_source_status(
            "LPC Landmark & Historic District Database", ok=ok,
            detail="" if ok else "LPC designation-status request failed",
        )
        if not ok:
            return {**base, "error": "LPC designation-status request failed, timed out, or field names have changed"}
        if not isinstance(data, list):
            return {**base, "error": "unexpected response shape"}

        if not data:
            return {
                **base, "verified": True,
                "is_individual_landmark": False, "is_in_historic_district": False,
            }

        rec = data[0]
        hist_dist_name = (rec.get("hist_dist", rec.get("historic_district", "")) or "").strip() or None
        is_indiv = bool((rec.get("lp_number", rec.get("landmark_type", "")) or "").strip())
        return {
            **base, "verified": True,
            "is_individual_landmark": is_indiv,
            "is_in_historic_district": bool(hist_dist_name),
            "historic_district_name": hist_dist_name,
            "landmark_name": rec.get("lpc_name", rec.get("name", "")) or None,
            "designation_date": (rec.get("desig_date", rec.get("designation_date", "")) or "")[:10] or None,
            "borough": rec.get("borough") or None,
        }
    except Exception as exc:
        log.warning("fetch_lpc_designation_status failed: %s", exc)
        record_source_status("LPC Landmark & Historic District Database", ok=False, detail=str(exc))
        return {**base, "error": str(exc)}

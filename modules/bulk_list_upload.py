"""
Bring Your Own List — CSV upload sourcing path for Site Finder.

Lets a user upload their own shortlist of BBLs or street addresses
(instead of, or as a supplement to, the live PLUTO Investment Criteria
search) and run it through the exact same downstream pipeline as a live
search: modules.property_search.fetch_properties_by_bbls() ->
modules.site_finder_ui._enrich_and_score().

Both functions here NEVER raise — every failure mode (malformed CSV,
empty file, a geocode miss, a network error) degrades to an empty/partial
result plus a populated error/unresolved list, mirroring the "never
raises" convention used by every fetcher module in this codebase
(modules/acris_fetcher.py, modules/zola_fetcher.py, etc.).
"""

from __future__ import annotations
import io
import re
import time

import pandas as pd

from modules.zola_fetcher import geosearch_bbl

# Paced identically to modules.ownership_research.enrich_ownership_batch's
# per-property pacing (0.4s between iterations) — geosearch_bbl() is a
# single unauthenticated request per address, the same burstiness concern
# that pacing convention exists to avoid.
_GEOCODE_PACING_SECONDS = 0.4


def parse_uploaded_list(file_bytes: bytes) -> tuple[list[str], list[str], dict]:
    """
    Parse an uploaded CSV (raw bytes) into (bbls, addresses_needing_geocode, status).

    Column detection, in priority order:
      1. A column named "bbl" (case-insensitive) -> its values are used
         directly as BBLs (non-digit characters stripped).
      2. Else a column named "address" (case-insensitive) -> returned for
         the caller to geocode via resolve_addresses_to_bbls().
      3. Else the CSV's first column is treated as address text.

    Never raises: any parsing failure (malformed CSV, empty file, unreadable
    bytes, etc.) is caught and reported via status["error"], returning
    ([], [], status) rather than propagating the exception.

    status = {"error": str | None, "rows_parsed": int}
    """
    status = {"error": None, "rows_parsed": 0}
    try:
        df = pd.read_csv(io.BytesIO(file_bytes))
    except Exception as exc:
        status["error"] = str(exc)
        return [], [], status

    try:
        if len(df.columns) == 0:
            status["error"] = "CSV has no columns."
            return [], [], status

        def _clean_values(col) -> list[str]:
            return [
                s for s in (str(v).strip() for v in df[col].tolist())
                if s and s.lower() != "nan"
            ]

        bbl_col = next((c for c in df.columns if str(c).strip().lower() == "bbl"), None)
        if bbl_col is not None:
            bbls = [re.sub(r"\D", "", v) for v in _clean_values(bbl_col)]
            bbls = [b for b in bbls if b]
            status["rows_parsed"] = len(df)
            return bbls, [], status

        addr_col = next((c for c in df.columns if str(c).strip().lower() == "address"), None)
        if addr_col is None:
            addr_col = df.columns[0]

        addresses = _clean_values(addr_col)
        status["rows_parsed"] = len(df)
        return [], addresses, status

    except Exception as exc:
        status["error"] = str(exc)
        return [], [], status


def resolve_addresses_to_bbls(
    addresses: list[str],
    max_rows: int = 200,
    progress_callback=None,
) -> tuple[list[str], list[str]]:
    """
    Geocode each address (capped at max_rows) to a BBL using the same
    NYC GeoSearch primitive the rest of the app already uses for
    address -> BBL resolution (modules.zola_fetcher.geosearch_bbl() —
    the same function backing the app's existing address search box).

    Paced identically to modules.ownership_research.enrich_ownership_batch's
    per-row sleep (0.4s between calls) to stay clear of anonymous-tier
    rate limiting on a burst of back-to-back geocode requests.

    progress_callback(i, n): optional callable invoked after each geocode
    attempt, e.g. for a Streamlit progress bar (same shape as
    enrich_ownership_batch's progress_callback).

    Never raises: any per-address geocode failure (including an exception
    from the underlying geocoder) is treated the same as "not found" and
    the address is added to `unresolved`, never propagated.

    Returns (resolved_bbls, unresolved_addresses).
    """
    to_resolve = (addresses or [])[:max_rows]
    resolved: list[str] = []
    unresolved: list[str] = []

    n = len(to_resolve)
    for i, addr in enumerate(to_resolve, start=1):
        try:
            hit = geosearch_bbl(addr)
            if hit and hit.get("bbl"):
                resolved.append(hit["bbl"])
            else:
                unresolved.append(addr)
        except Exception:
            unresolved.append(addr)
        if progress_callback:
            progress_callback(i, n)
        if i < n:
            time.sleep(_GEOCODE_PACING_SECONDS)

    return resolved, unresolved

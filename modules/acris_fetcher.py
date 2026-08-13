"""
ACRIS Property Document Fetcher — NYC Open Data (no API key required).

Retrieval pipeline:
  1. Convert address to BBL via NYC GeoSearch or accept raw BBL string
  2. Query NYC Open Data ACRIS datasets (NOT website scraping):
       - ACRIS Real Property Master  (bnx9-e6tj)
       - ACRIS Real Property Parties (636b-3b5g)
       - ACRIS Real Property Legals  (2ydnx-akef)
  3. Filter by borough, block, lot; sort by document_date DESC
  4. Extract: deeds, mortgages, foreclosures, UCC, air rights, assignments
  5. Fallback logic:
       - Exact BBL match → confidence = "High"
       - Building-level lot (7501) retry for condos → confidence = "Medium"
       - Block-only match (ignore lot) → confidence = "Medium"
       - Nearby lots (±1-2) → confidence = "Low"
  6. No hard failure — always returns best available result

Returns structured dict with confidence flag, chronology, and summary callouts.
"""

from __future__ import annotations
import re
import time
import requests

from modules.app_logging import get_logger, record_source_status

log = get_logger(__name__)
from typing import Optional

_DOC_MASTER_URL = "https://data.cityofnewyork.us/resource/bnx9-e6tj.json"
_PARTY_URL      = "https://data.cityofnewyork.us/resource/636b-3b5g.json"
_LEGALS_URL     = "https://data.cityofnewyork.us/resource/2ydnx-akef.json"

# Document type groupings
_DEED_TYPES  = {"DEED", "DEEDP", "DEED,RP", "SPECDEED", "DEED (CO-OP)", "DEED, CORRECTIVE"}
_MTGE_TYPES  = {"MTGE", "AGMT", "LNAGMT", "ASSG OF LNAGMT", "MLTG", "CORR MTGE",
                "SPREAGMT", "SUBORDINATION AGMT"}
_FRCL_TYPES  = {"LIS PENDENS", "FORECLOSURE", "NOTICE OF DEFAULT", "FORECL JUDG",
                "COMMENCEMENT OF ACTION", "SUPREME COURT JUDGMENT"}
_UCC_TYPES   = {"UCC1", "UCC2", "UCC3", "UCC AMENDMENT", "UCC TERMINATION"}
_AIR_TYPES   = {"TDEVEL", "TRIGHT", "DEV RIGHTS", "AIR RIGHTS", "EASEMENT"}
_ASSG_TYPES  = {"ASSG", "ASSG OF MTGE", "ASSG OF LEASE", "ASSG OF AGMT"}
_LIEN_TYPES  = {"TAX LIEN", "MECHANICS LIEN", "LIEN", "NOTICE OF LIEN",
                "ENVIRONMENTAL RESTRICTION"}

_TIMEOUT  = 14
_MAX_DOCS = 300

_ACRIS_BASE_URL   = "https://a836-acris.nyc.gov/DS/DocumentSearch/DocumentDetail?doc_id="
_ACRIS_BBL_URL    = "https://a836-acris.nyc.gov/DS/DocumentSearch/BBL?borough_id={b}&block={blk}&lot={lt}"
_ACRIS_BLOCK_URL  = "https://a836-acris.nyc.gov/DS/DocumentSearch/BBL?borough_id={b}&block={blk}"


def _parse_bbl(bbl: str) -> Optional[tuple]:
    """
    Split 10-digit BBL into (borough, block_pad, lot_pad, block_int, lot_int).
    Accepts '1001670001', '1-00167-0001', '1 00167 0001', etc.
    Returns None if invalid.
    """
    clean = re.sub(r"\D", "", str(bbl))
    if len(clean) != 10:
        return None
    borough   = clean[0]
    block_pad = clean[1:6]
    lot_pad   = clean[6:10]
    block_int = block_pad.lstrip("0") or "0"
    lot_int   = lot_pad.lstrip("0") or "0"
    return borough, block_pad, lot_pad, block_int, lot_int


def _get(url: str, params: dict) -> tuple[list, bool]:
    """
    Fetch JSON list from a Socrata endpoint.

    Returns (rows, ok) — ok=False means the request itself failed
    (network error, timeout, non-2xx status), NOT that it legitimately
    returned zero rows. Callers must treat rows==[] and ok==False as
    "unknown" (the fetch may be incomplete), not "confirmed empty".
    """
    try:
        params.setdefault("$limit", _MAX_DOCS)
        r = requests.get(url, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        return (data if isinstance(data, list) else []), True
    except Exception as exc:
        log.warning("acris_fetcher request to %s failed: %s", url, exc)
        return [], False


def _fetch_parties(doc_id: str) -> list:
    """Fetch all parties for a single document_id. Best-effort: a failed
    party lookup degrades a document to missing buyer/lender names rather
    than invalidating the whole ACRIS result, so its ok flag is discarded
    here rather than propagated into fetch_acris()'s error field."""
    rows, _ok = _get(_PARTY_URL, {"document_id": doc_id, "$limit": 10})
    parties = []
    for r in rows:
        ptype = str(r.get("party_type", ""))
        if ptype == "1":
            role = "Grantor / Seller"
        elif ptype == "2":
            role = "Grantee / Buyer"
        elif ptype == "3":
            role = "Lender"
        else:
            role = f"Party {ptype}"
        name = r.get("name", "").strip().title()
        if name:
            parties.append({"role": role, "name": name})
    return parties


def _query_master(borough: str, block: str, lot: str,
                  order: str = "document_date DESC") -> tuple[list, bool]:
    """
    Query ACRIS Master via two-step Legals→Master lookup, then direct $where fallbacks.

    Socrata stores block/lot as zero-padded TEXT fields ("00167", "0001").
    Simple URL params (e.g. ?block=167) may coerce to integers and miss records.
    Using $where with quoted string literals forces string comparison.

    Returns (rows, any_error) — any_error is True if ANY underlying
    request along the way failed, even if a later step still found rows
    (a caller that got real data back may ignore any_error; a caller that
    ultimately found nothing should treat any_error as "unknown", not
    "confirmed empty").
    """
    block_pad = str(block).zfill(5)
    lot_pad   = str(lot).zfill(4)
    any_error = False

    # ── Step 1: Legals → document_ids (canonical BBL→doc mapping) ──────────
    leg_rows, ok = _get(_LEGALS_URL, {
        "$where": f"borough='{borough}' AND block='{block_pad}' AND lot='{lot_pad}'",
        "$select": "document_id",
        "$limit": 300,
    })
    any_error = any_error or not ok
    doc_ids = list({r["document_id"] for r in leg_rows if r.get("document_id")})
    if doc_ids:
        id_clause = ",".join(f"'{d}'" for d in doc_ids[:200])
        rows, ok = _get(_DOC_MASTER_URL, {
            "$where": f"document_id in ({id_clause})",
            "$order": order,
            "$limit": _MAX_DOCS,
        })
        any_error = any_error or not ok
        if rows:
            return rows, any_error

    # ── Step 2: Direct $where on Master with zero-padded strings ───────────
    rows, ok = _get(_DOC_MASTER_URL, {
        "$where": f"borough='{borough}' AND block='{block_pad}' AND lot='{lot_pad}'",
        "$order": order,
        "$limit": _MAX_DOCS,
    })
    any_error = any_error or not ok
    if rows:
        return rows, any_error

    # ── Step 3: Unpadded fallback ───────────────────────────────────────────
    block_int = str(block).lstrip("0") or "0"
    lot_int   = str(lot).lstrip("0") or "0"
    rows, ok = _get(_DOC_MASTER_URL, {
        "$where": f"borough='{borough}' AND block='{block_int}' AND lot='{lot_int}'",
        "$order": order,
        "$limit": _MAX_DOCS,
    })
    any_error = any_error or not ok
    return rows, any_error


def _build_doc(raw: dict, party_cache: dict) -> dict:
    """Normalize a raw ACRIS master row into a clean document dict."""
    doc_id   = raw.get("document_id", "")
    doc_type = raw.get("doc_type", "—").upper().strip()
    amount   = None
    try:
        amt_raw = raw.get("document_amt") or raw.get("good_through_date") or "0"
        amount  = float(str(amt_raw).replace(",", "")) or None
    except (ValueError, TypeError):
        amount = None

    return {
        "document_id": doc_id,
        "doc_type":    raw.get("doc_type", "—"),
        "date":        (raw.get("document_date") or raw.get("recorded_datetime") or "")[:10],
        "recorded":    (raw.get("recorded_datetime") or "")[:10],
        "amount":      amount,
        "parties":     party_cache.get(doc_id, []),
        "doc_url":     _ACRIS_BASE_URL + doc_id if doc_id else "",
        "good_through":(raw.get("good_through_date") or "")[:10],
        "doc_type_raw": doc_type,
    }


def _categorize_docs(documents: list) -> dict:
    """Split documents into category lists."""
    deeds, mortgages, foreclosures, ucc_list, air_list, assignments, liens = (
        [], [], [], [], [], [], []
    )
    for doc in documents:
        dt = doc.get("doc_type_raw", "")
        if dt in _DEED_TYPES or "DEED" in dt:
            deeds.append(doc)
        elif dt in _MTGE_TYPES or "MTGE" in dt or "MORTGAGE" in dt:
            mortgages.append(doc)
        elif dt in _FRCL_TYPES or "FORECL" in dt or "LIS PEN" in dt:
            foreclosures.append(doc)
        elif dt in _UCC_TYPES or dt.startswith("UCC"):
            ucc_list.append(doc)
        elif dt in _AIR_TYPES or "AIR" in dt or "DEVEL" in dt or "EASEMENT" in dt:
            air_list.append(doc)
        elif dt in _ASSG_TYPES or dt.startswith("ASSG"):
            assignments.append(doc)
        elif dt in _LIEN_TYPES or "LIEN" in dt:
            liens.append(doc)
    return {
        "deeds":        deeds,
        "mortgages":    mortgages,
        "foreclosures": foreclosures,
        "ucc":          ucc_list,
        "air_rights":   air_list,
        "assignments":  assignments,
        "liens":        liens,
    }


def _build_summary(cats: dict, documents: list) -> dict:
    """Build high-level summary callout dict from categorized documents."""
    deeds       = cats["deeds"]
    mortgages   = cats["mortgages"]
    foreclosures= cats["foreclosures"]
    ucc_list    = cats["ucc"]
    air_list    = cats["air_rights"]
    liens       = cats["liens"]

    latest_sale_price = None
    latest_sale_date  = None
    latest_buyer      = None
    if deeds:
        top = deeds[0]
        if top["amount"] and top["amount"] > 1_000:
            latest_sale_price = top["amount"]
        latest_sale_date = top["date"]
        buyers = [p["name"] for p in top["parties"] if "Buyer" in p["role"]]
        latest_buyer = buyers[0] if buyers else None

    active_mortgage_amt = None
    active_lender       = None
    if mortgages:
        top = mortgages[0]
        if top["amount"] and top["amount"] > 1_000:
            active_mortgage_amt = top["amount"]
        lenders = [p["name"] for p in top["parties"] if "Lender" in p["role"]]
        active_lender = lenders[0] if lenders else None

    return {
        "latest_sale_price":    latest_sale_price,
        "latest_sale_date":     latest_sale_date,
        "latest_buyer":         latest_buyer,
        "active_mortgage_amt":  active_mortgage_amt,
        "active_lender":        active_lender,
        "open_liens":           len(ucc_list) + len(liens),
        "foreclosure_count":    len(foreclosures),
        "has_air_rights":       len(air_list) > 0,
        "assignment_count":     len(cats["assignments"]),
        "total_docs":           len(documents),
    }


def _enrich_parties(raw_docs: list) -> dict:
    """Fetch parties for top key documents. Returns {doc_id: [party, ...]}."""
    key_docs = [
        d for d in raw_docs[:60]
        if d.get("doc_type", "").upper() in (
            _DEED_TYPES | _MTGE_TYPES | _AIR_TYPES | _FRCL_TYPES
        )
    ][:25]
    cache: dict = {}
    for d in key_docs:
        did = d.get("document_id", "")
        if did and did not in cache:
            cache[did] = _fetch_parties(did)
            time.sleep(0.08)
    return cache


def _attempt(borough: str, block: str, lot: str,
             acris_url: str, confidence: str) -> tuple[Optional[dict], bool]:
    """
    Try one specific (borough, block, lot) query.
    Returns (result_or_None, any_error) — result is populated if documents
    were found, else None; any_error reflects _query_master()'s fetch
    reliability regardless of whether documents were found.
    """
    raw_docs, any_error = _query_master(borough, block, lot)
    if not raw_docs:
        return None, any_error

    party_cache = _enrich_parties(raw_docs)
    documents   = [_build_doc(r, party_cache) for r in raw_docs]
    cats        = _categorize_docs(documents)
    summary     = _build_summary(cats, documents)

    return {
        "documents":    documents,
        "deeds":        cats["deeds"],
        "mortgages":    cats["mortgages"],
        "foreclosures": cats["foreclosures"],
        "ucc":          cats["ucc"],
        "air_rights":   cats["air_rights"],
        "assignments":  cats["assignments"],
        "liens":        cats["liens"],
        "summary":      summary,
        "acris_url":    acris_url,
        "confidence":   confidence,
        "match_method": f"{confidence} — BBL {borough}-{block}-{lot}",
        "error":        None,
    }, any_error


def fetch_acris(bbl: str) -> dict:
    """Fetch ACRIS document history for a BBL, then record the outcome in
    the sidebar Data Health panel. See _fetch_acris_impl() for the full
    fallback logic and return-shape documentation."""
    result = _fetch_acris_impl(bbl)
    record_source_status("ACRIS", ok=(not result.get("error")), detail=result.get("error") or "")
    return result


def _fetch_acris_impl(bbl: str) -> dict:
    """
    Fetch ACRIS document history for a BBL with multi-level fallback.

    Fallback order:
      1. Exact BBL match                     → confidence = "High"
      2. Condo building-level lot (7501)     → confidence = "Medium"
      3. Block-only (ignore lot)             → confidence = "Medium"
      4. Nearby lots (±1, ±2)               → confidence = "Low"

    Returns:
      {
        documents, deeds, mortgages, foreclosures, ucc, air_rights,
        assignments, liens,
        summary: {
          latest_sale_price, latest_sale_date, latest_buyer,
          active_mortgage_amt, active_lender,
          open_liens, foreclosure_count, has_air_rights,
          assignment_count, total_docs,
        },
        acris_url:    str,
        confidence:   "High" | "Medium" | "Low" | "None",
        match_method: str,   # description of which match succeeded
        error:        str | None,
      }
    """
    parsed = _parse_bbl(bbl)

    _empty = {
        "documents": [], "deeds": [], "mortgages": [],
        "foreclosures": [], "ucc": [], "air_rights": [],
        "assignments": [], "liens": [],
        "summary": {
            "latest_sale_price": None, "latest_sale_date": None,
            "latest_buyer": None, "active_mortgage_amt": None,
            "active_lender": None, "open_liens": 0,
            "foreclosure_count": 0, "has_air_rights": False,
            "assignment_count": 0, "total_docs": 0,
        },
        "acris_url":    "",
        "confidence":   "None",
        "match_method": "No results found",
        "error":        None,
    }

    if not parsed:
        return {**_empty, "error": f"Invalid BBL: {bbl}"}

    borough, block_pad, lot_pad, block_int, lot_int = parsed

    acris_url_exact = _ACRIS_BBL_URL.format(
        b=borough, blk=block_int, lt=lot_int
    )
    _empty["acris_url"] = acris_url_exact
    any_error = False

    # ── Attempt 1: Exact BBL ────────────────────────────────────────────────
    result, err = _attempt(borough, block_int, lot_int, acris_url_exact, "High")
    any_error = any_error or err
    if result:
        return result

    # ── Attempt 2: Condo building-level lot (7501) ──────────────────────────
    condo_lot = "7501"
    if lot_int != condo_lot:
        result, err = _attempt(borough, block_int, condo_lot,
                          _ACRIS_BBL_URL.format(b=borough, blk=block_int, lt=condo_lot),
                          "Medium")
        any_error = any_error or err
        if result:
            result["match_method"] = f"Medium — condo building lot {borough}-{block_int}-7501"
            return result

    # ── Attempt 3: Block-only (ignore lot) ─────────────────────────────────
    block_url = _ACRIS_BLOCK_URL.format(b=borough, blk=block_int)
    raw_block, ok = _get(_DOC_MASTER_URL, {
        "$where": f"borough='{borough}' AND block='{block_pad}'",
        "$order": "document_date DESC", "$limit": _MAX_DOCS,
    })
    any_error = any_error or not ok
    if raw_block:
        party_cache = _enrich_parties(raw_block)
        documents   = [_build_doc(r, party_cache) for r in raw_block]
        cats        = _categorize_docs(documents)
        summary     = _build_summary(cats, documents)
        return {
            "documents":    documents,
            "deeds":        cats["deeds"],
            "mortgages":    cats["mortgages"],
            "foreclosures": cats["foreclosures"],
            "ucc":          cats["ucc"],
            "air_rights":   cats["air_rights"],
            "assignments":  cats["assignments"],
            "liens":        cats["liens"],
            "summary":      summary,
            "acris_url":    block_url,
            "confidence":   "Medium",
            "match_method": f"Medium — block-level match {borough}-{block_int}",
            "error":        None,
        }

    # ── Attempt 4: Nearby lots (±1, ±2) ────────────────────────────────────
    try:
        base_lot = int(lot_int)
    except ValueError:
        return {**_empty, "error": "BBL parse error"}

    for delta in (1, -1, 2, -2):
        near_lot = str(max(1, base_lot + delta))
        result, err = _attempt(
            borough, block_int, near_lot,
            _ACRIS_BBL_URL.format(b=borough, blk=block_int, lt=near_lot),
            "Low",
        )
        any_error = any_error or err
        if result:
            result["match_method"] = (
                f"Low — nearby lot {borough}-{block_int}-{near_lot} "
                f"(subject lot {lot_int})"
            )
            return result

    if any_error:
        return {
            **_empty,
            "error": "One or more NYC Open Data (ACRIS) requests failed or timed out "
                     "— this result may be incomplete, not a confirmed clean record.",
            "match_method": "No documents found after all fallbacks (with fetch errors)",
        }
    return {**_empty, "error": None, "match_method": "No documents found after all fallbacks"}

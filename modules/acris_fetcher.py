"""
ACRIS Property Document Fetcher — NYC Open Data (no API key required).

Fetches mortgage, deed, UCC, and air rights document history for a
given BBL (Borough-Block-Lot) from the NYC ACRIS (Automated City Register
Information System) via NYC Open Data Socrata APIs.

Returns structured data including:
  - Chronological document history (deeds, mortgages, UCC, transfers)
  - Ownership history (parties to each deed)
  - Active mortgage summary (lender, amount)
  - Air rights / development rights transfers
  - Quick-summary callout dict for dashboard display
"""

from __future__ import annotations
import re
import time
import requests

_DOC_MASTER_URL = "https://data.cityofnewyork.us/resource/bnx9-e6tj.json"
_PARTY_URL      = "https://data.cityofnewyork.us/resource/636b-3b5g.json"
_LEGALS_URL     = "https://data.cityofnewyork.us/resource/2ydnx-akef.json"

# Document type groupings
_DEED_TYPES     = {"DEED", "DEEDP", "DEED,RP", "SPECDEED", "DEED (CO-OP)"}
_MTGE_TYPES     = {"MTGE", "AGMT", "LNAGMT", "ASSG OF LNAGMT", "MLTG", "CORR MTGE"}
_UCC_TYPES      = {"UCC1", "UCC2", "UCC3"}
_AIR_TYPES      = {"TDEVEL", "TRIGHT", "DEV RIGHTS", "AIR RIGHTS"}

_TIMEOUT = 12
_MAX_DOCS = 200  # cap to avoid huge payloads

_ACRIS_BASE_URL = "https://a836-acris.nyc.gov/DS/DocumentSearch/DocumentDetail?doc_id="


def _parse_bbl(bbl: str) -> tuple[str, str, str, str, str] | None:
    """Split 10-digit BBL into (borough, block_padded, lot_padded, block_int, lot_int)."""
    clean = re.sub(r"\D", "", str(bbl))
    if len(clean) != 10:
        return None
    borough    = clean[0]
    block_pad  = clean[1:6]          # zero-padded: "00167"
    lot_pad    = clean[6:10]         # zero-padded: "0001"
    block_int  = block_pad.lstrip("0") or "0"   # Socrata expects integer string
    lot_int    = lot_pad.lstrip("0") or "0"
    return borough, block_pad, lot_pad, block_int, lot_int


def _get(url: str, params: dict) -> list[dict]:
    """Fetch JSON list from Socrata endpoint, return [] on failure."""
    try:
        # Add $limit to avoid default 1000 row cap issues
        params.setdefault("$limit", _MAX_DOCS)
        r = requests.get(url, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json() if isinstance(r.json(), list) else []
    except Exception:
        return []


def _fetch_parties(doc_id: str) -> list[dict]:
    """Fetch all parties for a single document_id."""
    rows = _get(_PARTY_URL, {"document_id": doc_id, "$limit": 10})
    parties = []
    for r in rows:
        ptype = str(r.get("party_type", ""))
        role = "Grantor/Seller" if ptype == "1" else ("Grantee/Buyer" if ptype == "2" else "Lender" if ptype == "3" else f"Party {ptype}")
        name = r.get("name", "").strip().title()
        if name:
            parties.append({"role": role, "name": name})
    return parties


def fetch_acris(bbl: str) -> dict:
    """
    Fetch ACRIS document history for a BBL.

    Returns:
        {
          "documents":  list[dict],   # all docs, newest-first
          "deeds":      list[dict],   # deed transfers
          "mortgages":  list[dict],   # mortgage documents
          "ucc":        list[dict],   # UCC filings
          "air_rights": list[dict],   # development/air rights transfers
          "summary": {
            "latest_sale_price":   float | None,
            "latest_sale_date":    str | None,
            "latest_buyer":        str | None,
            "active_mortgage_amt": float | None,
            "active_lender":       str | None,
            "open_liens":          int,
            "has_air_rights":      bool,
            "total_docs":          int,
          },
          "acris_url": str,   # link to ACRIS search for this property
          "error":     str | None,
        }
    """
    parsed = _parse_bbl(bbl)
    if not parsed:
        return {"error": f"Invalid BBL: {bbl}", "documents": [], "deeds": [], "mortgages": [], "ucc": [], "air_rights": [], "summary": {}}

    borough, block_pad, lot_pad, block_int, lot_int = parsed

    # Build ACRIS search URL for the property (human-facing link)
    acris_url = (
        f"https://a836-acris.nyc.gov/DS/DocumentSearch/BBL?"
        f"borough_id={borough}&block={block_int}&lot={lot_int}"
    )

    # Fetch document master — try integer-style first (what ACRIS Socrata expects),
    # then fall back to zero-padded, then to full BBL $where clause.
    _empty = {"documents": [], "deeds": [], "mortgages": [], "ucc": [], "air_rights": [],
              "summary": {"total_docs": 0, "latest_sale_price": None, "latest_sale_date": None,
                          "latest_buyer": None, "active_mortgage_amt": None,
                          "active_lender": None, "open_liens": 0, "has_air_rights": False},
              "acris_url": acris_url, "error": None}

    raw_docs = _get(_DOC_MASTER_URL, {
        "borough": borough, "block": block_int, "lot": lot_int,
        "$order": "document_date DESC", "$limit": _MAX_DOCS,
    })
    if not raw_docs:
        # Fallback: zero-padded block/lot
        raw_docs = _get(_DOC_MASTER_URL, {
            "borough": borough, "block": block_pad, "lot": lot_pad,
            "$order": "document_date DESC", "$limit": _MAX_DOCS,
        })
    if not raw_docs:
        # Fallback: full 10-digit BBL via $where
        bbl_clean = re.sub(r"\D", "", str(bbl))
        raw_docs = _get(_DOC_MASTER_URL, {
            "$where": f"bbl='{bbl_clean}'",
            "$order": "document_date DESC", "$limit": _MAX_DOCS,
        })

    if not raw_docs:
        return {**_empty, "acris_url": acris_url}

    # Categorize and enrich documents
    documents, deeds, mortgages, ucc_list, air_list = [], [], [], [], []

    # Only fetch parties for top 20 most relevant docs to avoid too many requests
    key_docs = [d for d in raw_docs[:50] if d.get("doc_type","").upper() in
                (_DEED_TYPES | _MTGE_TYPES | _AIR_TYPES)][:20]
    party_cache: dict[str, list] = {}
    for doc in key_docs:
        did = doc.get("document_id", "")
        if did and did not in party_cache:
            party_cache[did] = _fetch_parties(did)
            time.sleep(0.1)

    for raw in raw_docs:
        doc_type = raw.get("doc_type", "").upper().strip()
        doc_id   = raw.get("document_id", "")
        amount   = None
        try:
            amount = float(raw.get("document_amt", 0) or 0)
        except (ValueError, TypeError):
            amount = None

        doc = {
            "document_id":   doc_id,
            "doc_type":      raw.get("doc_type", "—"),
            "date":          (raw.get("document_date") or raw.get("recorded_datetime") or "")[:10],
            "recorded":      (raw.get("recorded_datetime") or "")[:10],
            "amount":        amount,
            "parties":       party_cache.get(doc_id, []),
            "doc_url":       _ACRIS_BASE_URL + doc_id if doc_id else "",
            "good_through":  (raw.get("good_through_date") or "")[:10],
        }
        documents.append(doc)

        if doc_type in _DEED_TYPES:
            deeds.append(doc)
        elif doc_type in _MTGE_TYPES:
            mortgages.append(doc)
        elif doc_type in _UCC_TYPES:
            ucc_list.append(doc)
        elif doc_type in _AIR_TYPES or "AIR" in doc_type or "DEVEL" in doc_type:
            air_list.append(doc)

    # Build summary
    latest_sale_price = None
    latest_sale_date  = None
    latest_buyer      = None
    if deeds:
        top_deed = deeds[0]
        latest_sale_price = top_deed["amount"] if top_deed["amount"] and top_deed["amount"] > 1000 else None
        latest_sale_date  = top_deed["date"]
        buyers = [p["name"] for p in top_deed["parties"] if p["role"] == "Grantee/Buyer"]
        latest_buyer = buyers[0] if buyers else None

    active_mortgage_amt = None
    active_lender       = None
    if mortgages:
        top_mtge = mortgages[0]
        active_mortgage_amt = top_mtge["amount"] if top_mtge["amount"] and top_mtge["amount"] > 1000 else None
        lenders = [p["name"] for p in top_mtge["parties"] if p["role"] == "Lender"]
        active_lender = lenders[0] if lenders else None

    summary = {
        "latest_sale_price":   latest_sale_price,
        "latest_sale_date":    latest_sale_date,
        "latest_buyer":        latest_buyer,
        "active_mortgage_amt": active_mortgage_amt,
        "active_lender":       active_lender,
        "open_liens":          len(ucc_list),
        "has_air_rights":      len(air_list) > 0,
        "total_docs":          len(documents),
    }

    return {
        "documents":  documents,
        "deeds":      deeds,
        "mortgages":  mortgages,
        "ucc":        ucc_list,
        "air_rights": air_list,
        "summary":    summary,
        "acris_url":  acris_url,
        "error":      None,
    }

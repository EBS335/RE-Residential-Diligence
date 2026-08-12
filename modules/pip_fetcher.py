"""
NYC Property Information Portal — Full Property History Fetcher.

Aggregates DOB (Department of Buildings), HPD (Housing Preservation &
Development), and ECB (Environmental Control Board) records from NYC Open Data
for a given BBL or address.  Also constructs a direct link to the official
NYC Property Information Portal page for the property.

NYC Open Data endpoints used (no API key required):
  DOB Permits     — https://data.cityofnewyork.us/resource/ipu4-2q9a.json
  DOB Jobs        — https://data.cityofnewyork.us/resource/ic3t-wcy2.json
  DOB Complaints  — https://data.cityofnewyork.us/resource/eabe-havv.json
  DOB Violations  — https://data.cityofnewyork.us/resource/3h2n-5cm9.json
  HPD Buildings   — https://data.cityofnewyork.us/resource/kj4p-ruqc.json
  HPD Violations  — https://data.cityofnewyork.us/resource/wvxf-dwi5.json  (used by ecb_fetcher)

NYC Property Information Portal:
  https://propertyinformationportal.nyc.gov/parcels/detail/{bbl}
"""

from __future__ import annotations
import re
import requests

from modules.app_logging import get_logger

log = get_logger(__name__)

_TIMEOUT        = 14
_PIP_BASE       = "https://propertyinformationportal.nyc.gov"
_DOB_PERMITS    = "https://data.cityofnewyork.us/resource/ipu4-2q9a.json"
_DOB_JOBS       = "https://data.cityofnewyork.us/resource/ic3t-wcy2.json"
_DOB_COMPLAINTS = "https://data.cityofnewyork.us/resource/eabe-havv.json"
_DOB_VIOLATIONS = "https://data.cityofnewyork.us/resource/3h2n-5cm9.json"
_HPD_BUILDINGS  = "https://data.cityofnewyork.us/resource/kj4p-ruqc.json"
_HPD_VIOLATIONS = "https://data.cityofnewyork.us/resource/wvxf-dwi5.json"

_HEADERS = {"Accept": "application/json"}
_MAX     = 200


def _clean_bbl(bbl: str) -> str:
    """Normalise BBL to 10-digit zero-padded string."""
    digits = re.sub(r"\D", "", str(bbl))
    return digits.zfill(10) if digits else ""


def _bbl_parts(bbl10: str) -> tuple[str, str, str]:
    """Split 10-digit BBL into (borough_code, block_5, lot_4)."""
    if len(bbl10) < 10:
        return "", "", ""
    return bbl10[0], bbl10[1:6], bbl10[6:]


def _get(url: str, params: dict) -> list[dict]:
    """GET a Socrata endpoint, returning list of records or []."""
    try:
        r = requests.get(url, params=params, headers=_HEADERS, timeout=_TIMEOUT)
        if r.status_code == 200:
            return r.json() if isinstance(r.json(), list) else []
    except Exception as exc:
        # Individual sub-request failures (one of 6 DOB/HPD endpoints) are
        # frequent/expected — debug level, not warning, to avoid log spam.
        log.debug("pip_fetcher request to %s failed: %s", url, exc)
    return []


# DOB job-type codes → human labels
_JOB_TYPE = {
    "NB":  "New Building",
    "A1":  "Major Alteration",
    "A2":  "Minor Alteration",
    "A3":  "Minor Work",
    "DM":  "Demolition",
    "SG":  "Sign",
    "FO":  "Foundation",
    "EQ":  "Earthwork",
    "SD":  "Stand-Alone Sprinkler/Standpipe",
}

# DOB violation categories
_DOB_CAT = {
    "CONSTRUCTION": "Construction",
    "ELECTRICAL":   "Electrical",
    "PLUMBING":     "Plumbing",
    "ELEVATOR":     "Elevator",
    "SAFETY":       "Safety",
}

# Borough code to name mapping
_BOROUGH_NAME = {
    "1": "Manhattan",
    "2": "Bronx",
    "3": "Brooklyn",
    "4": "Queens",
    "5": "Staten Island",
}

def _extract_sales_from_acris(acris_dict: dict) -> list[dict]:
    """Extract sale transactions from ACRIS document list."""
    sales = []
    docs = acris_dict.get("documents", []) if acris_dict else []
    for d in docs:
        dt = str(d.get("doc_type", "")).upper()
        # Deeds typically represent sales
        if any(x in dt for x in ("DEED", "SPECDEED")):
            date = d.get("date", "")
            amt = d.get("amount")
            parties = d.get("parties", [])
            seller = buyer = ""
            for p in parties:
                role = p.get("role", "").upper()
                if "SELLER" in role or "GRANTOR" in role:
                    seller = p.get("name", "")
                elif "BUYER" in role or "GRANTEE" in role:
                    buyer = p.get("name", "")
            sales.append({
                "date": date, "amount": amt, "seller": seller, "buyer": buyer,
                "doc_type": d.get("doc_type"), "doc_url": d.get("doc_url"),
            })
    return sales


def _extract_mortgages_from_acris(acris_dict: dict) -> list[dict]:
    """Extract mortgage documents from ACRIS document list."""
    mortgages = []
    docs = acris_dict.get("documents", []) if acris_dict else []
    for d in docs:
        dt = str(d.get("doc_type", "")).upper()
        if any(x in dt for x in ("MTGE", "MORTGAGE", "LNAGMT")):
            date = d.get("date", "")
            amt = d.get("amount")
            parties = d.get("parties", [])
            lender = borrower = ""
            for p in parties:
                role = p.get("role", "").upper()
                if "LENDER" in role or "MORTGAGEE" in role:
                    lender = p.get("name", "")
                elif "BORROWER" in role or "MORTGAGOR" in role:
                    borrower = p.get("name", "")
            mortgages.append({
                "date": date, "amount": amt, "lender": lender, "borrower": borrower,
                "doc_type": d.get("doc_type"), "doc_url": d.get("doc_url"),
            })
    return mortgages


def _extract_liens_from_acris(acris_dict: dict) -> list[dict]:
    """Extract lien/UCC documents from ACRIS document list."""
    liens = []
    docs = acris_dict.get("documents", []) if acris_dict else []
    for d in docs:
        dt = str(d.get("doc_type", "")).upper()
        if any(x in dt for x in ("UCC", "LIEN", "JUDGMENT")):
            date = d.get("date", "")
            parties = d.get("parties", [])
            party_str = "; ".join(f"{p.get('role')}: {p.get('name')}" for p in parties[:2])
            liens.append({
                "date": date, "type": d.get("doc_type"), "parties": party_str,
                "doc_url": d.get("doc_url"),
            })
    return liens


def _fetch_dob_permits(block5: str, lot4: str, borough_name: str) -> list[dict]:
    """Fetch DOB Permit Issuances for block/lot."""
    rows = _get(_DOB_PERMITS, {
        "$where": f"block='{block5}' AND lot='{lot4}' AND borough='{borough_name.upper()}'",
        "$order": "issuance_date DESC",
        "$limit": _MAX,
    })
    permits = []
    for r in rows:
        permits.append({
            "job_number":    r.get("job__", ""),
            "job_type":      _JOB_TYPE.get(r.get("job_type", ""), r.get("job_type", "")),
            "permit_type":   r.get("permit_type", ""),
            "permit_status": r.get("permit_status", ""),
            "filing_date":   (r.get("filing_date") or "")[:10],
            "issuance_date": (r.get("issuance_date") or "")[:10],
            "expiration_date": (r.get("expiration_date") or "")[:10],
            "description":   r.get("job_description", ""),
            "owner":         r.get("owner_s_business_name", "") or r.get("owner_s_last_name", ""),
            "permittee":     r.get("permittee_s_business_name", "") or r.get("permittee_s_last_name", ""),
        })
    return permits


def _fetch_dob_jobs(block5: str, lot4: str, borough_code: str) -> list[dict]:
    """Fetch DOB Job Application Filings for block/lot."""
    rows = _get(_DOB_JOBS, {
        "$where": f"block='{block5}' AND lot='{lot4}' AND borough='{borough_code}'",
        "$order": "pre__filing_date DESC",
        "$limit": _MAX,
    })
    jobs = []
    for r in rows:
        jobs.append({
            "job_number":    r.get("job__", ""),
            "job_type":      _JOB_TYPE.get(r.get("job_type", ""), r.get("job_type", "")),
            "job_status":    r.get("job_status_descrp", r.get("job_status", "")),
            "filing_date":   (r.get("pre__filing_date") or "")[:10],
            "approval_date": (r.get("approval_date") or "")[:10],
            "description":   r.get("job_description", ""),
            "floors":        r.get("stories", ""),
            "existing_sqft": r.get("existing_zoning_sqft", ""),
            "proposed_sqft": r.get("proposed_zoning_sqft", ""),
            "owner":         r.get("owner_s_business_name", "") or r.get("owner_s_last_name", ""),
        })
    return jobs


def _fetch_dob_complaints(block5: str, lot4: str, boro_code: str) -> list[dict]:
    """Fetch DOB Complaints for block/lot."""
    rows = _get(_DOB_COMPLAINTS, {
        "$where": f"block='{block5}' AND lot='{lot4}' AND boro='{boro_code}'",
        "$order": "date_entered DESC",
        "$limit": 100,
    })
    complaints = []
    for r in rows:
        complaints.append({
            "complaint_number": r.get("complaint_number", ""),
            "status":           r.get("status", ""),
            "date":             (r.get("date_entered") or "")[:10],
            "category":         r.get("complaint_category", ""),
            "description":      r.get("descriptor", ""),
            "unit":             r.get("unit", ""),
            "disposition":      r.get("disposition_description", "") or r.get("status", ""),
        })
    return complaints


def _fetch_dob_violations(block5: str, lot4: str, boro_code: str) -> list[dict]:
    """Fetch DOB Violations for block/lot."""
    rows = _get(_DOB_VIOLATIONS, {
        "$where": f"block='{block5}' AND lot='{lot4}' AND boro='{boro_code}'",
        "$order": "issue_date DESC",
        "$limit": 100,
    })
    violations = []
    for r in rows:
        violations.append({
            "violation_number": r.get("isn_dob_bis_viol", ""),
            "category":         r.get("violation_category", ""),
            "description":      r.get("description", "") or r.get("violation_type", ""),
            "issue_date":       (r.get("issue_date") or "")[:10],
            "disposition_date": (r.get("disposition_date") or "")[:10],
            "status":           "Closed" if r.get("disposition_date") else "Open",
            "ecb_number":       r.get("ecb_number", ""),
        })
    return violations


def _fetch_hpd_building(block5: str, lot4: str, boro_name: str) -> dict:
    """Fetch HPD Building registration record."""
    rows = _get(_HPD_BUILDINGS, {
        "$where": f"block='{block5}' AND lot='{lot4}' AND boroid='{boro_name.title()}'",
        "$limit": 5,
    })
    if not rows:
        return {}
    r = rows[0]
    return {
        "building_id":       r.get("buildingid", ""),
        "registration_id":   r.get("registrationid", ""),
        "lifecycle_stage":   r.get("lifecyclestage", ""),
        "dwelling_units":    r.get("dwellingunits", ""),
        "community_board":   r.get("communityboard", ""),
        "management_program": r.get("managementprogram", ""),
        "dob_class":         r.get("dobbuildingunitscount", ""),
        "address":           f"{r.get('housenumber','')} {r.get('streetname','')}".strip(),
        "zip":               r.get("zip", ""),
        "status":            r.get("registrationcontacttype", ""),
    }


def fetch_property_history(
    bbl: str,
    borough_name: str = "",
    address: str = "",
) -> dict:
    """
    Fetch full property history from NYC Open Data for the given BBL.

    Args:
        bbl:          10-digit BBL string (or with dashes/spaces).
        borough_name: Borough name (Manhattan/Brooklyn/Queens/Bronx/Staten Island).
        address:      Street address (for display only).

    Returns dict:
        pip_url          — direct link to NYC Property Information Portal
        permits          — list of DOB permit issuances
        jobs             — list of DOB job application filings
        complaints       — list of DOB complaints
        dob_violations   — list of DOB violations
        hpd_building     — HPD building registration record
        summary          — high-level counts dict
        error            — str | None
    """
    bbl10 = _clean_bbl(bbl)
    if not bbl10 or len(bbl10) < 10:
        return {"error": "Invalid BBL", "pip_url": "", "permits": [],
                "jobs": [], "complaints": [], "dob_violations": [], "hpd_building": {}, "summary": {}}

    boro_code, block5, lot4 = _bbl_parts(bbl10)

    if not borough_name:
        borough_name = _BOROUGH_NAME.get(boro_code, "Manhattan")

    boro_name_title = borough_name.title()
    pip_url = f"{_PIP_BASE}/parcels/detail/{bbl10}"

    try:
        permits       = _fetch_dob_permits(block5, lot4, boro_name_title)
        jobs          = _fetch_dob_jobs(block5, lot4, boro_code)
        complaints    = _fetch_dob_complaints(block5, lot4, boro_code)
        dob_viol      = _fetch_dob_violations(block5, lot4, boro_code)
        hpd_bld       = _fetch_hpd_building(block5, lot4, boro_name_title)

        open_complaints = sum(1 for c in complaints if c.get("status", "").upper() not in ("CLOSED", "RESOLVE", "RESOLVED", "INACTIVE"))
        open_dob_viol   = sum(1 for v in dob_viol if v.get("status") == "Open")
        nb_jobs         = sum(1 for j in jobs if "New Building" in j.get("job_type", ""))
        alteration_jobs = sum(1 for j in jobs if "Alteration" in j.get("job_type", ""))
        active_permits  = sum(1 for p in permits if p.get("permit_status", "").upper() in ("ISSUED", "RENEWED"))

        return {
            "pip_url":        pip_url,
            "permits":        permits,
            "jobs":           jobs,
            "complaints":     complaints,
            "dob_violations": dob_viol,
            "hpd_building":   hpd_bld,
            "summary": {
                "total_permits":      len(permits),
                "active_permits":     active_permits,
                "total_jobs":         len(jobs),
                "new_building_jobs":  nb_jobs,
                "alteration_jobs":    alteration_jobs,
                "total_complaints":   len(complaints),
                "open_complaints":    open_complaints,
                "total_dob_viol":     len(dob_viol),
                "open_dob_viol":      open_dob_viol,
                "dwelling_units":     hpd_bld.get("dwelling_units", ""),
            },
            "error": None,
        }
    except Exception as exc:
        log.warning("fetch_property_history failed for BBL %s: %s", bbl10, exc)
        return {
            "pip_url":        pip_url,
            "permits":        [],
            "jobs":           [],
            "complaints":     [],
            "dob_violations": [],
            "hpd_building":   {},
            "summary":        {},
            "error":          str(exc),
        }

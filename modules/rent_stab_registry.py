"""
NYC Rent-Stabilized Buildings Registry — ground-truth lookup against the
NYC Rent Guidelines Board's building list, bundled locally as
reference_data/nyc_rent_stabilized_buildings.xlsx (~49k rows, all five
boroughs).

Important limitation, stated plainly because it affects how callers should
label results: this is a *containment* list — it names buildings the RGB
has identified as containing AT LEAST ONE stabilized unit. It is NOT proof
a specific apartment is stabilized, and a building's ABSENCE from the list
is NOT proof it has no stabilized units (list coverage/updates lag real
conditions). Treat a "confirmed" match as strong positive evidence and
"not_found" as merely "not on this particular list" — never present it as
"confirmed not stabilized."

Two match strategies, tried in order:
  1. Exact (borough, block, lot) key — covers ~79% of source rows, which
     already carry BLOCK/LOT columns. Robust, O(1), no fuzzy logic.
  2. Normalized-address fallback — for the remaining rows (mostly
     multi-building "garden complex" listings), normalizes both the query
     address and the source STREET/BUILDING_NO columns (street-suffix
     expansion, directional expansion, and spelled-out-number <-> digit
     normalization for both street names and building numbers — e.g. "1"
     <-> "One", "First Avenue" <-> "1st Avenue") and matches on
     (borough, normalized_street, building_no-in-range). Range building
     numbers in the source data ("303 TO 309") are matched by containment.
     Hyphenated Queens/Staten-Island-style numbers ("87-15") are matched
     as opaque normalized strings, not true numeric ranges — the RGB
     dataset's own range syntax for those ("87-15 TO 87-45") isn't a
     simple numeric interval, and building that arithmetic is out of
     scope here.

No Streamlit dependency (matches this codebase's convention of keeping
data/business-logic modules framework-agnostic) — the module-level
registry is a lazy singleton built on first use and reused for the rest
of the process; callers needing Streamlit-level caching can wrap
check_rent_stabilized() themselves.
"""

from __future__ import annotations
import os
import re

_XLSX_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "reference_data", "nyc_rent_stabilized_buildings.xlsx",
)
_SHEET_NAME = "All"

# Spreadsheet's BOROUGH text -> the standard 1-5 NYC BBL borough digit
# (Manhattan=1, Bronx=2, Brooklyn=3, Queens=4, Staten Island=5 — the same
# digit modules/property_search.py derives from bbl[0]). Deliberately NOT
# property_search.BOROUGH_CODES, which holds the unrelated 2-letter PLUTO
# filter code (MN/BX/BK/QN/SI).
_BOROUGH_TO_CODE = {
    "Manhattan": "1", "Bronx": "2", "Brooklyn": "3",
    "Queens": "4", "Staten Island": "5",
}

_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_ORDINAL_ONES = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
    "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11,
    "twelfth": 12, "thirteenth": 13, "fourteenth": 14, "fifteenth": 15,
    "sixteenth": 16, "seventeenth": 17, "eighteenth": 18, "nineteenth": 19,
}
_ORDINAL_TENS = {
    "twentieth": 20, "thirtieth": 30, "fortieth": 40, "fiftieth": 50,
    "sixtieth": 60, "seventieth": 70, "eightieth": 80, "ninetieth": 90,
}

_STREET_SUFFIXES = {
    "st": "street", "street": "street",
    "ave": "avenue", "av": "avenue", "avenue": "avenue",
    "blvd": "boulevard", "boulevard": "boulevard",
    "pl": "place", "place": "place",
    "rd": "road", "road": "road",
    "dr": "drive", "drive": "drive",
    "ln": "lane", "lane": "lane",
    "ct": "court", "court": "court",
    "pkwy": "parkway", "parkway": "parkway",
    "sq": "square", "square": "square",
    "ter": "terrace", "terrace": "terrace",
    "cir": "circle", "circle": "circle",
    "expy": "expressway", "expressway": "expressway",
    "hwy": "highway", "highway": "highway",
    "plz": "plaza", "plaza": "plaza",
}
_DIRECTIONALS = {
    "n": "north", "north": "north",
    "s": "south", "south": "south",
    "e": "east", "east": "east",
    "w": "west", "west": "west",
}


def _word_to_number(word: str) -> int | None:
    """'twenty-one'/'twenty one' -> 21, 'seven' -> 7. None if not a number word."""
    w = word.lower().strip()
    if w in _ONES:
        return _ONES[w]
    if w in _TENS:
        return _TENS[w]
    parts = re.split(r"[-\s]+", w)
    if len(parts) == 2 and parts[0] in _TENS and parts[1] in _ONES:
        return _TENS[parts[0]] + _ONES[parts[1]]
    return None


def _ordinal_word_to_digit_str(word: str) -> str | None:
    """'first' -> '1st', 'twenty-first' -> '21st'. None if not an ordinal word."""
    w = word.lower().strip()
    n = None
    if w in _ORDINAL_ONES:
        n = _ORDINAL_ONES[w]
    elif w in _ORDINAL_TENS:
        n = _ORDINAL_TENS[w]
    else:
        parts = re.split(r"[-\s]+", w)
        if len(parts) == 2 and parts[0] in _TENS and parts[1] in _ORDINAL_ONES:
            n = _TENS[parts[0]] + _ORDINAL_ONES[parts[1]]
    if n is None:
        return None
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def normalize_street(street: str) -> str:
    """Canonicalize a street name for matching: lowercase, strip punctuation,
    expand suffix/directional abbreviations, normalize number words to
    digit-ordinals. Never raises."""
    if not street:
        return ""
    s = re.sub(r"[.,]", "", str(street).strip().lower())
    if not s:
        return ""
    tokens = s.split()
    out = []
    for tok in tokens:
        ord_digit = _ordinal_word_to_digit_str(tok)
        if ord_digit:
            out.append(ord_digit)
            continue
        if tok in _DIRECTIONALS:
            out.append(_DIRECTIONALS[tok])
            continue
        if tok in _STREET_SUFFIXES:
            out.append(_STREET_SUFFIXES[tok])
            continue
        out.append(tok)
    return " ".join(out)


def _parse_building_no_range(raw) -> tuple[int, int] | None:
    """Numeric (low, high) inclusive range for a building-number cell.
    Handles plain numbers and 'X TO Y' ranges. Returns None for hyphenated
    (Queens/SI-style) or otherwise non-numeric values — those fall back to
    opaque string matching in _address_key()."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        n = int(raw)
        return (n, n)
    s = str(raw).strip()
    if not s:
        return None
    m = re.match(r"^(\d+)\s*TO\s*(\d+)$", s, re.IGNORECASE)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    if s.isdigit():
        n = int(s)
        return (n, n)
    return None


_LEADING_TOKEN_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9\-]*)\s+(.*)$")


def split_address(address: str) -> tuple[str, str]:
    """'123 Main St' -> ('123', 'Main St'). 'One Main St' -> ('One', 'Main St').
    Returns ('', address) if no leading token can be split off. Never raises."""
    address = (address or "").strip()
    if not address:
        return "", ""
    m = _LEADING_TOKEN_RE.match(address)
    if not m:
        return "", address
    return m.group(1), m.group(2)


def _building_no_to_int(raw: str) -> int | None:
    """'123' -> 123, 'One' -> 1, '87-15' -> None (opaque, not numeric)."""
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)
    n = _word_to_number(raw)
    return n


class _Registry:
    """Lazily-built in-memory index. One instance is module-level-cached
    (see get_registry())."""

    def __init__(self):
        # Exact BBL index: (borough_code, block, lot) -> row dict
        self.bbl_index: dict[tuple[str, int, int], dict] = {}
        # Address fallback index: (borough, normalized_street) -> list of
        # (building_no_range | None, raw_building_no_str, row dict)
        self.address_index: dict[tuple[str, str], list] = {}
        self.loaded = False
        self.load_error: str | None = None

    def load(self, path: str = _XLSX_PATH) -> None:
        try:
            import openpyxl
        except ImportError as exc:
            self.load_error = f"openpyxl not available: {exc}"
            self.loaded = True
            return
        try:
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            ws = wb[_SHEET_NAME]
            for row in ws.iter_rows(min_row=2, values_only=True):
                if not row or len(row) < 13:
                    continue
                building_no, street, borough, zipc, block, lot, county, city, s1, s2, s3, lat, lon = row[:13]
                borough_code = _BOROUGH_TO_CODE.get(str(borough or "").strip())
                notes = [n for n in (s1, s2, s3) if n]
                record = {
                    "building_no": building_no,
                    "street": street,
                    "borough": borough,
                    "zip": zipc,
                    "block": block,
                    "lot": lot,
                    "notes": notes,
                    "latitude": lat,
                    "longitude": lon,
                }
                has_bbl = (
                    borough_code is not None
                    and block is not None
                    and lot is not None
                )
                if has_bbl:
                    try:
                        key = (borough_code, int(block), int(lot))
                        self.bbl_index[key] = record
                    except (TypeError, ValueError):
                        has_bbl = False
                if not has_bbl and borough_code is not None and street:
                    norm_street = normalize_street(street)
                    if norm_street:
                        bno_range = _parse_building_no_range(building_no)
                        bno_str = str(building_no).strip().lower() if building_no is not None else ""
                        idx_key = (borough_code, norm_street)
                        self.address_index.setdefault(idx_key, []).append((bno_range, bno_str, record))
        except Exception as exc:
            self.load_error = str(exc)
        finally:
            self.loaded = True

    def lookup_bbl(self, borough_code: str, block, lot) -> dict | None:
        try:
            key = (str(borough_code), int(block), int(lot))
        except (TypeError, ValueError):
            return None
        return self.bbl_index.get(key)

    def lookup_address(self, borough_code: str, address: str) -> dict | None:
        building_no_raw, street = split_address(address)
        norm_street = normalize_street(street)
        if not norm_street:
            return None
        candidates = self.address_index.get((str(borough_code), norm_street))
        if not candidates:
            return None
        query_no = _building_no_to_int(building_no_raw)
        query_no_str = building_no_raw.strip().lower()
        for bno_range, bno_str, record in candidates:
            if query_no is not None and bno_range is not None:
                if bno_range[0] <= query_no <= bno_range[1]:
                    return record
            elif bno_str and query_no_str and bno_str == query_no_str:
                return record
        return None


_registry: _Registry | None = None


def get_registry() -> _Registry:
    """Module-level lazy singleton — built once per process, reused after."""
    global _registry
    if _registry is None:
        _registry = _Registry()
        _registry.load()
    return _registry


def check_rent_stabilized(borough_code: str, block, lot, address: str) -> dict:
    """
    Look up a property against the bundled NYC RGB rent-stabilized
    buildings list.

    Returns (always this shape, never raises):
        {
          "status": "confirmed" | "not_found" | "unavailable",
          "match_type": "bbl" | "address" | None,
          "notes": list[str],       # e.g. ["421-A (1-15)", "J-51"]
          "error": str | None,
        }

    "confirmed" means the property matched a building on the list — strong
    positive evidence of at least one stabilized unit. "not_found" means no
    match was found on THIS list; per the module docstring, that is not
    proof the building has no stabilized units.
    """
    base = {"status": "not_found", "match_type": None, "notes": [], "error": None}
    try:
        reg = get_registry()
        if reg.load_error:
            return {**base, "status": "unavailable", "error": reg.load_error}

        record = reg.lookup_bbl(borough_code, block, lot)
        if record:
            return {**base, "status": "confirmed", "match_type": "bbl", "notes": record["notes"]}

        record = reg.lookup_address(borough_code, address)
        if record:
            return {**base, "status": "confirmed", "match_type": "address", "notes": record["notes"]}

        return base
    except Exception as exc:
        return {**base, "status": "unavailable", "error": str(exc)}

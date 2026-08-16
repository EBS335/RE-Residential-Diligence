"""
Consultant-Proposal PDF Parser — text extraction, fee estimation, scope-
keyword matrix, for comparing multiple uploaded consultant proposal PDFs.

Nothing in this app parses PDFs today — modules/report_exporter.py's
reportlab usage is generation-only, in the opposite direction (bytes
out, not bytes in). This module follows report_exporter.py's exact
optional-dependency convention (try/except ImportError with a clear
pip-install hint) for its own new dependency, pdfplumber.

Every function takes/returns plain bytes/str/dict — no Streamlit,
no UploadedFile references — so this module is usable and testable
completely independent of the UI layer that calls it (app.py's
st.file_uploader handles converting UploadedFile -> bytes before
calling in).

Pure/offline once given bytes — no network call. Never raises; a
corrupt or scanned (image-only, no extractable text) PDF is a valid,
clearly-labeled result (empty text), not an exception.
"""

from __future__ import annotations

import re

# Category -> keyword list for the scope-comparison matrix. Illustrative
# NYC development-diligence consultant categories — extend freely.
SCOPE_KEYWORD_CATEGORIES: dict[str, list[str]] = {
    "Structural Survey": ["structural survey", "structural engineer", "structural assessment", "structural inspection"],
    "Phase I ESA": ["phase i esa", "phase i environmental", "environmental site assessment"],
    "Zoning Analysis": ["zoning analysis", "zoning compliance", "zoning opinion", "zoning letter"],
    "Title Review": ["title review", "title report", "title search", "title insurance"],
    "Land/ALTA Survey": ["alta survey", "boundary survey", "topographic survey", "land survey"],
    "Geotechnical": ["geotechnical", "soil boring", "subsurface investigation"],
}

_FEE_KEYWORDS = ("total fee", "not to exceed", "lump sum", "professional fee", "fixed fee", "total cost")
_DOLLAR_RE = re.compile(r"\$\s?([\d,]+(?:\.\d{2})?)")


def extract_proposal_text(pdf_bytes: bytes) -> dict:
    """
    Extract all text from a PDF's pages.

    Returns (always this shape, never raises):
        {"text": str, "page_count": int, "error": str | None}
    A scanned/image-only PDF (no extractable text) returns text="" with
    error=None — that's a valid, expected outcome, not a failure.
    """
    try:
        import pdfplumber
    except ImportError as exc:
        raise ImportError("Install `pdfplumber` to enable proposal parsing: pip install pdfplumber") from exc

    base = {"text": "", "page_count": 0, "error": None}
    try:
        import io
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages_text = [p.extract_text() or "" for p in pdf.pages]
            return {**base, "text": "\n".join(pages_text), "page_count": len(pdf.pages)}
    except Exception as exc:
        return {**base, "error": str(exc)}


def extract_fee_estimate(text: str) -> float | None:
    """
    Best-effort regex extraction of a total-fee dollar figure, by looking
    near fee-indicating keywords first, falling back to the largest
    dollar figure in the document. Never raises; returns None if no
    dollar figure is found at all.
    """
    if not text:
        return None
    try:
        lower = text.lower()
        candidates: list[float] = []
        for keyword in _FEE_KEYWORDS:
            idx = lower.find(keyword)
            if idx == -1:
                continue
            window = text[idx: idx + 200]
            for m in _DOLLAR_RE.finditer(window):
                try:
                    candidates.append(float(m.group(1).replace(",", "")))
                except ValueError:
                    continue
        if candidates:
            return max(candidates)

        # Fallback: largest dollar figure anywhere in the document.
        all_amounts = [float(m.group(1).replace(",", "")) for m in _DOLLAR_RE.finditer(text)]
        return max(all_amounts) if all_amounts else None
    except Exception:
        return None


def score_scope_keywords(text: str, categories: dict[str, list[str]] | None = None) -> dict[str, int]:
    """
    Case-insensitive substring count per scope category. Never raises;
    returns a dict with every category present (0 if no keywords matched)
    so callers can build a comparison matrix without missing-key checks.
    """
    categories = categories if categories is not None else SCOPE_KEYWORD_CATEGORIES
    try:
        lower = (text or "").lower()
        return {
            category: sum(lower.count(kw) for kw in keywords)
            for category, keywords in categories.items()
        }
    except Exception:
        return {category: 0 for category in categories}

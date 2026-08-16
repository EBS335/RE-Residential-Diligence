"""
Distress Scorer — weighted 0-100 composite distress score.

Combines the distress-relevant signals already fetched elsewhere in the
app (ACRIS foreclosures/liens via modules.ownership_research, DOB
violations/complaints via modules.pip_fetcher, HPD violations, OATH/ECB
hearings via modules.oath_fetcher, and Tax Lien Sale List status via
modules.tax_lien_fetcher) into ONE score with user-configurable component
weights — replacing the app's previous three separate, overlapping,
non-unified distress computations (modules.ecb_fetcher's 3-tier HPD-only
signal, modules.ownership_research.classify_distress()'s small integer
score, and deal_scorer.compute_deal_score()'s own 0-8/17/25-point
distress bucket) with a single canonical number.

Pure function, no network call — same house pattern as
modules/deal_scorer.py and modules/abatement_estimator.py: every input is
a pre-computed value or already-fetched signal dict from other modules,
fixed-shape dict return, never raises.

The older signals (ecb_fetcher's 3-tier level, classify_distress()'s
small integer score) are NOT removed — they still feed other call sites
unchanged. This is a new, additional canonical score, not a breaking
replacement.
"""

from __future__ import annotations

DEFAULT_WEIGHTS: dict[str, float] = {
    "acris":     0.30,   # foreclosures / lis pendens / open liens
    "dob":       0.25,   # DOB violations + complaints
    "hpd":       0.20,   # HPD violations
    "oath":      0.15,   # OATH/ECB hearings with an open balance due
    "tax_lien":  0.10,   # on the current DOF Tax Lien Sale List
}

_TIER_THRESHOLDS = [
    (70, "Severe"),
    (40, "Elevated"),
    (15, "Moderate"),
    (0,  "Minimal"),
]


def _tier_for(score: int) -> str:
    for threshold, label in _TIER_THRESHOLDS:
        if score >= threshold:
            return label
    return "Minimal"


def _normalize_weights(weights: dict[str, float] | None) -> dict[str, float]:
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    total = sum(w.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {k: v / total for k, v in w.items()}


def compute_composite_distress_score(
    acris_summary: dict | None = None,
    dob_open_violations: int = 0,
    dob_open_complaints: int = 0,
    hpd_open_violations: int = 0,
    oath_data: dict | None = None,
    tax_lien_data: dict | None = None,
    weights: dict[str, float] | None = None,
) -> dict:
    """
    Compute a weighted 0-100 distress score from already-fetched signals.

    Args:
        acris_summary: modules.acris_fetcher.fetch_acris()'s "summary" dict
            (reads foreclosure_count / open_liens if present).
        dob_open_violations, dob_open_complaints: counts from
            modules.pip_fetcher.
        hpd_open_violations: count of open HPD violations (from an
            HPD-violations-count fetch — NOT the same as HPD *building
            registration* data, which pip_fetcher.py's fetch_property_history
            pulls today; the caller is responsible for a real violation
            count if this component should be meaningful).
        oath_data: modules.oath_fetcher.fetch_oath_hearings()'s return dict
            (reads open_balance_count / verified).
        tax_lien_data: modules.tax_lien_fetcher.fetch_tax_lien_status()'s
            return dict (reads on_lien_list / verified).
        weights: optional override for DEFAULT_WEIGHTS component shares
            (e.g. from a sidebar slider) — normalized to sum to 1.0
            regardless of what's passed in.

    Returns (always this shape, never raises):
        {
          "score": int (0-100),
          "tier": "Minimal" | "Moderate" | "Elevated" | "Severe",
          "breakdown": {component: {"score": int, "max": int, "weight": float, "reasoning": str}},
          "components_with_data": list[str],   # which components had real signal vs. defaulted to 0
        }
    """
    try:
        w = _normalize_weights(weights)
        acris_summary = acris_summary or {}
        oath_data = oath_data or {}
        tax_lien_data = tax_lien_data or {}

        components_with_data: list[str] = []
        breakdown: dict[str, dict] = {}

        # ── ACRIS: foreclosures / lis pendens / open liens ──────────────────
        forecl = int(acris_summary.get("foreclosure_count", 0) or 0)
        liens  = int(acris_summary.get("open_liens", 0) or 0)
        if acris_summary:
            components_with_data.append("acris")
        acris_raw = min(100, forecl * 50 + liens * 20)
        breakdown["acris"] = {
            "score": round(acris_raw * w["acris"]), "max": round(100 * w["acris"]),
            "weight": w["acris"],
            "reasoning": f"{forecl} foreclosure/lis pendens filing(s), {liens} open lien(s)",
        }

        # ── DOB: open violations + complaints ────────────────────────────────
        dob_raw = min(100, dob_open_violations * 10 + dob_open_complaints * 5)
        if dob_open_violations or dob_open_complaints:
            components_with_data.append("dob")
        breakdown["dob"] = {
            "score": round(dob_raw * w["dob"]), "max": round(100 * w["dob"]),
            "weight": w["dob"],
            "reasoning": f"{dob_open_violations} open DOB violation(s), {dob_open_complaints} open complaint(s)",
        }

        # ── HPD: open violations ─────────────────────────────────────────────
        hpd_raw = min(100, hpd_open_violations * 8)
        if hpd_open_violations:
            components_with_data.append("hpd")
        breakdown["hpd"] = {
            "score": round(hpd_raw * w["hpd"]), "max": round(100 * w["hpd"]),
            "weight": w["hpd"],
            "reasoning": f"{hpd_open_violations} open HPD violation(s)",
        }

        # ── OATH/ECB: hearings with an open balance ──────────────────────────
        oath_open = int(oath_data.get("open_balance_count", 0) or 0)
        oath_raw = min(100, oath_open * 25)
        if oath_data.get("verified"):
            components_with_data.append("oath")
        breakdown["oath"] = {
            "score": round(oath_raw * w["oath"]), "max": round(100 * w["oath"]),
            "weight": w["oath"],
            "reasoning": f"{oath_open} OATH/ECB hearing(s) with an open balance due",
        }

        # ── Tax Lien Sale List ────────────────────────────────────────────────
        on_lien_list = bool(tax_lien_data.get("on_lien_list"))
        tax_lien_raw = 100 if on_lien_list else 0
        if tax_lien_data.get("verified"):
            components_with_data.append("tax_lien")
        breakdown["tax_lien"] = {
            "score": round(tax_lien_raw * w["tax_lien"]), "max": round(100 * w["tax_lien"]),
            "weight": w["tax_lien"],
            "reasoning": "On the current DOF Tax Lien Sale List" if on_lien_list
                         else "Not on the current DOF Tax Lien Sale List (or unconfirmed)",
        }

        total = sum(c["score"] for c in breakdown.values())
        total = max(0, min(100, int(round(total))))

        return {
            "score": total,
            "tier": _tier_for(total),
            "breakdown": breakdown,
            "components_with_data": components_with_data,
        }
    except Exception:
        return {
            "score": 0, "tier": "Minimal", "breakdown": {}, "components_with_data": [],
        }

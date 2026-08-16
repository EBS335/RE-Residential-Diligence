"""
Composite Risk Scorecard — Physical / Financial / Regulatory, 0-100 each.

Consolidates signals already computed/fetched elsewhere in the app into
three explicit buckets, replacing the previously ad-hoc "Property-Specific
Risk Signals" flag list (app.py's Investment Risk Analysis section) with a
numerically scored, bucketed scorecard plus an explicit "needs manual
review" flag — while leaving modules/risk_matrix.py's static macro/micro
risk tables in place as complementary qualitative context (not replaced).

  Physical:   DOB open violations/complaints, FEMA flood zone,
              structural-vintage risk (modules.structural_risk)
  Financial:  ACRIS foreclosures/liens, composite distress score
              (modules.distress_scorer), tax-exemption-expiration
              uncertainty
  Regulatory: rent stabilization, landmark/historic-district status

Pure function, no network call — every input is an already-fetched signal
dict or pre-computed value, same house style as modules/deal_scorer.py.
Fixed-shape dict return, never raises.
"""

from __future__ import annotations

_TIER_THRESHOLDS = [(70, "High"), (40, "Moderate"), (0, "Low")]


def _tier_for(score: int) -> str:
    for threshold, label in _TIER_THRESHOLDS:
        if score >= threshold:
            return label
    return "Low"


def compute_composite_risk_scorecard(
    dob_open_violations: int = 0,
    dob_open_complaints: int = 0,
    flood_data: dict | None = None,
    structural_risk_result: dict | None = None,
    acris_summary: dict | None = None,
    distress_score_result: dict | None = None,
    tax_exempt: bool = False,
    rent_stab_likely: bool = False,
    is_landmark: bool = False,
    is_historic_district: bool = False,
    data_gaps: list[str] | None = None,
) -> dict:
    """
    Compute the three-bucket composite risk scorecard.

    Args:
        dob_open_violations, dob_open_complaints: from modules.pip_fetcher's
            fetch_property_history()'s summary dict.
        flood_data: modules.environmental_fetcher.fetch_flood_zone()'s
            return dict.
        structural_risk_result: modules.structural_risk
            .compute_structural_vintage_risk()'s return dict.
        acris_summary: modules.acris_fetcher.fetch_acris()'s "summary" dict.
        distress_score_result: modules.distress_scorer
            .compute_composite_distress_score()'s return dict.
        tax_exempt: whether the property currently has a tax exemption
            (from modules.abatement_estimator's signal) — an UNCERTAINTY
            flag (exemption could phase out), not itself bad, so it
            contributes a small amount to Financial risk.
        rent_stab_likely: rent-stabilization signal (registry-confirmed or
            heuristic-estimated).
        is_landmark, is_historic_district: landmark/historic-district flags.
        data_gaps: optional list of human-readable strings naming any
            signal that could NOT be fetched (e.g. "ACRIS request failed")
            — surfaced verbatim in "needs_manual_review_reasons" so a
            missing signal is never silently treated as "no risk found."

    Returns (always this shape, never raises):
        {
          "physical": {"score": int, "tier": str, "factors": list[str]},
          "financial": {"score": int, "tier": str, "factors": list[str]},
          "regulatory": {"score": int, "tier": str, "factors": list[str]},
          "overall_score": int,          # simple average of the 3 buckets
          "overall_tier": str,
          "needs_manual_review": bool,
          "needs_manual_review_reasons": list[str],
        }
    """
    try:
        flood_data = flood_data or {}
        structural_risk_result = structural_risk_result or {}
        acris_summary = acris_summary or {}
        distress_score_result = distress_score_result or {}
        data_gaps = list(data_gaps or [])

        # ── Physical ──────────────────────────────────────────────────────
        phys_factors: list[str] = []
        phys_score = 0
        dob_component = min(50, dob_open_violations * 5 + dob_open_complaints * 2)
        if dob_component:
            phys_score += dob_component
            phys_factors.append(f"{dob_open_violations} open DOB violation(s), {dob_open_complaints} open complaint(s)")
        if flood_data.get("in_special_flood_hazard_area"):
            phys_score += 30
            phys_factors.append(f"FEMA Special Flood Hazard Area (Zone {flood_data.get('flood_zone', '—')})")
        elif flood_data.get("flood_zone") == "X500":
            phys_score += 10
            phys_factors.append("500-year floodplain (FEMA Zone X500)")
        struct_score = structural_risk_result.get("score")
        if struct_score is not None:
            phys_score += round(struct_score * 0.20)
            phys_factors.append(f"Structural-vintage risk: {structural_risk_result.get('era_label', '—')}")
        phys_score = max(0, min(100, phys_score))

        # ── Financial ─────────────────────────────────────────────────────
        fin_factors: list[str] = []
        fin_score = 0
        forecl = int(acris_summary.get("foreclosure_count", 0) or 0)
        liens = int(acris_summary.get("open_liens", 0) or 0)
        if forecl:
            fin_score += min(50, forecl * 40)
            fin_factors.append(f"{forecl} foreclosure/lis pendens filing(s) on ACRIS")
        if liens:
            fin_score += min(30, liens * 15)
            fin_factors.append(f"{liens} open lien(s)/UCC filing(s)")
        dist_score = distress_score_result.get("score")
        if dist_score is not None:
            fin_score += round(dist_score * 0.30)
            if dist_score:
                fin_factors.append(f"Composite distress score: {dist_score}/100 ({distress_score_result.get('tier', '—')})")
        if tax_exempt:
            fin_score += 5
            fin_factors.append("Currently tax-exempt — confirm expiration/phase-out schedule before underwriting stabilized taxes")
        fin_score = max(0, min(100, fin_score))

        # ── Regulatory ────────────────────────────────────────────────────
        reg_factors: list[str] = []
        reg_score = 0
        if rent_stab_likely:
            reg_score += 45
            reg_factors.append("Likely rent-stabilized — limits rent upside, may constrain conversion/demolition strategies")
        if is_landmark:
            reg_score += 35
            reg_factors.append("LPC-designated individual landmark — Landmarks Preservation Commission approval required for exterior work")
        if is_historic_district:
            reg_score += 25
            reg_factors.append("Within a historic district — Certificate of Appropriateness required for exterior work")
        reg_score = max(0, min(100, reg_score))

        overall = round((phys_score + fin_score + reg_score) / 3)

        needs_review = False
        reasons: list[str] = list(data_gaps)
        if data_gaps:
            needs_review = True
        if phys_score >= 70 or fin_score >= 70 or reg_score >= 70:
            needs_review = True
            reasons.append("One or more risk buckets scored High (≥70) — recommend manual diligence review before proceeding")

        return {
            "physical":  {"score": phys_score, "tier": _tier_for(phys_score), "factors": phys_factors},
            "financial": {"score": fin_score,  "tier": _tier_for(fin_score),  "factors": fin_factors},
            "regulatory": {"score": reg_score, "tier": _tier_for(reg_score),  "factors": reg_factors},
            "overall_score": overall,
            "overall_tier": _tier_for(overall),
            "needs_manual_review": needs_review,
            "needs_manual_review_reasons": reasons,
        }
    except Exception:
        return {
            "physical": {"score": 0, "tier": "Low", "factors": []},
            "financial": {"score": 0, "tier": "Low", "factors": []},
            "regulatory": {"score": 0, "tier": "Low", "factors": []},
            "overall_score": 0, "overall_tier": "Low",
            "needs_manual_review": True,
            "needs_manual_review_reasons": ["Scorecard computation failed — review manually."],
        }

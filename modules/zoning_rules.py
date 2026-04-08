"""
Static NYC Zoning Development Standards.

Data sourced from NYC Zoning Resolution (ZR), NYC Planning website, and the
NYC Zoning Handbook. Covers residential (R), commercial (C), and manufacturing
(M) districts. No API key required — entirely local lookup.

Each district entry contains:
  base_far        — permitted FAR (base, without bonuses)
  max_far         — max FAR including bonuses (IH, FRESH, MIH, etc.)
  res_far         — residential component
  comm_far        — commercial/retail component
  base_height_ft  — max height before setback is required (contextual districts)
  max_height_ft   — absolute max height after setback; 0 = sky exposure plane only
  front_yard_ft   — min front yard depth (0 = none required)
  rear_yard_ft    — min rear yard depth
  side_yard_ft    — min side yard (per side; 0 = none)
  lot_coverage_pct— max lot coverage percentage (0 = no direct limit)
  contextual      — True if district enforces base/max height via street wall rules
  tower_rules     — True if tower-on-base rules apply (high-rise with open space)
  sky_exp_plane   — True if sky exposure plane governs envelope instead of abs. height
  description     — brief plain-English summary for display
"""

from __future__ import annotations

# ── Data table ────────────────────────────────────────────────────────────────
_RULES: dict[str, dict] = {

    # ── R1 Low-Density Detached ─────────────────────────────────────────────
    "R1-1": {
        "description":     "Lowest-density detached single-family. Large lots, generous setbacks.",
        "base_far": 0.5,  "max_far": 0.5,  "res_far": 0.5,  "comm_far": 0.0,
        "base_height_ft": 35, "max_height_ft": 35,
        "front_yard_ft": 20, "rear_yard_ft": 30, "side_yard_ft": 8,
        "lot_coverage_pct": 30, "contextual": False, "tower_rules": False, "sky_exp_plane": False,
    },
    "R1-2": {
        "description":     "Low-density detached single-family on slightly smaller lots.",
        "base_far": 0.5,  "max_far": 0.5,  "res_far": 0.5,  "comm_far": 0.0,
        "base_height_ft": 35, "max_height_ft": 35,
        "front_yard_ft": 20, "rear_yard_ft": 30, "side_yard_ft": 8,
        "lot_coverage_pct": 35, "contextual": False, "tower_rules": False, "sky_exp_plane": False,
    },

    # ── R2 Low-Density ──────────────────────────────────────────────────────
    "R2": {
        "description":     "Low-density detached single-family.",
        "base_far": 0.5,  "max_far": 0.5,  "res_far": 0.5,  "comm_far": 0.0,
        "base_height_ft": 35, "max_height_ft": 35,
        "front_yard_ft": 15, "rear_yard_ft": 30, "side_yard_ft": 8,
        "lot_coverage_pct": 40, "contextual": False, "tower_rules": False, "sky_exp_plane": False,
    },
    "R2A": {
        "description":     "Contextual R2 requiring detached one- or two-family homes.",
        "base_far": 0.5,  "max_far": 0.5,  "res_far": 0.5,  "comm_far": 0.0,
        "base_height_ft": 25, "max_height_ft": 35,
        "front_yard_ft": 10, "rear_yard_ft": 30, "side_yard_ft": 5,
        "lot_coverage_pct": 45, "contextual": True, "tower_rules": False, "sky_exp_plane": False,
    },
    "R2X": {
        "description":     "Wide detached housing, slightly larger bulk than R2.",
        "base_far": 0.85, "max_far": 0.85, "res_far": 0.85, "comm_far": 0.0,
        "base_height_ft": 35, "max_height_ft": 35,
        "front_yard_ft": 10, "rear_yard_ft": 30, "side_yard_ft": 8,
        "lot_coverage_pct": 45, "contextual": False, "tower_rules": False, "sky_exp_plane": False,
    },

    # ── R3 Low-Density ──────────────────────────────────────────────────────
    "R3A": {
        "description":     "Low-density detached and semi-detached homes.",
        "base_far": 0.5,  "max_far": 0.5,  "res_far": 0.5,  "comm_far": 0.0,
        "base_height_ft": 35, "max_height_ft": 35,
        "front_yard_ft": 10, "rear_yard_ft": 30, "side_yard_ft": 5,
        "lot_coverage_pct": 45, "contextual": False, "tower_rules": False, "sky_exp_plane": False,
    },
    "R3B": {
        "description":     "Low-density rowhouses and semi-detached homes.",
        "base_far": 0.5,  "max_far": 0.5,  "res_far": 0.5,  "comm_far": 0.0,
        "base_height_ft": 35, "max_height_ft": 35,
        "front_yard_ft": 10, "rear_yard_ft": 30, "side_yard_ft": 0,
        "lot_coverage_pct": 55, "contextual": False, "tower_rules": False, "sky_exp_plane": False,
    },
    "R3X": {
        "description":     "Low-density detached housing on wider lots.",
        "base_far": 0.5,  "max_far": 0.5,  "res_far": 0.5,  "comm_far": 0.0,
        "base_height_ft": 35, "max_height_ft": 35,
        "front_yard_ft": 10, "rear_yard_ft": 30, "side_yard_ft": 8,
        "lot_coverage_pct": 40, "contextual": False, "tower_rules": False, "sky_exp_plane": False,
    },

    # ── R4 Medium-Low ───────────────────────────────────────────────────────
    "R4": {
        "description":     "Medium-low density allowing detached, semi-detached, and small apartments.",
        "base_far": 0.9,  "max_far": 0.9,  "res_far": 0.9,  "comm_far": 0.0,
        "base_height_ft": 35, "max_height_ft": 35,
        "front_yard_ft": 10, "rear_yard_ft": 30, "side_yard_ft": 0,
        "lot_coverage_pct": 55, "contextual": False, "tower_rules": False, "sky_exp_plane": False,
    },
    "R4A": {
        "description":     "Contextual R4 — detached and semi-detached homes only.",
        "base_far": 0.9,  "max_far": 0.9,  "res_far": 0.9,  "comm_far": 0.0,
        "base_height_ft": 30, "max_height_ft": 35,
        "front_yard_ft": 10, "rear_yard_ft": 30, "side_yard_ft": 5,
        "lot_coverage_pct": 55, "contextual": True, "tower_rules": False, "sky_exp_plane": False,
    },
    "R4B": {
        "description":     "Contextual R4 for rowhouses — street wall required.",
        "base_far": 0.9,  "max_far": 0.9,  "res_far": 0.9,  "comm_far": 0.0,
        "base_height_ft": 24, "max_height_ft": 33,
        "front_yard_ft": 0,  "rear_yard_ft": 30, "side_yard_ft": 0,
        "lot_coverage_pct": 65, "contextual": True, "tower_rules": False, "sky_exp_plane": False,
    },
    "R4-1": {
        "description":     "R4 infill variant with slightly lower density than base R4.",
        "base_far": 0.9,  "max_far": 0.9,  "res_far": 0.9,  "comm_far": 0.0,
        "base_height_ft": 35, "max_height_ft": 35,
        "front_yard_ft": 10, "rear_yard_ft": 30, "side_yard_ft": 0,
        "lot_coverage_pct": 55, "contextual": False, "tower_rules": False, "sky_exp_plane": False,
    },

    # ── R5 Medium ───────────────────────────────────────────────────────────
    "R5": {
        "description":     "Medium density allowing a range of housing types up to 4 stories.",
        "base_far": 1.25, "max_far": 1.25, "res_far": 1.25, "comm_far": 0.0,
        "base_height_ft": 40, "max_height_ft": 40,
        "front_yard_ft": 10, "rear_yard_ft": 30, "side_yard_ft": 0,
        "lot_coverage_pct": 65, "contextual": False, "tower_rules": False, "sky_exp_plane": False,
    },
    "R5A": {
        "description":     "Contextual R5 emphasizing detached and semi-detached small buildings.",
        "base_far": 1.35, "max_far": 1.35, "res_far": 1.35, "comm_far": 0.0,
        "base_height_ft": 21, "max_height_ft": 30,
        "front_yard_ft": 10, "rear_yard_ft": 30, "side_yard_ft": 5,
        "lot_coverage_pct": 55, "contextual": True, "tower_rules": False, "sky_exp_plane": False,
    },
    "R5B": {
        "description":     "Contextual R5 for rowhouses and small apartment buildings.",
        "base_far": 1.35, "max_far": 1.35, "res_far": 1.35, "comm_far": 0.0,
        "base_height_ft": 30, "max_height_ft": 40,
        "front_yard_ft": 0,  "rear_yard_ft": 30, "side_yard_ft": 0,
        "lot_coverage_pct": 65, "contextual": True, "tower_rules": False, "sky_exp_plane": False,
    },
    "R5D": {
        "description":     "Higher-bulk R5 variant allowing more floor area on larger lots.",
        "base_far": 2.0,  "max_far": 2.0,  "res_far": 2.0,  "comm_far": 0.0,
        "base_height_ft": 40, "max_height_ft": 40,
        "front_yard_ft": 0,  "rear_yard_ft": 30, "side_yard_ft": 0,
        "lot_coverage_pct": 70, "contextual": False, "tower_rules": False, "sky_exp_plane": False,
    },

    # ── R6 Medium-High ──────────────────────────────────────────────────────
    "R6": {
        "description":     "Medium-high density; non-contextual permits towers with open space via sky exposure plane.",
        "base_far": 2.43, "max_far": 3.0,  "res_far": 2.43, "comm_far": 0.0,
        "base_height_ft": 0,  "max_height_ft": 0,
        "front_yard_ft": 0,  "rear_yard_ft": 30, "side_yard_ft": 0,
        "lot_coverage_pct": 60, "contextual": False, "tower_rules": False, "sky_exp_plane": True,
    },
    "R6A": {
        "description":     "Contextual R6 — base height 60–70 ft, max 85 ft. Common in brownstone Brooklyn.",
        "base_far": 3.0,  "max_far": 3.6,  "res_far": 3.0,  "comm_far": 0.0,
        "base_height_ft": 60, "max_height_ft": 85,
        "front_yard_ft": 0,  "rear_yard_ft": 30, "side_yard_ft": 0,
        "lot_coverage_pct": 70, "contextual": True, "tower_rules": False, "sky_exp_plane": False,
    },
    "R6B": {
        "description":     "Contextual R6 for lower-scale neighborhoods — base 30–40 ft, max 50 ft.",
        "base_far": 2.0,  "max_far": 2.0,  "res_far": 2.0,  "comm_far": 0.0,
        "base_height_ft": 30, "max_height_ft": 50,
        "front_yard_ft": 0,  "rear_yard_ft": 30, "side_yard_ft": 0,
        "lot_coverage_pct": 70, "contextual": True, "tower_rules": False, "sky_exp_plane": False,
    },

    # ── R7 High ─────────────────────────────────────────────────────────────
    "R7": {
        "description":     "High density residential; sky exposure plane governs; towers possible.",
        "base_far": 3.44, "max_far": 4.0,  "res_far": 3.44, "comm_far": 0.0,
        "base_height_ft": 0,  "max_height_ft": 0,
        "front_yard_ft": 0,  "rear_yard_ft": 30, "side_yard_ft": 0,
        "lot_coverage_pct": 65, "contextual": False, "tower_rules": False, "sky_exp_plane": True,
    },
    "R7A": {
        "description":     "Contextual high-density — base 60–70 ft, max 80 ft. Typical Midtown/UWS blocks.",
        "base_far": 4.0,  "max_far": 4.6,  "res_far": 4.0,  "comm_far": 1.0,
        "base_height_ft": 60, "max_height_ft": 80,
        "front_yard_ft": 0,  "rear_yard_ft": 30, "side_yard_ft": 0,
        "lot_coverage_pct": 70, "contextual": True, "tower_rules": False, "sky_exp_plane": False,
    },
    "R7B": {
        "description":     "Contextual high-density at lower scale — base 40–50 ft, max 60 ft.",
        "base_far": 3.0,  "max_far": 3.0,  "res_far": 3.0,  "comm_far": 0.0,
        "base_height_ft": 40, "max_height_ft": 60,
        "front_yard_ft": 0,  "rear_yard_ft": 30, "side_yard_ft": 0,
        "lot_coverage_pct": 70, "contextual": True, "tower_rules": False, "sky_exp_plane": False,
    },
    "R7D": {
        "description":     "High-density contextual — similar to R7A but with slightly higher bulk.",
        "base_far": 4.2,  "max_far": 5.0,  "res_far": 4.2,  "comm_far": 1.0,
        "base_height_ft": 60, "max_height_ft": 85,
        "front_yard_ft": 0,  "rear_yard_ft": 30, "side_yard_ft": 0,
        "lot_coverage_pct": 70, "contextual": True, "tower_rules": False, "sky_exp_plane": False,
    },
    "R7X": {
        "description":     "High-density contextual — base 60–75 ft, max 95 ft. Used in Hudson Yards area.",
        "base_far": 3.75, "max_far": 5.0,  "res_far": 3.75, "comm_far": 1.0,
        "base_height_ft": 60, "max_height_ft": 95,
        "front_yard_ft": 0,  "rear_yard_ft": 30, "side_yard_ft": 0,
        "lot_coverage_pct": 70, "contextual": True, "tower_rules": False, "sky_exp_plane": False,
    },

    # ── R8 Very High ─────────────────────────────────────────────────────────
    "R8": {
        "description":     "Very high density; sky exposure plane; towers on large lots. Common in Manhattan.",
        "base_far": 6.02, "max_far": 7.2,  "res_far": 6.02, "comm_far": 2.0,
        "base_height_ft": 0,  "max_height_ft": 0,
        "front_yard_ft": 0,  "rear_yard_ft": 30, "side_yard_ft": 0,
        "lot_coverage_pct": 0,  "contextual": False, "tower_rules": True,  "sky_exp_plane": True,
    },
    "R8A": {
        "description":     "Contextual very high density — base 60–85 ft, max 120 ft.",
        "base_far": 6.02, "max_far": 7.2,  "res_far": 6.02, "comm_far": 2.0,
        "base_height_ft": 60, "max_height_ft": 120,
        "front_yard_ft": 0,  "rear_yard_ft": 30, "side_yard_ft": 0,
        "lot_coverage_pct": 70, "contextual": True, "tower_rules": False, "sky_exp_plane": False,
    },
    "R8B": {
        "description":     "Contextual very high density at lower scale — base 40–55 ft, max 75 ft.",
        "base_far": 4.0,  "max_far": 4.0,  "res_far": 4.0,  "comm_far": 0.0,
        "base_height_ft": 40, "max_height_ft": 75,
        "front_yard_ft": 0,  "rear_yard_ft": 30, "side_yard_ft": 0,
        "lot_coverage_pct": 70, "contextual": True, "tower_rules": False, "sky_exp_plane": False,
    },
    "R8X": {
        "description":     "Extra-bulk contextual high-rise — base 105–115 ft, max 150 ft.",
        "base_far": 6.0,  "max_far": 9.0,  "res_far": 6.0,  "comm_far": 2.0,
        "base_height_ft": 105, "max_height_ft": 150,
        "front_yard_ft": 0,  "rear_yard_ft": 30, "side_yard_ft": 0,
        "lot_coverage_pct": 70, "contextual": True, "tower_rules": False, "sky_exp_plane": False,
    },

    # ── R9 Ultrahigh ────────────────────────────────────────────────────────
    "R9": {
        "description":     "Ultra-high density; tower rules apply; sky exposure plane. Core Manhattan.",
        "base_far": 7.52, "max_far": 9.0,  "res_far": 7.52, "comm_far": 2.0,
        "base_height_ft": 0,  "max_height_ft": 0,
        "front_yard_ft": 0,  "rear_yard_ft": 30, "side_yard_ft": 0,
        "lot_coverage_pct": 0,  "contextual": False, "tower_rules": True,  "sky_exp_plane": True,
    },
    "R9A": {
        "description":     "Contextual ultra-high density — base 60–85 ft.",
        "base_far": 7.52, "max_far": 9.0,  "res_far": 7.52, "comm_far": 2.0,
        "base_height_ft": 60, "max_height_ft": 145,
        "front_yard_ft": 0,  "rear_yard_ft": 30, "side_yard_ft": 0,
        "lot_coverage_pct": 70, "contextual": True, "tower_rules": False, "sky_exp_plane": False,
    },
    "R9D": {
        "description":     "Contextual ultra-high density — similar to R9A.",
        "base_far": 7.52, "max_far": 9.0,  "res_far": 7.52, "comm_far": 2.0,
        "base_height_ft": 60, "max_height_ft": 145,
        "front_yard_ft": 0,  "rear_yard_ft": 30, "side_yard_ft": 0,
        "lot_coverage_pct": 70, "contextual": True, "tower_rules": False, "sky_exp_plane": False,
    },
    "R9X": {
        "description":     "Extra-bulk contextual ultra-high density — base 60–90 ft.",
        "base_far": 8.0,  "max_far": 9.6,  "res_far": 8.0,  "comm_far": 2.0,
        "base_height_ft": 60, "max_height_ft": 160,
        "front_yard_ft": 0,  "rear_yard_ft": 30, "side_yard_ft": 0,
        "lot_coverage_pct": 70, "contextual": True, "tower_rules": False, "sky_exp_plane": False,
    },

    # ── R10 Maximum Density ─────────────────────────────────────────────────
    "R10": {
        "description":     "Highest residential FAR (10.0). Tower rules; no absolute height limit. Midtown/FiDi.",
        "base_far": 10.0, "max_far": 12.0, "res_far": 10.0, "comm_far": 2.0,
        "base_height_ft": 0,  "max_height_ft": 0,
        "front_yard_ft": 0,  "rear_yard_ft": 0,  "side_yard_ft": 0,
        "lot_coverage_pct": 0,  "contextual": False, "tower_rules": True,  "sky_exp_plane": True,
    },
    "R10A": {
        "description":     "Contextual R10 — enforces street wall; max height ~185 ft.",
        "base_far": 10.0, "max_far": 12.0, "res_far": 10.0, "comm_far": 2.0,
        "base_height_ft": 60, "max_height_ft": 185,
        "front_yard_ft": 0,  "rear_yard_ft": 0,  "side_yard_ft": 0,
        "lot_coverage_pct": 70, "contextual": True, "tower_rules": False, "sky_exp_plane": False,
    },
    "R10H": {
        "description":     "Highest contextual density (Hudson Yards / West Side). Max 260 ft.",
        "base_far": 10.0, "max_far": 15.0, "res_far": 10.0, "comm_far": 6.0,
        "base_height_ft": 85, "max_height_ft": 260,
        "front_yard_ft": 0,  "rear_yard_ft": 0,  "side_yard_ft": 0,
        "lot_coverage_pct": 70, "contextual": True, "tower_rules": False, "sky_exp_plane": False,
    },

    # ── Commercial C1 / C2 (overlays — shown here as standalone where mapped) ─
    "C1-1": {
        "description": "Local retail/service (low density residential context). FAR 1.0.",
        "base_far": 1.0, "max_far": 1.0, "res_far": 0.0, "comm_far": 1.0,
        "base_height_ft": 25, "max_height_ft": 25,
        "front_yard_ft": 0, "rear_yard_ft": 20, "side_yard_ft": 0,
        "lot_coverage_pct": 65, "contextual": False, "tower_rules": False, "sky_exp_plane": False,
    },
    "C1-2": {
        "description": "Local retail/service (low-medium density context). FAR 1.0.",
        "base_far": 1.0, "max_far": 1.0, "res_far": 0.0, "comm_far": 1.0,
        "base_height_ft": 30, "max_height_ft": 30,
        "front_yard_ft": 0, "rear_yard_ft": 20, "side_yard_ft": 0,
        "lot_coverage_pct": 70, "contextual": False, "tower_rules": False, "sky_exp_plane": False,
    },
    "C2-1": {
        "description": "Local retail/service with wider use group. FAR 2.0.",
        "base_far": 2.0, "max_far": 2.0, "res_far": 0.0, "comm_far": 2.0,
        "base_height_ft": 25, "max_height_ft": 25,
        "front_yard_ft": 0, "rear_yard_ft": 20, "side_yard_ft": 0,
        "lot_coverage_pct": 65, "contextual": False, "tower_rules": False, "sky_exp_plane": False,
    },
    "C2-4": {
        "description": "Local retail/service overlay in higher-density context. FAR 3.4.",
        "base_far": 3.4, "max_far": 3.4, "res_far": 0.0, "comm_far": 3.4,
        "base_height_ft": 60, "max_height_ft": 60,
        "front_yard_ft": 0, "rear_yard_ft": 20, "side_yard_ft": 0,
        "lot_coverage_pct": 70, "contextual": False, "tower_rules": False, "sky_exp_plane": False,
    },

    # ── C3 ─────────────────────────────────────────────────────────────────
    "C3": {
        "description": "Waterfront recreation commercial (boatyards, marinas). FAR 0.5.",
        "base_far": 0.5, "max_far": 0.5, "res_far": 0.0, "comm_far": 0.5,
        "base_height_ft": 35, "max_height_ft": 35,
        "front_yard_ft": 0, "rear_yard_ft": 20, "side_yard_ft": 0,
        "lot_coverage_pct": 35, "contextual": False, "tower_rules": False, "sky_exp_plane": False,
    },

    # ── C4 Regional Commercial ──────────────────────────────────────────────
    "C4-1": {
        "description": "Regional commercial in low-density context. FAR 1.0.",
        "base_far": 1.0, "max_far": 1.0, "res_far": 0.0, "comm_far": 1.0,
        "base_height_ft": 25, "max_height_ft": 40,
        "front_yard_ft": 0, "rear_yard_ft": 20, "side_yard_ft": 0,
        "lot_coverage_pct": 65, "contextual": False, "tower_rules": False, "sky_exp_plane": False,
    },
    "C4-2": {
        "description": "Regional commercial — shopping centers, large retail. FAR 3.4.",
        "base_far": 3.4, "max_far": 3.4, "res_far": 0.0, "comm_far": 3.4,
        "base_height_ft": 60, "max_height_ft": 85,
        "front_yard_ft": 0, "rear_yard_ft": 20, "side_yard_ft": 0,
        "lot_coverage_pct": 70, "contextual": False, "tower_rules": False, "sky_exp_plane": False,
    },
    "C4-3": {
        "description": "Regional commercial — medium-high density. FAR 4.8.",
        "base_far": 4.8, "max_far": 4.8, "res_far": 0.0, "comm_far": 4.8,
        "base_height_ft": 85, "max_height_ft": 105,
        "front_yard_ft": 0, "rear_yard_ft": 20, "side_yard_ft": 0,
        "lot_coverage_pct": 70, "contextual": False, "tower_rules": False, "sky_exp_plane": False,
    },
    "C4-4": {
        "description": "Regional commercial — high density. FAR 3.4 commercial / 2.43 residential.",
        "base_far": 3.4, "max_far": 4.0, "res_far": 2.43, "comm_far": 3.4,
        "base_height_ft": 0, "max_height_ft": 0,
        "front_yard_ft": 0, "rear_yard_ft": 20, "side_yard_ft": 0,
        "lot_coverage_pct": 70, "contextual": False, "tower_rules": False, "sky_exp_plane": True,
    },
    "C4-4A": {
        "description": "Contextual C4-4 — base 60 ft, max 85 ft.",
        "base_far": 3.4, "max_far": 4.0, "res_far": 2.43, "comm_far": 3.4,
        "base_height_ft": 60, "max_height_ft": 85,
        "front_yard_ft": 0, "rear_yard_ft": 20, "side_yard_ft": 0,
        "lot_coverage_pct": 70, "contextual": True, "tower_rules": False, "sky_exp_plane": False,
    },
    "C4-5": {
        "description": "Regional commercial — highest density. FAR up to 10.0.",
        "base_far": 10.0, "max_far": 10.0, "res_far": 0.0, "comm_far": 10.0,
        "base_height_ft": 0, "max_height_ft": 0,
        "front_yard_ft": 0, "rear_yard_ft": 0, "side_yard_ft": 0,
        "lot_coverage_pct": 0, "contextual": False, "tower_rules": True, "sky_exp_plane": True,
    },
    "C4-6": {
        "description": "Regional commercial — very high density. FAR up to 10.0.",
        "base_far": 10.0, "max_far": 10.0, "res_far": 0.0, "comm_far": 10.0,
        "base_height_ft": 0, "max_height_ft": 0,
        "front_yard_ft": 0, "rear_yard_ft": 0, "side_yard_ft": 0,
        "lot_coverage_pct": 0, "contextual": False, "tower_rules": True, "sky_exp_plane": True,
    },
    "C4-7": {
        "description": "Highest commercial density (Times Square). FAR up to 15.0.",
        "base_far": 15.0, "max_far": 15.0, "res_far": 0.0, "comm_far": 15.0,
        "base_height_ft": 0, "max_height_ft": 0,
        "front_yard_ft": 0, "rear_yard_ft": 0, "side_yard_ft": 0,
        "lot_coverage_pct": 0, "contextual": False, "tower_rules": True, "sky_exp_plane": True,
    },

    # ── C5 Central Business ─────────────────────────────────────────────────
    "C5-1": {
        "description": "Central business district. FAR 4.0 commercial.",
        "base_far": 4.0, "max_far": 4.0, "res_far": 0.0, "comm_far": 4.0,
        "base_height_ft": 0, "max_height_ft": 0,
        "front_yard_ft": 0, "rear_yard_ft": 0, "side_yard_ft": 0,
        "lot_coverage_pct": 0, "contextual": False, "tower_rules": False, "sky_exp_plane": True,
    },
    "C5-2": {
        "description": "Central business district — high-density offices. FAR up to 15.0.",
        "base_far": 15.0, "max_far": 15.0, "res_far": 0.0, "comm_far": 15.0,
        "base_height_ft": 0, "max_height_ft": 0,
        "front_yard_ft": 0, "rear_yard_ft": 0, "side_yard_ft": 0,
        "lot_coverage_pct": 0, "contextual": False, "tower_rules": True, "sky_exp_plane": True,
    },
    "C5-3": {
        "description": "High-density central office district. FAR up to 15.0.",
        "base_far": 15.0, "max_far": 15.0, "res_far": 0.0, "comm_far": 15.0,
        "base_height_ft": 0, "max_height_ft": 0,
        "front_yard_ft": 0, "rear_yard_ft": 0, "side_yard_ft": 0,
        "lot_coverage_pct": 0, "contextual": False, "tower_rules": True, "sky_exp_plane": True,
    },

    # ── C6 General Central Commercial ──────────────────────────────────────
    "C6-1": {
        "description": "General commercial — offices, hotels, retail. FAR 6.0.",
        "base_far": 6.0, "max_far": 6.0, "res_far": 2.43, "comm_far": 6.0,
        "base_height_ft": 0, "max_height_ft": 0,
        "front_yard_ft": 0, "rear_yard_ft": 0, "side_yard_ft": 0,
        "lot_coverage_pct": 0, "contextual": False, "tower_rules": False, "sky_exp_plane": True,
    },
    "C6-2": {
        "description": "General commercial — high density. FAR 6.0.",
        "base_far": 6.0, "max_far": 6.5, "res_far": 3.44, "comm_far": 6.0,
        "base_height_ft": 0, "max_height_ft": 0,
        "front_yard_ft": 0, "rear_yard_ft": 0, "side_yard_ft": 0,
        "lot_coverage_pct": 0, "contextual": False, "tower_rules": False, "sky_exp_plane": True,
    },
    "C6-3": {
        "description": "General commercial — high density. FAR 9.0.",
        "base_far": 9.0, "max_far": 9.0, "res_far": 7.52, "comm_far": 9.0,
        "base_height_ft": 0, "max_height_ft": 0,
        "front_yard_ft": 0, "rear_yard_ft": 0, "side_yard_ft": 0,
        "lot_coverage_pct": 0, "contextual": False, "tower_rules": True, "sky_exp_plane": True,
    },
    "C6-4": {
        "description": "Very high-density general commercial / mixed-use. FAR 10.0.",
        "base_far": 10.0, "max_far": 10.0, "res_far": 10.0, "comm_far": 10.0,
        "base_height_ft": 0, "max_height_ft": 0,
        "front_yard_ft": 0, "rear_yard_ft": 0, "side_yard_ft": 0,
        "lot_coverage_pct": 0, "contextual": False, "tower_rules": True, "sky_exp_plane": True,
    },

    # ── M1 Light Manufacturing ──────────────────────────────────────────────
    "M1-1": {
        "description": "Light industrial/manufacturing — no residential permitted. FAR 1.0.",
        "base_far": 1.0, "max_far": 1.0, "res_far": 0.0, "comm_far": 0.0,
        "base_height_ft": 40, "max_height_ft": 40,
        "front_yard_ft": 0, "rear_yard_ft": 20, "side_yard_ft": 0,
        "lot_coverage_pct": 70, "contextual": False, "tower_rules": False, "sky_exp_plane": False,
    },
    "M1-2": {
        "description": "Light industrial — medium density. FAR 2.0.",
        "base_far": 2.0, "max_far": 2.0, "res_far": 0.0, "comm_far": 0.0,
        "base_height_ft": 60, "max_height_ft": 60,
        "front_yard_ft": 0, "rear_yard_ft": 20, "side_yard_ft": 0,
        "lot_coverage_pct": 70, "contextual": False, "tower_rules": False, "sky_exp_plane": False,
    },
    "M1-3": {
        "description": "Light industrial — medium-high density. FAR 2.0.",
        "base_far": 2.0, "max_far": 2.0, "res_far": 0.0, "comm_far": 0.0,
        "base_height_ft": 60, "max_height_ft": 60,
        "front_yard_ft": 0, "rear_yard_ft": 20, "side_yard_ft": 0,
        "lot_coverage_pct": 70, "contextual": False, "tower_rules": False, "sky_exp_plane": False,
    },
    "M1-4": {
        "description": "Light industrial — high density. FAR 2.0.",
        "base_far": 2.0, "max_far": 2.0, "res_far": 0.0, "comm_far": 0.0,
        "base_height_ft": 0, "max_height_ft": 0,
        "front_yard_ft": 0, "rear_yard_ft": 20, "side_yard_ft": 0,
        "lot_coverage_pct": 0, "contextual": False, "tower_rules": False, "sky_exp_plane": True,
    },
    "M1-5": {
        "description": "Light industrial — very high density (Midtown South). FAR 5.0.",
        "base_far": 5.0, "max_far": 5.0, "res_far": 0.0, "comm_far": 0.0,
        "base_height_ft": 0, "max_height_ft": 0,
        "front_yard_ft": 0, "rear_yard_ft": 0, "side_yard_ft": 0,
        "lot_coverage_pct": 0, "contextual": False, "tower_rules": False, "sky_exp_plane": True,
    },
    "M1-6": {
        "description": "Light industrial — highest density (Garment District). FAR 10.0.",
        "base_far": 10.0, "max_far": 10.0, "res_far": 0.0, "comm_far": 0.0,
        "base_height_ft": 0, "max_height_ft": 0,
        "front_yard_ft": 0, "rear_yard_ft": 0, "side_yard_ft": 0,
        "lot_coverage_pct": 0, "contextual": False, "tower_rules": True, "sky_exp_plane": True,
    },

    # ── M2 Medium Manufacturing ─────────────────────────────────────────────
    "M2-1": {
        "description": "Medium manufacturing — heavier industrial uses. FAR 2.0.",
        "base_far": 2.0, "max_far": 2.0, "res_far": 0.0, "comm_far": 0.0,
        "base_height_ft": 60, "max_height_ft": 60,
        "front_yard_ft": 0, "rear_yard_ft": 20, "side_yard_ft": 0,
        "lot_coverage_pct": 70, "contextual": False, "tower_rules": False, "sky_exp_plane": False,
    },
    "M2-2": {
        "description": "Medium manufacturing — medium density. FAR 2.0.",
        "base_far": 2.0, "max_far": 2.0, "res_far": 0.0, "comm_far": 0.0,
        "base_height_ft": 60, "max_height_ft": 60,
        "front_yard_ft": 0, "rear_yard_ft": 20, "side_yard_ft": 0,
        "lot_coverage_pct": 70, "contextual": False, "tower_rules": False, "sky_exp_plane": False,
    },
    "M2-3": {
        "description": "Medium manufacturing — medium-high density. FAR 2.0.",
        "base_far": 2.0, "max_far": 2.0, "res_far": 0.0, "comm_far": 0.0,
        "base_height_ft": 0, "max_height_ft": 0,
        "front_yard_ft": 0, "rear_yard_ft": 20, "side_yard_ft": 0,
        "lot_coverage_pct": 0, "contextual": False, "tower_rules": False, "sky_exp_plane": True,
    },
    "M2-4": {
        "description": "Medium manufacturing — high density. FAR 2.0.",
        "base_far": 2.0, "max_far": 2.0, "res_far": 0.0, "comm_far": 0.0,
        "base_height_ft": 0, "max_height_ft": 0,
        "front_yard_ft": 0, "rear_yard_ft": 0, "side_yard_ft": 0,
        "lot_coverage_pct": 0, "contextual": False, "tower_rules": False, "sky_exp_plane": True,
    },

    # ── M3 Heavy Manufacturing ──────────────────────────────────────────────
    "M3-1": {
        "description": "Heavy manufacturing — fuel storage, power plants, noxious uses. FAR 2.0.",
        "base_far": 2.0, "max_far": 2.0, "res_far": 0.0, "comm_far": 0.0,
        "base_height_ft": 60, "max_height_ft": 60,
        "front_yard_ft": 0, "rear_yard_ft": 20, "side_yard_ft": 0,
        "lot_coverage_pct": 70, "contextual": False, "tower_rules": False, "sky_exp_plane": False,
    },
    "M3-2": {
        "description": "Heavy manufacturing — larger facilities. FAR 2.0.",
        "base_far": 2.0, "max_far": 2.0, "res_far": 0.0, "comm_far": 0.0,
        "base_height_ft": 0, "max_height_ft": 0,
        "front_yard_ft": 0, "rear_yard_ft": 0, "side_yard_ft": 0,
        "lot_coverage_pct": 0, "contextual": False, "tower_rules": False, "sky_exp_plane": True,
    },
}

# ── Public API ────────────────────────────────────────────────────────────────

def get_zoning_rules(district: str) -> dict | None:
    """
    Return the development standards dict for the given zoning district.

    Matching strategy:
    1. Exact match  (e.g. "R7A" → "R7A")
    2. Normalised uppercase (handles lowercase input)
    3. Strip trailing modifier (e.g. "R6A-1" → try "R6A")
    4. Strip everything after first dash/letter suffix (e.g. "M1-1/R5" → "M1-1")

    Returns None if no match is found.
    """
    if not district:
        return None

    # normalise
    d = str(district).strip().upper()

    # 1. Exact
    if d in _RULES:
        return _RULES[d]

    # 2. Strip slash (split-zone notation like "R7A/C1-4")
    d = d.split("/")[0].strip()
    if d in _RULES:
        return _RULES[d]

    # 3. Strip trailing modifier separated by dash (e.g. "C4-4A" → check "C4-4" if "C4-4A" not found)
    parts = d.rsplit("-", 1)
    if len(parts) == 2 and parts[1].endswith(("A", "B", "D", "X", "H")):
        base = parts[0] + "-" + parts[1][:-1]
        if base in _RULES:
            return _RULES[base]

    # 4. Try truncating to base letter prefix (R7, C4, M1, etc.)
    import re as _re
    m = _re.match(r'^([A-Z]+\d+)', d)
    if m:
        base = m.group(1)
        if base in _RULES:
            return _RULES[base]

    return None


def all_districts() -> list[str]:
    """Return a sorted list of all known zoning district codes."""
    return sorted(_RULES.keys())


# ── Special Districts Lookup ──────────────────────────────────────────────────
# Maps NYC special purpose district codes → {name, description, url}
# Source: NYC Planning Zoning Resolution, Article IX

SPECIAL_DISTRICTS: dict[str, dict] = {
    "SB": {
        "name": "Special Battery Park City District",
        "description": (
            "Governs development in Battery Park City, Lower Manhattan. Requires compliance "
            "with Battery Park City Authority design guidelines. Strict height, setback, and "
            "ground-floor retail activation requirements."
        ),
        "url": "https://zoning.nyc.gov/article-ix/chapter-1",
    },
    "SCD": {
        "name": "Special Coney Island District",
        "description": (
            "Encourages amusement and entertainment uses in Coney Island, Brooklyn. Includes "
            "mandatory ground-floor entertainment uses and signage requirements along Surf Avenue. "
            "Mixed-use residential and entertainment development promoted."
        ),
        "url": "https://zoning.nyc.gov/article-ix/chapter-5",
    },
    "SCE": {
        "name": "Special Coastal Risk District",
        "description": (
            "Applies in flood-prone coastal areas. Requires ground-floor flood mitigation, "
            "elevated mechanical systems, and limits certain ground-floor uses. Properties "
            "may require FEMA flood zone compliance for financing."
        ),
        "url": "https://zoning.nyc.gov/article-ix/chapter-4",
    },
    "SCI": {
        "name": "Special Clinton District",
        "description": (
            "Protects the Clinton neighborhood (Hell's Kitchen) in Manhattan. Restricts "
            "demolition of residential buildings, requires replacement housing, and limits "
            "commercial development on residential streets."
        ),
        "url": "https://zoning.nyc.gov/article-ix/chapter-9",
    },
    "SDI": {
        "name": "Special Downtown Jamaica District",
        "description": (
            "Promotes transit-oriented mixed-use development around Jamaica Station, Queens. "
            "Higher FARs near transit, ground-floor retail activation required on major corridors, "
            "and streamlined approval for mixed-income housing."
        ),
        "url": "https://zoning.nyc.gov/article-ix/chapter-32",
    },
    "SG": {
        "name": "Special Garment Center District",
        "description": (
            "Protects garment and light industrial space in Midtown Manhattan. Restrictions on "
            "conversion of manufacturing loft space to non-industrial use. Floor area requirements "
            "for preserving production space in certain sub-areas."
        ),
        "url": "https://zoning.nyc.gov/article-ix/chapter-12",
    },
    "SHP": {
        "name": "Special Hunts Point District",
        "description": (
            "Promotes food distribution and manufacturing uses in Hunts Point, Bronx. "
            "Restrictions on residential development in core industrial areas. "
            "Focus on job retention in food supply chain facilities."
        ),
        "url": "https://zoning.nyc.gov/article-ix/chapter-43",
    },
    "SHY": {
        "name": "Special Hudson Yards District",
        "description": (
            "Governs Manhattan's far West Side redevelopment. Includes FAR bonuses for public "
            "space, mandatory ground-floor retail, phased development requirements, and "
            "transit improvements tied to the 7 train extension. Very high permitted densities."
        ),
        "url": "https://zoning.nyc.gov/article-ix/chapter-33",
    },
    "SL": {
        "name": "Special Lincoln Square District",
        "description": (
            "Applies to the Lincoln Center area on Manhattan's Upper West Side. Permits "
            "higher densities near cultural institutions, requires theatrical/cultural uses "
            "on certain sites, and includes specific streetscape requirements."
        ),
        "url": "https://zoning.nyc.gov/article-ix/chapter-8",
    },
    "SLI": {
        "name": "Special Little Italy District",
        "description": (
            "Protects the historic character of Little Italy in Lower Manhattan. Limits "
            "building heights, requires ground-floor retail consistent with the neighborhood's "
            "cultural character, and restricts certain modern commercial uses."
        ),
        "url": "https://zoning.nyc.gov/article-ix/chapter-15",
    },
    "SMD": {
        "name": "Special Midtown District",
        "description": (
            "Governs development in Midtown Manhattan's commercial core. Includes FAR "
            "bonuses for public plazas, subway improvements, and theater preservation. "
            "Sub-areas include Theater Sub-district, Fifth Avenue Sub-district, and "
            "Grand Central Sub-district with specific use and bulk controls."
        ),
        "url": "https://zoning.nyc.gov/article-ix/chapter-17",
    },
    "SMP": {
        "name": "Special Manhattan Parking District",
        "description": (
            "Restricts new accessory parking facilities in high-density Midtown areas to "
            "reduce traffic congestion and encourage transit use. Limits on parking spaces "
            "per building."
        ),
        "url": "https://zoning.nyc.gov/article-ix/chapter-13",
    },
    "SN": {
        "name": "Special Natural Area District",
        "description": (
            "Protects environmentally sensitive natural features including ridgelines, "
            "shorelines, and vegetation. Development must minimize disturbance to natural "
            "topography and vegetation. Common in Staten Island and outer-borough hillside areas."
        ),
        "url": "https://zoning.nyc.gov/article-ix/chapter-16",
    },
    "SOC": {
        "name": "Special Ocean Parkway District",
        "description": (
            "Applies along Ocean Parkway in Brooklyn. Preserves the historic character of "
            "the parkway boulevard by restricting parking strips along the frontage and "
            "maintaining consistent setbacks and landscaping."
        ),
        "url": "https://zoning.nyc.gov/article-ix/chapter-10",
    },
    "SP": {
        "name": "Special Forest Hills Special District",
        "description": (
            "Preserves the historic garden city character of Forest Hills Gardens, Queens. "
            "Strict controls on demolition, additions, and new construction to maintain "
            "the neighborhood's English garden-style design."
        ),
        "url": "https://zoning.nyc.gov/article-ix/chapter-23",
    },
    "SRD": {
        "name": "Special Sheepshead Bay / Brighton Beach District",
        "description": (
            "Governs development along the Sheepshead Bay waterfront. Restrictions on "
            "building heights and uses near the bay to maintain recreational and "
            "maritime character."
        ),
        "url": "https://zoning.nyc.gov/article-ix/chapter-11",
    },
    "SSQ": {
        "name": "Special Union Square District",
        "description": (
            "Promotes active ground-floor retail and transit-oriented uses around Union "
            "Square in Manhattan. FAR bonuses for subway station improvements and "
            "public space activation."
        ),
        "url": "https://zoning.nyc.gov/article-ix/chapter-31",
    },
    "SWC": {
        "name": "Special West Chelsea District",
        "description": (
            "Governs the High Line corridor in West Chelsea, Manhattan. Promotes mixed-use "
            "development with ground-floor retail, arts-related uses, and High Line "
            "access improvements. Includes FAR transfer provisions for High Line bonus."
        ),
        "url": "https://zoning.nyc.gov/article-ix/chapter-34",
    },
    "SWSS": {
        "name": "Special West Side Sub-district",
        "description": (
            "Part of the larger Hudson Yards framework. Addresses areas west of Tenth "
            "Avenue with specific height, setback, and use mix requirements tied to "
            "public open space improvements."
        ),
        "url": "https://zoning.nyc.gov/article-ix/chapter-33",
    },
    "S125": {
        "name": "Special 125th Street District",
        "description": (
            "Promotes economic vitality and cultural preservation along 125th Street (Harlem's "
            "main commercial corridor) in Manhattan. Requires ground-floor active uses, "
            "minimum commercial depths, and cultural facilities on certain sites."
        ),
        "url": "https://zoning.nyc.gov/article-ix/chapter-37",
    },
}

# Commercial overlay use permissions
COMMERCIAL_OVERLAYS: dict[str, dict] = {
    "C1-1": {"uses": "local retail and personal service establishments", "comm_far": 1.0},
    "C1-2": {"uses": "local retail and personal service establishments", "comm_far": 1.0},
    "C1-3": {"uses": "local retail and personal service establishments", "comm_far": 1.0},
    "C1-4": {"uses": "local retail and personal service establishments", "comm_far": 2.0},
    "C1-5": {"uses": "local retail and personal service establishments", "comm_far": 2.0},
    "C2-1": {"uses": "local retail, personal services, and community facilities", "comm_far": 1.0},
    "C2-2": {"uses": "local retail, personal services, and community facilities", "comm_far": 1.0},
    "C2-3": {"uses": "local retail, personal services, and community facilities", "comm_far": 1.0},
    "C2-4": {"uses": "local retail, personal services, community facilities, and automotive services", "comm_far": 2.0},
    "C2-5": {"uses": "local retail, personal services, community facilities, and automotive services", "comm_far": 2.0},
}


def get_special_district_info(code: str) -> dict | None:
    """Return info dict for a special district code, or None if unknown."""
    if not code:
        return None
    return SPECIAL_DISTRICTS.get(str(code).strip().upper())

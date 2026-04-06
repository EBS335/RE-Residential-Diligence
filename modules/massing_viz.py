"""
3D Building Massing Visualizations using Plotly — 10 Scenarios.

Generates interactive 3D diagrams of NYC building envelopes for 10 distinct
design scenarios spanning Low / Medium / High investment risk tiers.

Each scenario includes:
  - Colored 3D building mass (Mesh3d + wireframe)
  - Lot boundary footprint
  - Faded dashed zoning envelope overlay (height limits, setback planes, SEP)

Scenarios:
  LOW RISK
    1. Gut Renovation / Adaptive Reuse        (25% loss factor)
    2. Contextual Infill — Base Height         (15% loss factor)
    3. Low-Rise Residential (2–3 stories)      (15% loss factor)
  MEDIUM RISK
    4. Mid-Rise Mixed-Use                      (15% loss factor)
    5. Standard Residential Tower              (15% loss factor)
    6. Courtyard Apartment                     (15% loss factor)
    7. Stacked Townhouse / Rowhouse            (15% loss factor)
  HIGH RISK
    8. Max FAR Residential Tower               (15% loss factor)
    9. Slender Luxury Tower                    (15% loss factor)
   10. Full Development — Max Bonus FAR (IH)   (15% loss factor)
  - Zoning rules (FAR, height limits, setbacks from zoning_rules.py)

Each returns a go.Figure that can be rendered with st.plotly_chart().
"""

from __future__ import annotations
import math
import plotly.graph_objects as go


# ── Color palette ─────────────────────────────────────────────────────────────
_CLR_LOT     = "rgba(100,100,100,0.18)"
_CLR_SETBACK = "rgba(255,200,0,0.22)"
_CLR_LINE    = "#374151"
_CLR_ENV     = "rgba(180,180,180,0.50)"   # zoning envelope overlay

# LOW risk — greens
_CLR_LOW_1   = "rgba(16,185,129,0.38)"
_CLR_LOW_2   = "rgba(52,211,153,0.38)"
_CLR_LOW_3   = "rgba(110,231,183,0.38)"

# MED risk — ambers
_CLR_MED_1   = "rgba(245,158,11,0.42)"
_CLR_MED_2   = "rgba(251,191,36,0.42)"
_CLR_MED_3   = "rgba(253,224,71,0.42)"
_CLR_MED_4   = "rgba(234,179,8,0.42)"

# HIGH risk — reds
_CLR_HIGH_1  = "rgba(239,68,68,0.45)"
_CLR_HIGH_2  = "rgba(220,38,38,0.45)"
_CLR_HIGH_3  = "rgba(185,28,28,0.45)"


# ── Mesh helpers ──────────────────────────────────────────────────────────────

def _box_mesh(x0: float, y0: float, z0: float,
              x1: float, y1: float, z1: float,
              color: str = _CLR_MASS_1,
              name: str = "",
              show_legend: bool = True) -> go.Mesh3d:
    """
    Build a go.Mesh3d rectangular prism (box) from corner coordinates.
    Uses 8 vertices + 12 triangular faces (standard cube triangulation).
    """
    vx = [x0, x0, x1, x1, x0, x0, x1, x1]
    vy = [y0, y1, y1, y0, y0, y1, y1, y0]
    vz = [z0, z0, z0, z0, z1, z1, z1, z1]
    # Triangle indices for 6 faces (2 triangles each)
    ti = [7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2]
    tj = [3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3]
    tk = [0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6]
    return go.Mesh3d(
        x=vx, y=vy, z=vz,
        i=ti, j=tj, k=tk,
        color=color, opacity=0.45,
        name=name, showlegend=show_legend,
        flatshading=True,
        lighting=dict(ambient=0.7, diffuse=0.8, specular=0.1),
    )


def _line_box(x0, y0, z0, x1, y1, z1, color=_CLR_LINE, name="", width=2):
    """Wireframe edges of a box as go.Scatter3d lines."""
    # 12 edges of a box, each drawn as a segment with None separator
    edges = [
        # Bottom face
        (x0,y0,z0),(x1,y0,z0),(None,None,None),
        (x1,y0,z0),(x1,y1,z0),(None,None,None),
        (x1,y1,z0),(x0,y1,z0),(None,None,None),
        (x0,y1,z0),(x0,y0,z0),(None,None,None),
        # Top face
        (x0,y0,z1),(x1,y0,z1),(None,None,None),
        (x1,y0,z1),(x1,y1,z1),(None,None,None),
        (x1,y1,z1),(x0,y1,z1),(None,None,None),
        (x0,y1,z1),(x0,y0,z1),(None,None,None),
        # Verticals
        (x0,y0,z0),(x0,y0,z1),(None,None,None),
        (x1,y0,z0),(x1,y0,z1),(None,None,None),
        (x1,y1,z0),(x1,y1,z1),(None,None,None),
        (x0,y1,z0),(x0,y1,z1),(None,None,None),
    ]
    xs = [p[0] for p in edges]
    ys = [p[1] for p in edges]
    zs = [p[2] for p in edges]
    return go.Scatter3d(
        x=xs, y=ys, z=zs,
        mode="lines",
        line=dict(color=color, width=width),
        name=name, showlegend=False,
        hoverinfo="skip",
    )


def _label(x, y, z, text, size=11):
    return go.Scatter3d(
        x=[x], y=[y], z=[z],
        mode="text",
        text=[text],
        textfont=dict(size=size, color=_CLR_LINE),
        showlegend=False,
        hoverinfo="skip",
    )


# ── Layout helper ─────────────────────────────────────────────────────────────

def _base_layout(title: str, lot_front: float, lot_depth: float,
                 max_z: float) -> dict:
    pad = max(lot_front, lot_depth) * 0.15
    return dict(
        title=dict(text=title, font=dict(size=12, color="#111827"), x=0.5),
        scene=dict(
            xaxis=dict(title="", range=[-pad, lot_front + pad],
                       showbackground=False, gridcolor="#E5E7EB",
                       showticklabels=False),
            yaxis=dict(title="", range=[-pad, lot_depth + pad],
                       showbackground=False, gridcolor="#E5E7EB",
                       showticklabels=False),
            zaxis=dict(title="ft", range=[0, max_z * 1.20],
                       showbackground=False, gridcolor="#E5E7EB"),
            aspectmode="data",
            camera=dict(eye=dict(x=1.5, y=-1.5, z=1.1)),
            bgcolor="rgba(248,249,250,1)",
        ),
        margin=dict(l=0, r=0, t=32, b=0),
        paper_bgcolor="rgba(248,249,250,1)",
        height=320,
        legend=dict(x=0.01, y=0.99, bgcolor="rgba(255,255,255,0.70)",
                    font=dict(size=9)),
    )


# ── Zoning envelope overlay ───────────────────────────────────────────────────

def _zoning_envelope_traces(lot_front: float, lot_depth: float,
                             rules: dict) -> list:
    """
    Return a list of go.Scatter3d dashed-line traces showing the zoning
    development envelope (height limits, setback planes, sky exposure plane).
    All lines are faded grey dashes so they read as reference guides, not data.
    """
    traces: list = []
    env_kw = dict(color=_CLR_ENV, dash="dash", width=1)
    first  = True  # only the first trace carries the legend label

    def _env_line(xs, ys, zs, label="— Zoning Envelope"):
        nonlocal first
        t = go.Scatter3d(
            x=xs, y=ys, z=zs,
            mode="lines",
            line=env_kw,
            name=label if first else "",
            showlegend=first,
            hoverinfo="skip",
        )
        first = False
        return t

    def _hrect(z: float) -> go.Scatter3d:
        """Horizontal rectangle (height-limit plane) at elevation z."""
        xs = [0, lot_front, lot_front, 0, 0, None]
        ys = [0, 0, lot_depth, lot_depth, 0, None]
        zs = [z, z, z, z, z, None]
        return _env_line(xs, ys, zs)

    def _vrect_y(y: float, z_top: float) -> go.Scatter3d:
        """Vertical plane at constant Y (front/rear yard setback)."""
        xs = [0, lot_front, lot_front, 0, 0, None]
        ys = [y, y, y, y, y, None]
        zs = [0, 0, z_top, z_top, 0, None]
        return _env_line(xs, ys, zs)

    def _vrect_x(x: float, z_top: float) -> go.Scatter3d:
        """Vertical plane at constant X (side yard setback)."""
        xs = [x, x, x, x, x, None]
        ys = [0, lot_depth, lot_depth, 0, 0, None]
        zs = [0, 0, z_top, z_top, 0, None]
        return _env_line(xs, ys, zs)

    base_h = rules.get("base_height_ft", 0) or 0
    max_h  = rules.get("max_height_ft",  0) or 0
    fr     = rules.get("front_yard_ft",  0) or 0
    rr     = rules.get("rear_yard_ft",   0) or 0
    sy     = rules.get("side_yard_ft",   0) or 0
    z_ref  = max(base_h, max_h, 40)

    # 1. Base height plane
    if base_h > 0:
        traces.append(_hrect(base_h))

    # 2. Max height plane (only if different from base)
    if max_h > 0 and abs(max_h - base_h) > 2:
        traces.append(_hrect(max_h))

    # 3. Front yard setback
    if fr > 0:
        traces.append(_vrect_y(fr, z_ref))

    # 4. Rear yard setback
    if rr > 0:
        traces.append(_vrect_y(lot_depth - rr, z_ref))

    # 5. Side yard setbacks
    if sy > 0:
        traces.append(_vrect_x(sy, z_ref))
        traces.append(_vrect_x(lot_front - sy, z_ref))

    # 6. Sky exposure plane (2.7:1 slope from front street wall)
    if rules.get("sky_exp_plane") and base_h > 0:
        slope   = 1.0 / 2.7          # rise/run — for every 1 ft back, rises 1/2.7 ft
        max_run = min(lot_depth * 0.7, base_h / slope)
        steps   = 6
        sep_xs  = [0.0,  lot_front, None]
        sep_ys  = [fr,   fr,        None]
        sep_zs  = [base_h, base_h,  None]
        for i in range(1, steps + 1):
            run = max_run * i / steps
            z_s = base_h + run * slope
            sep_xs += [0.0, lot_front, None]
            sep_ys += [fr + run, fr + run, None]
            sep_zs += [z_s, z_s, None]
        traces.append(_env_line(sep_xs, sep_ys, sep_zs, "Sky Exp. Plane"))

    return traces


# ── Massing calculator ────────────────────────────────────────────────────────

def _calc_massing(lot_front: float, lot_depth: float, lot_area: float,
                  rules: dict) -> dict:
    """
    Compute key massing parameters from lot dimensions and zoning rules.
    Returns a dict of derived values used by all three massing options.
    """
    fr  = rules["front_yard_ft"]
    rr  = rules["rear_yard_ft"]
    sy  = rules["side_yard_ft"]

    # Buildable footprint after setbacks
    b_front = max(10, lot_front - 2 * sy)
    b_depth = max(10, lot_depth - fr - rr)
    footprint = b_front * b_depth

    # FAR to use (prefer residential, fall back to base)
    far = rules["res_far"] if rules["res_far"] > 0 else rules["base_far"]
    if far <= 0:
        far = rules["base_far"]

    total_area = lot_area * far

    # Height caps
    base_h = rules["base_height_ft"] or 40
    max_h  = rules["max_height_ft"]  or base_h * 2

    # Floor-to-floor assumption: 12 ft residential, 14 ft commercial
    f2f = 12.0

    # Typical floor plate for max envelope
    floors_at_base = max(1, int(base_h / f2f))
    typical_floor  = min(footprint, total_area / max(1, floors_at_base))

    return dict(
        b_front=b_front, b_depth=b_depth,
        footprint=footprint,
        fr=fr, rr=rr, sy=sy,
        far=far,
        total_area=total_area,
        base_h=base_h, max_h=max_h,
        f2f=f2f,
        floors_at_base=floors_at_base,
        typical_floor=typical_floor,
    )


# ── Shared scenario builder helpers ──────────────────────────────────────────

def _make_fig(lot_front, lot_depth, traces, title, height_ft, rules):
    """Assemble a go.Figure: lot boundary → envelope overlays → building traces."""
    base_traces = []
    # Lot boundary slab
    base_traces.append(_box_mesh(0, 0, 0, lot_front, lot_depth, 0.5,
                                  color=_CLR_LOT, name="Lot Boundary"))
    base_traces.append(_line_box(0, 0, 0, lot_front, lot_depth, 0.5,
                                  color="#9CA3AF"))
    # Zoning envelope overlays (faded dashed reference lines)
    base_traces.extend(_zoning_envelope_traces(lot_front, lot_depth, rules))
    # Building mass traces
    base_traces.extend(traces)
    fig = go.Figure(data=base_traces)
    fig.update_layout(_base_layout(title, lot_front, lot_depth, height_ft + 20))
    return fig


def _scenario_dict(name, risk_level, description, strategy,
                   fig, lot_area, far, height_ft, footprint_sqft,
                   floors, typical_floor_sqft, loss_factor,
                   is_conversion=False):
    """Build the standard scenario result dict."""
    total_sqft       = int(lot_area * far)
    net_rentable     = int(total_sqft * (1 - loss_factor))
    return {
        "name":               name,
        "risk_level":         risk_level,
        "description":        description,
        "strategy":           strategy,
        "fig":                fig,
        "total_sqft":         total_sqft,
        "floors":             max(1, floors),
        "typical_floor_sqft": max(1, int(typical_floor_sqft)),
        "height_ft":          max(1, int(height_ft)),
        "footprint_sqft":     max(1, int(footprint_sqft)),
        "loss_factor":        loss_factor,
        "net_rentable_sqft":  net_rentable,
        "is_conversion":      is_conversion,
    }


# ── 10 Scenario builders ──────────────────────────────────────────────────────

def _option_1(lot_front, lot_depth, lot_area, rules, m) -> dict:
    """LOW — Gut Renovation / Adaptive Reuse"""
    b_front, b_depth = m["b_front"], m["b_depth"]
    fr, rr, sy       = m["fr"], m["rr"], m["sy"]
    base_h, f2f      = m["base_h"], m["f2f"]
    far              = m["far"]

    fp_ratio = 0.85
    w = max(10.0, b_front * fp_ratio)
    d = max(10.0, b_depth * fp_ratio)
    x0 = sy + (b_front - w) / 2
    y0 = fr + (b_depth - d) / 2
    height = max(20.0, base_h * 0.60)
    floors = max(1, int(height / f2f))

    traces = [
        _box_mesh(x0, y0, 0, x0+w, y0+d, height, color=_CLR_LOW_1, name="Existing Structure"),
        _line_box(x0, y0, 0, x0+w, y0+d, height, color="#059669"),
        _label(lot_front/2, -2, height, f"{height:.0f} ft"),
    ]
    fig = _make_fig(lot_front, lot_depth, traces,
                    "1. Gut Renovation", height, rules)
    return _scenario_dict(
        name="Gut Renovation / Adaptive Reuse",
        risk_level="LOW",
        description=(
            f"Renovates existing structure to its current envelope (~{height:.0f} ft, "
            f"{floors} stories). Preserves the building shell, reducing structural risk "
            f"and entitlement exposure. 25% loss factor applied for conversion inefficiencies."
        ),
        strategy=(
            "Lowest-cost path to market-rate rents. Capture rent growth through "
            "renovation without new construction risk. Best for cash-flow stabilization."
        ),
        fig=fig,
        lot_area=lot_area, far=far * 0.60,
        height_ft=height, footprint_sqft=w*d,
        floors=floors, typical_floor_sqft=w*d,
        loss_factor=0.25, is_conversion=True,
    )


def _option_2(lot_front, lot_depth, lot_area, rules, m) -> dict:
    """LOW — Contextual Infill — Base Height"""
    b_front, b_depth = m["b_front"], m["b_depth"]
    fr, rr, sy       = m["fr"], m["rr"], m["sy"]
    base_h, f2f      = m["base_h"], m["f2f"]
    far              = m["far"]

    fp_ratio = 0.85
    w = max(10.0, b_front * fp_ratio)
    d = max(10.0, b_depth * fp_ratio)
    x0 = sy + (b_front - w) / 2
    y0 = fr + (b_depth - d) / 2
    height = base_h
    floors = max(1, int(height / f2f))

    traces = [
        _box_mesh(x0, y0, 0, x0+w, y0+d, height, color=_CLR_LOW_2, name="Building Mass"),
        _line_box(x0, y0, 0, x0+w, y0+d, height, color="#10B981"),
        _label(lot_front/2, -2, height, f"{height:.0f} ft"),
    ]
    fig = _make_fig(lot_front, lot_depth, traces,
                    "2. Contextual Infill", height, rules)
    return _scenario_dict(
        name="Contextual Infill — Base Height",
        risk_level="LOW",
        description=(
            f"Fills {fp_ratio*100:.0f}% of the buildable footprint to base height "
            f"({height:.0f} ft / {floors} floors). Fully as-of-right — no variances, "
            "special permits, or community board negotiation required."
        ),
        strategy=(
            "Lowest-risk new construction path. Maximizes predictability of schedule "
            "and cost. Targets contextual neighborhoods where community acceptance is high."
        ),
        fig=fig,
        lot_area=lot_area, far=far * fp_ratio,
        height_ft=height, footprint_sqft=w*d,
        floors=floors, typical_floor_sqft=w*d,
        loss_factor=0.15,
    )


def _option_3(lot_front, lot_depth, lot_area, rules, m) -> dict:
    """LOW — Low-Rise Residential (2–3 Stories)"""
    b_front, b_depth = m["b_front"], m["b_depth"]
    fr, rr, sy       = m["fr"], m["rr"], m["sy"]
    base_h, f2f      = m["base_h"], m["f2f"]
    far              = m["far"]

    fp_ratio = 0.80
    w = max(10.0, b_front * fp_ratio)
    d = max(10.0, b_depth * fp_ratio)
    x0 = sy + (b_front - w) / 2
    y0 = fr + (b_depth - d) / 2
    height = max(24.0, min(base_h, 35.0))
    floors = max(2, int(height / f2f))

    traces = [
        _box_mesh(x0, y0, 0, x0+w, y0+d, height, color=_CLR_LOW_3, name="Building Mass"),
        _line_box(x0, y0, 0, x0+w, y0+d, height, color="#34D399"),
        _label(lot_front/2, -2, height, f"{height:.0f} ft"),
    ]
    fig = _make_fig(lot_front, lot_depth, traces,
                    "3. Low-Rise Residential", height, rules)
    return _scenario_dict(
        name="Low-Rise Residential (2–3 Stories)",
        risk_level="LOW",
        description=(
            f"2–3 story building ({height:.0f} ft) across {fp_ratio*100:.0f}% of the "
            "buildable area. Ideal for R1–R5 districts and outer-borough infill. "
            "Lower construction cost and faster delivery than mid/high-rise."
        ),
        strategy=(
            "Sub-urban and outer-borough focus. Quicker lease-up vs. large projects. "
            "Lower per-unit construction cost; well-suited to family-oriented rentals."
        ),
        fig=fig,
        lot_area=lot_area, far=far * fp_ratio * (height / max(base_h, 1)),
        height_ft=height, footprint_sqft=w*d,
        floors=floors, typical_floor_sqft=w*d,
        loss_factor=0.15,
    )


def _option_4(lot_front, lot_depth, lot_area, rules, m) -> dict:
    """MED — Mid-Rise Mixed-Use"""
    b_front, b_depth = m["b_front"], m["b_depth"]
    fr, rr, sy       = m["fr"], m["rr"], m["sy"]
    base_h, f2f      = m["base_h"], m["f2f"]
    far              = m["far"]

    retail_h  = 15.0
    res_ratio = 0.85
    res_w = max(10.0, b_front * res_ratio)
    res_d = max(10.0, b_depth * res_ratio)
    ret_w = max(10.0, b_front * 0.90)
    ret_d = max(10.0, b_depth * 0.90)
    rx0 = sy + (b_front - ret_w) / 2
    ry0 = fr + (b_depth - ret_d) / 2
    rx1 = sx1 = sy + (b_front - res_w) / 2
    height = base_h
    floors = max(1, int((height - retail_h) / f2f)) + 1

    traces = [
        # Retail base
        _box_mesh(rx0, ry0, 0, rx0+ret_w, ry0+ret_d, retail_h,
                  color="rgba(99,102,241,0.40)", name="Retail / Commercial Base"),
        _line_box(rx0, ry0, 0, rx0+ret_w, ry0+ret_d, retail_h, color="#6366F1"),
        # Residential above
        _box_mesh(rx1, ry0 + (ret_d - res_d)/2, retail_h,
                  rx1+res_w, ry0 + (ret_d - res_d)/2 + res_d, height,
                  color=_CLR_MED_1, name="Residential Above"),
        _line_box(rx1, ry0 + (ret_d - res_d)/2, retail_h,
                  rx1+res_w, ry0 + (ret_d - res_d)/2 + res_d, height,
                  color="#D97706"),
        _label(lot_front/2, -2, height, f"{height:.0f} ft"),
    ]
    fig = _make_fig(lot_front, lot_depth, traces,
                    "4. Mid-Rise Mixed-Use", height, rules)
    return _scenario_dict(
        name="Mid-Rise Mixed-Use",
        risk_level="MED",
        description=(
            f"Ground-floor retail/commercial base ({retail_h:.0f} ft) topped by "
            f"residential floors to {height:.0f} ft total ({floors} stories). "
            "Two-program massing activates the street while adding income diversity."
        ),
        strategy=(
            "Ground-floor retail provides NOI diversification and improves street "
            "activation. Strong on high-foot-traffic corridors. Targets C1/C2 overlay zones."
        ),
        fig=fig,
        lot_area=lot_area, far=far * 0.90,
        height_ft=height, footprint_sqft=ret_w*ret_d,
        floors=floors, typical_floor_sqft=res_w*res_d,
        loss_factor=0.15,
    )


def _option_5(lot_front, lot_depth, lot_area, rules, m) -> dict:
    """MED — Standard Residential Tower"""
    b_front, b_depth = m["b_front"], m["b_depth"]
    fr, rr, sy       = m["fr"], m["rr"], m["sy"]
    base_h, max_h, f2f = m["base_h"], m["max_h"], m["f2f"]
    far              = m["far"]

    fp_ratio = 0.65
    w = max(10.0, b_front * fp_ratio)
    d = max(10.0, b_depth * fp_ratio)
    x0 = sy + (b_front - w) / 2
    y0 = fr + (b_depth - d) / 2
    height = max_h if max_h > 0 else base_h * 1.5
    height = max(height, 40.0)
    floors = max(1, int(height / f2f))

    traces = [
        _box_mesh(x0, y0, 0, x0+w, y0+d, height, color=_CLR_MED_2, name="Building Mass"),
        _line_box(x0, y0, 0, x0+w, y0+d, height, color="#F59E0B"),
        _label(lot_front/2, -2, height, f"{height:.0f} ft"),
    ]
    fig = _make_fig(lot_front, lot_depth, traces,
                    "5. Standard Tower", height, rules)
    return _scenario_dict(
        name="Standard Residential Tower",
        risk_level="MED",
        description=(
            f"65% buildable footprint rising to {height:.0f} ft ({floors} floors). "
            "Open space at grade improves amenity access. Standard R6–R8 development "
            "envelope — balances density with outdoor amenity."
        ),
        strategy=(
            "Mid-to-high-rise approach with open-space bonus potential. "
            "Appeals to amenity-driven renters. Strong NOI relative to construction cost."
        ),
        fig=fig,
        lot_area=lot_area, far=far * 0.65,
        height_ft=height, footprint_sqft=w*d,
        floors=floors, typical_floor_sqft=w*d,
        loss_factor=0.15,
    )


def _option_6(lot_front, lot_depth, lot_area, rules, m) -> dict:
    """MED — Courtyard Apartment"""
    b_front, b_depth = m["b_front"], m["b_depth"]
    fr, rr, sy       = m["fr"], m["rr"], m["sy"]
    base_h, f2f      = m["base_h"], m["f2f"]
    far              = m["far"]

    fp_ratio = 0.90
    w = max(10.0, b_front * fp_ratio)
    d = max(10.0, b_depth * fp_ratio)
    x0 = sy + (b_front - w) / 2
    y0 = fr + (b_depth - d) / 2
    height = base_h
    floors = max(1, int(height / f2f))

    ct_w = max(8.0, w * 0.30)
    ct_d = max(8.0, d * 0.30)
    ct_x = x0 + (w - ct_w) / 2
    ct_y = y0 + (d - ct_d) / 2
    net_floor = w * d - ct_w * ct_d

    traces = [
        _box_mesh(x0, y0, 0, x0+w, y0+d, height, color=_CLR_MED_3, name="Building Mass"),
        _line_box(x0, y0, 0, x0+w, y0+d, height, color="#CA8A04"),
        # Courtyard cutout (rendered as white void)
        _box_mesh(ct_x, ct_y, 0, ct_x+ct_w, ct_y+ct_d, height,
                  color="rgba(248,249,250,0.92)", name="Courtyard", show_legend=True),
        _line_box(ct_x, ct_y, 0, ct_x+ct_w, ct_y+ct_d, height,
                  color="#6EE7B7", width=2),
        _label(lot_front/2, -2, height, f"{height:.0f} ft"),
    ]
    fig = _make_fig(lot_front, lot_depth, traces,
                    "6. Courtyard Apartment", height, rules)
    return _scenario_dict(
        name="Courtyard Apartment",
        risk_level="MED",
        description=(
            f"Full perimeter building at {height:.0f} ft with a {ct_w:.0f}′×{ct_d:.0f}′ "
            "central light court. Classic NYC typology — all units get natural light and air. "
            f"Net floor plate ≈{net_floor:,.0f} SF per floor."
        ),
        strategy=(
            "Premium rents for all units due to natural light access. "
            "Strong for family-oriented renters. Higher per-unit cost offset by rent premium."
        ),
        fig=fig,
        lot_area=lot_area, far=far * fp_ratio * (net_floor / max(1, w*d)),
        height_ft=height, footprint_sqft=int(net_floor),
        floors=floors, typical_floor_sqft=int(net_floor),
        loss_factor=0.15,
    )


def _option_7(lot_front, lot_depth, lot_area, rules, m) -> dict:
    """MED — Stacked Townhouse / Rowhouse"""
    b_front, b_depth = m["b_front"], m["b_depth"]
    fr, rr, sy       = m["fr"], m["rr"], m["sy"]
    base_h, f2f      = m["base_h"], m["f2f"]
    far              = m["far"]

    fp_ratio = 0.95
    w = max(10.0, b_front * fp_ratio)
    d = max(10.0, b_depth * fp_ratio)
    x0 = sy + (b_front - w) / 2
    y0 = fr
    height = max(30.0, min(base_h, 45.0))
    floors = max(3, int(height / f2f))

    traces = [
        _box_mesh(x0, y0, 0, x0+w, y0+d, height, color=_CLR_MED_4, name="Building Mass"),
        _line_box(x0, y0, 0, x0+w, y0+d, height, color="#B45309"),
        _label(lot_front/2, -2, height, f"{height:.0f} ft"),
    ]
    fig = _make_fig(lot_front, lot_depth, traces,
                    "7. Stacked Townhouse", height, rules)
    return _scenario_dict(
        name="Stacked Townhouse / Rowhouse",
        risk_level="MED",
        description=(
            f"3–4 story attached rowhouses or stacked townhouse format at {height:.0f} ft. "
            "Full frontage build-out creates a continuous street wall. Works well in "
            "contextual R4–R6 districts where street character is preserved."
        ),
        strategy=(
            "Townhouse premiums of 15–20% above comparable apartments. "
            "Appeals to families and tenants seeking multi-floor private living."
        ),
        fig=fig,
        lot_area=lot_area, far=far * fp_ratio * (height / max(base_h, 1)),
        height_ft=height, footprint_sqft=w*d,
        floors=floors, typical_floor_sqft=int(w*d/floors),
        loss_factor=0.15,
    )


def _option_8(lot_front, lot_depth, lot_area, rules, m) -> dict:
    """HIGH — Max FAR Residential Tower"""
    b_front, b_depth = m["b_front"], m["b_depth"]
    fr, rr, sy       = m["fr"], m["rr"], m["sy"]
    base_h, max_h, f2f = m["base_h"], m["max_h"], m["f2f"]
    far              = m["far"]

    fp_ratio = 0.55
    w = max(10.0, b_front * fp_ratio)
    d = max(10.0, b_depth * fp_ratio)
    x0 = sy + (b_front - w) / 2
    y0 = fr + (b_depth - d) / 2
    height = max(80.0, max_h if max_h > 0 else base_h * 2.5)
    floors = max(1, int(height / f2f))

    traces = [
        _box_mesh(x0, y0, 0, x0+w, y0+d, height, color=_CLR_HIGH_1, name="Building Mass"),
        _line_box(x0, y0, 0, x0+w, y0+d, height, color="#DC2626"),
        _label(lot_front/2, -2, height, f"{height:.0f} ft"),
    ]
    fig = _make_fig(lot_front, lot_depth, traces,
                    "8. Max FAR Tower", height, rules)
    return _scenario_dict(
        name="Max FAR Residential Tower",
        risk_level="HIGH",
        description=(
            f"55% footprint tower rising to {height:.0f} ft ({floors} floors), "
            "utilizing maximum permitted residential FAR. Full air rights build-out "
            "maximizes rentable area and exit value."
        ),
        strategy=(
            "Maximizes gross value and rental income. Requires deep equity, robust "
            "construction budget, and premium rents to pencil. Best for institutional capital."
        ),
        fig=fig,
        lot_area=lot_area, far=far,
        height_ft=height, footprint_sqft=w*d,
        floors=floors, typical_floor_sqft=w*d,
        loss_factor=0.15,
    )


def _option_9(lot_front, lot_depth, lot_area, rules, m) -> dict:
    """HIGH — Slender Luxury Tower"""
    b_front, b_depth = m["b_front"], m["b_depth"]
    fr, rr, sy       = m["fr"], m["rr"], m["sy"]
    base_h, max_h, f2f = m["base_h"], m["max_h"], m["f2f"]
    far              = m["far"]

    fp_ratio = 0.30
    w = max(10.0, b_front * fp_ratio)
    d = max(10.0, b_depth * fp_ratio)
    x0 = sy + (b_front - w) / 2
    y0 = fr + (b_depth - d) / 2
    height = max_h * 1.2 if max_h > 0 else base_h * 3
    height = min(400.0, max(100.0, height))
    floors = max(1, int(height / f2f))

    traces = [
        _box_mesh(x0, y0, 0, x0+w, y0+d, height, color=_CLR_HIGH_2, name="Building Mass"),
        _line_box(x0, y0, 0, x0+w, y0+d, height, color="#B91C1C"),
        _label(lot_front/2, -2, height, f"{height:.0f} ft"),
    ]
    fig = _make_fig(lot_front, lot_depth, traces,
                    "9. Slender Luxury Tower", height, rules)
    return _scenario_dict(
        name="Slender Luxury Tower",
        risk_level="HIGH",
        description=(
            f"Ultra-slim 30% footprint tower rising to {height:.0f} ft ({floors} floors). "
            "Maximizes height over footprint for view premium and luxury positioning. "
            "Requires favorable sky exposure plane or tower rules."
        ),
        strategy=(
            "Luxury/condo-conversion pricing premium on upper floors. "
            "High construction cost per SF offset by top-floor revenue. "
            "Best for sites with unobstructed views or air rights acquisitions."
        ),
        fig=fig,
        lot_area=lot_area, far=far * fp_ratio,
        height_ft=height, footprint_sqft=w*d,
        floors=floors, typical_floor_sqft=w*d,
        loss_factor=0.15,
    )


def _option_10(lot_front, lot_depth, lot_area, rules, m) -> dict:
    """HIGH — Full Development — Max Bonus FAR (IH/MIH)"""
    b_front, b_depth = m["b_front"], m["b_depth"]
    fr, rr, sy       = m["fr"], m["rr"], m["sy"]
    base_h, max_h, f2f = m["base_h"], m["max_h"], m["f2f"]
    far              = m["far"]

    fp_ratio = 0.60
    w = max(10.0, b_front * fp_ratio)
    d = max(10.0, b_depth * fp_ratio)
    x0 = sy + (b_front - w) / 2
    y0 = fr + (b_depth - d) / 2

    bonus_far   = far * 1.20
    fp_sqft     = w * d
    height_raw  = (bonus_far * lot_area / fp_sqft) / f2f * f2f
    height      = min(300.0, max(base_h, height_raw))
    floors      = max(1, int(height / f2f))

    # Color: darker red for IH bonus
    traces = [
        _box_mesh(x0, y0, 0, x0+w, y0+d, height, color=_CLR_HIGH_3, name="Building Mass"),
        _line_box(x0, y0, 0, x0+w, y0+d, height, color="#991B1B"),
        _label(lot_front/2, -2, height, f"{height:.0f} ft"),
    ]
    fig = _make_fig(lot_front, lot_depth, traces,
                    "10. Max Bonus FAR (IH)", height, rules)
    return _scenario_dict(
        name="Full Development — Max Bonus FAR (IH)",
        risk_level="HIGH",
        description=(
            f"Full 60% footprint development using Inclusionary Housing (IH/MIH) "
            f"+20% FAR bonus, reaching {height:.0f} ft ({floors} floors). "
            "20–25% of units must be affordable (MIH Option 1 or 2)."
        ),
        strategy=(
            "Unlocks additional FAR and potential public subsidy (421-a/485-x successor). "
            "Maximizes gross value while satisfying affordability requirements. "
            "Requires ULURP or MIH compliance — plan for 18-month review timeline."
        ),
        fig=fig,
        lot_area=lot_area, far=bonus_far,
        height_ft=height, footprint_sqft=w*d,
        floors=floors, typical_floor_sqft=w*d,
        loss_factor=0.15,
    )


def build_massing_options(
    lot_front_ft: float,
    lot_depth_ft: float,
    lot_area_sqft: float,
    zoning_district: str,
    rules: dict,
) -> list[dict]:
    """
    Generate 10 massing scenario dicts for the given lot + zoning rules.

    Scenarios span three investment risk tiers:
      LOW  (1–3): Gut Reno, Contextual Infill, Low-Rise
      MED  (4–7): Mixed-Use, Standard Tower, Courtyard, Rowhouse
      HIGH (8–10): Max FAR Tower, Slender Luxury, Max Bonus FAR

    Each dict contains:
      name, risk_level, description, strategy, fig (go.Figure),
      total_sqft, floors, typical_floor_sqft, height_ft, footprint_sqft,
      loss_factor, net_rentable_sqft, is_conversion

    Returns an empty list if inputs are invalid or rules has no FAR.
    """
    try:
        lot_front = max(10.0, float(lot_front_ft))
        lot_depth = max(10.0, float(lot_depth_ft))
        lot_area  = max(100.0, float(lot_area_sqft))
    except (TypeError, ValueError):
        return []

    if not rules or rules.get("base_far", 0) <= 0:
        return []

    m = _calc_massing(lot_front, lot_depth, lot_area, rules)

    return [
        _option_1(lot_front, lot_depth, lot_area, rules, m),
        _option_2(lot_front, lot_depth, lot_area, rules, m),
        _option_3(lot_front, lot_depth, lot_area, rules, m),
        _option_4(lot_front, lot_depth, lot_area, rules, m),
        _option_5(lot_front, lot_depth, lot_area, rules, m),
        _option_6(lot_front, lot_depth, lot_area, rules, m),
        _option_7(lot_front, lot_depth, lot_area, rules, m),
        _option_8(lot_front, lot_depth, lot_area, rules, m),
        _option_9(lot_front, lot_depth, lot_area, rules, m),
        _option_10(lot_front, lot_depth, lot_area, rules, m),
    ]

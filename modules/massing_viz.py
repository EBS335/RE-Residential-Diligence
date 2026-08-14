"""
3D Building Massing Visualizations using Plotly — 10 Scenarios.

Generates interactive 3D diagrams of NYC building envelopes for 10 distinct
design scenarios spanning Low / Medium / High investment risk tiers.

Each scenario includes:
  - Colored 3D building mass (Mesh3d + wireframe)
  - Lot boundary footprint
  - Faded dashed zoning envelope overlay (height limits, setback planes, SEP)

Scenarios:
  LOW RISK (2)
    1. Gut Renovation / Adaptive Reuse        (25% loss factor)
    2. Contextual Infill — Base Height         (15% loss factor)
  MEDIUM RISK (3)
    3. Low-Rise Residential (2–3 stories)      (15% loss factor)
    4. Mid-Rise Mixed-Use                      (15% loss factor)
    5. Standard Residential Tower              (15% loss factor)
  HIGH RISK (5)
    6. Max FAR — 60% Footprint                 (15% loss factor)
    7. Max FAR — 75% Footprint, Lower Height   (15% loss factor)
    8. Max FAR — Full Coverage + Stepped       (15% loss factor)
    9. Max FAR + IH/MIH Bonus (+20% FAR)       (15% loss factor)
   10. Height Maximizer — Slender Tower        (15% loss factor)

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

# MED risk — ambers
_CLR_MED_1   = "rgba(245,158,11,0.42)"
_CLR_MED_2   = "rgba(251,191,36,0.42)"
_CLR_MED_3   = "rgba(253,224,71,0.42)"

# HIGH risk — reds
_CLR_HIGH_1  = "rgba(239,68,68,0.45)"
_CLR_HIGH_2  = "rgba(220,38,38,0.45)"
_CLR_HIGH_3  = "rgba(185,28,28,0.45)"
_CLR_HIGH_4  = "rgba(153,27,27,0.45)"
_CLR_HIGH_5  = "rgba(127,29,29,0.48)"

# Use-type colors
_CLR_RETAIL  = "rgba(99,102,241,0.45)"    # indigo — retail/commercial base
_CLR_COMM    = "rgba(59,130,246,0.40)"    # steel blue — commercial office
_CLR_NBR     = "rgba(150,150,150,0.22)"   # gray — neighboring buildings


# ── Mesh helpers ──────────────────────────────────────────────────────────────

def _box_mesh(x0: float, y0: float, z0: float,
              x1: float, y1: float, z1: float,
              color: str = _CLR_LOW_1,
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
        title=dict(text=title, font=dict(size=12, color="#EDEFF5"), x=0.5),
        scene=dict(
            xaxis=dict(title="", range=[-pad, lot_front + pad],
                       showbackground=False, gridcolor="#26304A",
                       showticklabels=False),
            yaxis=dict(title="", range=[-pad, lot_depth + pad],
                       showbackground=False, gridcolor="#26304A",
                       showticklabels=False),
            zaxis=dict(title="ft", range=[0, max_z * 1.20],
                       showbackground=False, gridcolor="#26304A",
                       color="#8590A8"),
            aspectmode="data",
            camera=dict(eye=dict(x=1.5, y=-1.5, z=1.1)),
            bgcolor="#121826",
        ),
        margin=dict(l=0, r=0, t=32, b=0),
        paper_bgcolor="#121826",
        height=320,
        legend=dict(x=0.01, y=0.99, bgcolor="rgba(18,24,38,0.75)",
                    font=dict(size=9, color="#C7CDDB")),
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

    # FAR to use — take the highest of residential, commercial, and base
    res_f  = rules.get("res_far",  0) or 0
    comm_f = rules.get("comm_far", 0) or 0
    base_f = rules.get("base_far", 0) or 0
    far = max(res_f, comm_f, base_f)
    if far <= 0:
        far = base_f or 1.0
    # Track which FAR type governs for display annotation
    far_type = (
        "Commercial FAR" if (comm_f > res_f and comm_f >= base_f and comm_f > 0)
        else ("Residential FAR" if (res_f > 0 and res_f >= base_f)
        else "Base FAR")
    )

    total_area = lot_area * far

    # Height caps — max_h=0 means no absolute limit (SEP zones or unlimited)
    base_h = rules.get("base_height_ft") or 40
    max_h  = rules.get("max_height_ft")  or 0

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
        far_type=far_type,
        total_area=total_area,
        base_h=base_h, max_h=max_h,
        f2f=f2f,
        floors_at_base=floors_at_base,
        typical_floor=typical_floor,
    )


def _far_height(far: float, lot_area: float, fp_sqft: float, f2f: float,
                base_h: float, max_h: float, min_h: float = 20.0) -> float:
    """
    Height needed to realise `far` on `fp_sqft` footprint.
    Always ≥ base_h (front-wall/street-wall requirement).
    Capped at max_h when max_h > 0 (absolute height limit).
    max_h == 0 means no absolute cap (sky-exposure-plane zones).
    """
    if fp_sqft > 0:
        implied = (far * lot_area / fp_sqft) * f2f
    else:
        implied = base_h or min_h
    h = max(min_h, base_h, implied)
    if max_h > 0:
        h = min(h, max_h)
    return min(h, 600.0)


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


def _lot_boundary_traces(lot_widths: list, lot_depth: float) -> list:
    """
    Draw horizontal lines on the XY ground plane showing individual lot boundaries.
    Only called when multiple lots are merged. Draws N-1 lines (skips the outer edges).
    """
    traces = []
    x_offset = 0.0
    first = True
    for w in lot_widths[:-1]:
        x_offset += float(w)
        traces.append(go.Scatter3d(
            x=[x_offset, x_offset],
            y=[0, lot_depth],
            z=[1, 1],
            mode="lines",
            line=dict(color="#6366F1", width=4),
            name="Lot Boundary" if first else "",
            showlegend=first,
            hoverinfo="skip",
        ))
        first = False
    return traces


def _sep_stepped_boxes(
    x_center: float, y_front: float,
    base_w: float, base_d: float,
    base_h: float, max_h: float,
    color: str, wire_color: str,
    name: str,
) -> list:
    """
    Build multi-step building massing that steps back per NYC Sky Exposure Plane.
    SEP slope: 2.7 horizontal per 1 vertical (i.e. rise = run / 2.7).
    Generates 3 steps: base, mid-step, top.
    """
    slope = 2.7  # horizontal ft per 1 ft rise
    traces = []

    if base_h > 0 and max_h > base_h:
        step_heights = [
            (0,      base_h,              base_w,    base_d),
            (base_h, base_h + (max_h - base_h) * 0.4,
             max(10, base_w - 2 * (max_h - base_h) * 0.4 / slope),
             max(10, base_d - (max_h - base_h) * 0.4 / slope)),
            (base_h + (max_h - base_h) * 0.4, max_h,
             max(10, base_w - 2 * (max_h - base_h) / slope),
             max(10, base_d - (max_h - base_h) / slope)),
        ]
    else:
        step_heights = [(0, max(base_h, max_h, 40.0), base_w, base_d)]

    first = True
    for z0, z1, sw, sd in step_heights:
        if z1 <= z0:
            continue
        sx0 = x_center - sw / 2
        sx1 = x_center + sw / 2
        sy0 = y_front
        sy1 = y_front + sd
        traces.append(_box_mesh(sx0, sy0, z0, sx1, sy1, z1,
                                color=color, name=name if first else "",
                                show_legend=first))
        traces.append(_line_box(sx0, sy0, z0, sx1, sy1, z1, color=wire_color))
        first = False

    return traces


def _scenario_dict(name, risk_level, description, strategy,
                   fig, lot_area, far, height_ft, footprint_sqft,
                   floors, typical_floor_sqft, loss_factor,
                   is_conversion=False, number=0):
    """Build the standard scenario result dict."""
    total_sqft       = int(lot_area * far)
    net_rentable     = int(total_sqft * (1 - loss_factor))
    units_est        = max(1, int(net_rentable / 750))
    return {
        "number":             number,
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
        "units_est":          units_est,
        "is_conversion":      is_conversion,
    }


def _floor_table_html(tiers: list) -> str:
    """Build a compact HTML floor-table for embedding in scenario descriptions.

    tiers: list of dicts with keys:
        label (str), floor_start (int), floor_end (int),
        width_ft (float), depth_ft (float), floor_sqft (float)
    """
    rows = ""
    for t in tiers:
        fl_range = (str(t["floor_start"]) if t["floor_start"] == t["floor_end"]
                    else f"{t['floor_start']}–{t['floor_end']}")
        rows += (
            f"<tr>"
            f"<td style='padding:2px 6px;font-weight:600'>{t['label']}</td>"
            f"<td style='padding:2px 6px;text-align:center'>{fl_range}</td>"
            f"<td style='padding:2px 6px;text-align:right'>"
            f"{t['width_ft']:.0f}′×{t['depth_ft']:.0f}′</td>"
            f"<td style='padding:2px 6px;text-align:right'>"
            f"{int(t['floor_sqft']):,} SF</td>"
            f"</tr>"
        )
    return (
        "<table style='width:100%;border-collapse:collapse;font-size:0.72rem;"
        "margin-top:6px;border:1px solid #E5E7EB'>"
        "<thead><tr style='background:#F3F4F6'>"
        "<th style='padding:3px 6px;text-align:left'>Tier</th>"
        "<th style='padding:3px 6px;text-align:center'>Floors</th>"
        "<th style='padding:3px 6px;text-align:right'>Plate Size</th>"
        "<th style='padding:3px 6px;text-align:right'>Floor SF</th>"
        "</tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


# ── 10 Scenario builders ──────────────────────────────────────────────────────

def _option_1(lot_front, lot_depth, lot_area, rules, m, existing_bldg=None) -> dict:
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
    if existing_bldg and existing_bldg.get("floors", 0) > 0:
        height = max(20.0, float(existing_bldg["floors"]) * 11.0)
    else:
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
        name="1. Gut Renovation / Adaptive Reuse",
        risk_level="LOW",
        number=1,
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
        name="2. Contextual Infill — Base Height",
        risk_level="LOW",
        number=2,
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
        lot_area=lot_area, far=far,
        height_ft=height, footprint_sqft=w*d,
        floors=floors, typical_floor_sqft=w*d,
        loss_factor=0.15,
    )


def _option_3(lot_front, lot_depth, lot_area, rules, m) -> dict:
    """MED — Low-Rise Residential (2–3 Stories)"""
    b_front, b_depth = m["b_front"], m["b_depth"]
    fr, rr, sy       = m["fr"], m["rr"], m["sy"]
    base_h, max_h, f2f = m["base_h"], m["max_h"], m["f2f"]
    far              = m["far"]

    fp_ratio = 0.80
    w = max(10.0, b_front * fp_ratio)
    d = max(10.0, b_depth * fp_ratio)
    x0 = sy + (b_front - w) / 2
    y0 = fr + (b_depth - d) / 2
    height = max(24.0, min(base_h, 35.0))
    if max_h > 0:
        height = min(height, max_h)
    floors = max(2, int(height / f2f))

    traces = [
        _box_mesh(x0, y0, 0, x0+w, y0+d, height, color=_CLR_MED_3, name="Building Mass"),
        _line_box(x0, y0, 0, x0+w, y0+d, height, color="#CA8A04"),
        _label(lot_front/2, -2, height, f"{height:.0f} ft"),
    ]
    fig = _make_fig(lot_front, lot_depth, traces,
                    "3. Low-Rise Residential", height, rules)
    return _scenario_dict(
        name="3. Low-Rise Residential (2–3 Stories)",
        risk_level="MED",
        number=3,
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
        lot_area=lot_area, far=far,
        height_ft=height, footprint_sqft=w*d,
        floors=floors, typical_floor_sqft=w*d,
        loss_factor=0.15,
    )


def _option_4(lot_front, lot_depth, lot_area, rules, m) -> dict:
    """MED — Mid-Rise Mixed-Use"""
    b_front, b_depth = m["b_front"], m["b_depth"]
    fr, rr, sy       = m["fr"], m["rr"], m["sy"]
    base_h, max_h, f2f = m["base_h"], m["max_h"], m["f2f"]
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
    if max_h > 0:
        height = min(height, max_h)
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
        name="4. Mid-Rise Mixed-Use",
        risk_level="MED",
        number=4,
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
        lot_area=lot_area, far=far,
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
    height = _far_height(far, lot_area, w * d, f2f, base_h, max_h, min_h=40.0)
    floors = max(1, int(height / f2f))

    x_center = sy + b_front / 2
    if rules.get("sky_exp_plane") and base_h > 0 and height > base_h:
        traces = _sep_stepped_boxes(x_center, fr, w, d, base_h, height,
                                    _CLR_MED_2, "#F59E0B", "Building Mass")
    else:
        traces = [
            _box_mesh(x0, y0, 0, x0+w, y0+d, height, color=_CLR_MED_2, name="Building Mass"),
            _line_box(x0, y0, 0, x0+w, y0+d, height, color="#F59E0B"),
        ]
    traces.append(_label(lot_front/2, -2, height, f"{height:.0f} ft"))
    fig = _make_fig(lot_front, lot_depth, traces,
                    "5. Standard Tower", height, rules)
    return _scenario_dict(
        name="5. Standard Residential Tower",
        risk_level="MED",
        number=5,
        description=(
            f"**65% buildable footprint** rising to **{height:.0f} ft** (**{floors} floors**). "
            "Open space at grade improves amenity access. Standard R6–R8 development "
            "envelope — balances density with outdoor amenity at **90% FAR utilization**."
        ),
        strategy=(
            "Mid-to-high-rise approach with open-space bonus potential. "
            "Appeals to amenity-driven renters. **Strong NOI** relative to construction cost."
        ),
        fig=fig,
        lot_area=lot_area, far=far,
        height_ft=height, footprint_sqft=w*d,
        floors=floors, typical_floor_sqft=w*d,
        loss_factor=0.15,
    )


def _option_6(lot_front, lot_depth, lot_area, rules, m) -> dict:
    """HIGH — Max FAR — Full Buildable Footprint, Standard Setbacks"""
    b_front, b_depth = m["b_front"], m["b_depth"]
    fr, rr, sy       = m["fr"], m["rr"], m["sy"]
    base_h, max_h, f2f = m["base_h"], m["max_h"], m["f2f"]
    far              = m["far"]

    # Full buildable footprint — fills to every required setback line
    w  = max(10.0, b_front)
    d  = max(10.0, b_depth)
    x0 = sy
    y0 = fr
    height = _far_height(far, lot_area, w * d, f2f, base_h, max_h, min_h=base_h)
    floors = max(1, int(height / f2f))

    x_center = sy + b_front / 2
    if rules.get("sky_exp_plane") and base_h > 0 and height > base_h:
        traces = _sep_stepped_boxes(x_center, fr, w, d, base_h, height,
                                    _CLR_HIGH_1, "#DC2626", "Building Mass")
    else:
        traces = [
            _box_mesh(x0, y0, 0, x0+w, y0+d, height, color=_CLR_HIGH_1, name="Building Mass"),
            _line_box(x0, y0, 0, x0+w, y0+d, height, color="#DC2626"),
        ]
    traces.append(_label(lot_front/2, -2, height, f"{height:.0f} ft"))
    fig = _make_fig(lot_front, lot_depth, traces,
                    "6. Max FAR — Full Buildable Footprint", height, rules)
    floor_tbl = _floor_table_html([{
        "label": "All Floors", "floor_start": 1, "floor_end": floors,
        "width_ft": w, "depth_ft": d, "floor_sqft": w * d,
    }])
    return _scenario_dict(
        name="6. Max FAR — Full Buildable Footprint",
        risk_level="HIGH",
        number=6,
        description=(
            f"**Full buildable footprint** ({w:.0f}′×{d:.0f}′ = {w*d:,.0f} SF) filling every "
            f"required setback line, rising to **{height:.0f} ft** (**{floors} floors**). "
            "Maximum floor-plate efficiency — no setback margin wasted. "
            "Fully as-of-right at max FAR with standard front/rear/side yards."
            + floor_tbl
        ),
        strategy=(
            "Largest possible floor plate at standard setbacks maximizes rentable SF per floor "
            "and lowers construction cost per unit. Best for residential or mixed-use at "
            "**full air rights build-out** with institutional capital."
        ),
        fig=fig,
        lot_area=lot_area, far=far,
        height_ft=height, footprint_sqft=w*d,
        floors=floors, typical_floor_sqft=w*d,
        loss_factor=0.15,
    )


def _option_7(lot_front, lot_depth, lot_area, rules, m) -> dict:
    """HIGH — Max FAR — 75% Footprint, Reduced Setbacks"""
    b_front, b_depth = m["b_front"], m["b_depth"]
    fr, rr, sy       = m["fr"], m["rr"], m["sy"]
    base_h, max_h, f2f = m["base_h"], m["max_h"], m["f2f"]
    far              = m["far"]

    fp_ratio = 0.75
    # Reduced side yards for larger footprint
    red_sy = max(0.0, sy * 0.5)
    w = max(10.0, b_front - 2 * red_sy)
    d = max(10.0, b_depth - fr - max(0.0, rr * 0.6))
    w = min(w, b_front * fp_ratio)
    x0 = red_sy
    y0 = fr
    height = _far_height(far, lot_area, w * d, f2f, base_h, max_h, min_h=40.0)
    floors = max(1, int(height / f2f))

    traces = [
        _box_mesh(x0, y0, 0, x0+w, y0+d, height, color=_CLR_HIGH_2, name="Building Mass"),
        _line_box(x0, y0, 0, x0+w, y0+d, height, color="#B91C1C"),
        _label(lot_front/2, -2, height, f"{height:.0f} ft"),
    ]
    fig = _make_fig(lot_front, lot_depth, traces,
                    "7. Max FAR Tower (75%)", height, rules)
    return _scenario_dict(
        name="7. Max FAR — 75% Footprint, Reduced Setbacks",
        risk_level="HIGH",
        number=7,
        description=(
            f"**Large 75% footprint** ({w:.0f}′×{d:.0f}′) with reduced side yards, "
            f"rising to **{height:.0f} ft** (**{floors} floors**). "
            "Wide floor plates maximize typical-floor efficiency. "
            "Requires setback waivers or variance — higher entitlement risk."
        ),
        strategy=(
            "Wide floor plates reduce core-to-perimeter ratio, improving unit mix flexibility. "
            "Lower per-floor cost; offset by entitlement complexity. Good for large family units."
        ),
        fig=fig,
        lot_area=lot_area, far=far,
        height_ft=height, footprint_sqft=w*d,
        floors=floors, typical_floor_sqft=w*d,
        loss_factor=0.15,
    )


def _option_8(lot_front, lot_depth, lot_area, rules, m) -> dict:
    """HIGH — Max FAR — Full Setback Podium + 75% Footprint Tower"""
    b_front, b_depth = m["b_front"], m["b_depth"]
    fr, rr, sy       = m["fr"], m["rr"], m["sy"]
    base_h, max_h, f2f = m["base_h"], m["max_h"], m["f2f"]
    far              = m["far"]

    # Podium: full buildable footprint at setback lines, up to base height
    pod_w = max(10.0, b_front)
    pod_d = max(10.0, b_depth)
    pod_h = max(base_h, 20.0)
    if max_h > 0:
        pod_h = min(pod_h, max_h)
    pod_floors = max(1, int(pod_h / f2f))

    # Tower above podium: 75% of buildable footprint, centered
    # Smaller plate → same FAR requires more floors → significantly taller than option 6
    tw  = max(10.0, pod_w * 0.75)
    td  = max(10.0, pod_d * 0.75)
    tx0 = sy + (b_front - tw) / 2
    ty0 = fr + (pod_d - td) / 2
    x_center = sy + b_front / 2

    height = _far_height(far, lot_area, tw * td, f2f, pod_h, max_h, min_h=pod_h + 12.0)
    floors = max(1, int(height / f2f))
    tower_floors = max(0, floors - pod_floors)

    traces = [
        # Podium fills full setback envelope
        _box_mesh(sy, fr, 0, sy + pod_w, fr + pod_d, pod_h,
                  color=_CLR_HIGH_3, name="Podium"),
        _line_box(sy, fr, 0, sy + pod_w, fr + pod_d, pod_h,
                  color="#991B1B"),
    ]
    # Tower above — SEP applies to tower footprint; plain box otherwise
    if height > pod_h:
        if rules.get("sky_exp_plane"):
            traces.extend(_sep_stepped_boxes(
                x_center, ty0, tw, td, pod_h, height,
                _CLR_HIGH_3, "#991B1B", "Tower Above",
            ))
        else:
            traces.extend([
                _box_mesh(tx0, ty0, pod_h, tx0 + tw, ty0 + td, height,
                          color=_CLR_HIGH_3, name="Tower Above"),
                _line_box(tx0, ty0, pod_h, tx0 + tw, ty0 + td, height,
                          color="#991B1B"),
            ])
    traces.append(_label(lot_front/2, -2, height, f"{height:.0f} ft"))
    fig = _make_fig(lot_front, lot_depth, traces,
                    "8. Full Setback Podium + 75% Tower", height, rules)
    tiers = [{
        "label": "Podium", "floor_start": 1, "floor_end": pod_floors,
        "width_ft": pod_w, "depth_ft": pod_d, "floor_sqft": pod_w * pod_d,
    }]
    if tower_floors > 0:
        tiers.append({
            "label": "Tower", "floor_start": pod_floors + 1, "floor_end": floors,
            "width_ft": tw, "depth_ft": td, "floor_sqft": tw * td,
        })
    floor_tbl = _floor_table_html(tiers)
    return _scenario_dict(
        name="8. Max FAR — Full Setback Podium + 75% Tower",
        risk_level="HIGH",
        number=8,
        description=(
            f"**Full buildable footprint** podium ({pod_w:.0f}′×{pod_d:.0f}′) to {pod_h:.0f} ft "
            f"({pod_floors} floors), then **75% footprint tower** ({tw:.0f}′×{td:.0f}′) above — "
            f"total **{height:.0f} ft** (**{floors} floors**). "
            "Narrower tower plate converts FAR into additional height well above option 6."
            + floor_tbl
        ),
        strategy=(
            "Largest possible ground floor program at every setback line; narrower tower above "
            "maximizes height while keeping lower floors at full coverage. "
            "Ideal for high-foot-traffic corridors — maximizes both commercial and residential income."
        ),
        fig=fig,
        lot_area=lot_area, far=far,
        height_ft=height, footprint_sqft=pod_w * pod_d,
        floors=floors, typical_floor_sqft=tw * td,
        loss_factor=0.15,
    )


def _option_9(lot_front, lot_depth, lot_area, rules, m) -> dict:
    """HIGH — Max FAR + IH/MIH Bonus (+20% FAR)"""
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
    # Use bonus FAR for height but still respect max_h (if any)
    height = _far_height(bonus_far, lot_area, w * d, f2f, base_h, max_h, min_h=base_h)
    floors = max(1, int(height / f2f))

    traces = [
        _box_mesh(x0, y0, 0, x0+w, y0+d, height, color=_CLR_HIGH_4, name="Building Mass"),
        _line_box(x0, y0, 0, x0+w, y0+d, height, color="#991B1B"),
        _label(lot_front/2, -2, height, f"{height:.0f} ft"),
    ]
    fig = _make_fig(lot_front, lot_depth, traces,
                    "9. Max Bonus FAR (IH/MIH)", height, rules)
    return _scenario_dict(
        name="9. Max FAR + IH/MIH Bonus",
        risk_level="HIGH",
        number=9,
        description=(
            f"**Full 60% footprint** using **Inclusionary Housing (IH/MIH) +20% FAR bonus**, "
            f"reaching **{height:.0f} ft** (**{floors} floors**). "
            "20–25% of units must be affordable (MIH Option 1 or 2)."
        ),
        strategy=(
            "Unlocks additional FAR and potential **public subsidy (421-a/485-x successor)**. "
            "Maximizes gross value while satisfying affordability requirements. "
            "Requires ULURP or MIH compliance — plan for **18-month review timeline**."
        ),
        fig=fig,
        lot_area=lot_area, far=bonus_far,
        height_ft=height, footprint_sqft=w*d,
        floors=floors, typical_floor_sqft=w*d,
        loss_factor=0.15,
    )


def _option_10(lot_front, lot_depth, lot_area, rules, m) -> dict:
    """HIGH — Tallest Permitted — Full Width, 90% Depth (Rear Yard Buffer)"""
    b_front, b_depth = m["b_front"], m["b_depth"]
    fr, rr, sy       = m["fr"], m["rr"], m["sy"]
    base_h, max_h, f2f = m["base_h"], m["max_h"], m["f2f"]
    far              = m["far"]

    # Full street-facing width, 90% buildable depth — rear yard buffer for light/air
    fp_w    = max(10.0, b_front)
    fp_d    = max(10.0, b_depth * 0.90)
    fp_sqft = fp_w * fp_d
    x0 = sy
    y0 = fr

    height = _far_height(far, lot_area, fp_sqft, f2f, base_h, max_h, min_h=base_h)
    floors = max(1, int(height / f2f))

    x_center = sy + b_front / 2
    if rules.get("sky_exp_plane") and base_h > 0 and height > base_h:
        traces = _sep_stepped_boxes(x_center, fr, fp_w, fp_d, base_h, height,
                                    _CLR_HIGH_5, "#7F1D1D", "Building Mass")
    else:
        traces = [
            _box_mesh(x0, y0, 0, x0+fp_w, y0+fp_d, height, color=_CLR_HIGH_5, name="Building Mass"),
            _line_box(x0, y0, 0, x0+fp_w, y0+fp_d, height, color="#7F1D1D"),
        ]
    traces.append(_label(lot_front/2, -2, height, f"{height:.0f} ft"))
    fig = _make_fig(lot_front, lot_depth, traces,
                    "10. Tallest Permitted — Full Width, Rear Yard", height, rules)
    floor_tbl = _floor_table_html([{
        "label": "All Floors", "floor_start": 1, "floor_end": floors,
        "width_ft": fp_w, "depth_ft": fp_d, "floor_sqft": fp_sqft,
    }])
    return _scenario_dict(
        name="10. Tallest Permitted — Full Width, Rear Yard",
        risk_level="HIGH",
        number=10,
        description=(
            f"**Full street width** ({fp_w:.0f}′) × **90% buildable depth** ({fp_d:.0f}′ = "
            f"{fp_sqft:,.0f} SF) — rear yard buffer improves light, air, and amenity options — "
            f"rising to **{height:.0f} ft** (**{floors} floors**). "
            "Slightly taller than option 6 due to reduced footprint; fully as-of-right."
            + floor_tbl
        ),
        strategy=(
            "**Maximum street presence** with a rear yard buffer for light wells, amenity terraces, "
            "or future courtyard programming. Marginally taller than option 6; shorter and wider "
            "than the podium+tower in option 8. Best for street-facing retail with residential above."
        ),
        fig=fig,
        lot_area=lot_area, far=far,
        height_ft=height, footprint_sqft=fp_sqft,
        floors=floors, typical_floor_sqft=fp_sqft,
        loss_factor=0.15,
    )


def floor_plate_fig(
    footprint_w: float,
    footprint_d: float,
    is_ground: bool = False,
    is_mixed_use: bool = False,
    is_commercial: bool = False,
    is_retail: bool = False,
) -> go.Figure:
    """
    2D top-down floor plate layout showing indicative unit/space placement.
    Returns a go.Figure suitable for st.plotly_chart() at height=380.

    Modes:
      is_commercial=True  — open office floor plate with columns and core
      is_retail=True      — retail bays with storefront at bottom edge
      is_ground + is_mixed_use — ground floor with retail strip + lobby
      is_ground only      — lobby/amenity core
      default             — typical residential floor with corridor + units
    """
    traces = []

    # ── Outer boundary ────────────────────────────────────────────────
    traces.append(go.Scatter(
        x=[0, footprint_w, footprint_w, 0, 0],
        y=[0, 0, footprint_d, footprint_d, 0],
        mode="lines",
        line=dict(color="#374151", width=2),
        fill="toself",
        fillcolor="rgba(249,250,251,0.9)",
        name="Floor Boundary",
        showlegend=False,
        hoverinfo="skip",
    ))

    if is_commercial:
        # Open office floor plate: boundary, structural columns, core, label
        col_spacing_x = max(15.0, footprint_w / max(2, int(footprint_w / 25)))
        col_spacing_y = max(15.0, footprint_d / max(2, int(footprint_d / 25)))
        core_w = min(footprint_w * 0.20, 25.0)
        core_d = min(footprint_d * 0.30, 35.0)
        cx0 = footprint_w/2 - core_w/2
        cx1 = footprint_w/2 + core_w/2
        cy0 = footprint_d/2 - core_d/2
        cy1 = footprint_d/2 + core_d/2
        # Office fill
        traces.append(go.Scatter(
            x=[0, footprint_w, footprint_w, 0, 0],
            y=[0, 0, footprint_d, footprint_d, 0],
            mode="lines", line=dict(color="#2563EB", width=1),
            fill="toself", fillcolor="rgba(59,130,246,0.10)",
            name="Open Office Area", showlegend=True, hoverinfo="skip",
        ))
        # Structural columns
        xc = col_spacing_x / 2
        while xc < footprint_w - 2:
            yc = col_spacing_y / 2
            while yc < footprint_d - 2:
                r = 1.2
                traces.append(go.Scatter(
                    x=[xc-r, xc+r, xc+r, xc-r, xc-r],
                    y=[yc-r, yc-r, yc+r, yc+r, yc-r],
                    mode="lines", line=dict(color="#94A3B8", width=1),
                    fill="toself", fillcolor="rgba(148,163,184,0.50)",
                    showlegend=False, hoverinfo="skip",
                ))
                yc += col_spacing_y
            xc += col_spacing_x
        # Elevator/stair core
        traces.append(go.Scatter(
            x=[cx0, cx1, cx1, cx0, cx0],
            y=[cy0, cy0, cy1, cy1, cy0],
            mode="lines", line=dict(color="#1D4ED8", width=2),
            fill="toself", fillcolor="rgba(59,130,246,0.35)",
            name="Core / Mechanicals", showlegend=True, hoverinfo="skip",
        ))
        traces.append(go.Scatter(
            x=[footprint_w/2], y=[footprint_d/2],
            mode="text", text=["CORE"], showlegend=False,
            textfont=dict(size=9, color="#FFFFFF"), hoverinfo="skip",
        ))
        traces.append(go.Scatter(
            x=[footprint_w/2], y=[footprint_d * 0.82],
            mode="text", text=["OPEN OFFICE FLOOR PLATE"], showlegend=False,
            textfont=dict(size=10, color="#1D4ED8"), hoverinfo="skip",
        ))
    elif is_retail:
        # Retail bays: storefront at bottom, bays ~30 ft wide
        bay_w = min(30.0, max(15.0, footprint_w / max(1, round(footprint_w / 30))))
        n_bays = max(1, int(footprint_w / bay_w))
        actual_bay_w = footprint_w / n_bays
        for bi in range(n_bays):
            bx0 = bi * actual_bay_w + 0.5
            bx1 = (bi + 1) * actual_bay_w - 0.5
            traces.append(go.Scatter(
                x=[bx0, bx1, bx1, bx0, bx0],
                y=[0, 0, footprint_d, footprint_d, 0],
                mode="lines", line=dict(color="#6366F1", width=1.5),
                fill="toself",
                fillcolor="rgba(99,102,241," + ("0.22" if bi % 2 == 0 else "0.12") + ")",
                name="Retail Bay" if bi == 0 else "",
                showlegend=(bi == 0),
                legendgroup="retail",
                hoverinfo="skip",
            ))
            approx_sf = int(actual_bay_w * footprint_d)
            traces.append(go.Scatter(
                x=[bx0 + actual_bay_w/2], y=[footprint_d/2],
                mode="text", text=[f"BAY {bi+1}<br>~{approx_sf} SF"],
                showlegend=False, textfont=dict(size=9, color="#4338CA"), hoverinfo="skip",
            ))
        # Storefront indicator
        traces.append(go.Scatter(
            x=[0, footprint_w], y=[1.5, 1.5],
            mode="lines", line=dict(color="#4338CA", width=3, dash="solid"),
            name="Storefront (Street)", showlegend=True, hoverinfo="skip",
        ))
        traces.append(go.Scatter(
            x=[footprint_w/2], y=[footprint_d * 0.88],
            mode="text", text=["RETAIL FLOOR PLATE  ←  STREET FRONTAGE"],
            showlegend=False, textfont=dict(size=9, color="#4338CA"), hoverinfo="skip",
        ))
    elif is_ground and is_mixed_use:
        # Ground floor of mixed-use: retail strip at front, lobby/core behind
        retail_d = min(footprint_d * 0.35, 25.0)
        # Retail
        traces.append(go.Scatter(
            x=[0, footprint_w, footprint_w, 0, 0],
            y=[0, 0, retail_d, retail_d, 0],
            mode="lines", line=dict(color="#6366F1", width=1),
            fill="toself", fillcolor="rgba(99,102,241,0.20)",
            name="Retail / Commercial", showlegend=True, hoverinfo="skip",
        ))
        traces.append(go.Scatter(
            x=[footprint_w*0.5], y=[retail_d*0.5],
            mode="text", text=["RETAIL"], showlegend=False,
            textfont=dict(size=9, color="#4338CA"), hoverinfo="skip",
        ))
        # Lobby
        lobby_w = min(footprint_w * 0.25, 30.0)
        lobby_d = footprint_d - retail_d
        traces.append(go.Scatter(
            x=[footprint_w/2 - lobby_w/2, footprint_w/2 + lobby_w/2,
               footprint_w/2 + lobby_w/2, footprint_w/2 - lobby_w/2, footprint_w/2 - lobby_w/2],
            y=[retail_d, retail_d, footprint_d, footprint_d, retail_d],
            mode="lines", line=dict(color="#9CA3AF", width=1),
            fill="toself", fillcolor="rgba(156,163,175,0.20)",
            name="Lobby / Core", showlegend=True, hoverinfo="skip",
        ))
        traces.append(go.Scatter(
            x=[footprint_w*0.5], y=[retail_d + lobby_d*0.5],
            mode="text", text=["LOBBY"], showlegend=False,
            textfont=dict(size=9, color="#6B7280"), hoverinfo="skip",
        ))
    elif is_ground:
        # Ground floor residential: lobby/amenity core + some ground units
        core_w = min(footprint_w * 0.30, 35.0)
        core_d = min(footprint_d * 0.50, 50.0)
        traces.append(go.Scatter(
            x=[footprint_w/2 - core_w/2, footprint_w/2 + core_w/2,
               footprint_w/2 + core_w/2, footprint_w/2 - core_w/2, footprint_w/2 - core_w/2],
            y=[footprint_d/2 - core_d/2, footprint_d/2 - core_d/2,
               footprint_d/2 + core_d/2, footprint_d/2 + core_d/2, footprint_d/2 - core_d/2],
            mode="lines", line=dict(color="#9CA3AF", width=1),
            fill="toself", fillcolor="rgba(156,163,175,0.25)",
            name="Lobby / Core / Amenity", showlegend=True, hoverinfo="skip",
        ))
        traces.append(go.Scatter(
            x=[footprint_w*0.5], y=[footprint_d*0.5],
            mode="text", text=["LOBBY\n/ CORE"], showlegend=False,
            textfont=dict(size=9, color="#6B7280"), hoverinfo="skip",
        ))
    else:
        # Upper floor: corridor down center, elevator/stair core, units on each side
        # Corridor (12% of footprint width)
        corr_w = max(6.0, footprint_w * 0.12)
        cx0 = footprint_w / 2 - corr_w / 2
        cx1 = footprint_w / 2 + corr_w / 2
        traces.append(go.Scatter(
            x=[cx0, cx1, cx1, cx0, cx0],
            y=[0, 0, footprint_d, footprint_d, 0],
            mode="lines", line=dict(color="#9CA3AF", width=1),
            fill="toself", fillcolor="rgba(156,163,175,0.20)",
            name="Corridor", showlegend=True, hoverinfo="skip",
        ))

        # Elevator/stair core: centered in corridor, ~30% of depth
        core_h = min(footprint_d * 0.30, 30.0)
        core_y0 = footprint_d / 2 - core_h / 2
        core_y1 = footprint_d / 2 + core_h / 2
        traces.append(go.Scatter(
            x=[cx0, cx1, cx1, cx0, cx0],
            y=[core_y0, core_y0, core_y1, core_y1, core_y0],
            mode="lines", line=dict(color="#6B7280", width=2),
            fill="toself", fillcolor="rgba(107,114,128,0.40)",
            name="Elev/Stair Core", showlegend=True, hoverinfo="skip",
        ))
        traces.append(go.Scatter(
            x=[footprint_w / 2], y=[footprint_d / 2],
            mode="text", text=["CORE"], showlegend=False,
            textfont=dict(size=9, color="#FFFFFF"),
            hoverinfo="skip",
        ))

        # Unit sizes (ft): Studio 25×28, 1Bed 30×35, 2Bed 35×42
        unit_specs = [
            ("Studio", 25, 28, "rgba(16,185,129,0.30)", "#059669"),
            ("1 Bed",  30, 35, "rgba(59,130,246,0.30)", "#2563EB"),
            ("2 Bed",  35, 42, "rgba(245,158,11,0.30)", "#D97706"),
        ]

        # Left side units (window on left)
        y_cur = 2.0
        side_d_avail = footprint_d - 4.0
        utype_idx = 0
        while y_cur < side_d_avail - 10:
            uw, ud, fc, lc = unit_specs[utype_idx % len(unit_specs)][1:]
            ulabel = unit_specs[utype_idx % len(unit_specs)][0]
            approx_sf = int(uw * ud)
            ud = min(ud, side_d_avail - y_cur)
            if ud < 10:
                break
            x0u = 0
            x1u = min(cx0 - 1, uw)
            traces.append(go.Scatter(
                x=[x0u, x1u, x1u, x0u, x0u],
                y=[y_cur, y_cur, y_cur+ud, y_cur+ud, y_cur],
                mode="lines", line=dict(color=lc, width=1),
                fill="toself", fillcolor=fc,
                name=ulabel,
                showlegend=(y_cur < 5),
                legendgroup=ulabel,
                hovertemplate=f"<b>{ulabel}</b><br>~{approx_sf} SF<extra></extra>",
            ))
            traces.append(go.Scatter(
                x=[(x0u+x1u)/2], y=[y_cur + ud/2],
                mode="text", text=[f"{ulabel}<br>~{approx_sf} SF"], showlegend=False,
                textfont=dict(size=10, color="#374151"),
                hoverinfo="skip",
            ))
            y_cur += ud + 2.0
            utype_idx += 1

        # Right side units (window on right)
        y_cur = 2.0
        utype_idx = 1  # offset for variety
        while y_cur < side_d_avail - 10:
            uw, ud, fc, lc = unit_specs[utype_idx % len(unit_specs)][1:]
            ulabel = unit_specs[utype_idx % len(unit_specs)][0]
            approx_sf = int(uw * ud)
            ud = min(ud, side_d_avail - y_cur)
            if ud < 10:
                break
            x0u = cx1 + 1
            x1u = footprint_w
            traces.append(go.Scatter(
                x=[x0u, x1u, x1u, x0u, x0u],
                y=[y_cur, y_cur, y_cur+ud, y_cur+ud, y_cur],
                mode="lines", line=dict(color=lc, width=1),
                fill="toself", fillcolor=fc,
                name=ulabel,
                showlegend=False,
                legendgroup=ulabel,
                hovertemplate=f"<b>{ulabel}</b><br>~{approx_sf} SF<extra></extra>",
            ))
            traces.append(go.Scatter(
                x=[(x0u+x1u)/2], y=[y_cur + ud/2],
                mode="text", text=[f"{ulabel}<br>~{approx_sf} SF"], showlegend=False,
                textfont=dict(size=10, color="#374151"),
                hoverinfo="skip",
            ))
            y_cur += ud + 2.0
            utype_idx += 1

    label = "Ground Floor Plan" if is_ground else "Typical Upper Floor Plan"
    fig = go.Figure(data=traces)
    fig.update_layout(
        title=dict(text=label, font=dict(size=13, color="#EDEFF5"), x=0.5),
        xaxis=dict(
            range=[-2, footprint_w + 2], showgrid=False,
            zeroline=False, showticklabels=False,
            scaleanchor="y", scaleratio=1,
        ),
        yaxis=dict(
            range=[-2, footprint_d + 2], showgrid=False,
            zeroline=False, showticklabels=False,
        ),
        margin=dict(l=0, r=0, t=36, b=0),
        height=380,
        paper_bgcolor="#121826",
        plot_bgcolor="#121826",
        legend=dict(x=1.01, y=0.99, font=dict(size=10, color="#C7CDDB")),
    )
    return fig


def build_massing_options(
    lot_front_ft: float,
    lot_depth_ft: float,
    lot_area_sqft: float,
    zoning_district: str,
    rules: dict,
    lot_widths: list | None = None,
    existing_bldg: dict | None = None,
    focus: str = "Residential",
    sub_components: list | None = None,
    show_neighbors: bool = False,
    neighbor_lots: list | None = None,
) -> list[dict]:
    """
    Generate 10 massing scenario dicts for the given lot + zoning rules.

    Scenarios span three investment risk tiers:
      LOW  (1–2): Gut Reno, Contextual Infill
      MED  (3–5): Low-Rise, Mixed-Use, Standard Tower
      HIGH (6–10): Max FAR 60%, Max FAR 75%, Full Coverage+Stepped, IH Bonus, Slender Tower

    Args:
        focus: "Residential" | "Commercial" | "Retail"
        sub_components: list of "Ground Floor Retail" | "Commercial Office" | "Residential Above"
        show_neighbors: if True, inject neighbor traces into each figure
        neighbor_lots: list of neighbor PLUTO dicts with lotfront/numfloors

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

    options = [
        _option_1(lot_front, lot_depth, lot_area, rules, m, existing_bldg),
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

    # Inject dotted lot-boundary traces when combining multiple lots
    if lot_widths and len(lot_widths) > 1:
        boundary_traces = _lot_boundary_traces(lot_widths, lot_depth)
        for opt in options:
            if opt and "fig" in opt:
                for tr in boundary_traces:
                    opt["fig"].add_trace(tr)

    # Inject neighboring property silhouettes when requested
    if show_neighbors and neighbor_lots:
        nbr_traces = _neighbor_traces(lot_front, lot_depth, neighbor_lots)
        for opt in options:
            if opt and "fig" in opt:
                for tr in nbr_traces:
                    opt["fig"].add_trace(tr)

    return options


def _neighbor_traces(subject_front: float, subject_depth: float,
                     nbr_lots: list) -> list:
    """
    Build semi-transparent gray box traces for neighboring buildings.
    Positions up to 3 neighbors on each side (left/right) of the subject lot.
    Neighbors with lower lot numbers are placed to the left (negative X offset),
    higher lot numbers to the right (positive X offset past subject_front).
    """
    traces = []
    left_x  = 0.0
    right_x = subject_front

    first = True
    for nb in nbr_lots[:6]:
        try:
            nb_front  = max(10.0, float(nb.get("lotfront") or nb.get("lot_frontage_ft") or 25))
            nb_floors = max(1, float(nb.get("numfloors") or nb.get("num_floors") or 2))
            nb_height = nb_floors * 11.0
            nb_depth  = max(20.0, float(nb.get("lotdepth") or nb.get("lot_depth_ft") or subject_depth))
        except (TypeError, ValueError):
            continue

        side = nb.get("_side", "left")
        if side == "left":
            x0 = left_x - nb_front
            x1 = left_x
            left_x = x0
        else:
            x0 = right_x
            x1 = right_x + nb_front
            right_x = x1

        y0 = 0.0
        y1 = min(nb_depth, subject_depth)
        lbl = "Neighboring Buildings" if first else ""
        traces.append(go.Mesh3d(
            x=[x0, x0, x1, x1, x0, x0, x1, x1],
            y=[y0, y1, y1, y0, y0, y1, y1, y0],
            z=[0,  0,  0,  0,  nb_height, nb_height, nb_height, nb_height],
            i=[7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2],
            j=[3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3],
            k=[0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6],
            color=_CLR_NBR,
            opacity=0.30,
            name=lbl,
            showlegend=first,
            flatshading=True,
            lighting=dict(ambient=0.8, diffuse=0.5),
        ))
        traces.append(go.Scatter3d(
            x=[x0,x1,x1,x0,x0, x0,x1,x1,x0,x0, x0,x0, x1,x1, x1,x1, x0,x0],
            y=[y0,y0,y1,y1,y0, y0,y0,y1,y1,y0, y0,y0, y0,y0, y1,y1, y1,y1],
            z=[0, 0, 0, 0, 0,  nb_height,nb_height,nb_height,nb_height,nb_height,
               0,nb_height, 0,nb_height, 0,nb_height, 0,nb_height],
            mode="lines",
            line=dict(color="#9CA3AF", width=1),
            showlegend=False,
            hoverinfo="skip",
        ))
        first = False

    return traces

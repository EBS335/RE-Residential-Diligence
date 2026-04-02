"""
3D Building Massing Visualizations using Plotly.

Generates interactive 3D diagrams of NYC building envelopes based on:
  - Lot dimensions (frontage × depth from PLUTO)
  - Zoning rules (FAR, height limits, setbacks from zoning_rules.py)

Three massing option archetypes are produced:
  1. Max As-of-Right  — full buildable footprint, base height then setback to max
  2. Slender Tower    — reduced footprint (35%), taller building
  3. Courtyard / Low  — wide footprint at base height only; interior courtyard

Each returns a go.Figure that can be rendered with st.plotly_chart().
"""

from __future__ import annotations
import math
import plotly.graph_objects as go


# ── Color palette ──────────────────────────────────────────────────────────────
_CLR_LOT      = "rgba(100, 100, 100, 0.20)"   # lot boundary footprint
_CLR_MASS_1   = "rgba(30,  90, 200, 0.40)"    # Max Envelope
_CLR_MASS_2   = "rgba(220, 90,  40, 0.40)"    # Slender Tower
_CLR_MASS_3   = "rgba(30, 160,  80, 0.40)"    # Courtyard / Low
_CLR_SETBACK  = "rgba(255, 200,  0, 0.35)"    # setback zone
_CLR_LINE     = "#374151"


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
        title=dict(text=title, font=dict(size=13, color="#111827"), x=0.5),
        scene=dict(
            xaxis=dict(title="Frontage (ft)", range=[-pad, lot_front + pad],
                       showbackground=False, gridcolor="#E5E7EB"),
            yaxis=dict(title="Depth (ft)",    range=[-pad, lot_depth + pad],
                       showbackground=False, gridcolor="#E5E7EB"),
            zaxis=dict(title="Height (ft)",   range=[0, max_z * 1.15],
                       showbackground=False, gridcolor="#E5E7EB"),
            aspectmode="data",
            camera=dict(eye=dict(x=1.6, y=-1.6, z=1.2)),
            bgcolor="rgba(248,249,250,1)",
        ),
        margin=dict(l=0, r=0, t=40, b=0),
        paper_bgcolor="rgba(248,249,250,1)",
        height=420,
        legend=dict(x=0.01, y=0.99, bgcolor="rgba(255,255,255,0.8)",
                    font=dict(size=11)),
    )


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


# ── Option builders ───────────────────────────────────────────────────────────

def _option_max_envelope(lot_front, lot_depth, lot_area, rules, m) -> dict:
    """
    Option 1 — Max As-of-Right:
    Fills the full buildable footprint, rises to base height, then
    steps back for a penthouse tier to reach max height.
    """
    b_front, b_depth = m["b_front"], m["b_depth"]
    fr, rr, sy = m["fr"], m["rr"], m["sy"]
    base_h, max_h = m["base_h"], m["max_h"]
    total_area = m["total_area"]
    f2f = m["f2f"]

    # Penthouse setback: 15 ft each side at top tier
    ph_setback = 15
    ph_front   = max(10, b_front - 2 * ph_setback)
    ph_depth   = max(10, b_depth - 2 * ph_setback)

    floors_base = max(1, int(base_h / f2f))
    floors_top  = max(0, int((max_h - base_h) / f2f))
    floors_total = floors_base + floors_top
    floor_area   = b_front * b_depth
    typical_floor = floor_area
    height = base_h + floors_top * f2f

    traces: list = []

    # Lot boundary
    traces.append(_box_mesh(0, 0, 0, lot_front, lot_depth, 0.5,
                             color=_CLR_LOT, name="Lot Boundary"))
    traces.append(_line_box(0, 0, 0, lot_front, lot_depth, 0.5,
                             color="#9CA3AF"))

    # Setback zones (front and rear — semi-transparent yellow)
    if fr > 0:
        traces.append(_box_mesh(sy, 0, 0, lot_front - sy, fr, base_h,
                                 color=_CLR_SETBACK, name="Front Yard Setback",
                                 show_legend=True))
    if rr > 0:
        traces.append(_box_mesh(sy, lot_depth - rr, 0,
                                 lot_front - sy, lot_depth, base_h,
                                 color=_CLR_SETBACK, name="Rear Yard Setback",
                                 show_legend=False))

    # Base mass
    traces.append(_box_mesh(sy, fr, 0, lot_front - sy, lot_depth - rr, base_h,
                             color=_CLR_MASS_1, name="Building Mass"))
    traces.append(_line_box(sy, fr, 0, lot_front - sy, lot_depth - rr, base_h))

    # Penthouse tier
    if floors_top > 0:
        px0 = sy + ph_setback
        py0 = fr + ph_setback
        px1 = lot_front - sy - ph_setback
        py1 = lot_depth - rr - ph_setback
        traces.append(_box_mesh(px0, py0, base_h, px1, py1, height,
                                 color="rgba(30,90,200,0.55)", name="Penthouse Tier"))
        traces.append(_line_box(px0, py0, base_h, px1, py1, height))

    # Height label
    traces.append(_label(lot_front / 2, -2, height, f"{height:.0f} ft"))

    fig = go.Figure(data=traces)
    fig.update_layout(_base_layout("Option 1 — Max As-of-Right",
                                    lot_front, lot_depth, height + 20))
    return {
        "name":               "Max As-of-Right",
        "description":        (
            f"Fills the entire buildable footprint ({b_front:.0f}′ × {b_depth:.0f}′) "
            f"to base height ({base_h} ft), then sets back {ph_setback} ft per side "
            f"for a penthouse tier reaching {height:.0f} ft total. "
            f"Maximises gross floor area at {total_area:,.0f} SF."
        ),
        "fig":                fig,
        "total_sqft":         int(total_area),
        "floors":             floors_total,
        "typical_floor_sqft": int(typical_floor),
        "height_ft":          int(height),
        "footprint_sqft":     int(floor_area),
    }


def _option_slender_tower(lot_front, lot_depth, lot_area, rules, m) -> dict:
    """
    Option 2 — Slender Tower:
    35 % of buildable footprint, rises to full max height.
    (Only meaningful in non-contextual districts; in contextual ones the
    tower matches the max height anyway.)
    """
    b_front, b_depth = m["b_front"], m["b_depth"]
    fr, rr, sy = m["fr"], m["rr"], m["sy"]
    max_h      = m["max_h"]
    total_area = m["total_area"]
    f2f        = m["f2f"]
    footprint  = m["footprint"]

    # Tower footprint is 35% of buildable, centred on lot
    ratio = 0.35
    tw    = max(20, b_front * math.sqrt(ratio))
    td    = max(20, b_depth * math.sqrt(ratio))
    tx0   = sy + (b_front - tw) / 2
    ty0   = fr + (b_depth - td) / 2
    tx1   = tx0 + tw
    ty1   = ty0 + td

    height = max_h if max_h > 0 else m["base_h"] * 2
    floors_total = max(1, int(height / f2f))
    floor_area   = tw * td
    typical_floor = floor_area

    traces = []
    traces.append(_box_mesh(0, 0, 0, lot_front, lot_depth, 0.5,
                             color=_CLR_LOT, name="Lot Boundary"))
    traces.append(_line_box(0, 0, 0, lot_front, lot_depth, 0.5,
                             color="#9CA3AF"))
    traces.append(_box_mesh(tx0, ty0, 0, tx1, ty1, height,
                             color=_CLR_MASS_2, name="Tower Mass"))
    traces.append(_line_box(tx0, ty0, 0, tx1, ty1, height,
                             color="#b45309"))
    traces.append(_label(lot_front / 2, -2, height, f"{height:.0f} ft"))

    fig = go.Figure(data=traces)
    fig.update_layout(_base_layout("Option 2 — Slender Tower",
                                    lot_front, lot_depth, height + 20))
    return {
        "name":               "Slender Tower",
        "description":        (
            f"Concentrates the program in a compact {tw:.0f}′ × {td:.0f}′ tower "
            f"footprint ({floor_area:,.0f} SF / floor) rising {height:.0f} ft "
            f"({floors_total} floors). Leaves ~{footprint - floor_area:,.0f} SF of "
            f"open space at grade. Best suited to non-contextual high-density districts."
        ),
        "fig":                fig,
        "total_sqft":         int(total_area),
        "floors":             floors_total,
        "typical_floor_sqft": int(typical_floor),
        "height_ft":          int(height),
        "footprint_sqft":     int(floor_area),
    }


def _option_courtyard(lot_front, lot_depth, lot_area, rules, m) -> dict:
    """
    Option 3 — Courtyard / Low & Wide:
    Uses full buildable footprint but stays at base height only.
    An interior light court is carved from the centre to provide
    air and light to all units.
    """
    b_front, b_depth = m["b_front"], m["b_depth"]
    fr, rr, sy = m["fr"], m["rr"], m["sy"]
    base_h     = m["base_h"]
    total_area = m["total_area"]
    f2f        = m["f2f"]

    height = base_h
    floors_total = max(1, int(height / f2f))

    # Courtyard: 30% of buildable width/depth, centred
    ct_w  = max(10, b_front * 0.30)
    ct_d  = max(10, b_depth * 0.30)
    ct_x0 = sy + (b_front - ct_w) / 2
    ct_y0 = fr + (b_depth - ct_d) / 2

    gross_floor = b_front * b_depth
    court_area  = ct_w * ct_d
    net_floor   = gross_floor - court_area
    typical_floor = net_floor

    traces = []
    traces.append(_box_mesh(0, 0, 0, lot_front, lot_depth, 0.5,
                             color=_CLR_LOT, name="Lot Boundary"))
    traces.append(_line_box(0, 0, 0, lot_front, lot_depth, 0.5,
                             color="#9CA3AF"))

    # Full mass
    traces.append(_box_mesh(sy, fr, 0, lot_front - sy, lot_depth - rr, height,
                             color=_CLR_MASS_3, name="Building Mass"))
    traces.append(_line_box(sy, fr, 0, lot_front - sy, lot_depth - rr, height,
                             color="#065f46"))

    # Courtyard cutout — visualise as a lighter inner box
    traces.append(_box_mesh(ct_x0, ct_y0, 0,
                             ct_x0 + ct_w, ct_y0 + ct_d, height,
                             color="rgba(248,249,250,0.85)",
                             name="Interior Courtyard"))
    traces.append(_line_box(ct_x0, ct_y0, 0,
                             ct_x0 + ct_w, ct_y0 + ct_d, height,
                             color="#6EE7B7", width=2))
    traces.append(_label(lot_front / 2, -2, height, f"{height:.0f} ft"))

    fig = go.Figure(data=traces)
    fig.update_layout(_base_layout("Option 3 — Courtyard / Low & Wide",
                                    lot_front, lot_depth, height + 20))
    return {
        "name":               "Courtyard / Low & Wide",
        "description":        (
            f"Fills the full {b_front:.0f}′ × {b_depth:.0f}′ buildable area at base "
            f"height ({height:.0f} ft / {floors_total} floors), with a "
            f"{ct_w:.0f}′ × {ct_d:.0f}′ interior courtyard providing light and air. "
            f"Net floor plate ≈ {net_floor:,.0f} SF. Maximises residential density "
            f"within contextual height limits."
        ),
        "fig":                fig,
        "total_sqft":         int(total_area),
        "floors":             floors_total,
        "typical_floor_sqft": int(typical_floor),
        "height_ft":          int(height),
        "footprint_sqft":     int(net_floor),
    }


# ── Public API ────────────────────────────────────────────────────────────────

def build_massing_options(
    lot_front_ft: float,
    lot_depth_ft: float,
    lot_area_sqft: float,
    zoning_district: str,
    rules: dict,
) -> list[dict]:
    """
    Generate three massing option dicts for the given lot + zoning rules.

    Each dict contains:
      name, description, fig (go.Figure),
      total_sqft, floors, typical_floor_sqft, height_ft, footprint_sqft

    Returns an empty list if the inputs are invalid.
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
        _option_max_envelope(lot_front, lot_depth, lot_area, rules, m),
        _option_slender_tower(lot_front, lot_depth, lot_area, rules, m),
        _option_courtyard(lot_front, lot_depth, lot_area, rules, m),
    ]

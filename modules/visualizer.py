"""
Visualisation helpers — Folium map, Plotly charts.
"""

import folium
from folium.plugins import MarkerCluster
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd

# ── Colour palette ────────────────────────────────────────────────────────────
UNIT_COLOURS = {
    "Studio":  "#F4A261",
    "1 Bed":   "#E76F51",
    "2 Bed":   "#2A9D8F",
    "3 Bed":   "#457B9D",
    "4+ Bed":  "#6A4C93",
    "Unknown": "#9CA3AF",
}

UNIT_ORDER = ["Studio", "1 Bed", "2 Bed", "3 Bed", "4+ Bed"]

# Free, keyless satellite imagery — shared across every map that offers a
# satellite/regular toggle, so the provider URL/attribution lives in one
# place rather than being duplicated verbatim at each call site. The
# surrounding folium.TileLayer()/LayerControl() calls are still written out
# inline at each map-building call site (app.py, visualizer.py,
# site_finder_ui.py) rather than wrapped in a helper — those sites'
# marker/layer logic diverges too much for a generic wrapper to be worth it,
# consistent with this codebase's existing per-call-site map construction.
ESRI_SATELLITE_TILES = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
ESRI_SATELLITE_ATTR = "Esri"


# ---------------------------------------------------------------------------
# Interactive map
# ---------------------------------------------------------------------------

def build_map(
    listings: list,
    center_lat: float,
    center_lon: float,
    radius_miles: float,
    subject_label: str,
) -> folium.Map:
    """Folium map: subject pin, radius ring, clustered listing markers."""
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=15,
        tiles="CartoDB positron",
    )

    # Radius circle
    folium.Circle(
        location=[center_lat, center_lon],
        radius=radius_miles * 1609.34,
        color="#1A3A6B",
        fill=True,
        fill_opacity=0.04,
        weight=2,
        dash_array="6 4",
        tooltip=f"Search radius: {radius_miles:.2f} mi",
    ).add_to(m)

    # Subject property pin
    folium.Marker(
        location=[center_lat, center_lon],
        icon=folium.Icon(color="red", icon="star", prefix="fa"),
        tooltip=f"<b>Subject Property</b><br>{subject_label}",
        popup=folium.Popup(
            f"<b>Subject Property</b><br><small>{subject_label}</small>",
            max_width=240,
        ),
    ).add_to(m)

    if not listings:
        folium.TileLayer(
            tiles=ESRI_SATELLITE_TILES, attr=ESRI_SATELLITE_ATTR,
            name="Satellite", overlay=False, control=True,
        ).add_to(m)
        folium.LayerControl(position="topright", collapsed=True).add_to(m)
        return m

    cluster = MarkerCluster(
        options={"maxClusterRadius": 40, "disableClusteringAtZoom": 16}
    ).add_to(m)

    for item in listings:
        clr   = UNIT_COLOURS.get(item.get("unit_type", "Unknown"), "#9CA3AF")
        rent  = f"${item['rent']:,.0f}/mo"
        dist  = f"{item['distance_miles']:.2f} mi"

        # ── Rich hover tooltip (visible on mouse-over, no click needed) ──────
        beds_label = item.get("unit_type") or "Unknown"
        addr_short = (item.get("address") or "")[:40]
        tooltip_html = (
            f"<div style='font-family:sans-serif;line-height:1.55;padding:2px'>"
            f"<b style='font-size:1rem'>{rent}</b>"
            f"&ensp;<span style='color:#374151'>{beds_label}</span><br>"
            f"<span style='color:#374151;font-size:0.82rem'>{addr_short}</span><br>"
            f"<span style='color:#6B7280;font-size:0.78rem'>{dist} &middot; {item.get('source','')}</span>"
            f"</div>"
        )

        # ── Photo ─────────────────────────────────────────────────────────────
        photo_html = ""
        if item.get("photos"):
            photo_html = (
                f'<img src="{item["photos"][0]}" width="240" '
                f'style="border-radius:7px;margin:6px 0 8px;display:block"/>'
            )

        # ── Optional detail lines ─────────────────────────────────────────────
        bldg_line = (
            f'<b>Building:</b> {item["building_name"]}<br>'
            if item.get("building_name") else ""
        )
        sqft_val  = item.get("sqft")
        sqft_line = f'<b>Size:</b> {sqft_val:,} SF<br>' if sqft_val else ""
        ppsf_line = ""
        if sqft_val and item.get("rent"):
            ppsf = item["rent"] / sqft_val
            ppsf_line = f'<b>$/SF:</b> ${ppsf:.2f}<br>'
        dom = item.get("days_on_market")
        dom_line  = f'<b>Days on Market:</b> {dom}<br>' if dom is not None else ""

        link_html = ""
        if item.get("url"):
            link_html = (
                f'<a href="{item["url"]}" target="_blank" '
                f'style="color:#1A3A6B;font-weight:600;text-decoration:none">'
                f'View listing →</a>'
            )

        popup_html = f"""
        <div style="font-family:sans-serif;min-width:230px;max-width:260px">
          {photo_html}
          <span style="font-size:1.15rem;font-weight:700;color:#111">{rent}</span>
          &nbsp;<span style="color:#6B7280;font-size:0.85rem">{beds_label}</span>
          <hr style="margin:6px 0;border-color:#E5E7EB"/>
          <b>Address:</b> {item.get('address','N/A')}<br>
          {bldg_line}
          <b>Beds:</b> {item.get('bedrooms', 0)} &nbsp;
          {sqft_line}{ppsf_line}{dom_line}
          <b>Distance:</b> {dist}<br>
          <b>Source:</b> <span style="color:#6B7280">{item.get('source','')}</span><br>
          <div style="margin-top:7px">{link_html}</div>
        </div>
        """

        folium.CircleMarker(
            location=[item["lat"], item["lon"]],
            radius=9,
            color="white",
            weight=1.5,
            fill=True,
            fill_color=clr,
            fill_opacity=0.92,
            tooltip=folium.Tooltip(tooltip_html, sticky=True),
            popup=folium.Popup(popup_html, max_width=280),
        ).add_to(cluster)

    # Legend
    legend_rows = "".join(
        f'<div style="display:flex;align-items:center;gap:7px;margin:3px 0">'
        f'<div style="width:13px;height:13px;border-radius:50%;background:{c}"></div>'
        f'<span style="font-size:12px">{u}</span></div>'
        for u, c in UNIT_COLOURS.items()
        if u != "Unknown"
    )
    m.get_root().html.add_child(folium.Element(f"""
    <div style="position:fixed;bottom:28px;left:28px;z-index:1000;
                background:white;padding:10px 14px;border-radius:10px;
                box-shadow:0 2px 12px rgba(0,0,0,0.14);font-family:sans-serif">
      <b style="font-size:12px;color:#374151">Unit Type</b>
      <div style="margin-top:5px">{legend_rows}</div>
      <hr style="margin:7px 0;border-color:#E5E7EB"/>
      <div style="display:flex;align-items:center;gap:7px">
        <span style="font-size:14px">⭐</span>
        <span style="font-size:12px">Subject Property</span>
      </div>
    </div>
    """))

    folium.TileLayer(
        tiles=ESRI_SATELLITE_TILES, attr=ESRI_SATELLITE_ATTR,
        name="Satellite", overlay=False, control=True,
    ).add_to(m)
    folium.LayerControl(position="topright", collapsed=True).add_to(m)

    return m


# ---------------------------------------------------------------------------
# Bar chart — avg vs median
# ---------------------------------------------------------------------------

def build_bar_chart(summary_df: pd.DataFrame) -> go.Figure:
    if summary_df.empty:
        return go.Figure()

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Avg Rent",
        x=summary_df["Unit Type"],
        y=summary_df["_avg"],
        marker_color="#1A1D2E",
        text=[f"${v:,.0f}" for v in summary_df["_avg"]],
        textposition="outside",
        textfont_size=12,
    ))
    fig.add_trace(go.Bar(
        name="Median Rent",
        x=summary_df["Unit Type"],
        y=summary_df["_median"],
        marker_color="#E76F51",
        text=[f"${v:,.0f}" for v in summary_df["_median"]],
        textposition="outside",
        textfont_size=12,
    ))
    fig.update_layout(
        barmode="group",
        title=dict(text="Avg vs Median Rent by Unit Type", font_size=14),
        yaxis=dict(title="Monthly Rent ($)", tickformat="$,.0f", showgrid=True, gridcolor="#E8E3D4"),
        xaxis_title="Unit Type",
        legend=dict(orientation="h", y=1.12, x=0.5, xanchor="center"),
        plot_bgcolor="#FFFFFF",
        paper_bgcolor="#FFFFFF",
        font=dict(family="Inter, sans-serif", size=12, color="#3D4152"),
        margin=dict(t=55, b=35, l=55, r=20),
        height=380,
    )
    return fig


# ---------------------------------------------------------------------------
# Range chart — min / avg / max
# ---------------------------------------------------------------------------

def build_range_chart(summary_df: pd.DataFrame) -> go.Figure:
    if summary_df.empty:
        return go.Figure()

    fig = go.Figure()
    for _, row in summary_df.iterrows():
        clr = UNIT_COLOURS.get(row["Unit Type"], "#9CA3AF")
        # Shaded range bar
        fig.add_trace(go.Bar(
            x=[row["Unit Type"]],
            y=[row["_max"] - row["_min"]],
            base=[row["_min"]],
            marker_color=clr,
            marker_opacity=0.22,
            showlegend=False,
            hoverinfo="skip",
            width=0.4,
        ))
        # Avg dot
        fig.add_trace(go.Scatter(
            x=[row["Unit Type"]],
            y=[row["_avg"]],
            mode="markers",
            marker=dict(size=13, color=clr, line=dict(color="white", width=2)),
            name=row["Unit Type"],
            hovertemplate=(
                f"<b>{row['Unit Type']}</b><br>"
                f"Avg: ${row['_avg']:,.0f}<br>"
                f"Min: ${row['_min']:,.0f}<br>"
                f"Max: ${row['_max']:,.0f}<extra></extra>"
            ),
        ))

    fig.update_layout(
        title=dict(text="Rent Range by Unit Type  (bar = min–max, dot = avg)", font_size=14),
        yaxis=dict(title="Monthly Rent ($)", tickformat="$,.0f", showgrid=True, gridcolor="#E8E3D4"),
        xaxis_title="Unit Type",
        showlegend=False,
        plot_bgcolor="#FFFFFF",
        paper_bgcolor="#FFFFFF",
        font=dict(family="Inter, sans-serif", size=12, color="#3D4152"),
        margin=dict(t=55, b=35, l=55, r=20),
        height=380,
    )
    return fig


# ---------------------------------------------------------------------------
# Box-plot distribution
# ---------------------------------------------------------------------------

def build_box_chart(listings: list) -> go.Figure:
    if not listings:
        return go.Figure()

    df = pd.DataFrame(listings)
    present = [u for u in UNIT_ORDER if u in df["unit_type"].values]

    fig = go.Figure()
    for u in present:
        rents = df[df["unit_type"] == u]["rent"]
        fig.add_trace(go.Box(
            y=rents,
            name=u,
            marker_color=UNIT_COLOURS.get(u, "#9CA3AF"),
            boxmean="sd",
            jitter=0.35,
            pointpos=-1.6,
            marker_size=5,
        ))

    fig.update_layout(
        title=dict(text="Rent Distribution by Unit Type", font_size=14),
        yaxis=dict(title="Monthly Rent ($)", tickformat="$,.0f", showgrid=True, gridcolor="#E8E3D4"),
        showlegend=False,
        plot_bgcolor="#FFFFFF",
        paper_bgcolor="#FFFFFF",
        font=dict(family="Inter, sans-serif", size=12, color="#3D4152"),
        margin=dict(t=55, b=35, l=55, r=20),
        height=380,
    )
    return fig


# ---------------------------------------------------------------------------
# Scatter — rent vs distance
# ---------------------------------------------------------------------------

def build_scatter_chart(listings: list) -> go.Figure:
    if not listings:
        return go.Figure()

    df = pd.DataFrame(listings)
    fig = px.scatter(
        df,
        x="distance_miles",
        y="rent",
        color="unit_type",
        color_discrete_map=UNIT_COLOURS,
        category_orders={"unit_type": UNIT_ORDER},
        hover_data={"address": True, "source": True, "sqft": True,
                    "distance_miles": ":.2f", "rent": ":$,.0f"},
        labels={
            "distance_miles": "Distance from Subject (mi)",
            "rent": "Monthly Rent ($)",
            "unit_type": "Unit Type",
        },
        title="Rent vs Distance from Subject Property",
        height=360,
    )
    fig.update_traces(
        marker=dict(size=9, opacity=0.82, line=dict(width=1, color="white"))
    )
    fig.update_layout(
        plot_bgcolor="#FFFFFF",
        paper_bgcolor="#FFFFFF",
        font=dict(family="Inter, sans-serif", size=12, color="#3D4152"),
        yaxis=dict(tickformat="$,.0f", showgrid=True, gridcolor="#E8E3D4"),
        xaxis=dict(showgrid=True, gridcolor="#E8E3D4"),
        legend_title="Unit Type",
        margin=dict(t=55, b=35, l=55, r=20),
    )
    return fig

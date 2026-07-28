"""Compact KPI-card mini-charts (sparkline / donut / mini-bar) -- the
Power-BI-style "number + small embedded chart in one card" pattern,
deliberately denser than a plain stat tile. Each mini-chart is stripped of
axes/gridlines/margins so it reads as part of the card, not a standalone
chart; real data only, no placeholder/dummy series.
"""
from __future__ import annotations

import plotly.graph_objects as go

from pipeline.reference.airlines import AIRLINE_COLOR_HEX, OTHER_COLOR_HEX

COLOR_BLUE = "#2a78d6"
COLOR_AQUA = "#1baf7a"
STATUS_COLORS = {"normal": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}


def _strip_chrome(fig: go.Figure, height: int) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=4, r=4, t=4, b=4),
        showlegend=False,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="system-ui, -apple-system, 'Segoe UI', sans-serif", size=10),
    )
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return fig


def sparkline_card(values: list[float], color: str = COLOR_BLUE, height: int = 70) -> go.Figure:
    """A minimal area+line sparkline -- the recent-trend mini-chart used
    inside a KPI card. Needs at least 2 points to draw a line; a single
    point renders as a lone marker instead of erroring."""
    x = list(range(len(values)))
    fig = go.Figure()
    if len(values) >= 2:
        fig.add_trace(
            go.Scatter(
                x=x, y=values, mode="lines", line=dict(color=color, width=2),
                fill="tozeroy", fillcolor=color + "22",
                hoverinfo="skip",
            )
        )
    elif len(values) == 1:
        fig.add_trace(go.Scatter(x=[0], y=values, mode="markers", marker=dict(color=color, size=8), hoverinfo="skip"))
    return _strip_chrome(fig, height)


def donut_card(labels: list[str], values: list[float], height: int = 130) -> go.Figure:
    """Compact donut using the fixed airline categorical order (never
    cycled) + a shared "Other" grey for anything uncatalogued -- same
    color-by-entity rule as the ranked airlines bar chart."""
    colors = [AIRLINE_COLOR_HEX.get(l, OTHER_COLOR_HEX) for l in labels]
    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            hole=0.62,
            marker=dict(colors=colors, line=dict(color="rgba(0,0,0,0)", width=0)),
            textinfo="none",
            hovertemplate="%{label}: %{value} (%{percent})<extra></extra>",
        )
    )
    return _strip_chrome(fig, height)


def mini_bar_card(labels: list[str], values: list[float], colors: list[str], height: int = 90) -> go.Figure:
    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker=dict(color=colors, cornerradius=3),
            hovertemplate="%{y}: %{x}<extra></extra>",
        )
    )
    fig.update_yaxes(autorange="reversed")
    return _strip_chrome(fig, height)

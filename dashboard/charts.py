"""Chart builders for the anomaly-trend view, the ranked bar, and the
current-alerts panel. Follows the validated default palette and mark specs
(rounded bars, hairline gridlines, transparent theme-adaptive surfaces) --
see dashboard/app.py's module docstring and the ev-charging-gap-analysis
sibling's dashboard for the established conventions this extends.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.graph_objects as go
from boto3.dynamodb.conditions import Key

from pipeline.aws_clients import dynamodb_resource
from pipeline.config import DYNAMODB_CONFLICT_EVENTS_TABLE, DYNAMODB_TRAFFIC_TABLE
from pipeline.reference.airlines import AIRLINE_COLOR_HEX, OTHER_COLOR_HEX

COLOR_BLUE = "#2a78d6"
COLOR_ORANGE = "#eb6834"
COLOR_AQUA = "#1baf7a"
STATUS_COLORS = {"normal": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}
STATUS_ICONS = {"normal": "✓", "warning": "⚠", "serious": "⚠", "critical": "✖"}


def _base_chart_layout(fig: go.Figure, title: str) -> go.Figure:
    fig.update_layout(
        title=title,
        template="plotly_white",
        margin=dict(l=40, r=20, t=50, b=40),
        font=dict(family="system-ui, -apple-system, 'Segoe UI', sans-serif"),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        hoverlabel=dict(font_size=13),
    )
    fig.update_xaxes(showgrid=True, gridcolor="rgba(128,128,128,0.2)", zeroline=False)
    fig.update_yaxes(showgrid=False, linecolor="rgba(128,128,128,0.4)")
    return fig


def load_region_history(region: str, hours_back: int) -> pd.DataFrame:
    table = dynamodb_resource().Table(DYNAMODB_TRAFFIC_TABLE)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours_back)).isoformat()
    resp = table.query(
        KeyConditionExpression=Key("region_pk").eq(f"REGION#{region}") & Key("bucket_sk").gte(f"BUCKET#{cutoff}"),
    )
    rows = []
    for item in resp["Items"]:
        rows.append(
            {
                "bucket_sk": pd.Timestamp(item["bucket_sk"].replace("BUCKET#", "")),
                "aircraft_count": float(item["aircraft_count"]),
                "rolling_mean": float(item["rolling_mean"]) if "rolling_mean" in item else None,
                "anomaly_status": item.get("anomaly_status", "insufficient_baseline"),
            }
        )
    return pd.DataFrame(rows).sort_values("bucket_sk") if rows else pd.DataFrame(
        columns=["bucket_sk", "aircraft_count", "rolling_mean", "anomaly_status"]
    )


def load_conflict_events(region: str, hours_back: int) -> pd.DataFrame:
    table = dynamodb_resource().Table(DYNAMODB_CONFLICT_EVENTS_TABLE)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours_back)).isoformat()
    resp = table.query(
        IndexName="gsi1_region_by_time",
        KeyConditionExpression=Key("region_gsi_pk").eq(f"REGION#{region}") & Key("event_timestamp").gte(cutoff),
    )
    return pd.DataFrame(resp["Items"])


def anomaly_trend_chart(region: str, hours_back: int, include_conflict_overlay: bool = True) -> go.Figure:
    history = load_region_history(region, hours_back)
    events = load_conflict_events(region, hours_back) if include_conflict_overlay else pd.DataFrame()

    fig = go.Figure()
    if not history.empty:
        fig.add_trace(
            go.Scatter(
                x=history["bucket_sk"],
                y=history["aircraft_count"],
                mode="lines+markers",
                name="Aircraft count",
                line=dict(color=COLOR_BLUE, width=2),
                marker=dict(size=8, color=COLOR_BLUE),
                hovertemplate="%{x|%H:%M}<br>%{y:.0f} aircraft<extra></extra>",
            )
        )
        baseline = history.dropna(subset=["rolling_mean"])
        if not baseline.empty:
            fig.add_trace(
                go.Scatter(
                    x=baseline["bucket_sk"],
                    y=baseline["rolling_mean"],
                    mode="lines",
                    name="Rolling baseline",
                    line=dict(color=COLOR_AQUA, width=2, dash="dot"),
                    hovertemplate="%{x|%H:%M}<br>baseline %{y:.1f}<extra></extra>",
                )
            )

    if not events.empty:
        events = events.copy()
        events["num_mentions"] = pd.to_numeric(events["num_mentions"], errors="coerce").fillna(1)
        events = events.sort_values("num_mentions", ascending=False)
        total_events = len(events)
        events = events.head(8)
        events["event_timestamp"] = pd.to_datetime(events["event_timestamp"])
        events["goldstein_scale"] = pd.to_numeric(events["goldstein_scale"], errors="coerce").fillna(0)
        marker_color = events["goldstein_scale"].apply(lambda g: STATUS_COLORS["critical"] if g < -7 else STATUS_COLORS["serious"])
        y_top = history["aircraft_count"].max() * 1.1 if not history.empty else 1

        fig.add_trace(
            go.Scatter(
                x=events["event_timestamp"],
                y=[y_top] * len(events),
                mode="markers",
                name="Conflict events (GDELT)",
                marker=dict(
                    size=(events["num_mentions"].clip(upper=50) / 3 + 8),
                    color=marker_color,
                    line=dict(width=1, color="rgba(0,0,0,0.3)"),
                ),
                customdata=events[["actor1_name", "actor2_name", "event_code", "num_mentions", "goldstein_scale", "source_url"]],
                hovertemplate=(
                    "<b>%{customdata[0]} / %{customdata[1]}</b><br>"
                    "Event code: %{customdata[2]}<br>"
                    "Mentions: %{customdata[3]}<br>"
                    "Goldstein: %{customdata[4]:.1f}<br>"
                    "%{customdata[5]}<extra></extra>"
                ),
            )
        )
        for ts in events["event_timestamp"]:
            fig.add_vline(x=ts, line_dash="dash", line_color="rgba(208,59,59,0.3)", line_width=1)

        caption_n = min(8, total_events)
        fig.update_layout(annotations=[dict(
            text=f"showing top {caption_n} of {total_events} conflict events by mentions",
            xref="paper", yref="paper", x=0, y=1.08, showarrow=False, font=dict(size=11, color="gray"),
        )])

    fig = _base_chart_layout(fig, f"{region}: Aircraft Traffic Over Time")
    fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0))
    # Fix the x-axis to the actual requested window rather than letting
    # Plotly autorange -- with only 1-2 real data points early on (before
    # the scheduled pipeline has accumulated history), autorange zooms in
    # to microsecond precision around the single timestamp, which is
    # confusing/broken-looking rather than just "sparse."
    now = datetime.now(timezone.utc)
    fig.update_xaxes(range=[now - timedelta(hours=hours_back), now])
    return fig


def ranked_traffic_bar(counts_by_region: dict[str, int]) -> go.Figure:
    """Ranked horizontal bar of current aircraft count by region -- same
    mark spec as the ev-charging-gap-analysis sibling (4px rounded corners,
    categorical blue, top-3 direct labels), deliberate visual continuity
    across the portfolio."""
    items = sorted(counts_by_region.items(), key=lambda kv: kv[1])
    regions = [k for k, _ in items]
    counts = [v for _, v in items]
    top3_cutoff = sorted(counts, reverse=True)[2] if len(counts) >= 3 else (max(counts) if counts else 0)
    text = [str(c) if c >= top3_cutoff else "" for c in counts]

    fig = go.Figure(
        go.Bar(
            x=counts,
            y=regions,
            orientation="h",
            marker=dict(color=COLOR_BLUE, cornerradius=4),
            text=text,
            textposition="outside",
            hovertemplate="%{y}<br>%{x} aircraft<extra></extra>",
        )
    )
    if counts:
        fig.update_xaxes(range=[0, max(counts) * 1.15])
    return _base_chart_layout(fig, "Aircraft Count by Region Right Now")


def ranked_airlines_bar(counts_by_airline: dict[str, int], top_n: int = 8) -> go.Figure:
    """Ranked horizontal bar of current aircraft count by airline. Unlike
    the map (an all-pairs context, capped at 3 categorical colors), a bar
    chart is adjacent-pairs only, so it can safely use the full validated
    8-slot categorical order -- each airline always gets the SAME color
    regardless of rank (dataviz skill: "color follows the entity, never
    its rank"), "Other"/uncatalogued airlines share one neutral grey.
    """
    items = sorted(counts_by_airline.items(), key=lambda kv: kv[1])[-top_n:]
    airlines = [k for k, _ in items]
    counts = [v for _, v in items]
    colors = [AIRLINE_COLOR_HEX.get(a, OTHER_COLOR_HEX) for a in airlines]
    top3_cutoff = sorted(counts, reverse=True)[2] if len(counts) >= 3 else (max(counts) if counts else 0)
    text = [str(c) if c >= top3_cutoff else "" for c in counts]

    fig = go.Figure(
        go.Bar(
            x=counts,
            y=airlines,
            orientation="h",
            marker=dict(color=colors, cornerradius=4),
            text=text,
            textposition="outside",
            hovertemplate="%{y}<br>%{x} aircraft<extra></extra>",
        )
    )
    if counts:
        fig.update_xaxes(range=[0, max(counts) * 1.15])
    return _base_chart_layout(fig, "Airlines in Middle East Airspace Right Now")


def alert_badges_html(airport_status: dict[str, str]) -> str:
    """Icon+label status badges, worst-first -- status color never carries
    meaning alone (dataviz skill: status colors always ship with icon+label)."""
    order = {"critical": 0, "serious": 1, "warning": 2, "normal": 3, "insufficient_baseline": 4}
    ranked = sorted(airport_status.items(), key=lambda kv: order.get(kv[1], 5))
    spans = []
    for region, status in ranked:
        color = STATUS_COLORS.get(status, "#898781")
        icon = STATUS_ICONS.get(status, "•")
        spans.append(
            f'<span class="alert-badge" style="background:{color}22;color:{color};border:1px solid {color}66">'
            f"{icon} {region}: {status}</span>"
        )
    return "".join(spans)

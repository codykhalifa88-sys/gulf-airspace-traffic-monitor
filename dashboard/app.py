"""
Streamlit dashboard for the Middle East Airspace Live Traffic & Disruption Monitor.

The live map polls OpenSky directly from this process on every autorefresh
tick (matching the crypto-streaming-pipeline sibling's st_autorefresh
pattern) -- showing current positions is already what OpenSky's /states/all
returns, so routing it through the Kinesis/S3/DynamoDB backbone first would
only add latency for zero benefit. That backbone exists to build history
(traffic-volume-over-time, the anomaly baseline, GDELT correlation) -- a
genuinely different job. If the direct poll fails/is rate-limited, the map
falls back to the most recent bronze S3 object with a "cached" banner.

Color usage follows the validated default palette (categorical blue/orange
/aqua/yellow/magenta/green/violet/red, status good/warning/serious/
critical) -- see dataviz skill's references/palette.md,
pipeline/reference/airlines.py's fixed categorical order, and
pipeline/serving/load_dynamodb.py's _ALERT_STATUSES. Chart chrome stays
theme-adaptive (Streamlit's own CSS variables, transparent Plotly
backgrounds) except the live map itself, a deliberate documented exception
(see live_map.py docstring).
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st
from boto3.dynamodb.conditions import Key
from streamlit_autorefresh import st_autorefresh

from dashboard.charts import (
    alert_badges_html,
    anomaly_trend_chart,
    load_conflict_events,
    load_region_history,
    ranked_airlines_bar,
    ranked_traffic_bar,
)
from dashboard.kpi_cards import donut_card, mini_bar_card, sparkline_card
from dashboard.live_map import build_map
from pipeline import s3_io
from pipeline.aws_clients import dynamodb_resource, s3_client
from pipeline.config import AIRPORTS, DYNAMODB_TRAFFIC_TABLE, S3_BUCKET_NAME
from pipeline.ingest.opensky_states import fetch_states, states_to_records
from pipeline.reference.restricted_airspace import DETOUR_AFFECTED_AIRLINES, estimate_detour_cost_usd, zone_for_point
from pipeline.transform.silver import clean_opensky_states

COLOR_BLUE = "#2a78d6"
COLOR_ORANGE = "#eb6834"
COLOR_AQUA = "#1baf7a"
STATUS_COLORS = {"normal": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}

st.set_page_config(page_title="Middle East Airspace Traffic Monitor", layout="wide", page_icon="\U0001f6eb")

st.markdown(
    """
    <style>
    .hero-banner {
        background: linear-gradient(120deg, #184f95 0%, #2a78d6 45%, #1baf7a 100%);
        border-radius: 16px;
        padding: 1.75rem 2rem;
        color: #ffffff;
        margin-bottom: 1rem;
    }
    .hero-banner h1 { margin: 0; font-size: 2rem; font-weight: 800; color: #ffffff; }
    .hero-banner p { margin: 0.35rem 0 0 0; opacity: 0.92; font-size: 0.95rem; }
    .alert-badge {
        display: inline-flex; align-items: center; gap: 0.4rem;
        padding: 0.3rem 0.7rem; border-radius: 999px; font-size: 0.85rem; font-weight: 600;
        margin: 0.15rem;
    }
    .cost-card {
        background: linear-gradient(135deg, #ec835a22 0%, #d03b3b22 100%);
        border: 1px solid #d03b3b55;
        border-radius: 12px;
        padding: 1.25rem 1.5rem;
    }
    .cost-card .headline { font-size: 1.6rem; font-weight: 800; color: #d03b3b; }
    .cost-card .sub { font-size: 0.85rem; opacity: 0.8; margin-top: 0.25rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=600)
def load_latest_status_per_region() -> dict[str, str]:
    """Most recent anomaly_status per region, for the map's airport halos
    -- a plain base-table Query (PK=region_pk), not the alert GSI, since we
    want every airport's current status (including "normal"), not just
    flagged ones."""
    table = dynamodb_resource().Table(DYNAMODB_TRAFFIC_TABLE)
    statuses = {}
    for code in AIRPORTS:
        resp = table.query(
            KeyConditionExpression=Key("region_pk").eq(f"REGION#{code}"),
            ScanIndexForward=False,
            Limit=1,
        )
        if resp["Items"]:
            statuses[code] = resp["Items"][0].get("anomaly_status", "insufficient_baseline")
    return statuses


def load_live_states() -> tuple[pd.DataFrame, str]:
    """Direct OpenSky poll for the live map. Falls back to the most recent
    bronze S3 object (with an honest "cached" freshness label) if the poll
    fails -- shared rate-limit budget across concurrent dashboard viewers
    makes an occasional failure a real, expected condition, not exceptional.
    """
    try:
        response = fetch_states()
        records = states_to_records(response)
        df = clean_opensky_states(records)
        return df, "live"
    except Exception:
        s3 = s3_client()
        objects = s3.list_objects_v2(Bucket=S3_BUCKET_NAME, Prefix="bronze/opensky_states/")
        contents = objects.get("Contents", [])
        if not contents:
            return pd.DataFrame(), "unavailable"
        latest = max(contents, key=lambda o: o["LastModified"])
        import json

        body = s3_io.read_bytes(latest["Key"])
        records = [json.loads(line) for line in body.decode().splitlines() if line.strip()]
        df = clean_opensky_states(records)
        return df, f"cached (from {latest['LastModified']:%H:%M UTC})"


st_autorefresh(interval=15_000, key="live_refresh")

st.markdown(
    """
    <div class="hero-banner">
        <h1>🛫 Middle East Airspace Live Traffic &amp; Disruption Monitor</h1>
        <p>Real-time aircraft across the Middle East &middot; traffic-anomaly detection correlated against real conflict events
        &middot; Middle East airspace-avoidance cost impact, grounded in real 2026 industry reporting</p>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Map controls")
    map_height = st.slider("Map height (px)", min_value=350, max_value=900, value=650, step=25)
    show_restricted_zones = st.checkbox("Show restricted airspace (Iran/Iraq/Yemen)", value=True)
    show_corridor_lines = st.checkbox("Show nearby-airport corridor lines", value=True)

    st.header("Filters")
    trend_region = st.selectbox("Region (trend chart / airport detail)", list(AIRPORTS.keys()), index=0)
    hours_back = st.select_slider("Time range", options=[6, 24, 72], value=24, format_func=lambda h: f"{h}h")
    show_conflict_overlay = st.checkbox("Show conflict-event overlay", value=True)

    st.header("Playback")
    playback_hours_ago = st.slider(
        "Replay airport status (hours ago)",
        min_value=0.0,
        max_value=float(hours_back),
        value=0.0,
        step=1.0 if hours_back >= 24 else 0.5,
        help="Scrub back to see each airport's anomaly status at an earlier point in the selected time range. "
        "Aircraft positions on the map are always live -- only the airport status halos replay historically "
        "(we store traffic-count history per region, not raw historical aircraft positions).",
    )

states_df, freshness = load_live_states()
airport_status = load_latest_status_per_region()

_event_regions = list(AIRPORTS.keys()) + ["OTHER"]
all_events = (
    pd.concat([load_conflict_events(code, hours_back) for code in _event_regions], ignore_index=True)
    if _event_regions
    else pd.DataFrame()
)

with st.sidebar:
    if not states_df.empty and "airline" in states_df.columns:
        all_airlines = sorted(states_df["airline"].unique())
        selected_airlines = st.multiselect("Airlines (map + counts)", all_airlines, default=[])
    else:
        selected_airlines = []

filtered_states = (
    states_df[states_df["airline"].isin(selected_airlines)] if selected_airlines and not states_df.empty else states_df
)


@st.cache_data(ttl=60)
def load_status_history_all(hours_back: int) -> dict[str, pd.DataFrame]:
    """Per-region traffic history for the playback slider -- cached
    separately from load_latest_status_per_region since this pulls the
    full window, not just the latest item."""
    return {code: load_region_history(code, hours_back) for code in AIRPORTS}


def status_at_offset(histories: dict[str, pd.DataFrame], hours_ago: float) -> dict[str, str]:
    target = pd.Timestamp(datetime.now(timezone.utc) - timedelta(hours=hours_ago))
    statuses = {}
    for code, hist in histories.items():
        past = hist[hist["bucket_sk"] <= target] if not hist.empty else hist
        statuses[code] = past.iloc[-1]["anomaly_status"] if not past.empty else "insufficient_baseline"
    return statuses


if playback_hours_ago > 0:
    viewing_time = datetime.now(timezone.utc) - timedelta(hours=playback_hours_ago)
    map_airport_status = status_at_offset(load_status_history_all(hours_back), playback_hours_ago)
    playback_caption = f"⏪ Replaying airport status as of **{viewing_time:%Y-%m-%d %H:%M} UTC** — aircraft positions shown are still live"
else:
    map_airport_status = airport_status
    playback_caption = None

if filtered_states.empty:
    st.info("No live aircraft data available right now (OpenSky may be rate-limited, or your airline filter matched nothing) -- try again shortly.")
else:
    deck = build_map(
        filtered_states,
        map_airport_status,
        height=map_height,
        show_restricted_zones=show_restricted_zones,
        show_corridor_lines=show_corridor_lines,
    )
    st.pydeck_chart(deck, use_container_width=True)

if playback_caption:
    st.warning(playback_caption)
st.caption(f"Last refreshed {datetime.now(timezone.utc):%H:%M:%S} UTC · auto-refreshes every 15s")

# ---- Airport detail panel -- a click-to-inspect popover would need a
# newer st.pydeck_chart selection API than this Streamlit version exposes,
# so the sidebar's region selector (shared with the trend chart below)
# drives this panel instead: pick an airport, see its own history here. ----
with st.container(border=True):
    detail_status = airport_status.get(trend_region, "insufficient_baseline")
    detail_color = STATUS_COLORS.get(detail_status, "#898781")
    detail_history = load_region_history(trend_region, hours_back)
    d_col1, d_col2 = st.columns([1, 2])
    with d_col1:
        st.markdown(f"#### ✈️ {trend_region} detail")
        st.markdown(
            f'<span class="alert-badge" style="background:{detail_color}22;color:{detail_color};'
            f'border:1px solid {detail_color}66">current status: {detail_status}</span>',
            unsafe_allow_html=True,
        )
        if not detail_history.empty:
            latest_count = int(detail_history.iloc[-1]["aircraft_count"])
            mean_count = detail_history["aircraft_count"].mean()
            st.metric("Latest bucket aircraft count", latest_count, delta=f"{latest_count - mean_count:+.1f} vs {hours_back}h avg")
        else:
            st.caption("No history yet for this airport in the selected window.")
    with d_col2:
        if not detail_history.empty:
            st.plotly_chart(
                sparkline_card(list(detail_history["aircraft_count"]), color=COLOR_BLUE, height=90),
                use_container_width=True,
                config={"displayModeBar": False},
            )
            st.caption(f"Aircraft-count trend, last {hours_back}h ({len(detail_history)} buckets)")
        else:
            st.caption("Pick a different region above, or wait for the scheduled pipeline to accumulate history.")

# ---- KPI card row: number + embedded mini-chart per card, Power-BI-style ----
active_alerts = sum(1 for s in airport_status.values() if s in ("warning", "serious", "critical"))
busiest = filtered_states["nearest_region"].value_counts().idxmax() if not filtered_states.empty else "—"

card1, card2, card3, card4 = st.columns(4)

with card1:
    with st.container(border=True):
        st.caption("Aircraft tracked")
        st.markdown(f"### {len(filtered_states):,}")
        if not filtered_states.empty:
            top5 = filtered_states["nearest_region"].value_counts().head(5)
            st.plotly_chart(
                mini_bar_card(list(top5.index), list(top5.values), [COLOR_BLUE] * len(top5)),
                use_container_width=True,
                config={"displayModeBar": False},
            )
        st.caption(f"Busiest right now: **{busiest}**")

with card2:
    with st.container(border=True):
        st.caption("Airlines active")
        n_airlines = filtered_states["airline"].nunique() if not filtered_states.empty and "airline" in filtered_states.columns else 0
        st.markdown(f"### {n_airlines}")
        if not filtered_states.empty and "airline" in filtered_states.columns:
            top_airlines = filtered_states["airline"].value_counts().head(6)
            st.plotly_chart(
                donut_card(list(top_airlines.index), list(top_airlines.values)),
                use_container_width=True,
                config={"displayModeBar": False},
            )
        st.caption("Top 6 by aircraft currently tracked")

with card3:
    with st.container(border=True):
        st.caption("Anomaly alerts")
        st.markdown(f"### {active_alerts}")
        status_counts = pd.Series(list(airport_status.values())).value_counts() if airport_status else pd.Series(dtype=int)
        if not status_counts.empty:
            order = ["critical", "serious", "warning", "normal", "insufficient_baseline"]
            ordered = [(s, status_counts.get(s, 0)) for s in order if status_counts.get(s, 0) > 0]
            st.plotly_chart(
                mini_bar_card(
                    [s for s, _ in ordered],
                    [c for _, c in ordered],
                    [STATUS_COLORS.get(s, "#898781") for s, _ in ordered],
                ),
                use_container_width=True,
                config={"displayModeBar": False},
            )
        st.caption(f"across {len(AIRPORTS)} tracked airports")

with card4:
    with st.container(border=True):
        st.caption("Data freshness")
        st.markdown(f"### {freshness}")
        st.plotly_chart(
            mini_bar_card(["tracked airports", "restricted zones"], [len(AIRPORTS), 3], [COLOR_AQUA, "#d03b3b"]),
            use_container_width=True,
            config={"displayModeBar": False},
        )
        st.caption("15 Middle East airports, 3 restricted-zone overlays")

# ---- Second KPI row: restricted-zone proximity, altitude/speed profile, conflict events in window ----
if not filtered_states.empty:
    zone_hits = filtered_states.apply(lambda r: zone_for_point(r["latitude"], r["longitude"]), axis=1)
    near_restricted_count = int(zone_hits.notna().sum())
    zone_counts = zone_hits.dropna().value_counts()
else:
    near_restricted_count = 0
    zone_counts = pd.Series(dtype=int)

card5, card6, card7 = st.columns(3)

with card5:
    with st.container(border=True):
        st.caption("Near restricted airspace")
        st.markdown(f"### {near_restricted_count}")
        if not zone_counts.empty:
            st.plotly_chart(
                mini_bar_card(list(zone_counts.index), list(zone_counts.values), ["#d03b3b"] * len(zone_counts)),
                use_container_width=True,
                config={"displayModeBar": False},
            )
        st.caption("aircraft currently inside the simplified Iran/Iraq/Yemen boxes")

with card6:
    with st.container(border=True):
        st.caption("Avg altitude / speed")
        if not filtered_states.empty and filtered_states["baro_altitude"].notna().any():
            avg_alt_ft = filtered_states["baro_altitude"].dropna().mean() * 3.28084
            avg_speed_kt = filtered_states["velocity"].dropna().mean() * 1.94384
            st.markdown(f"### {avg_alt_ft:,.0f} ft")
            bins = [-1, 3000, 9000, 100000]
            labels = ["<10k ft", "10-30k ft", ">30k ft"]
            bands = pd.cut(filtered_states["baro_altitude"].dropna(), bins=bins, labels=labels).value_counts().reindex(labels, fill_value=0)
            st.plotly_chart(
                mini_bar_card(list(bands.index), list(bands.values), [COLOR_AQUA] * len(bands)),
                use_container_width=True,
                config={"displayModeBar": False},
            )
            st.caption(f"avg speed **{avg_speed_kt:,.0f} kt** across {len(filtered_states)} tracked aircraft")
        else:
            st.markdown("### —")
            st.caption("No altitude/speed data in the current selection.")

with card7:
    with st.container(border=True):
        st.caption("Conflict events (window)")
        st.markdown(f"### {len(all_events):,}")
        if not all_events.empty and "nearest_region" in all_events.columns:
            top_event_regions = all_events["nearest_region"].value_counts().head(5)
            st.plotly_chart(
                mini_bar_card(list(top_event_regions.index), list(top_event_regions.values), [COLOR_ORANGE] * len(top_event_regions)),
                use_container_width=True,
                config={"displayModeBar": False},
            )
        st.caption(f"GDELT conflict events near tracked regions, last {hours_back}h")

st.divider()

# ---- Middle East airspace-avoidance cost impact -- grounded in real 2026 reporting ----
st.subheader("🌍 Middle East Airspace Avoidance — Real Cost Impact")
detour_count = int(filtered_states["airline"].isin(DETOUR_AFFECTED_AIRLINES).sum()) if not filtered_states.empty and "airline" in filtered_states.columns else 0
cost = estimate_detour_cost_usd(detour_count)

cost_col, info_col = st.columns([1, 2])
with cost_col:
    st.markdown(
        f"""
        <div class="cost-card">
            <div class="headline">${cost['low_usd']:,} – ${cost['high_usd']:,}</div>
            <div class="sub">estimated extra fuel cost right now, for {detour_count} tracked flights on airlines
            named in 2026 reporting as avoiding Iranian/Iraqi airspace</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with info_col:
    st.markdown(
        r"""
        Real, cited 2026 industry reporting: rerouting around Iranian/Iraqi airspace adds **300–800 nautical miles**
        and **45–120 minutes** of block time on affected Europe–Asia routes. A 2–3 hour widebody detour can add
        **\$6,000+ per flight hour** in operating cost; fuel alone adds **\$5,000+ per sector** at recent jet-fuel
        pricing. Etihad cancelled 450+ flights and Air India halted transit-dependent long-haul routes in the same
        period. Economists estimate the cumulative industry-wide cost could **exceed \$1 billion** if the conflict
        extends. *(Sources: EASA guidance, SimpleFlying, The National, aerospaceglobalnews.com — see
        docs/data_dictionary.md for full citations.)*
        """
    )
st.caption(
    "This dashboard's estimate applies those real per-hour cost figures to currently-tracked flights on the "
    "airlines named as most disrupted — it is an illustrative estimate using published methodology, not a "
    "precise per-flight measurement (this project doesn't have route/schedule data to confirm any single "
    "flight is actually detouring)."
)

st.divider()

st.subheader("Current alerts")
if airport_status:
    st.markdown(alert_badges_html(airport_status), unsafe_allow_html=True)
else:
    st.caption("No alert data yet -- the scheduled pipeline needs to run a few times first.")

st.divider()

left, right = st.columns(2)
with left:
    if not filtered_states.empty:
        counts_by_region = filtered_states["nearest_region"].value_counts().to_dict()
        st.plotly_chart(ranked_traffic_bar(counts_by_region), use_container_width=True)

with right:
    if not filtered_states.empty and "airline" in filtered_states.columns:
        counts_by_airline = filtered_states["airline"].value_counts().to_dict()
        st.plotly_chart(ranked_airlines_bar(counts_by_airline), use_container_width=True)

st.divider()

trend_fig = anomaly_trend_chart(trend_region, hours_back, include_conflict_overlay=show_conflict_overlay)
st.plotly_chart(trend_fig, use_container_width=True)
if airport_status.get(trend_region) == "insufficient_baseline" or trend_region not in airport_status:
    st.caption(
        f"{trend_region}'s rolling baseline is still filling in (needs ~1h of scheduled-run history "
        "before anomaly status becomes meaningful)."
    )

st.divider()
st.subheader("Recent conflict events near tracked regions (GDELT)")
# Includes "OTHER" (overflight/transit traffic, beyond 150km of any of the
# 15 named airports) alongside the airports -- real events during
# development landed there, not at a named airport, and omitting it would
# silently hide genuine Middle East conflict events from this table.
# (all_events was already loaded earlier, alongside the sidebar controls,
# so the "Conflict events (window)" KPI card and this table share one query.)
if not all_events.empty:
    display_cols = [c for c in ["event_timestamp", "nearest_region", "actor1_name", "actor2_name", "event_code", "num_mentions", "goldstein_scale", "source_url"] if c in all_events.columns]
    st.dataframe(
        all_events[display_cols].sort_values("event_timestamp", ascending=False),
        use_container_width=True,
        height=300,
        column_config={"source_url": st.column_config.LinkColumn("Source")},
    )
else:
    st.caption("No conflict-relevant GDELT events near tracked regions in this time window.")

st.divider()
st.caption(
    "⚠️ OpenSky anonymous access is rate-limited (400 req/2.2hr) and shared across concurrent viewers -- "
    "the live map may occasionally show cached data. GDELT ActionGeo_CountryCode is FIPS 10-4, not ISO. "
    "Restricted-zone boundaries are simplified rectangular approximations, not exact FIR boundaries. "
    "The rolling anomaly baseline is recency-based (not seasonal/weekday-aware) and needs real accumulated "
    "history from the scheduled pipeline before it's meaningful -- a real spike (e.g. Hajj/Umrah season "
    "traffic into JED) is not the same as a disruption, and is surfaced separately as anomaly_direction."
)

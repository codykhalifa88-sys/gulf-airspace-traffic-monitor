"""Live pydeck radar map -- the dashboard's visual centerpiece. Deliberately
stays permanently dark (CARTO/deck.gl DARK basemap), not theme-adaptive like
the rest of the dashboard: a radar display reads best dark always, and the
basemap's own grays/blues are chrome/context, not encoded data, so they sit
outside the app's categorical palette on purpose.

IconLayer's rotation renders the "ATC radar" look Plotly can't do (no
scattermapbox token needed, no scattergeo street tiles at all) -- per-point
rotation via get_angle driven by true_track (heading), the one feature that
makes this look like real air-traffic radar instead of a scatter plot.

Aircraft are colored by airline, capped at the 3 Gulf carriers most
frequently named in real 2026 reporting as disrupted by Iran/Iraq airspace
avoidance (Emirates, Etihad, Qatar Airways) plus "Other" -- a map/scatter
context needs the all-pairs CVD cap (dataviz skill: "the first three slots
validate all-pairs... past three, fold to Other"), not the 8-color
adjacent-pairs cap a bar chart could use. The fuller airline breakdown
(all real airlines seen) is a separate ranked bar chart in the dashboard,
which can safely use more categorical slots since bars are only
adjacent-pairs, not all-pairs.
"""
from __future__ import annotations

import base64
from pathlib import Path

import pandas as pd
import pydeck as pdk

from pipeline.config import AIRPORTS
from pipeline.reference.airlines import AIRLINE_CATEGORICAL_ORDER, AIRLINE_COLOR_HEX
from pipeline.reference.restricted_airspace import RESTRICTED_ZONES

COLOR_GREY = [137, 135, 129, 255]


def _hex_to_rgb(h: str) -> list[int]:
    h = h.lstrip("#")
    return [int(h[i : i + 2], 16) for i in (0, 2, 4)] + [255]


# Map is an all-pairs context (many points visible simultaneously) -- the
# dataviz skill caps that at 3 categorical slots; the fuller 8-airline
# breakdown lives in the separate ranked bar chart (adjacent-pairs only).
_MAP_AIRLINE_ORDER = AIRLINE_CATEGORICAL_ORDER[:3]
AIRLINE_COLORS = {name: _hex_to_rgb(AIRLINE_COLOR_HEX[name]) for name in _MAP_AIRLINE_ORDER}

STATUS_COLORS = {
    "critical": [208, 59, 59, 140],
    "serious": [236, 131, 90, 140],
    "warning": [250, 178, 25, 140],
    "normal": [12, 163, 12, 60],
    "insufficient_baseline": [137, 135, 129, 50],
}

_ICON_PATH = Path(__file__).parent / "assets" / "plane_icon.png"


def _plane_icon_data_uri() -> str:
    b64 = base64.b64encode(_ICON_PATH.read_bytes()).decode()
    return f"data:image/png;base64,{b64}"


def _zone_polygon(box: dict) -> list[list[float]]:
    return [
        [box["lomin"], box["lamin"]],
        [box["lomax"], box["lamin"]],
        [box["lomax"], box["lamax"]],
        [box["lomin"], box["lamax"]],
    ]


def build_map(
    states_df: pd.DataFrame,
    airport_status: dict[str, str],
    height: int = 520,
    show_restricted_zones: bool = True,
    show_corridor_lines: bool = True,
) -> pdk.Deck:
    """states_df: real-time OpenSky state vectors with at least
    [longitude, latitude, true_track, callsign, airline, origin_country,
    baro_altitude, velocity, nearest_region]. airport_status: {airport_code:
    anomaly_status} for the translucent halo under each airport, e.g.
    {"DXB": "critical"}. Airports with no current status default to
    "insufficient_baseline" styling (dim, not alarming) rather than being
    omitted. height controls the map's rendered size (user-adjustable via a
    sidebar slider in dashboard/app.py). show_corridor_lines draws a thin
    arc from each aircraft to its nearest tracked airport (only drawn for
    aircraft already within the 150km assign_nearest_region threshold, i.e.
    genuinely in that airport's approach/departure corridor right now) --
    this is NOT a real flight route (OpenSky gives no flight-plan/route
    data), so it's deliberately framed as "nearest tracked corridor," not
    "origin-destination."
    """
    icon_uri = _plane_icon_data_uri()
    planes = states_df.copy()
    planes["icon_data"] = [
        {"url": icon_uri, "id": "plane", "width": 128, "height": 128, "anchorY": 64, "anchorX": 64, "mask": True}
        for _ in range(len(planes))
    ]
    planes["angle"] = planes["true_track"].fillna(0)
    planes["plane_color"] = planes.get("airline", pd.Series(dtype=object)).map(AIRLINE_COLORS)
    planes["plane_color"] = planes["plane_color"].apply(lambda c: c if isinstance(c, list) else COLOR_GREY)

    layers = []

    if show_restricted_zones:
        zone_rows = [
            {"name": name, "polygon": _zone_polygon(box), "fill_color": box["color"]}
            for name, box in RESTRICTED_ZONES.items()
        ]
        layers.append(
            pdk.Layer(
                "PolygonLayer",
                data=zone_rows,
                get_polygon="polygon",
                get_fill_color="fill_color",
                get_line_color=[208, 59, 59, 160],
                line_width_min_pixels=1,
                pickable=True,
                stroked=True,
                filled=True,
            )
        )

    airport_rows = [
        {
            "code": code,
            "longitude": lon_lat[1],
            "latitude": lon_lat[0],
            "status": airport_status.get(code, "insufficient_baseline"),
        }
        for code, lon_lat in AIRPORTS.items()
    ]
    airports_df = pd.DataFrame(airport_rows)
    airports_df["halo_color"] = airports_df["status"].map(STATUS_COLORS)

    layers.append(
        pdk.Layer(
            "ScatterplotLayer",
            data=airports_df,
            get_position=["longitude", "latitude"],
            get_fill_color="halo_color",
            get_radius=35000,
            pickable=True,
        )
    )
    layers.append(
        pdk.Layer(
            "ScatterplotLayer",
            data=airports_df,
            get_position=["longitude", "latitude"],
            get_fill_color=[255, 255, 255, 200],
            get_radius=4000,
            pickable=True,
        )
    )
    if show_corridor_lines and "nearest_region" in planes.columns:
        corridor_rows = []
        for _, row in planes.iterrows():
            region = row["nearest_region"]
            if region in AIRPORTS:
                apt_lat, apt_lon = AIRPORTS[region]
                corridor_rows.append(
                    {
                        "source": [row["longitude"], row["latitude"]],
                        "target": [apt_lon, apt_lat],
                        "color": row["plane_color"][:3] + [90],
                    }
                )
        if corridor_rows:
            layers.append(
                pdk.Layer(
                    "ArcLayer",
                    data=corridor_rows,
                    get_source_position="source",
                    get_target_position="target",
                    get_source_color="color",
                    get_target_color="color",
                    get_width=1.2,
                    great_circle=False,
                    pickable=False,
                )
            )

    layers.append(
        pdk.Layer(
            "IconLayer",
            data=planes,
            get_position=["longitude", "latitude"],
            get_icon="icon_data",
            get_size=24,
            get_angle="angle",
            get_color="plane_color",
            pickable=True,
            billboard=True,
        )
    )

    # Centered/zoomed to fit the full Middle East bbox (Egypt to Iran,
    # Yemen to Iraq/Syria), not just the Gulf.
    view_state = pdk.ViewState(latitude=24.75, longitude=47.0, zoom=4.3, pitch=0)

    return pdk.Deck(
        layers=layers,
        initial_view_state=view_state,
        map_style=pdk.map_styles.DARK,
        height=height,
        tooltip={
            "html": (
                "<b>{callsign}</b> &middot; {airline}<br/>{origin_country}<br/>"
                "Alt: {baro_altitude}m &middot; Spd: {velocity} m/s<br/>{code} {status}{name}"
            ),
            "style": {"backgroundColor": "#1a1a19", "color": "white"},
        },
    )

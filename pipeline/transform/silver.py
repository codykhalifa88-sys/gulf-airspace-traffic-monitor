"""Bronze -> silver cleaning. Pure functions (DataFrame in, DataFrame out,
no boto3/network) so they're directly unit-testable; run()/handler() at the
bottom do the S3 I/O around them -- same split as the ev-charging-gap-analysis
sibling, for the same reason (moto can't execute Lambda code without Docker,
so the orchestrator calls run() directly)."""
from __future__ import annotations

import io
import json
import logging
import zipfile
from datetime import date

import pandas as pd

from pipeline import s3_io
from pipeline.config import GDELT_MIN_QUAD_CLASS, GULF_BBOX
from pipeline.reference.airlines import get_airline
from pipeline.reference.airports import assign_nearest_region

logger = logging.getLogger(__name__)

_OPENSKY_COLUMNS = [
    "icao24",
    "callsign",
    "airline",
    "origin_country",
    "longitude",
    "latitude",
    "baro_altitude",
    "velocity",
    "true_track",
    "vertical_rate",
    "on_ground",
    "poll_timestamp",
    "nearest_region",
]


def clean_opensky_states(records: list[dict]) -> pd.DataFrame:
    """Kinesis-consumed OpenSky records (as written to bronze NDJSON) ->
    [icao24, callsign, airline, origin_country, longitude, latitude,
    baro_altitude, velocity, true_track, vertical_rate, on_ground,
    poll_timestamp, nearest_region]. Drops rows with null lat/lon --
    OpenSky commonly returns these for aircraft with a stale/lost position,
    a real condition, not hypothetical (confirmed in OpenSky's own field
    semantics, even though this session's captured fixture happened not to
    contain one). airline is resolved from the callsign's ICAO prefix (see
    pipeline/reference/airlines.py) -- "Unknown / private" for callsigns
    with no recognizable prefix, "Other" for a recognized-but-uncatalogued
    prefix, never silently dropped.
    """
    if not records:
        return pd.DataFrame(columns=_OPENSKY_COLUMNS)

    df = pd.DataFrame(records)
    df = df.dropna(subset=["longitude", "latitude"])
    if df.empty:
        return pd.DataFrame(columns=_OPENSKY_COLUMNS)
    df["nearest_region"] = df.apply(lambda r: assign_nearest_region(r["latitude"], r["longitude"]), axis=1)
    df["airline"] = df["callsign"].apply(get_airline)
    return df[_OPENSKY_COLUMNS].reset_index(drop=True)


# GDELT Event Database v2.0's export.CSV has NO header row -- these are the
# real, documented column names in their real, confirmed order (61 columns,
# verified against an actual downloaded export file during planning, not
# assumed from memory). We only need a subset; the rest are still named so
# `usecols` selection below is self-documenting.
_GDELT_COLUMNS = [
    "GLOBALEVENTID", "SQLDATE", "MonthYear", "Year", "FractionDate",
    "Actor1Code", "Actor1Name", "Actor1CountryCode", "Actor1KnownGroupCode", "Actor1EthnicCode",
    "Actor1Religion1Code", "Actor1Religion2Code", "Actor1Type1Code", "Actor1Type2Code", "Actor1Type3Code",
    "Actor2Code", "Actor2Name", "Actor2CountryCode", "Actor2KnownGroupCode", "Actor2EthnicCode",
    "Actor2Religion1Code", "Actor2Religion2Code", "Actor2Type1Code", "Actor2Type2Code", "Actor2Type3Code",
    "IsRootEvent", "EventCode", "EventBaseCode", "EventRootCode", "QuadClass",
    "GoldsteinScale", "NumMentions", "NumSources", "NumArticles", "AvgTone",
    "Actor1Geo_Type", "Actor1Geo_FullName", "Actor1Geo_CountryCode", "Actor1Geo_ADM1Code", "Actor1Geo_ADM2Code",
    "Actor1Geo_Lat", "Actor1Geo_Long", "Actor1Geo_FeatureID",
    "Actor2Geo_Type", "Actor2Geo_FullName", "Actor2Geo_CountryCode", "Actor2Geo_ADM1Code", "Actor2Geo_ADM2Code",
    "Actor2Geo_Lat", "Actor2Geo_Long", "Actor2Geo_FeatureID",
    "ActionGeo_Type", "ActionGeo_FullName", "ActionGeo_CountryCode", "ActionGeo_ADM1Code", "ActionGeo_ADM2Code",
    "ActionGeo_Lat", "ActionGeo_Long", "ActionGeo_FeatureID",
    "DATEADDED", "SOURCEURL",
]

_GDELT_SILVER_COLUMNS = [
    "global_event_id",
    "event_timestamp",
    "actor1_name",
    "actor2_name",
    "event_code",
    "quad_class",
    "goldstein_scale",
    "num_mentions",
    "num_sources",
    "num_articles",
    "action_geo_lat",
    "action_geo_long",
    "action_geo_country_code",
    "source_url",
    "nearest_region",
]


def clean_gdelt_events(raw_zip_bytes: bytes) -> pd.DataFrame:
    """Raw GDELT export.CSV.zip bytes (as downloaded to bronze) ->
    [global_event_id, event_timestamp, actor1_name, actor2_name, event_code,
    quad_class, goldstein_scale, num_mentions, num_sources, num_articles,
    action_geo_lat, action_geo_long, action_geo_country_code, source_url,
    nearest_region]. Filters to the Gulf bounding box (real, precise
    geo-filter) and QuadClass >= GDELT_MIN_QUAD_CLASS (3 = verbal conflict
    or worse -- the conflict-relevance filter). ActionGeo_CountryCode is
    FIPS 10-4, not ISO (confirmed against real data: Saudi Arabia is "SA",
    Iraq is "IZ" not ISO's "IQ") -- kept only as a display field, not used
    for filtering, since the bbox + lat/long filter is more precise and
    doesn't depend on getting every Gulf country's FIPS code exactly right.
    """
    with zipfile.ZipFile(io.BytesIO(raw_zip_bytes)) as z:
        name = z.namelist()[0]
        with z.open(name) as f:
            df = pd.read_csv(f, sep="\t", header=None, names=_GDELT_COLUMNS, dtype=str, low_memory=False)

    if df.empty:
        return pd.DataFrame(columns=_GDELT_SILVER_COLUMNS)

    df["ActionGeo_Lat"] = pd.to_numeric(df["ActionGeo_Lat"], errors="coerce")
    df["ActionGeo_Long"] = pd.to_numeric(df["ActionGeo_Long"], errors="coerce")
    df["QuadClass"] = pd.to_numeric(df["QuadClass"], errors="coerce")

    in_bbox = (
        df["ActionGeo_Lat"].between(GULF_BBOX["lamin"], GULF_BBOX["lamax"])
        & df["ActionGeo_Long"].between(GULF_BBOX["lomin"], GULF_BBOX["lomax"])
    )
    df = df[in_bbox & df["ActionGeo_Lat"].notna() & (df["QuadClass"] >= GDELT_MIN_QUAD_CLASS)]
    if df.empty:
        return pd.DataFrame(columns=_GDELT_SILVER_COLUMNS)

    df["nearest_region"] = df.apply(lambda r: assign_nearest_region(r["ActionGeo_Lat"], r["ActionGeo_Long"]), axis=1)
    df["event_timestamp"] = pd.to_datetime(df["DATEADDED"], format="%Y%m%d%H%M%S", errors="coerce").dt.strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    out = pd.DataFrame(
        {
            "global_event_id": df["GLOBALEVENTID"],
            "event_timestamp": df["event_timestamp"],
            "actor1_name": df["Actor1Name"],
            "actor2_name": df["Actor2Name"],
            "event_code": df["EventCode"],
            "quad_class": df["QuadClass"].astype(int),
            "goldstein_scale": pd.to_numeric(df["GoldsteinScale"], errors="coerce"),
            "num_mentions": pd.to_numeric(df["NumMentions"], errors="coerce"),
            "num_sources": pd.to_numeric(df["NumSources"], errors="coerce"),
            "num_articles": pd.to_numeric(df["NumArticles"], errors="coerce"),
            "action_geo_lat": df["ActionGeo_Lat"],
            "action_geo_long": df["ActionGeo_Long"],
            "action_geo_country_code": df["ActionGeo_CountryCode"],
            "source_url": df["SOURCEURL"],
            "nearest_region": df["nearest_region"],
        }
    )
    return out.reset_index(drop=True)


def run(bronze_keys: dict[str, str | None], snapshot_date: date | None = None) -> dict[str, str]:
    """bronze_keys: {"opensky_states": key_or_None, "gdelt": key_or_None}
    (as returned by the two ingest modules). Returns the silver S3 keys
    written -- a source with no new bronze data simply doesn't appear in
    the result, rather than writing an empty placeholder file.
    """
    snapshot = (snapshot_date or date.today()).isoformat()
    silver_keys: dict[str, str] = {}

    opensky_key = bronze_keys.get("opensky_states")
    if opensky_key:
        body = s3_io.read_bytes(opensky_key)
        records = [json.loads(line) for line in body.decode().splitlines() if line.strip()]
        states = clean_opensky_states(records)
        silver_keys["opensky_states"] = s3_io.write_parquet(
            states, f"silver/opensky_states/dt={snapshot}/opensky_states.parquet"
        )
        logger.info("Wrote %d cleaned state vectors", len(states))

    gdelt_key = bronze_keys.get("gdelt")
    if gdelt_key:
        raw_zip = s3_io.read_bytes(gdelt_key)
        events = clean_gdelt_events(raw_zip)
        silver_keys["gdelt_events"] = s3_io.write_parquet(events, f"silver/gdelt_events/dt={snapshot}/gdelt_events.parquet")
        logger.info("Wrote %d Gulf-region conflict events", len(events))

    return silver_keys


def handler(event, context) -> dict:
    return run(bronze_keys=event["bronze_keys"])

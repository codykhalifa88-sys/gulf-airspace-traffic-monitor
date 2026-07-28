# Architecture

```mermaid
flowchart TD
    subgraph Sources["Real data sources"]
        OpenSky["OpenSky Network\n/api/states/all (poll, live aircraft)"]
        GDELT["GDELT Event Database v2\nlastupdate.txt -> .export.CSV.zip"]
    end

    subgraph Ingest["Ingest (Lambda, moto-backed locally)"]
        I1["ingest.opensky_states\n(poll -> PutRecords)"]
        Kinesis["Kinesis: gulf-airspace-states\n(1 shard, genuinely exercised against moto)"]
        I2["ingest.kinesis_consumer\n(drain-once, checkpoint shards)"]
        I3["ingest.gdelt"]
    end

    subgraph S3["S3 data lake"]
        Bronze["bronze/\n(raw NDJSON / CSV.zip)"]
        Silver["silver/\n(cleaned, typed, Parquet)"]
        Gold["gold/\n(traffic-by-region + conflict events)"]
    end

    subgraph Transform["Transform (Lambda, moto-backed locally)"]
        T1["transform.silver"]
        T2["transform.gold\n(rolling baseline + anomaly detection)"]
    end

    subgraph Serving["Serving layer"]
        DDB1["DynamoDB: gulf_traffic_by_region\n(GSI1: status-ranked alerts)"]
        DDB2["DynamoDB: gulf_conflict_events\n(GSI1: region + time window)"]
        DDB3["DynamoDB: gulf_pipeline_manifest\n(ETags + per-shard Kinesis checkpoints)"]
    end

    Dash["Streamlit dashboard"]

    OpenSky --> I1 --> Kinesis --> I2 --> Bronze
    GDELT --> I3 --> Bronze
    Bronze --> T1 --> Silver
    Silver --> T2 --> Gold
    Gold --> DDB1
    Gold --> DDB2
    I2 -. "shard_checkpoints" .-> DDB3
    I3 -. "ETag check" .-> DDB3
    T2 -. "fetch_recent_history\n(reads its own prior output)" .-> DDB1
    DDB1 --> Dash
    DDB2 --> Dash
    OpenSky -. "direct poll every 15s\n(bypasses the backbone for live positions)" .-> Dash
```

## Two different jobs, not one pipeline forcing both

The **live map polls OpenSky directly from the Streamlit process** on every
autorefresh tick — showing current aircraft positions is already what
`/states/all` returns, so routing it through S3 → Kinesis → DynamoDB first
would only add latency for zero benefit. The **Kinesis → S3 → DynamoDB
backbone exists to build history**: traffic-volume-over-time, the rolling
anomaly baseline, and GDELT correlation — a genuinely different job. If the
direct poll fails or is rate-limited, the map falls back to the most recent
bronze S3 object with an honest "cached" freshness label.

## What's real vs. moto-backed vs. real-AWS-only

| Piece | Status |
|---|---|
| S3, DynamoDB, Lambda (create), IAM | Real service semantics via moto — genuinely tested (S3 put/get, DynamoDB queries/GSIs, `terraform apply` creating real resources) |
| **Kinesis** | Genuinely exercised against moto — real `PutRecords`/`GetRecords`/shard semantics, not a metadata stub. No `enable_x` gate needed, unlike the resources below |
| Lambda **execution** | Not exercised — moto can't run Lambda code without Docker. The orchestrator calls the same plain Python functions directly instead (thin-handler/pure-core split, see `pipeline/ingest/*.py`) |
| Step Functions, EventBridge Scheduler, Glue, Athena | Defined in Terraform (`infra/stepfunctions.tf`, `infra/eventbridge.tf`, `infra/glue_athena.tf`) as the real-AWS migration path — never applied against moto (gated by `enable_real_aws_orchestration` / `enable_glue_athena`, both default `false`) |
| Scheduling | `.github/workflows/scheduled_refresh.yml`'s cron (every 5 minutes) is the real, working stand-in — it actually fires and runs the real pipeline against live data |

## Why Kinesis, not just S3 directly

OpenSky is a **poll API, not a push/streaming one** — there's no webhook or
subscription. "Streaming" here is modeled honestly as
poll → durable stream → consumer, which is exactly the problem Kinesis
solves: it decouples the poller (which must run frequently and briefly) from
the consumer (which drains, checkpoints per shard via
`pipeline/manifest.py`'s `shard_checkpoints`, and writes one durable bronze
file per run), rather than writing directly to S3 and losing shard-level
replay semantics.

## Why pydeck, not Plotly, for the live map

`st.pydeck_chart`'s `IconLayer` supports per-point rotation (`get_angle`
driven by real `true_track`/heading) — the one feature that makes the map
read as ATC radar instead of a scatter plot. Plotly's `scattermapbox` needs a
Mapbox token for a real basemap; `scattergeo` has no street/terrain tiles at
all. pydeck gets a free, no-token dark basemap via CARTO
(`pdk.map_styles.DARK`) and is core Streamlit API, not an extra heavy
dependency.

## Why moto, not LocalStack

Same reasoning as the ev-charging-gap-analysis sibling: LocalStack's free
Community tier paywalls Step Functions/Glue/Athena/Redshift/EventBridge and
requires Docker regardless (unavailable in this project's dev environment).
moto is pure Python, needs no Docker, and genuinely supports everything this
pipeline exercises functionally — including Kinesis's real shard/record
semantics, which this project relies on more heavily than the sibling did.

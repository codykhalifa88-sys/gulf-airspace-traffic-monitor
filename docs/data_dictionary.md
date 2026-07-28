# Data dictionary

## S3 layout

```
bronze/opensky_states/dt=YYYY-MM-DD/HHMMSS_states_raw.ndjson
bronze/gdelt/dt=YYYY-MM-DD/export.CSV.zip
silver/opensky_states/dt=YYYY-MM-DD/opensky_states.parquet
silver/gdelt_events/dt=YYYY-MM-DD/gdelt_events.parquet
gold/traffic_by_region/dt=YYYY-MM-DD/traffic_by_region.parquet
gold/conflict_events/dt=YYYY-MM-DD/conflict_events.parquet
```
`bronze/*` has a 30-day S3 lifecycle expiration (real AWS only — moto's
`GetBucketLifecycleConfiguration` never satisfies the Terraform AWS
provider's post-apply waiter, so this resource is gated `real-AWS-only`, the
same gotcha the ev-charging-gap-analysis sibling found). `silver/`/`gold/`
are kept.

## OpenSky state vector schema (real, confirmed field order)

`/api/states/all` returns each aircraft as a 17-field array, not an object —
confirmed against a real captured response, not assumed from memory:

```
[icao24, callsign, origin_country, time_position, last_contact, longitude,
 latitude, baro_altitude, on_ground, velocity, true_track, vertical_rate,
 sensors, geo_altitude, squawk, spi, position_source]
```

`silver.clean_opensky_states` drops rows with null lat/lon (OpenSky commonly
returns these for aircraft with a stale/lost position — a real condition,
confirmed in OpenSky's own field semantics) and resolves `airline` from the
callsign's ICAO prefix.

## DynamoDB tables

### `gulf_traffic_by_region` (primary time-series table)

| Attribute | Type | Notes |
|---|---|---|
| `region_pk` | S (PK) | `REGION#<airport_code>` (or `REGION#OTHER` for overflight traffic beyond 150km of any tracked airport) |
| `bucket_sk` | S (SK) | `BUCKET#<iso8601>`, floored to 5-minute buckets |
| `aircraft_count` | N | distinct `icao24` seen in that region+bucket |
| `rolling_mean` / `rolling_std` | N | preceding-window baseline (see below), absent until `baseline_n >= 12` |
| `z_score` | N | `(aircraft_count - rolling_mean) / max(rolling_std, 1.0)` |
| `baseline_n` | N | how many preceding buckets the baseline is built from (capped at 288 = 24h) |
| `anomaly_status` | S | `insufficient_baseline` / `normal` / `warning` / `serious` / `critical` |
| `anomaly_direction` | S | `spike` / `drop`, **absent** for `normal`/`insufficient_baseline` |
| `status_gsi_pk` | S | `STATUS#<status>`, present **only** for `warning`-or-worse rows |

**GSI `gsi1_status_ranked`**: PK `status_gsi_pk`, SK `bucket_sk`. Supports
"every currently-flagged region right now" as one `Query` instead of a table
scan — this project's version of the ev-charging-gap-analysis sibling's
"most resume-relevant DynamoDB decision," applied to alerting instead of
ranking. `status_gsi_pk` is omitted entirely for `normal`/
`insufficient_baseline` rows, so DynamoDB naturally excludes them from the
ranked-alert query without a filter expression — the base table alone
already answers "region X's own time series" (`Query` by PK, no GSI needed
for that).

### `gulf_conflict_events`

| Attribute | Type | Notes |
|---|---|---|
| `event_pk` | S (PK) | `EVENT#<GLOBALEVENTID>` — GDELT's own natural key, so repeated pulls across overlapping time windows dedupe for free via idempotent upserts |
| `region_gsi_pk` | S | `REGION#<nearest_region>` |
| `event_timestamp` | S | ISO 8601, from GDELT's `DATEADDED` |
| `action_geo_lat` / `action_geo_long` | N | |
| `quad_class` | N | 1=verbal cooperation, 2=material cooperation, 3=verbal conflict, 4=material conflict. This project filters to `>= 3` |
| `goldstein_scale` | N | -10 (most conflictual) to +10 (most cooperative) |
| `num_mentions` / `num_sources` / `num_articles` | N | |
| `actor1_name` / `actor2_name` | S | |
| `source_url` | S | |

**GSI `gsi1_region_by_time`**: PK `region_gsi_pk`, SK `event_timestamp`.
Supports "conflict events near region X within the dashboard's visible time
window" as one `Query` — exactly what the anomaly-trend chart's GDELT
overlay needs.

### `gulf_pipeline_manifest` (idempotency + Kinesis checkpoint watermark)

| Attribute | Type | Notes |
|---|---|---|
| `source_name` | S (PK) | `opensky_kinesis` / `gdelt` |
| `source_etag_or_hash` | S | used by the GDELT ingest (its own export filename doubles as an etag) |
| `last_fetched_at` | S | ISO 8601 |
| `last_s3_key` | S | |
| `last_run_status` | S | |
| `shard_checkpoints` | **Map** | `{shard_id: sequence_number}` — a genuinely new pattern vs. the sibling project's flat-string rows, needed so `ingest.kinesis_consumer` resumes each shard from where it last left off (`TRIM_HORIZON` only on a shard's first-ever consume) rather than re-reading the whole stream or losing its place. See `pipeline/manifest.py:get_shard_checkpoints`/`update_shard_checkpoints`. |

## Rolling anomaly baseline — method and thresholds

Per region, a rolling mean/std over the **preceding window only**
(`shift(1)` before `.rolling(...)`, so the current bucket never leaks into
its own baseline) — window size is `max(12, min(len(history), 288))`
(1 hour minimum history considered, 24 hour ceiling), with a **std floor of
1.0** aircraft so a low-traffic airport (e.g. MCT, KWI) doesn't read
ordinary count-to-count noise as a huge z-score.

| `abs(z_score)` | `baseline_n` | `anomaly_status` |
|---|---|---|
| n/a | < 12 | `insufficient_baseline` |
| < 1.5 | ≥ 12 | `normal` |
| 1.5–2.5 | ≥ 12 | `warning` |
| 2.5–3.5 | ≥ 12 | `serious` |
| ≥ 3.5 | ≥ 12 | `critical` |

`anomaly_direction` is surfaced **separately** from `anomaly_status`: a
**spike** (`z_score > 0`) is often perfectly ordinary — e.g. real seasonal
Hajj/Umrah traffic into JED — while a **drop** (`z_score < 0`) is the
operationally meaningful "possible disruption" signal this project's GDELT
correlation actually cares about. Conflating the two would treat a
legitimate surge as equally suspicious as a genuine collapse.

**Critical correctness guard**: a traffic bucket row exists **only when a
poll actually happened** and produced data for that region — a plain
`groupby` over real input rows, never a resample/reindex that would backfill
a `0` for a bucket where a scheduled run was simply missed or ran late.
Conflating "no data collected" with "genuinely zero aircraft observed" would
silently manufacture fake traffic-collapse anomalies out of ordinary
scheduling lag.

**Known, honestly-documented limitation**: this is a recency-based rolling
baseline, not a seasonal/weekday-aware one, since the project starts with
zero real history. A real spike into JED during Hajj season would currently
still be flagged as a statistical anomaly (correctly labeled `spike`, not
`drop`) rather than recognized as an expected yearly pattern — a
weekday/seasonal-aware baseline is a natural future improvement once enough
real history has accumulated.

## GDELT: real gotchas confirmed during development

- **Bulk file, not the query API.** `lastupdate.txt` lists 3 product types
  per 15-minute update; only the `.export.CSV.zip` line is the event table
  (the other two are mentions and GKG files this project doesn't use). The
  separate DOC 2.0 *query* API is rate-limited (1 req/5s) — the bulk-file
  pattern has no such limit.
- **No header row.** The real, documented 61-column layout is hardcoded in
  `pipeline/transform/silver.py:_GDELT_COLUMNS`, verified against an actual
  downloaded export file, not assumed from memory.
- **`ActionGeo_CountryCode` is FIPS 10-4, not ISO 3166.** Confirmed against
  real data: Saudi Arabia is `SA` (matches ISO by coincidence), but Iraq is
  `IZ`, not ISO's `IQ`. Kept only as a display field, never used for
  filtering — the lat/long bounding-box filter is more precise and doesn't
  depend on getting every Middle East country's FIPS code exactly right.

## Restricted airspace zones and the cost-impact estimate

`pipeline/reference/restricted_airspace.py`'s `RESTRICTED_ZONES` (Iran,
Iraq, Yemen) are **deliberately simplified rectangular bounding boxes**, not
exact FIR/ICAO airspace boundaries — good enough to show "real countries
whose airspace is being avoided" and to flag aircraft flying near them,
always caveated as approximate wherever it's surfaced (never presented as
precise airspace boundaries). One consequence of the rectangular
approximation: Iran's box necessarily covers some open Gulf waters near its
real coastline, and Iraq's box covers part of Kuwait's real airspace/territory
— both accepted trade-offs of a bounding-box approximation, not bugs.

The cost-impact estimate (`estimate_detour_cost_usd`) applies real, cited
2026 industry-reporting figures — not invented numbers — to currently
-tracked flights on airlines named as most disrupted:

- Rerouting around Iranian/Iraqi airspace adds 300–800 nautical miles and
  45–120 minutes of block time on affected Europe–Asia routes (SimpleFlying
  / industry reporting, 2026)
- ~13,000 lbs additional fuel burn per extra flight hour for a widebody
  (777/A350-class) ≈ $5,000+ per sector in added fuel cost alone at recent
  jet-fuel pricing (SimpleFlying, "Fuel & Flight-Paths: The Hidden Cost of
  Avoiding Hostile Airspace," 2026)
- 2–3 hour detours can add $6,000+ per flight hour in total operating cost
  (The National / industry estimates, 2026)
- Cumulative industry-wide cost estimated to exceed $1 billion if the
  conflict extends (aerospaceglobalnews.com, 2026)
- Etihad cancelled 450+ flights and Air India halted transit-dependent
  long-haul routes in the same period (simpleflying.com, 2026)
- EASA guidance urges carriers to avoid Iranian and Iraqi airspace entirely,
  at all altitudes (aviationnews.eu, July 2026)

The dashboard's own estimate is explicitly labeled as **illustrative** — it
applies the real per-hour figures to currently-tracked flights on the
airlines named as most disrupted, using the midpoint of the cited 45–120
minute detour range; it is not a precise per-flight measurement, since this
project has no route/schedule data to confirm any single tracked flight is
actually detouring.

## Airline categorical color assignment

`pipeline/reference/airlines.py`'s `AIRLINE_CATEGORICAL_ORDER` is a fixed,
never-cycled 8-slot assignment (dataviz skill: "color follows the entity,
never its rank"). The live map is an **all-pairs context** (many aircraft
visible simultaneously), so it's capped to the first 3 slots (Emirates,
Etihad Airways, Qatar Airways — the Gulf carriers most frequently named in
real 2026 reporting as disrupted by Iran/Iraq airspace avoidance) plus
"Other" in neutral grey. The ranked-airlines bar chart is an
**adjacent-pairs-only** context and safely uses all 8 slots — each airline
always renders in the same color in both places, regardless of current rank
or active filters.

## Known limitation: history doesn't persist across scheduled CI runs

`scheduled_refresh.yml` runs the real pipeline against real live data on a
schedule, but each GitHub Actions run starts a **fresh, empty moto_server
and a fresh `terraform apply`** — there's no free persistent AWS account for
this project to write real DynamoDB tables that survive between CI runs.
This means the rolling anomaly baseline and traffic history you see
accumulate in a **long-lived local `moto_server` instance during
development** (e.g. this repo's own screenshots), not from the CI schedule
itself. In a real AWS deployment, DynamoDB is naturally persistent and this
limitation disappears entirely — the scheduled workflow here exists to prove
the pipeline continues to run correctly against live upstream data on a
cadence, not to build long-term history inside this project's free-tier
sandbox.

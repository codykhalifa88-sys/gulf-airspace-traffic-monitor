# PK region_pk / SK bucket_sk answers "region X's time series" directly
# (Query by PK, no GSI needed for that). GSI1 flips the key order for the
# genuinely different access pattern this project needs: "every currently
# -flagged region right now" as one Query instead of a table scan --
# status_gsi_pk is present ONLY when anomaly_status is warning-or-worse
# (same "omit the GSI attribute for non-qualifying rows" pattern proven in
# the ev-charging-gap-analysis sibling), so normal/insufficient-baseline
# rows simply don't show up in a ranked-alert query.
resource "aws_dynamodb_table" "traffic_by_region" {
  name         = "gulf_traffic_by_region"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "region_pk"
  range_key    = "bucket_sk"

  attribute {
    name = "region_pk"
    type = "S"
  }
  attribute {
    name = "bucket_sk"
    type = "S"
  }
  attribute {
    name = "status_gsi_pk"
    type = "S"
  }

  global_secondary_index {
    name            = "gsi1_status_ranked"
    hash_key        = "status_gsi_pk"
    range_key       = "bucket_sk"
    projection_type = "ALL"
  }
}

# event_pk is a natural key (GLOBALEVENTID) -- repeated GDELT pulls dedupe
# for free via idempotent upserts. GSI1 supports "conflict events near
# region X within the chart's visible time window" as one Query, which is
# exactly what the dashboard's GDELT overlay needs.
resource "aws_dynamodb_table" "conflict_events" {
  name         = "gulf_conflict_events"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "event_pk"

  attribute {
    name = "event_pk"
    type = "S"
  }
  attribute {
    name = "region_gsi_pk"
    type = "S"
  }
  attribute {
    name = "event_timestamp"
    type = "S"
  }

  global_secondary_index {
    name            = "gsi1_region_by_time"
    hash_key        = "region_gsi_pk"
    range_key       = "event_timestamp"
    projection_type = "ALL"
  }
}

# Same shape as the sibling project's manifest table, plus shard_checkpoints
# (a Map attribute) on the opensky_kinesis item -- a genuinely new pattern
# for tracking per-shard Kinesis consumer position (see pipeline/manifest.py).
resource "aws_dynamodb_table" "pipeline_manifest" {
  name         = "gulf_pipeline_manifest"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "source_name"

  attribute {
    name = "source_name"
    type = "S"
  }
}

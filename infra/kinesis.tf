# Genuinely exercised against moto (real PutRecords/GetRecords/shard
# semantics, not a metadata stub like Step Functions/Glue/Athena/EventBridge)
# -- no enable_x gate needed. This is the real streaming backbone: OpenSky
# itself is a poll API, not push, so "streaming" is modeled as
# poll -> durable stream -> consumer, which is exactly what Kinesis is for.
resource "aws_kinesis_stream" "opensky_states" {
  name             = var.kinesis_stream_name
  shard_count      = 1 # ~50-300 records/poll every 5 min is far under 1000 rec/s/shard
  retention_period = 24
}

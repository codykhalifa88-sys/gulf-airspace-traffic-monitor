output "bucket_name" {
  value = aws_s3_bucket.data_lake.bucket
}

output "kinesis_stream_name" {
  value = aws_kinesis_stream.opensky_states.name
}

output "dynamodb_traffic_table" {
  value = aws_dynamodb_table.traffic_by_region.name
}

output "dynamodb_conflict_events_table" {
  value = aws_dynamodb_table.conflict_events.name
}

output "dynamodb_manifest_table" {
  value = aws_dynamodb_table.pipeline_manifest.name
}

output "lambda_function_names" {
  value = [for fn in aws_lambda_function.pipeline : fn.function_name]
}

# One build artifact, 6 handler entrypoints, same rationale as the sibling
# project: the orchestrator calls the plain Python functions directly
# (moto can't execute Lambda code without Docker) -- these resources exist
# to prove the IaC/IAM-per-function modeling for the real-AWS migration path.
data "archive_file" "pipeline_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../pipeline"
  output_path = "${path.module}/build/pipeline.zip"
}

locals {
  lambda_functions = {
    ingest_opensky_states = {
      handler = "ingest.opensky_states.handler"
      role    = aws_iam_role.lambda_ingest.arn
    }
    ingest_kinesis_consumer = {
      handler = "ingest.kinesis_consumer.handler"
      role    = aws_iam_role.lambda_ingest.arn
    }
    ingest_gdelt = {
      handler = "ingest.gdelt.handler"
      role    = aws_iam_role.lambda_ingest.arn
    }
    transform_silver = {
      handler = "transform.silver.handler"
      role    = aws_iam_role.lambda_transform.arn
    }
    transform_gold = {
      handler = "transform.gold.handler"
      role    = aws_iam_role.lambda_transform.arn
    }
    load_serving = {
      handler = "serving.load_dynamodb.handler"
      role    = aws_iam_role.lambda_serving.arn
    }
  }
}

resource "aws_lambda_function" "pipeline" {
  for_each = local.lambda_functions

  function_name    = "gulf-${each.key}-${var.environment}"
  role             = each.value.role
  handler          = each.value.handler
  runtime          = "python3.12"
  timeout          = 60
  filename         = data.archive_file.pipeline_zip.output_path
  source_code_hash = data.archive_file.pipeline_zip.output_base64sha256

  environment {
    variables = {
      S3_BUCKET_NAME                 = aws_s3_bucket.data_lake.bucket
      KINESIS_STREAM_NAME            = aws_kinesis_stream.opensky_states.name
      DYNAMODB_TRAFFIC_TABLE         = aws_dynamodb_table.traffic_by_region.name
      DYNAMODB_CONFLICT_EVENTS_TABLE = aws_dynamodb_table.conflict_events.name
      DYNAMODB_MANIFEST_TABLE        = aws_dynamodb_table.pipeline_manifest.name
    }
  }
}

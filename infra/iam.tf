data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# --- ingest: writes bronze, puts/consumes Kinesis, tracks manifest ---
resource "aws_iam_role" "lambda_ingest" {
  name               = "gulf-lambda-ingest-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

data "aws_iam_policy_document" "lambda_ingest_policy" {
  statement {
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/bronze/*"]
  }
  statement {
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.pipeline_manifest.arn]
  }
  statement {
    actions   = ["kinesis:PutRecord", "kinesis:PutRecords", "kinesis:GetRecords", "kinesis:GetShardIterator", "kinesis:DescribeStream", "kinesis:ListShards"]
    resources = [aws_kinesis_stream.opensky_states.arn]
  }
  statement {
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "lambda_ingest" {
  name   = "gulf-lambda-ingest-policy"
  role   = aws_iam_role.lambda_ingest.id
  policy = data.aws_iam_policy_document.lambda_ingest_policy.json
}

# --- transform: reads bronze, writes silver+gold ---
resource "aws_iam_role" "lambda_transform" {
  name               = "gulf-lambda-transform-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

data "aws_iam_policy_document" "lambda_transform_policy" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/bronze/*"]
  }
  statement {
    actions = ["s3:PutObject"]
    resources = [
      "${aws_s3_bucket.data_lake.arn}/silver/*",
      "${aws_s3_bucket.data_lake.arn}/gold/*",
    ]
  }
  statement {
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "lambda_transform" {
  name   = "gulf-lambda-transform-policy"
  role   = aws_iam_role.lambda_transform.id
  policy = data.aws_iam_policy_document.lambda_transform_policy.json
}

# --- serving: reads gold, writes DynamoDB ---
resource "aws_iam_role" "lambda_serving" {
  name               = "gulf-lambda-serving-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

data "aws_iam_policy_document" "lambda_serving_policy" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/gold/*"]
  }
  statement {
    actions = ["dynamodb:PutItem", "dynamodb:BatchWriteItem", "dynamodb:UpdateItem"]
    resources = [
      aws_dynamodb_table.traffic_by_region.arn,
      aws_dynamodb_table.conflict_events.arn,
    ]
  }
  statement {
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "lambda_serving" {
  name   = "gulf-lambda-serving-policy"
  role   = aws_iam_role.lambda_serving.id
  policy = data.aws_iam_policy_document.lambda_serving_policy.json
}

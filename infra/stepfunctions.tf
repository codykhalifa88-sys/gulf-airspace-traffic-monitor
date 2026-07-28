# Real-AWS migration path only (see infra/eventbridge.tf for the rationale).
# Chains the 6 Lambdas: parallel ingest (OpenSky + GDELT) -> consume Kinesis
# -> silver -> gold -> serving. Never applied against moto.
resource "aws_iam_role" "step_functions_exec" {
  count = var.enable_real_aws_orchestration ? 1 : 0

  name = "gulf-stepfunctions-role-${var.environment}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "states.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "step_functions_invoke_lambda" {
  count = var.enable_real_aws_orchestration ? 1 : 0

  name = "gulf-stepfunctions-invoke-lambda"
  role = aws_iam_role.step_functions_exec[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = [for fn in aws_lambda_function.pipeline : fn.arn]
    }]
  })
}

resource "aws_sfn_state_machine" "pipeline" {
  count = var.enable_real_aws_orchestration ? 1 : 0

  name     = "gulf-airspace-traffic-monitor-${var.environment}"
  role_arn = aws_iam_role.step_functions_exec[0].arn

  definition = jsonencode({
    Comment = "Ingest (OpenSky+GDELT) -> consume Kinesis -> silver -> gold -> serving, real-AWS orchestration"
    StartAt = "IngestSources"
    States = {
      IngestSources = {
        Type = "Parallel"
        Branches = [
          { StartAt = "IngestOpenSky", States = { IngestOpenSky = { Type = "Task", Resource = aws_lambda_function.pipeline["ingest_opensky_states"].arn, End = true } } },
          { StartAt = "IngestGdelt", States = { IngestGdelt = { Type = "Task", Resource = aws_lambda_function.pipeline["ingest_gdelt"].arn, End = true } } },
        ]
        Next  = "ConsumeKinesis"
        Retry = [{ ErrorEquals = ["States.TaskFailed"], MaxAttempts = 2, IntervalSeconds = 15 }]
      }
      ConsumeKinesis = {
        Type     = "Task"
        Resource = aws_lambda_function.pipeline["ingest_kinesis_consumer"].arn
        Next     = "TransformSilver"
        Retry    = [{ ErrorEquals = ["States.TaskFailed"], MaxAttempts = 2, IntervalSeconds = 15 }]
      }
      TransformSilver = {
        Type     = "Task"
        Resource = aws_lambda_function.pipeline["transform_silver"].arn
        Next     = "TransformGold"
        Retry    = [{ ErrorEquals = ["States.TaskFailed"], MaxAttempts = 2, IntervalSeconds = 15 }]
      }
      TransformGold = {
        Type     = "Task"
        Resource = aws_lambda_function.pipeline["transform_gold"].arn
        Next     = "LoadServing"
        Retry    = [{ ErrorEquals = ["States.TaskFailed"], MaxAttempts = 2, IntervalSeconds = 15 }]
      }
      LoadServing = {
        Type     = "Task"
        Resource = aws_lambda_function.pipeline["load_serving"].arn
        End      = true
        Retry    = [{ ErrorEquals = ["States.TaskFailed"], MaxAttempts = 2, IntervalSeconds = 15 }]
      }
    }
  })
}

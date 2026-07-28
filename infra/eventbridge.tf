# Real-AWS migration path only. Gated behind enable_real_aws_orchestration
# (default false) -- moto's EventBridge support is metadata-stub only, so
# creating this against moto would produce a rule that silently never fires.
# Locally, .github/workflows/scheduled_refresh.yml's cron trigger (every 5
# minutes) is the real, working equivalent (see README "Key Design Decisions").
resource "aws_scheduler_schedule" "frequent_refresh" {
  count = var.enable_real_aws_orchestration ? 1 : 0

  name       = "gulf-frequent-refresh-${var.environment}"
  group_name = "default"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression = "rate(5 minutes)"

  target {
    arn      = aws_sfn_state_machine.pipeline[0].arn
    role_arn = aws_iam_role.scheduler_invoke_step_functions[0].arn
  }
}

resource "aws_iam_role" "scheduler_invoke_step_functions" {
  count = var.enable_real_aws_orchestration ? 1 : 0

  name = "gulf-scheduler-role-${var.environment}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "scheduler_invoke_step_functions" {
  count = var.enable_real_aws_orchestration ? 1 : 0

  name = "gulf-scheduler-invoke-policy"
  role = aws_iam_role.scheduler_invoke_step_functions[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "states:StartExecution"
      Resource = aws_sfn_state_machine.pipeline[0].arn
    }]
  })
}

variable "aws_region" {
  description = "AWS region (real or moto)"
  type        = string
  default     = "eu-central-1"
}

variable "environment" {
  description = "Environment name, used in resource naming"
  type        = string
  default     = "dev"
}

variable "moto_endpoint" {
  description = "moto_server endpoint URL for local dev. Set to \"\" to target real AWS."
  type        = string
  default     = ""
}

variable "kinesis_stream_name" {
  description = "Kinesis stream name for OpenSky state-vector ingestion"
  type        = string
  default     = "gulf-airspace-states-dev"
}

variable "enable_real_aws_orchestration" {
  description = <<-EOT
    Gates EventBridge Scheduler + Step Functions resources (infra/eventbridge.tf,
    infra/stepfunctions.tf). Kept false against moto -- moto's support for these
    services is metadata-stub only (a created state machine never actually
    executes), so applying them locally would create resources that silently do
    nothing rather than proving anything. This is the real-AWS migration path,
    only meant to be set true when applying against a real AWS account.
  EOT
  type    = bool
  default = false
}

variable "enable_glue_athena" {
  description = "Stretch goal, not required for the core pipeline. See infra/glue_athena.tf."
  type        = bool
  default     = false
}

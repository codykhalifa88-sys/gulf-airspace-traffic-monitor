terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

locals {
  using_moto = var.moto_endpoint != ""
}

# When using_moto, every endpoint below is overridden to moto_server.
# s3_use_path_style = true is required against moto/LocalStack -- without it,
# the AWS provider tries virtual-hosted-style bucket routing
# (bucket.s3.region.amazonaws.com) which doesn't resolve to localhost. This
# was a real "found it by actually running it" gotcha in the sibling project.
provider "aws" {
  region                      = var.aws_region
  access_key                  = local.using_moto ? "test" : null
  secret_key                  = local.using_moto ? "test" : null
  s3_use_path_style           = local.using_moto
  skip_credentials_validation = local.using_moto
  skip_metadata_api_check     = local.using_moto
  skip_requesting_account_id  = local.using_moto

  dynamic "endpoints" {
    for_each = local.using_moto ? [1] : []
    content {
      s3       = var.moto_endpoint
      dynamodb = var.moto_endpoint
      lambda   = var.moto_endpoint
      iam      = var.moto_endpoint
      sts      = var.moto_endpoint
      kinesis  = var.moto_endpoint
    }
  }
}

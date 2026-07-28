resource "aws_s3_bucket" "data_lake" {
  bucket = "gulf-airspace-traffic-monitor-${var.environment}"

  # true against moto so `terraform destroy` can tear down a bucket the
  # pipeline/tests have already written objects into; false for real AWS.
  force_destroy = local.using_moto
}

# Gated real-AWS only: moto's PutBucketLifecycleConfiguration accepts the
# request but its GetBucketLifecycleConfiguration response never satisfies
# the AWS provider's post-apply waiter (confirmed in the sibling project --
# terraform apply hangs ~3 minutes then fails on this resource specifically).
resource "aws_s3_bucket_lifecycle_configuration" "data_lake" {
  count  = local.using_moto ? 0 : 1
  bucket = aws_s3_bucket.data_lake.id

  rule {
    id     = "expire-bronze"
    status = "Enabled"

    filter {
      prefix = "bronze/"
    }

    expiration {
      days = 30
    }
  }
}

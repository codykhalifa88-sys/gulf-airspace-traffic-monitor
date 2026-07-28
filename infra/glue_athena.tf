# Stretch goal, gated off by default and not applied against moto (Glue/Athena
# support there isn't meaningfully exercised without real data volume) --
# kept here to prove the skill exists as a real-AWS migration option, same
# pattern as the ev-charging-gap-analysis sibling's unchecked stretch goals.
resource "aws_glue_catalog_database" "traffic_monitor" {
  count = var.enable_glue_athena ? 1 : 0
  name  = "gulf_airspace_traffic_monitor_${var.environment}"
}

resource "aws_glue_crawler" "gold_layer" {
  count         = var.enable_glue_athena ? 1 : 0
  name          = "gulf-gold-crawler-${var.environment}"
  role          = aws_iam_role.lambda_transform.arn
  database_name = aws_glue_catalog_database.traffic_monitor[0].name

  s3_target {
    path = "s3://${aws_s3_bucket.data_lake.bucket}/gold/"
  }
}

resource "aws_athena_workgroup" "traffic_monitor" {
  count = var.enable_glue_athena ? 1 : 0
  name  = "gulf-airspace-traffic-monitor-${var.environment}"
}

resource "aws_athena_named_query" "recent_critical_alerts" {
  count     = var.enable_glue_athena ? 1 : 0
  name      = "recent_critical_traffic_anomalies"
  workgroup = aws_athena_workgroup.traffic_monitor[0].name
  database  = aws_glue_catalog_database.traffic_monitor[0].name
  query     = <<-SQL
    SELECT region_pk, bucket_sk, aircraft_count, z_score, anomaly_direction
    FROM traffic_by_region
    WHERE anomaly_status = 'critical'
    ORDER BY bucket_sk DESC
    LIMIT 50;
  SQL
}

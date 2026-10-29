resource "aws_dynamodb_table" "runs" {
  name         = "bisectr-runs"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "run_id"

  attribute {
    name = "run_id"
    type = "S"
  }

  attribute {
    name = "kind"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "N"
  }

  global_secondary_index {
    name            = "kind-created_at-index"
    hash_key        = "kind"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}

resource "aws_dynamodb_table" "baselines" {
  name         = "bisectr-baselines"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "cache_key"

  attribute {
    name = "cache_key"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}

resource "aws_s3_bucket" "reports" {
  bucket = "bisectr-reports-${data.aws_caller_identity.me.account_id}-${var.region}"
}

resource "aws_s3_bucket_public_access_block" "reports" {
  bucket                  = aws_s3_bucket.reports.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "reports" {
  bucket = aws_s3_bucket.reports.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "reports" {
  bucket = aws_s3_bucket.reports.id

  rule {
    id     = "expire-reports"
    status = "Enabled"

    filter {
      prefix = "reports/"
    }

    expiration {
      days = 90
    }
  }
}

output "runs_table" {
  value = aws_dynamodb_table.runs.name
}

output "baseline_table" {
  value = aws_dynamodb_table.baselines.name
}

output "reports_bucket" {
  value = aws_s3_bucket.reports.bucket
}

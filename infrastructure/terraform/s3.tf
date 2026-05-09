# Bucket dla raw payloads (Strava streams JSON, Health Auto Export raw)
# i FAISS index (recipe search). Versioning + SSE + public block + 90d
# noncurrent expiration.
resource "aws_s3_bucket" "data" {
  bucket = local.data_bucket_name

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket = aws_s3_bucket.data.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Defense-in-depth: explicit deny dla request'ów po HTTP. AWS S3 redirects
# HTTP→HTTPS automatycznie, ale wstępny request po plain HTTP może wyciec
# metadata (bucket name w Host header, path). Compliance baseline (Security Hub).
resource "aws_s3_bucket_policy" "data_deny_non_tls" {
  bucket = aws_s3_bucket.data.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyNonTLS"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.data.arn,
          "${aws_s3_bucket.data.arn}/*",
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      },
    ]
  })

  depends_on = [aws_s3_bucket_public_access_block.data]
}

resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }

  # Sprint 3.5 — raw HAE payloads (post-mortem retention).
  # IA → Glacier → expiration: ~$0.004/GB-month w Glacier vs $0.023 w STANDARD,
  # przy <100MB/dzień to grosze. Po 365d expiration — debug horizon
  # wystarczy na N follow-up PR-ów na shape changes HAE iOS.
  rule {
    id     = "hae-raw-archive"
    status = "Enabled"

    filter {
      prefix = "raw/health-auto-export/"
    }

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = 90
      storage_class = "GLACIER"
    }

    expiration {
      days = 365
    }
  }
}

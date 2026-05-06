# Single-table DDB per CLAUDE.md (PK=USER#{id}, SK={TYPE}#{date}).
# GSI-1 to inverted index (SK as PK, PK as SK) dla query po typie.
# `ttl` attribute służy idempotency table EVENT#strava (auto-expire 7d).
resource "aws_dynamodb_table" "data" {
  name         = local.ddb_table_name
  billing_mode = "PAY_PER_REQUEST"

  # NOTE: AWS provider 6.43-6.44 emituje deprecation warning na hash_key/
  # range_key z sugestią `key_schema`, ale alternatywa NIE jest jeszcze
  # zaimplementowana w provider'ze (block ani argument odrzucone). To
  # pre-emptive deprecation — provider zapowiada przyszłą zmianę. Zostajemy
  # przy legacy syntax, warning ignorowany. Migracja gdy `key_schema`
  # pojawi się w provider'ze (śledź release notes).
  hash_key  = "PK"
  range_key = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  global_secondary_index {
    name            = "GSI-1"
    hash_key        = "SK"
    range_key       = "PK"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  lifecycle {
    prevent_destroy = true
  }
}

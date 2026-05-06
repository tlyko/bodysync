# Single-table DDB per CLAUDE.md (PK=USER#{id}, SK={TYPE}#{date}).
# GSI-1 to inverted index (SK as PK, PK as SK) dla query po typie.
# `ttl` attribute służy idempotency table EVENT#strava (auto-expire 7d).
resource "aws_dynamodb_table" "data" {
  name         = local.ddb_table_name
  billing_mode = "PAY_PER_REQUEST"

  # NOTE: `range_key` deprecated w AWS provider 6.x na rzecz `key_schema`,
  # ale `key_schema` jeszcze nie jest stabilne (różne syntaxes per minor
  # version, provider 6.43 nie akceptuje block ani list-of-object). Wracamy
  # do legacy hash_key/range_key — warning ignorowany. Migracja w osobnym
  # PR przy bumpie provider'a.
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

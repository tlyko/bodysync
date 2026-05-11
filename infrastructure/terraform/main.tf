data "aws_caller_identity" "current" {}

# Import istniejącego SSM param utworzonego ręcznie przez ownera 2026-05-07
# (przed renamem partner → weronika w handlerze). Bez tego TF próbowałby
# CreateParameter na existing → ParameterAlreadyExists. Po pierwszym apply
# można ten blok usunąć (idempotent — TF widzi że state już ma resource).
import {
  to = aws_ssm_parameter.securestring["/bodysync/health-auto-export/webhook_secret_weronika"]
  id = "/bodysync/health-auto-export/webhook_secret_weronika"
}

# Sprint 5 — owner stworzył /bodysync/google/service_account_json ręcznie
# pre-PR #112 (zostawione z eksperymentu lub ręczne setup'u). Pipeline #112
# apply padł z ParameterAlreadyExists. Po pierwszym apply z tym importem
# można blok usunąć (analogicznie do PR #66 dla openai/api_key).
import {
  to = aws_ssm_parameter.google_service_account_json
  id = "/bodysync/google/service_account_json"
}

# API Gateway HTTP — single shared API dla wszystkich endpointów bodysync.
module "api_gateway" {
  source  = "./modules/api-gateway"
  project = local.project
}

# Pierwsza Lambda: POST /api/auth/google.
module "google_auth" {
  source = "./modules/lambda"

  project       = local.project
  function_name = "google-auth"
  source_zip    = "${path.module}/../../apps/api/dist/google_auth.zip"
  handler       = "handlers.google_auth.handler.handler"
  memory_size   = 512
  timeout       = 10

  environment = {
    TABLE_NAME = aws_dynamodb_table.data.name
    ENV        = "prod"
  }

  extra_iam_statements = [
    {
      # Sec audit H5 — defense in depth dla CLAUDE.md "Reguła PK isolation".
      # Bez condition Lambda mogłaby pisać/czytać dowolny PK (EVENT#strava
      # idempotency, RECIPES, profiles innego usera) jeśli przyszły bug
      # w handlerze pozwoli na PK injection. LeadingKeys=USER#* zamyka to
      # na poziomie IAM — kod może mieć błąd, IAM odrzuci wywołanie.
      Sid      = "DDBWriteUserProfile"
      Effect   = "Allow"
      Action   = ["dynamodb:GetItem", "dynamodb:PutItem"]
      Resource = aws_dynamodb_table.data.arn
      Condition = {
        "ForAllValues:StringLike" = {
          "dynamodb:LeadingKeys" = ["USER#*"]
        }
      }
    },
    {
      Sid    = "ReadAuthSecrets"
      Effect = "Allow"
      Action = ["ssm:GetParameter"]
      Resource = [
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/jwt/signing_secret",
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/google/oauth_client_id",
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/auth/allowed_emails",
      ]
    },
  ]
}

resource "aws_apigatewayv2_integration" "google_auth" {
  api_id                 = module.api_gateway.api_id
  integration_type       = "AWS_PROXY"
  integration_uri        = module.google_auth.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "google_auth" {
  api_id    = module.api_gateway.api_id
  route_key = "POST /api/auth/google"
  target    = "integrations/${aws_apigatewayv2_integration.google_auth.id}"
}

resource "aws_lambda_permission" "google_auth_apigw" {
  statement_id  = "AllowAPIGWInvoke"
  action        = "lambda:InvokeFunction"
  function_name = module.google_auth.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${module.api_gateway.execution_arn}/*/*"
}

# Sprint 7 — POST /api/auth/logout. Czyści Set-Cookie sesji.
# Idempotent — nie wymaga JWT, nie czyta DDB/SSM. Najlżejszy handler:
# 256MB / 5s, brak `extra_iam_statements` (tylko basic CloudWatch logs
# z modułu Lambda).
module "auth_logout" {
  source = "./modules/lambda"

  project       = local.project
  function_name = "auth-logout"
  source_zip    = "${path.module}/../../apps/api/dist/auth_logout.zip"
  handler       = "handlers.auth_logout.handler.handler"
  memory_size   = 256
  timeout       = 5

  environment = {
    ENV = "prod"
  }
}

resource "aws_apigatewayv2_integration" "auth_logout" {
  api_id                 = module.api_gateway.api_id
  integration_type       = "AWS_PROXY"
  integration_uri        = module.auth_logout.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "auth_logout" {
  api_id    = module.api_gateway.api_id
  route_key = "POST /api/auth/logout"
  target    = "integrations/${aws_apigatewayv2_integration.auth_logout.id}"
}

resource "aws_lambda_permission" "auth_logout_apigw" {
  statement_id  = "AllowAPIGWInvokeAuthLogout"
  action        = "lambda:InvokeFunction"
  function_name = module.auth_logout.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${module.api_gateway.execution_arn}/*/*"
}

# Sprint 9 — GET + PUT /api/profile/targets. JWT auth, czyta + merguje
# kcal_target/protein_target_g/fat_target_g/carbs_target_g do PROFILE row.
# Pojedyncza Lambda handluje obie metody (dispatch po HTTP method).
module "profile_targets" {
  source = "./modules/lambda"

  project       = local.project
  function_name = "profile-targets"
  source_zip    = "${path.module}/../../apps/api/dist/profile_targets.zip"
  handler       = "handlers.profile_targets.handler.handler"
  memory_size   = 512
  timeout       = 5

  environment = {
    TABLE_NAME = aws_dynamodb_table.data.name
    ENV        = "prod"
  }

  extra_iam_statements = [
    {
      # Read + Write PROFILE row + Query BIOMETRY (calculate-tdee — `get_latest_weight_kg`).
      # LeadingKeys USER#* defense in depth (handler i tak zawsze operuje pod
      # {user_id z JWT}, ale gdyby kiedy się wjebała PK injection w kodzie,
      # IAM zatrzyma operację na non-USER prefix).
      Sid      = "DDBProfileRW"
      Effect   = "Allow"
      Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query"]
      Resource = aws_dynamodb_table.data.arn
      Condition = {
        "ForAllValues:StringLike" = {
          "dynamodb:LeadingKeys" = ["USER#*"]
        }
      }
    },
    {
      Sid    = "ReadJWTSecret"
      Effect = "Allow"
      Action = ["ssm:GetParameter"]
      Resource = [
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/jwt/signing_secret",
      ]
    },
  ]
}

resource "aws_apigatewayv2_integration" "profile_targets" {
  api_id                 = module.api_gateway.api_id
  integration_type       = "AWS_PROXY"
  integration_uri        = module.profile_targets.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "profile_targets_get" {
  api_id    = module.api_gateway.api_id
  route_key = "GET /api/profile/targets"
  target    = "integrations/${aws_apigatewayv2_integration.profile_targets.id}"
}

resource "aws_apigatewayv2_route" "profile_targets_put" {
  api_id    = module.api_gateway.api_id
  route_key = "PUT /api/profile/targets"
  target    = "integrations/${aws_apigatewayv2_integration.profile_targets.id}"
}

# Sprint 10 A0 — TDEE calculator. Reuse profile_targets Lambda (read PROFILE
# + read latest weight z BIOMETRY, no DDB write). Handler dispatchuje per
# rawPath substring "calculate-tdee".
resource "aws_apigatewayv2_route" "profile_calculate_tdee" {
  api_id    = module.api_gateway.api_id
  route_key = "POST /api/profile/calculate-tdee"
  target    = "integrations/${aws_apigatewayv2_integration.profile_targets.id}"
}

resource "aws_lambda_permission" "profile_targets_apigw" {
  statement_id  = "AllowAPIGWInvokeProfileTargets"
  action        = "lambda:InvokeFunction"
  function_name = module.profile_targets.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${module.api_gateway.execution_arn}/*/*"
}

# Sprint 11.5 (per ADR-009) — diet check / progress narrative. Read PROFILE
# + Query BIOMETRY 14d window → evaluate_diet_check → opcjonalnie LLM Haiku
# narrative (graceful degradation gdy SSM key missing / API down) → PutItem
# PROFILE z `diet_check_history` (cap 10 FIFO) + `diet_check_last`. Handler
# dispatchuje HTTP (POST /api/tdee/recalc — endpoint reuse z Sprint 11) i
# EventBridge cron `rate(14 days)` (log only per ADR-009 sec 6).
#
# Memory 1024MB (advisor_chat baseline dla anthropic SDK), timeout 30s
# (LLM call 2-4s + DDB ~100ms + cold start init).
module "tdee_recalc" {
  source = "./modules/lambda"

  project       = local.project
  function_name = "tdee-recalc"
  source_zip    = "${path.module}/../../apps/api/dist/tdee_recalc.zip"
  handler       = "handlers.tdee_recalc.handler.handler"
  memory_size   = 1024
  timeout       = 30

  environment = {
    TABLE_NAME = aws_dynamodb_table.data.name
    ENV        = "prod"
  }

  extra_iam_statements = [
    {
      Sid      = "DDBProfileDietCheck"
      Effect   = "Allow"
      Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query"]
      Resource = aws_dynamodb_table.data.arn
      Condition = {
        "ForAllValues:StringLike" = {
          "dynamodb:LeadingKeys" = ["USER#*"]
        }
      }
    },
    {
      Sid    = "ReadJWTAndAnthropicSecrets"
      Effect = "Allow"
      Action = ["ssm:GetParameter"]
      Resource = [
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/jwt/signing_secret",
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/anthropic/api_key",
      ]
    },
  ]
}

resource "aws_apigatewayv2_integration" "tdee_recalc" {
  api_id                 = module.api_gateway.api_id
  integration_type       = "AWS_PROXY"
  integration_uri        = module.tdee_recalc.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "tdee_recalc_post" {
  api_id    = module.api_gateway.api_id
  route_key = "POST /api/tdee/recalc"
  target    = "integrations/${aws_apigatewayv2_integration.tdee_recalc.id}"
}

resource "aws_lambda_permission" "tdee_recalc_apigw" {
  statement_id  = "AllowAPIGWInvokeTdeeRecalc"
  action        = "lambda:InvokeFunction"
  function_name = module.tdee_recalc.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${module.api_gateway.execution_arn}/*/*"
}

# Sprint 10 A0.5 — LLM-driven activity level suggestion dla TDEE wizard.
# Anthropic Haiku ocenia poziom aktywności na bazie ostatnich 7d Strava +
# biometry. Memory 1024MB / timeout 15s — Anthropic SDK cold start ~500ms +
# DDB query ~50ms + LLM call 2-4s + JSON parse. Cost: ~$0.001 per call
# (system prompt cached). Cost-guard alarm shared z advisor_chat (log shape
# `anthropic_call` matchuje cloudwatch.tf metric filter).
module "activity_suggestion" {
  source = "./modules/lambda"

  project       = local.project
  function_name = "activity-suggestion"
  source_zip    = "${path.module}/../../apps/api/dist/activity_suggestion.zip"
  handler       = "handlers.activity_suggestion.handler.handler"
  memory_size   = 1024
  timeout       = 15

  environment = {
    TABLE_NAME = aws_dynamodb_table.data.name
    ENV        = "prod"
  }

  extra_iam_statements = [
    {
      # Read ACTIVITY + BIOMETRY rows pod USER#{id} — gather_activity_context.
      # NO write. LeadingKeys USER#* defense in depth — handler i tak query
      # zawsze pod {user_id z JWT}, IAM zatrzymuje cross-PK leak przy bug'u.
      Sid      = "DDBReadActivityBiometry"
      Effect   = "Allow"
      Action   = ["dynamodb:Query"]
      Resource = aws_dynamodb_table.data.arn
      Condition = {
        "ForAllValues:StringLike" = {
          "dynamodb:LeadingKeys" = ["USER#*"]
        }
      }
    },
    {
      Sid    = "ReadJWTSecret"
      Effect = "Allow"
      Action = ["ssm:GetParameter"]
      Resource = [
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/jwt/signing_secret",
      ]
    },
    {
      Sid    = "ReadAnthropicKey"
      Effect = "Allow"
      Action = ["ssm:GetParameter"]
      Resource = [
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/anthropic/api_key",
      ]
    },
  ]
}

resource "aws_apigatewayv2_integration" "activity_suggestion" {
  api_id                 = module.api_gateway.api_id
  integration_type       = "AWS_PROXY"
  integration_uri        = module.activity_suggestion.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "activity_suggestion" {
  api_id    = module.api_gateway.api_id
  route_key = "POST /api/profile/suggest-activity-level"
  target    = "integrations/${aws_apigatewayv2_integration.activity_suggestion.id}"
}

resource "aws_lambda_permission" "activity_suggestion_apigw" {
  statement_id  = "AllowAPIGWInvokeActivitySuggestion"
  action        = "lambda:InvokeFunction"
  function_name = module.activity_suggestion.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${module.api_gateway.execution_arn}/*/*"
}

# Sprint 5 — Google Sheets training plan. GET /api/plan, JWT cookie auth,
# 15min DDB cache w PLAN#current, force-refresh przez ?refresh=1.
# google-api-python-client + google-auth — większy bundle (~10MB) ale w limicie
# Lambda zip (50MB compressed). Memory 512MB / timeout 15s (Sheets API call ~1s
# typowo + cold start credentials init).
module "plan" {
  source = "./modules/lambda"

  project       = local.project
  function_name = "plan"
  source_zip    = "${path.module}/../../apps/api/dist/plan.zip"
  handler       = "handlers.plan.handler.handler"
  memory_size   = 512
  timeout       = 15

  environment = {
    TABLE_NAME = aws_dynamodb_table.data.name
    ENV        = "prod"
  }

  extra_iam_statements = [
    {
      # Read + Write PLAN#current row. LeadingKeys USER#* defense in depth.
      Sid      = "DDBPlanRW"
      Effect   = "Allow"
      Action   = ["dynamodb:GetItem", "dynamodb:PutItem"]
      Resource = aws_dynamodb_table.data.arn
      Condition = {
        "ForAllValues:StringLike" = {
          "dynamodb:LeadingKeys" = ["USER#*"]
        }
      }
    },
    {
      Sid    = "ReadJWTSecret"
      Effect = "Allow"
      Action = ["ssm:GetParameter"]
      Resource = [
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/jwt/signing_secret",
      ]
    },
    {
      # Google Sheets credentials (SA JSON, SecureString) + per-user
      # sheet-id/sheet-tab. Wildcard na user portion — handler scope'uje
      # na user_id z JWT, IAM allowuje wszystkie userów (pozwala otworzyć
      # projekt dla nowych userów bez TF apply per user).
      Sid    = "ReadPlanConfig"
      Effect = "Allow"
      Action = ["ssm:GetParameter"]
      Resource = [
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/google/service_account_json",
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/*/training-sheet-id",
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/*/training-sheet-tab",
      ]
    },
  ]
}

resource "aws_apigatewayv2_integration" "plan" {
  api_id                 = module.api_gateway.api_id
  integration_type       = "AWS_PROXY"
  integration_uri        = module.plan.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "plan_get" {
  api_id    = module.api_gateway.api_id
  route_key = "GET /api/plan"
  target    = "integrations/${aws_apigatewayv2_integration.plan.id}"
}

resource "aws_lambda_permission" "plan_apigw" {
  statement_id  = "AllowAPIGWInvokePlan"
  action        = "lambda:InvokeFunction"
  function_name = module.plan.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${module.api_gateway.execution_arn}/*/*"
}

# SSM placeholders dla Google Sheets config — owner wpisuje wartości po
# pierwszym deployu (manualnie via aws ssm put-parameter, NIE w TF state).
# `ignore_changes = [value]` żeby owner update'y SSM nie były revertowane
# przez następne `terraform apply`.
resource "aws_ssm_parameter" "google_service_account_json" {
  name        = "/bodysync/google/service_account_json"
  description = "Google service account JSON dla Sheets API readonly. Owner: pobierz z GCP Console → IAM → SA → Keys → Add → JSON, wklej całą zawartość."
  type        = "SecureString"
  value       = "PLACEHOLDER"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "training_sheet_id_tomek" {
  name        = "/bodysync/tomek/training-sheet-id"
  description = "Spreadsheet ID z URL: docs.google.com/spreadsheets/d/<TEN>/edit. Owner wpisuje ręcznie."
  type        = "String"
  value       = "PLACEHOLDER"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "training_sheet_tab_tomek" {
  name        = "/bodysync/tomek/training-sheet-tab"
  description = "Nazwa zakładki z aktywnym tygodniem (np. Arkusz5). Owner update gdy trenerka zmieni layout."
  type        = "String"
  value       = "PLACEHOLDER"

  lifecycle {
    ignore_changes = [value]
  }
}

# Sprint 3 — Apple Health webhook. POST /api/health/webhook,
# Bearer auth (per-user secret w SSM, server resolves user_id po hmac match).
module "health_webhook" {
  source = "./modules/lambda"

  project       = local.project
  function_name = "health-webhook"
  source_zip    = "${path.module}/../../apps/api/dist/health_webhook.zip"
  handler       = "handlers.health_webhook.handler.handler"
  memory_size   = 512
  timeout       = 10

  environment = {
    TABLE_NAME      = aws_dynamodb_table.data.name
    ENV             = "prod"
    RAW_BUCKET_NAME = aws_s3_bucket.data.id
  }

  extra_iam_statements = [
    {
      # Per CLAUDE.md "Reguła PK isolation" + sec audit H5 — IAM jako druga
      # linia obrony przy PK injection. health_webhook pisze tylko BIOMETRY#*
      # pod USER#* PK, tak samo jak google_auth.
      Sid      = "DDBWriteBiometry"
      Effect   = "Allow"
      Action   = ["dynamodb:PutItem"]
      Resource = aws_dynamodb_table.data.arn
      Condition = {
        "ForAllValues:StringLike" = {
          "dynamodb:LeadingKeys" = ["USER#*"]
        }
      }
    },
    {
      Sid    = "ReadHaeWebhookSecrets"
      Effect = "Allow"
      Action = ["ssm:GetParameter"]
      Resource = [
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/health-auto-export/webhook_secret_tomek",
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/health-auto-export/webhook_secret_weronika",
      ]
    },
    {
      # Sprint 3.5 — raw HAE payloads archive dla post-mortem (debug HAE
      # shape changes, np. faktyczny field name w sleep_analysis).
      # Prefix-scoped: lambda nie pisze poza raw/health-auto-export/*.
      Sid      = "S3ArchiveRawHaePayloads"
      Effect   = "Allow"
      Action   = ["s3:PutObject"]
      Resource = "${aws_s3_bucket.data.arn}/raw/health-auto-export/*"
    },
  ]
}

resource "aws_apigatewayv2_integration" "health_webhook" {
  api_id                 = module.api_gateway.api_id
  integration_type       = "AWS_PROXY"
  integration_uri        = module.health_webhook.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "health_webhook" {
  api_id    = module.api_gateway.api_id
  route_key = "POST /api/health/webhook"
  target    = "integrations/${aws_apigatewayv2_integration.health_webhook.id}"
}

resource "aws_lambda_permission" "health_webhook_apigw" {
  statement_id  = "AllowAPIGWInvoke"
  action        = "lambda:InvokeFunction"
  function_name = module.health_webhook.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${module.api_gateway.execution_arn}/*/*"
}

# api_read — dispatcher dla GET endpointów frontu (/api/me, /api/biometry).
# JWT cookie verification (set przez google_auth), DDB query po USER#{id}.
module "api_read" {
  source = "./modules/lambda"

  project       = local.project
  function_name = "api-read"
  source_zip    = "${path.module}/../../apps/api/dist/api_read.zip"
  handler       = "handlers.api_read.handler.handler"
  memory_size   = 512
  timeout       = 10

  environment = {
    TABLE_NAME = aws_dynamodb_table.data.name
    ENV        = "prod"
  }

  extra_iam_statements = [
    {
      Sid      = "DDBReadUserData"
      Effect   = "Allow"
      Action   = ["dynamodb:GetItem", "dynamodb:Query"]
      Resource = aws_dynamodb_table.data.arn
      Condition = {
        "ForAllValues:StringLike" = {
          "dynamodb:LeadingKeys" = ["USER#*"]
        }
      }
    },
    {
      Sid      = "ReadJwtSecret"
      Effect   = "Allow"
      Action   = ["ssm:GetParameter"]
      Resource = "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/jwt/signing_secret"
    },
  ]
}

resource "aws_apigatewayv2_integration" "api_read" {
  api_id                 = module.api_gateway.api_id
  integration_type       = "AWS_PROXY"
  integration_uri        = module.api_read.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "api_me" {
  api_id    = module.api_gateway.api_id
  route_key = "GET /api/me"
  target    = "integrations/${aws_apigatewayv2_integration.api_read.id}"
}

resource "aws_apigatewayv2_route" "api_biometry" {
  api_id    = module.api_gateway.api_id
  route_key = "GET /api/biometry"
  target    = "integrations/${aws_apigatewayv2_integration.api_read.id}"
}

resource "aws_lambda_permission" "api_read_apigw" {
  statement_id  = "AllowAPIGWInvoke"
  action        = "lambda:InvokeFunction"
  function_name = module.api_read.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${module.api_gateway.execution_arn}/*/*"
}

# Sprint 6.1 — advisor_chat. POST /api/advisor/chat. JWT cookie auth,
# Anthropic Haiku 4.5 z prompt cache (ephemeral) + multi-turn DDB history.
# 1024MB / 30s — LLM call latency p95 ~3s + 2 retry budget. Per ADR-007
# (supersedes ADR-006 dinner advisor — chat refactor PR1, RAG dochodzi w PR2).
module "advisor_chat" {
  source = "./modules/lambda"

  project       = local.project
  function_name = "advisor-chat"
  source_zip    = "${path.module}/../../apps/api/dist/advisor_chat.zip"
  handler       = "handlers.advisor_chat.handler.handler"
  memory_size   = 1024
  timeout       = 30

  environment = {
    TABLE_NAME     = aws_dynamodb_table.data.name
    ENV            = "prod"
    RECIPES_BUCKET = aws_s3_bucket.data.id
  }

  extra_iam_statements = [
    {
      # Per CLAUDE.md "Reguła PK isolation" + sec audit H5 — IAM jako
      # druga linia obrony. advisor_chat czyta BIOMETRY (Query po
      # USER#{id} + sk_prefix) + PROFILE (GetItem) + chat history (Query
      # CHAT#{date}#*), pisze chat turns (PutItem CHAT#{date}#{idx}),
      # czyści chat history przy "Wyczyść rozmowę" (BatchWriteItem delete)
      # — wszystko pod USER#{id} PK.
      Sid    = "DDBReadBiometryWriteChat"
      Effect = "Allow"
      Action = [
        "dynamodb:GetItem",
        "dynamodb:Query",
        "dynamodb:PutItem",
        "dynamodb:DeleteItem",
        "dynamodb:BatchWriteItem",
      ]
      Resource = aws_dynamodb_table.data.arn
      Condition = {
        "ForAllValues:StringLike" = {
          "dynamodb:LeadingKeys" = ["USER#*"]
        }
      }
    },
    {
      Sid    = "ReadAdvisorSecrets"
      Effect = "Allow"
      Action = ["ssm:GetParameter"]
      Resource = [
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/anthropic/api_key",
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/jwt/signing_secret",
      ]
    },
    {
      # Sprint 6.2 RAG — recipes/{slug}/{embeddings.faiss,index.json,recipes.json}.
      # Prefix-scoped do `recipes/*` żeby Lambda nie czytała raw HAE payloads
      # (raw/health-auto-export/*) ani innych obszarów bucketa.
      Sid      = "S3ReadRecipesIndex"
      Effect   = "Allow"
      Action   = ["s3:GetObject"]
      Resource = "${aws_s3_bucket.data.arn}/recipes/*"
    },
    {
      Sid      = "ReadOpenAISecret"
      Effect   = "Allow"
      Action   = ["ssm:GetParameter"]
      Resource = "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/openai/api_key"
    },
    {
      # Sprint 6.2 RAG — pierwszy non-USER# pattern w bodysync (RECIPES PK).
      # IAM NIE może warunkować na non-LeadingKeys (Condition LeadingKeys=USER#*
      # zablokowałoby Query po PK=RECIPES). Defense-in-depth = handler kod
      # (rag.py retrieve()) explicit `KeyConditionExpression=PK = :pk` z
      # `:pk = "RECIPES"` literal — bez user-supplied PK input. Plus test
      # `test_retrieve_only_queries_recipes_pk` (Step 7) bronia regression.
      # Security note per ADR-007 negative consequences.
      Sid      = "DDBReadRecipes"
      Effect   = "Allow"
      Action   = ["dynamodb:GetItem", "dynamodb:Query"]
      Resource = aws_dynamodb_table.data.arn
    },
  ]
}

resource "aws_apigatewayv2_integration" "advisor_chat" {
  api_id                 = module.api_gateway.api_id
  integration_type       = "AWS_PROXY"
  integration_uri        = module.advisor_chat.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "advisor_chat" {
  api_id    = module.api_gateway.api_id
  route_key = "POST /api/advisor/chat"
  target    = "integrations/${aws_apigatewayv2_integration.advisor_chat.id}"
}

# Sprint 10 A1 — chat history GET dla frontend hydrate na mount.
# Reuse advisor_chat Lambda — same handler dispatchuje per HTTP method.
resource "aws_apigatewayv2_route" "advisor_chat_history" {
  api_id    = module.api_gateway.api_id
  route_key = "GET /api/advisor/chat/history"
  target    = "integrations/${aws_apigatewayv2_integration.advisor_chat.id}"
}

# Hard wipe dzisiejszej chat history — "Wyczyść rozmowę" przycisk w ChatScreen.
# Same Lambda dispatchuje per method (DELETE → _history_handler.handle_delete_history).
resource "aws_apigatewayv2_route" "advisor_chat_history_delete" {
  api_id    = module.api_gateway.api_id
  route_key = "DELETE /api/advisor/chat/history"
  target    = "integrations/${aws_apigatewayv2_integration.advisor_chat.id}"
}

resource "aws_lambda_permission" "advisor_chat_apigw" {
  statement_id  = "AllowAPIGWInvoke"
  action        = "lambda:InvokeFunction"
  function_name = module.advisor_chat.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${module.api_gateway.execution_arn}/*/*"
}

# ─── Sprint 4 — Strava integration (3 lambdas + 4 routes) ───────────────────

# OAuth start: GET /api/strava/oauth/start
# JWT auth → mint state row w DDB (PK=STRAVA_OAUTH_STATE#{state}) → 302 do
# strava.com/oauth/authorize. Lekki handler: 256 MB / 5 s, no SSM secrets.
module "strava_oauth_start" {
  source = "./modules/lambda"

  project       = local.project
  function_name = "strava-oauth-start"
  source_zip    = "${path.module}/../../apps/api/dist/strava_oauth_start.zip"
  handler       = "handlers.strava_oauth_start.handler.handler"
  memory_size   = 256
  timeout       = 5

  environment = {
    TABLE_NAME = aws_dynamodb_table.data.name
    ENV        = "prod"
  }

  extra_iam_statements = [
    {
      # Pisze tylko CSRF state row pod PK=STRAVA_OAUTH_STATE#*. NIE potrzebuje
      # USER#* ani EVENT#strava — dedykowany prefix.
      Sid      = "DDBWriteOAuthState"
      Effect   = "Allow"
      Action   = ["dynamodb:PutItem"]
      Resource = aws_dynamodb_table.data.arn
      Condition = {
        "ForAllValues:StringLike" = {
          "dynamodb:LeadingKeys" = ["STRAVA_OAUTH_STATE#*"]
        }
      }
    },
    {
      Sid    = "ReadJWTAndStravaPubKey"
      Effect = "Allow"
      Action = ["ssm:GetParameter"]
      Resource = [
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/jwt/signing_secret",
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/strava/client_id",
      ]
    },
  ]
}

resource "aws_apigatewayv2_integration" "strava_oauth_start" {
  api_id                 = module.api_gateway.api_id
  integration_type       = "AWS_PROXY"
  integration_uri        = module.strava_oauth_start.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "strava_oauth_start" {
  api_id    = module.api_gateway.api_id
  route_key = "GET /api/strava/oauth/start"
  target    = "integrations/${aws_apigatewayv2_integration.strava_oauth_start.id}"
}

resource "aws_lambda_permission" "strava_oauth_start_apigw" {
  statement_id  = "AllowAPIGWInvokeStravaOAuthStart"
  action        = "lambda:InvokeFunction"
  function_name = module.strava_oauth_start.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${module.api_gateway.execution_arn}/*/*"
}

# OAuth callback: GET /api/strava/oauth/callback
# Strava redirektuje user'a po authorize. Atomic state delete + token exchange
# z httpx + persist tokens do per-user SSM SecureString. 512 MB bo httpx +
# pydantic + boto3 vendored (~2.85 MB zip).
module "strava_oauth_callback" {
  source = "./modules/lambda"

  project       = local.project
  function_name = "strava-oauth-callback"
  source_zip    = "${path.module}/../../apps/api/dist/strava_oauth_callback.zip"
  handler       = "handlers.strava_oauth_callback.handler.handler"
  memory_size   = 512
  timeout       = 10

  environment = {
    TABLE_NAME = aws_dynamodb_table.data.name
    ENV        = "prod"
  }

  extra_iam_statements = [
    {
      # Atomic delete state nonce (single-use guard).
      Sid      = "DDBDeleteOAuthState"
      Effect   = "Allow"
      Action   = ["dynamodb:DeleteItem"]
      Resource = aws_dynamodb_table.data.arn
      Condition = {
        "ForAllValues:StringLike" = {
          "dynamodb:LeadingKeys" = ["STRAVA_OAUTH_STATE#*"]
        }
      }
    },
    {
      Sid    = "ReadStravaConfig"
      Effect = "Allow"
      Action = ["ssm:GetParameter"]
      Resource = [
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/strava/client_id",
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/strava/client_secret",
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/strava/athlete-to-user",
      ]
    },
    {
      # Per-user tokens write — wildcard `bodysync/strava/*/tokens` pozwala
      # na nowych userów bez Terraform changes. Athlete-to-user write też.
      Sid    = "WriteStravaTokensAndAthleteMap"
      Effect = "Allow"
      Action = ["ssm:PutParameter"]
      Resource = [
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/strava/*/tokens",
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/strava/athlete-to-user",
      ]
    },
  ]
}

resource "aws_apigatewayv2_integration" "strava_oauth_callback" {
  api_id                 = module.api_gateway.api_id
  integration_type       = "AWS_PROXY"
  integration_uri        = module.strava_oauth_callback.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "strava_oauth_callback" {
  api_id    = module.api_gateway.api_id
  route_key = "GET /api/strava/oauth/callback"
  target    = "integrations/${aws_apigatewayv2_integration.strava_oauth_callback.id}"
}

resource "aws_lambda_permission" "strava_oauth_callback_apigw" {
  statement_id  = "AllowAPIGWInvokeStravaOAuthCallback"
  action        = "lambda:InvokeFunction"
  function_name = module.strava_oauth_callback.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${module.api_gateway.execution_arn}/*/*"
}

# Webhook: GET (handshake) + POST (event). 5 s timeout — Strava budget < 2 s
# więc 5 s to spory headroom. 512 MB bo pydantic vendored.
module "strava_webhook" {
  source = "./modules/lambda"

  project       = local.project
  function_name = "strava-webhook"
  source_zip    = "${path.module}/../../apps/api/dist/strava_webhook.zip"
  handler       = "handlers.strava_webhook.handler.handler"
  memory_size   = 512
  timeout       = 5

  environment = {
    TABLE_NAME = aws_dynamodb_table.data.name
    ENV        = "prod"
  }

  extra_iam_statements = [
    {
      # Idempotent write event row (PK=EVENT#strava).
      Sid      = "DDBWriteStravaEvent"
      Effect   = "Allow"
      Action   = ["dynamodb:PutItem"]
      Resource = aws_dynamodb_table.data.arn
      Condition = {
        "ForAllValues:StringLike" = {
          "dynamodb:LeadingKeys" = ["EVENT#strava"]
        }
      }
    },
    {
      Sid    = "ReadStravaWebhookConfig"
      Effect = "Allow"
      Action = ["ssm:GetParameter"]
      Resource = [
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/strava/verify_token",
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/strava/subscription_id",
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/strava/athlete-to-user",
      ]
    },
  ]
}

resource "aws_apigatewayv2_integration" "strava_webhook" {
  api_id                 = module.api_gateway.api_id
  integration_type       = "AWS_PROXY"
  integration_uri        = module.strava_webhook.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "strava_webhook_get" {
  api_id    = module.api_gateway.api_id
  route_key = "GET /api/strava/webhook"
  target    = "integrations/${aws_apigatewayv2_integration.strava_webhook.id}"
}

resource "aws_apigatewayv2_route" "strava_webhook_post" {
  api_id    = module.api_gateway.api_id
  route_key = "POST /api/strava/webhook"
  target    = "integrations/${aws_apigatewayv2_integration.strava_webhook.id}"
}

resource "aws_lambda_permission" "strava_webhook_apigw" {
  statement_id  = "AllowAPIGWInvokeStravaWebhook"
  action        = "lambda:InvokeFunction"
  function_name = module.strava_webhook.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${module.api_gateway.execution_arn}/*/*"
}

# ─── Sprint 4 — Strava fetcher (DDB Streams trigger) + activities API ─────

# Fetcher Lambda — triggered z DDB Streams INSERT events na EVENT#strava
# partition. 1024 MB / 60 s — Strava API call (~500 ms) + S3 PutObject + DDB
# write. 60 s timeout daje headroom dla token refresh + activity + streams +
# persist (typowo ~3 s, headroom dla cold start).
module "strava_fetcher" {
  source = "./modules/lambda"

  project       = local.project
  function_name = "strava-fetcher"
  source_zip    = "${path.module}/../../apps/api/dist/strava_fetcher.zip"
  handler       = "handlers.strava_fetcher.handler.handler"
  memory_size   = 1024
  timeout       = 60

  environment = {
    TABLE_NAME      = aws_dynamodb_table.data.name
    RAW_BUCKET_NAME = aws_s3_bucket.data.id
    ENV             = "prod"
  }

  extra_iam_statements = [
    {
      Sid    = "DDBStreamRead"
      Effect = "Allow"
      Action = [
        "dynamodb:DescribeStream",
        "dynamodb:GetRecords",
        "dynamodb:GetShardIterator",
        "dynamodb:ListStreams",
      ]
      Resource = "${aws_dynamodb_table.data.arn}/stream/*"
    },
    {
      # Pisze ACTIVITY rows pod USER#* — defense in depth (kod używa
      # user_id z webhook event row, ale IAM zatrzyma jeśli kiedy bug
      # spróbuje pisać pod nie-USER prefix).
      Sid      = "DDBWriteActivity"
      Effect   = "Allow"
      Action   = ["dynamodb:PutItem"]
      Resource = aws_dynamodb_table.data.arn
      Condition = {
        "ForAllValues:StringLike" = {
          "dynamodb:LeadingKeys" = ["USER#*"]
        }
      }
    },
    {
      Sid    = "ReadStravaTokensAndConfig"
      Effect = "Allow"
      Action = ["ssm:GetParameter"]
      Resource = [
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/strava/client_id",
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/strava/client_secret",
        # Per-user tokens — wildcard.
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/strava/*/tokens",
      ]
    },
    {
      # Token refresh rotuje refresh_token — fetcher nadpisuje SSM po
      # successful refresh. Wildcard `*/tokens` pozwala na nowych userów
      # bez Terraform changes.
      Sid    = "WriteRotatedStravaTokens"
      Effect = "Allow"
      Action = ["ssm:PutParameter"]
      Resource = [
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/strava/*/tokens",
      ]
    },
    {
      # Streams JSON do S3 raw bucket, prefix `strava/streams/{user_id}/`.
      Sid      = "S3WriteStravaStreams"
      Effect   = "Allow"
      Action   = ["s3:PutObject"]
      Resource = "${aws_s3_bucket.data.arn}/strava/streams/*"
    },
  ]
}

# Event source mapping z filter_criteria — fetcher invoked TYLKO dla INSERT
# eventów na PK=EVENT#strava (cost + correctness disaster bez tego —
# wszystkie biometry/activity writes invokowałyby fetcher).
resource "aws_lambda_event_source_mapping" "strava_fetcher_stream" {
  event_source_arn  = aws_dynamodb_table.data.stream_arn
  function_name     = module.strava_fetcher.function_name
  starting_position = "LATEST"
  batch_size        = 10
  # Maximum 5 minut żeby fetcher nie wisiał na slow batch (Strava API rare
  # 5xx/timeout) — zwykle batch <1s.
  maximum_batching_window_in_seconds = 5

  filter_criteria {
    filter {
      pattern = jsonencode({
        eventName = ["INSERT"]
        dynamodb = {
          NewImage = {
            PK = {
              S = ["EVENT#strava"]
            }
          }
        }
      })
    }
  }
}

# Activities list — GET /api/activities. JWT auth, query po PK=USER#{user_id}
# z SK begins_with ACTIVITY#. Lekki: 256 MB / 5 s, brak external deps poza
# pyjwt + boto3 (vendored).
module "activities_list" {
  source = "./modules/lambda"

  project       = local.project
  function_name = "activities-list"
  source_zip    = "${path.module}/../../apps/api/dist/activities_list.zip"
  handler       = "handlers.activities_list.handler.handler"
  memory_size   = 256
  timeout       = 5

  environment = {
    TABLE_NAME = aws_dynamodb_table.data.name
    ENV        = "prod"
  }

  extra_iam_statements = [
    {
      Sid      = "DDBReadActivities"
      Effect   = "Allow"
      Action   = ["dynamodb:Query"]
      Resource = aws_dynamodb_table.data.arn
      Condition = {
        "ForAllValues:StringLike" = {
          "dynamodb:LeadingKeys" = ["USER#*"]
        }
      }
    },
    {
      Sid    = "ReadJWTSecret"
      Effect = "Allow"
      Action = ["ssm:GetParameter"]
      Resource = [
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/jwt/signing_secret",
      ]
    },
  ]
}

resource "aws_apigatewayv2_integration" "activities_list" {
  api_id                 = module.api_gateway.api_id
  integration_type       = "AWS_PROXY"
  integration_uri        = module.activities_list.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "activities_list" {
  api_id    = module.api_gateway.api_id
  route_key = "GET /api/activities"
  target    = "integrations/${aws_apigatewayv2_integration.activities_list.id}"
}

resource "aws_lambda_permission" "activities_list_apigw" {
  statement_id  = "AllowAPIGWInvokeActivitiesList"
  action        = "lambda:InvokeFunction"
  function_name = module.activities_list.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${module.api_gateway.execution_arn}/*/*"
}

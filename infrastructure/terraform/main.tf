data "aws_caller_identity" "current" {}

# Import istniejącego SSM param utworzonego ręcznie przez ownera 2026-05-07
# (przed renamem partner → weronika w handlerze). Bez tego TF próbowałby
# CreateParameter na existing → ParameterAlreadyExists. Po pierwszym apply
# można ten blok usunąć (idempotent — TF widzi że state już ma resource).
import {
  to = aws_ssm_parameter.securestring["/bodysync/health-auto-export/webhook_secret_weronika"]
  id = "/bodysync/health-auto-export/webhook_secret_weronika"
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
      # Read + Write PROFILE row — LeadingKeys USER#* defense in depth (handler
      # i tak zawsze pisze pod {user_id z JWT}, ale gdyby kiedy się wjebała
      # PK injection w kodzie, IAM zatrzyma write na non-USER prefix).
      Sid      = "DDBProfileRW"
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

resource "aws_lambda_permission" "profile_targets_apigw" {
  statement_id  = "AllowAPIGWInvokeProfileTargets"
  action        = "lambda:InvokeFunction"
  function_name = module.profile_targets.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${module.api_gateway.execution_arn}/*/*"
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
      # CHAT#{date}#*), pisze chat turns (PutItem CHAT#{date}#{idx})
      # — wszystko pod USER#{id} PK.
      Sid      = "DDBReadBiometryWriteChat"
      Effect   = "Allow"
      Action   = ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem"]
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

resource "aws_lambda_permission" "advisor_chat_apigw" {
  statement_id  = "AllowAPIGWInvoke"
  action        = "lambda:InvokeFunction"
  function_name = module.advisor_chat.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${module.api_gateway.execution_arn}/*/*"
}

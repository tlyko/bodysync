data "aws_caller_identity" "current" {}

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

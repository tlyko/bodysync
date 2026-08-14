# Serwer MCP — endpoint danych zdrowotnych dla custom connectora Claude
# plus własny serwer autoryzacji OAuth 2.0. Patrz ADR-010.
#
# Jedna Lambda obsługuje wszystkie siedem tras: `POST /mcp` (JSON-RPC) oraz
# sześć endpointów OAuth. Rozdzielanie ich na osobne funkcje dałoby siedem
# osobnych cold startów zamiast jednego współdzielonego kontenera.

# 1024 MB, nie 512 — CPU w Lambdzie jest proporcjonalne do pamięci, więc
# ~2x vCPU skraca init (ta sama sztuczka co PR #170 dla HAE webhooka).
# Przy kilku wywołaniach dziennie różnica w koszcie jest nieodczuwalna
# w free tier, a cold start dotyka pierwszego requestu każdej rozmowy.
module "mcp" {
  source = "./modules/lambda"

  project       = local.project
  function_name = "mcp"
  source_zip    = "${path.module}/../../apps/api/dist/mcp.zip"
  handler       = "handlers.mcp.handler.handler"
  memory_size   = 1024
  timeout       = 10

  environment = {
    TABLE_NAME = aws_dynamodb_table.data.name
    ENV        = "prod"
  }

  extra_iam_statements = [
    # Odczyt danych zdrowotnych. `LeadingKeys` wymusza PK isolation na poziomie
    # IAM — nawet błąd w kodzie nie sięgnie poza `USER#*`.
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
    # Stan OAuth: rejestracje klientów (DCR), kody autoryzacyjne, refresh
    # tokeny. Osobne prefiksy PK, więc uprawnienie zapisu nie dotyka danych
    # użytkownika — Lambda MCP nie ma `PutItem` na `USER#*`.
    {
      Sid      = "DDBOAuthState"
      Effect   = "Allow"
      Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"]
      Resource = aws_dynamodb_table.data.arn
      Condition = {
        "ForAllValues:StringLike" = {
          "dynamodb:LeadingKeys" = ["MCP_CLIENT#*", "MCP_CODE#*", "MCP_REFRESH#*"]
        }
      }
    },
    # Dwa sekrety, dwie role: `mcp/token_signing_secret` podpisuje tokeny MCP,
    # `jwt/signing_secret` służy WYŁĄCZNIE do weryfikacji cookie sesyjnego na
    # ekranie zgody. Rozdzielenie kluczy opisane w handlers/mcp/oauth.py.
    {
      Sid    = "ReadSigningSecrets"
      Effect = "Allow"
      Action = ["ssm:GetParameter"]
      Resource = [
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/mcp/token_signing_secret",
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/jwt/signing_secret",
      ]
    },
  ]
}

resource "aws_apigatewayv2_integration" "mcp" {
  api_id                 = module.api_gateway.api_id
  integration_type       = "AWS_PROXY"
  integration_uri        = module.mcp.invoke_arn
  payload_format_version = "2.0"
}

# Trasy. Klucze muszą się zgadzać co do znaku z `routeKey` w handlerze —
# nieznana trasa kończy się tam świadomym 404.
#
# `.well-known/*` siedzi w korzeniu api.bodysync.pl, bo RFC 8414 i 9728
# wymagają tych ścieżek na poziomie issuera, nie pod prefiksem /mcp.
locals {
  mcp_routes = {
    rpc                = "POST /mcp"
    protected_resource = "GET /.well-known/oauth-protected-resource"
    auth_server        = "GET /.well-known/oauth-authorization-server"
    register           = "POST /mcp/register"
    authorize_get      = "GET /mcp/authorize"
    authorize_post     = "POST /mcp/authorize"
    token              = "POST /mcp/token"
  }
}

resource "aws_apigatewayv2_route" "mcp" {
  for_each = local.mcp_routes

  api_id    = module.api_gateway.api_id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.mcp.id}"
}

resource "aws_lambda_permission" "mcp_apigw" {
  statement_id  = "AllowAPIGWInvoke"
  action        = "lambda:InvokeFunction"
  function_name = module.mcp.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${module.api_gateway.execution_arn}/*/*"
}

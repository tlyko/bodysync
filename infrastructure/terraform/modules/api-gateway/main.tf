resource "aws_apigatewayv2_api" "this" {
  name          = "${var.project}-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins     = var.cors_allow_origins
    allow_methods     = var.cors_allow_methods
    allow_headers     = var.cors_allow_headers
    allow_credentials = true
    max_age           = 300
  }
}

resource "aws_cloudwatch_log_group" "access" {
  name              = "/aws/apigatewayv2/${var.project}-api"
  retention_in_days = var.log_retention_days
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.access.arn
    format = jsonencode({
      requestId          = "$context.requestId"
      ip                 = "$context.identity.sourceIp"
      requestTime        = "$context.requestTime"
      httpMethod         = "$context.httpMethod"
      routeKey           = "$context.routeKey"
      status             = "$context.status"
      protocol           = "$context.protocol"
      responseLength     = "$context.responseLength"
      integrationLatency = "$context.integrationLatency"
    })
  }

  # Defense-in-depth throttling (security audit 2026-05-09 W3). 2-user prod
  # — 50 req/s sustained / 100 burst jest hojnie, ale blokuje DDoS i auth
  # spam (każdy /api/auth/google = JWKS fetch + crypto verify, $).
  default_route_settings {
    throttling_rate_limit  = var.default_throttle_rate
    throttling_burst_limit = var.default_throttle_burst
  }

  # Per-route override dla advisor chat — chroni Anthropic API key cost.
  # Burst 10 / sustained 5 req/s wystarcza na realne usage (DAILY_USER_TURN_LIMIT
  # = 30/dzień DDB-side i tak gateway'uje), ale blokuje burst attack z
  # valid JWT (np. po XSS via 'unsafe-inline' style-src — backlog W4).
  # Nie używamy `for_each` bo aktualnie tylko advisor ma override; gdy
  # dojdzie więcej routes przemyśleć map var.
  route_settings {
    route_key              = "POST /api/advisor/chat"
    throttling_rate_limit  = var.advisor_chat_throttle_rate
    throttling_burst_limit = var.advisor_chat_throttle_burst
  }
}

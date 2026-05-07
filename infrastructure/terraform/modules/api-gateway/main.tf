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
}

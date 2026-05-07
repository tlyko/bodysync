output "api_id" {
  value = aws_apigatewayv2_api.this.id
}

output "api_endpoint" {
  value       = aws_apigatewayv2_api.this.api_endpoint
  description = "Default execute-api URL (used until custom domain api.bodysync.pl is wired)."
}

output "execution_arn" {
  value       = aws_apigatewayv2_api.this.execution_arn
  description = "ARN źródłowy dla aws_lambda_permission source_arn (allow API GW invoke)."
}

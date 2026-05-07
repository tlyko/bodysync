output "function_name" {
  value = aws_lambda_function.this.function_name
}

output "function_arn" {
  value = aws_lambda_function.this.arn
}

output "invoke_arn" {
  value       = aws_lambda_function.this.invoke_arn
  description = "ARN do podpięcia jako API GW integration (aws_apigatewayv2_integration.integration_uri)."
}

output "role_name" {
  value = aws_iam_role.this.name
}

locals {
  qualified_name = "${var.project}-${var.function_name}"
}

resource "aws_iam_role" "this" {
  name = "${local.qualified_name}-exec"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "basic_exec" {
  role       = aws_iam_role.this.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "extra" {
  count = length(var.extra_iam_statements) > 0 ? 1 : 0

  name = "${local.qualified_name}-extra"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = var.extra_iam_statements
  })
}

resource "aws_cloudwatch_log_group" "this" {
  name              = "/aws/lambda/${local.qualified_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "this" {
  function_name = local.qualified_name
  role          = aws_iam_role.this.arn
  handler       = var.handler
  runtime       = "python3.12"
  architectures = ["arm64"]
  memory_size   = var.memory_size
  timeout       = var.timeout

  filename         = var.source_zip
  source_code_hash = filebase64sha256(var.source_zip)

  environment {
    variables = var.environment
  }

  depends_on = [
    aws_cloudwatch_log_group.this,
    aws_iam_role_policy_attachment.basic_exec,
  ]
}

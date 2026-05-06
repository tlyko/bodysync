output "state_bucket" {
  description = "S3 bucket holding Terraform remote state."
  value       = aws_s3_bucket.tf_state.id
}

output "lock_table" {
  description = "DynamoDB table used for Terraform state locking."
  value       = aws_dynamodb_table.tf_lock.name
}

output "aws_region" {
  description = "Region where state backend lives."
  value       = var.aws_region
}

output "aws_account_id" {
  description = "AWS account ID (handy for downstream config)."
  value       = data.aws_caller_identity.current.account_id
}

output "github_actions_role_arn" {
  description = "IAM role ARN that GitHub Actions assumes via OIDC. Set this as the `AWS_ROLE_ARN` repository variable."
  value       = aws_iam_role.github_actions.arn
}

output "oidc_provider_arn" {
  description = "GitHub Actions OIDC provider ARN (shared across projects, managed by tlyko/sprawdzamszlak)."
  value       = data.aws_iam_openid_connect_provider.github_actions.arn
}

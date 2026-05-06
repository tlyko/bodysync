locals {
  # NOTE: `syncbody` is a legacy literówka — current state has Project=syncbody
  # tag and `syncbody-github-actions` IAM role. Renaming to "bodysync" is
  # destructive (IAM role DELETE+CREATE + GitHub variable AWS_ROLE_ARN reset)
  # and tracked as a follow-up in PROJECT-STATUS.md backlog.
  project      = "syncbody"
  aws_region   = "eu-west-1"
  github_owner = "tlyko"
  github_repo  = "bodysync"

  tags = {
    Project     = local.project
    Environment = "shared"
    ManagedBy   = "terraform"
    Component   = "bootstrap"
  }

  state_bucket_name = "${local.project}-tfstate-${data.aws_caller_identity.current.account_id}"
  lock_table_name   = "${local.project}-tflock"
}

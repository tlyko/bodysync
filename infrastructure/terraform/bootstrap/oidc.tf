# OIDC provider for token.actions.githubusercontent.com is shared across
# all GitHub Actions in this AWS account and is owned by another project
# (tlyko/sprawdzamszlak — see its terraform/cicd.tf). We reference it via
# a data source — never manage it from here. Touching it would cause drift
# pingpong with the other project's terraform state.
data "aws_iam_openid_connect_provider" "github_actions" {
  url = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_role" "github_actions" {
  name        = "${local.project}-github-actions"
  description = "Role assumed by GitHub Actions in ${local.github_owner}/${local.github_repo} via OIDC."

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = data.aws_iam_openid_connect_provider.github_actions.arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          # Sec audit H4 — `repo:owner/repo:*` było zbyt szerokie, łapało
          # PR'y z forków, ref'y feature branchy etc. Każdy ref mógł próbować
          # assume role. Whitelist konkretnych subject patterns:
          # - main push (terraform-apply)
          # - pull_request od MAIN repo (nie forków — GHA dla pull_request_target
          #   z forka dostaje subject `repo:fork-owner/repo:pull_request`)
          "token.actions.githubusercontent.com:sub" = [
            "repo:${local.github_owner}/${local.github_repo}:ref:refs/heads/main",
            "repo:${local.github_owner}/${local.github_repo}:pull_request",
          ]
        }
      }
    }]
  })
}

# Broad infrastructure permissions for managing project resources (S3, DynamoDB,
# Lambda, API Gateway, EventBridge, SSM, CloudWatch, etc.). Excludes IAM —
# managed separately below with a tighter scope.
resource "aws_iam_role_policy_attachment" "github_actions_power_user" {
  role       = aws_iam_role.github_actions.name
  policy_arn = "arn:aws:iam::aws:policy/PowerUserAccess"
}

# IAM permissions are scoped to project-prefixed resources only. PassRole is
# required for Lambda execution roles created by Terraform.
resource "aws_iam_role_policy" "github_actions_iam" {
  name = "iam-management"
  role = aws_iam_role.github_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ManageProjectRolesAndPolicies"
        Effect = "Allow"
        Action = [
          "iam:CreateRole",
          "iam:DeleteRole",
          "iam:GetRole",
          "iam:UpdateRole",
          "iam:UpdateRoleDescription",
          "iam:UpdateAssumeRolePolicy",
          "iam:CreatePolicy",
          "iam:DeletePolicy",
          "iam:GetPolicy",
          "iam:GetPolicyVersion",
          "iam:CreatePolicyVersion",
          "iam:DeletePolicyVersion",
          "iam:ListPolicyVersions",
          "iam:AttachRolePolicy",
          "iam:DetachRolePolicy",
          "iam:ListAttachedRolePolicies",
          "iam:PutRolePolicy",
          "iam:DeleteRolePolicy",
          "iam:GetRolePolicy",
          "iam:ListRolePolicies",
          # AWS provider 5.x+ wymaga przy aws_iam_role delete (Lambda exec
          # role lifecycle: PR #59 destroy advisor_dinner-exec faila bez tego).
          "iam:ListInstanceProfilesForRole",
          "iam:TagRole",
          "iam:UntagRole",
          "iam:TagPolicy",
          "iam:UntagPolicy",
        ]
        # `local.project` to legacy literówka "syncbody" (zob. backlog
        # PROJECT-STATUS — destruktywny rename do bodysync osobno). Główny
        # workspace IaC tworzy resources z prefixem "bodysync-*" — dopisujemy
        # oba żeby uniknąć recreate IAM role + reset AWS_ROLE_ARN. Po rename
        # do bodysync usuwamy "syncbody-*".
        Resource = [
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.project}-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/${local.project}-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/bodysync-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/bodysync-*",
        ]
      },
      {
        # Sec audit H3 — `iam:PassRole` bez condition jest klasyczną ścieżką
        # privilege escalation z PowerUserAccess (GHA → EC2 RunInstances z
        # naszą Lambda exec role jako instance profile → DDB+SSM dump).
        # Restykcja do lambda.amazonaws.com zamyka ten wektor.
        Sid    = "PassRoleToLambdaOnly"
        Effect = "Allow"
        Action = "iam:PassRole"
        Resource = [
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.project}-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/bodysync-*",
        ]
        Condition = {
          StringEquals = {
            "iam:PassedToService" = "lambda.amazonaws.com"
          }
        }
      },
      {
        Sid    = "ListIamForPlanning"
        Effect = "Allow"
        Action = [
          "iam:ListRoles",
          "iam:ListPolicies",
          "iam:ListOpenIDConnectProviders",
        ]
        Resource = "*"
      },
    ]
  })
}

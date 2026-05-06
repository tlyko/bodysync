# Bootstrap — Terraform state backend + GitHub OIDC

Provisions the prerequisites that the rest of the infra depends on:

- **S3 bucket** `syncbody-tfstate-<account_id>` — remote state for the root config (versioned, encrypted, public access blocked, noncurrent versions expire after 90d).
- **DynamoDB table** `syncbody-tflock` — state locking.
- **IAM role** `syncbody-github-actions` — assumed by GitHub Actions running in `tlyko/bodysync` via OIDC, no static keys. The OIDC provider itself (`token.actions.githubusercontent.com`) is account-wide and owned by another project (`tlyko/sprawdzamszlak`); we reference it via a data source.

## State

This module uses **local state**. The remote backend in S3 is exactly what we're creating here, so it can't host its own state. `terraform.tfstate` is `.gitignored`. Apply this module manually, once. After that, don't touch it.

## File layout (per ADR-003)

- `config.tf` — terraform{} (required_version + required_providers) + provider "aws" with default_tags
- `locals.tf` — project name, region, github owner/repo, common tags, computed names
- `main.tf` — `data "aws_caller_identity"` + S3 state bucket + DynamoDB lock table
- `oidc.tf` — `data "aws_iam_openid_connect_provider"` + IAM role + policies for GitHub Actions

No `variables.tf` / `outputs.tf` in root (per ADR-003 — fetch values via `terraform state show` or `aws` CLI when needed).

## Usage

```bash
aws sso login                        # ensure creds are fresh
cd infrastructure/terraform
terraform init
terraform plan                       # review
terraform apply

# fetch IAM role ARN for GitHub Actions setup
aws iam get-role --role-name syncbody-github-actions --query 'Role.Arn' --output text
```

Then in GitHub repo settings → Settings → Secrets and variables → Actions → **Variables** tab, add:

- `AWS_ROLE_ARN` = the ARN printed above (this is a *variable*, not a secret — ARNs are not sensitive).

## Resources are protected against accidental destroy

Both the state bucket and lock table have `prevent_destroy = true`. To delete them you'd have to remove that lifecycle rule first, then `terraform destroy`. Don't.

## Re-running

Re-applying is safe — Terraform will report "no changes" once everything's in place. If you change the OIDC trust policy (e.g., new repo), `terraform apply` updates it in place.

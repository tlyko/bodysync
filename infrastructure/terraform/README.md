# Bootstrap — Terraform state backend + GitHub OIDC

Provisions the prerequisites that the rest of the infra depends on:

- **S3 bucket** `syncbody-tfstate-<account_id>` — remote state for the root config (versioned, encrypted, public access blocked, noncurrent versions expire after 90d).
- **DynamoDB table** `syncbody-tflock` — state locking.
- **IAM role** `syncbody-github-actions` — assumed by GitHub Actions running in `tlyko/bodysync` via OIDC, no static keys. The OIDC provider itself (`token.actions.githubusercontent.com`) is account-wide and owned by another project (`tlyko/sprawdzamszlak`); we reference it via a data source.

## State

This module uses **local state**. The remote backend in S3 is exactly what we're creating here, so it can't host its own state. `terraform.tfstate` is `.gitignored`. Apply this module manually, once. After that, don't touch it.

## Usage

```bash
aws sso login                        # ensure creds are fresh
cd terraform/bootstrap
terraform init
terraform plan                       # review
terraform apply

# capture outputs for downstream config
terraform output -json > ../../docs/infra-outputs.json
terraform output github_actions_role_arn
```

Then in GitHub repo settings → Settings → Secrets and variables → Actions → **Variables** tab, add:

- `AWS_ROLE_ARN` = value of `github_actions_role_arn` output (this is a *variable*, not a secret — ARNs are not sensitive).

## Resources are protected against accidental destroy

Both the state bucket and lock table have `prevent_destroy = true`. To delete them you'd have to remove that lifecycle rule first, then `terraform destroy`. Don't.

## Re-running

Re-applying is safe — Terraform will report "no changes" once everything's in place. If you change the OIDC trust policy (e.g., new repo), `terraform apply` updates it in place.

# Skill: Terraform Infrastructure

## When to use
Any task involving AWS infrastructure, modules, variables, or deployment.

## Root layout (per ADR-003)
- `infrastructure/terraform/config.tf` — `terraform {}` (required_version + required_providers + backend "s3") plus `provider "aws"` z default_tags. Wszystko co konfiguruje runtime Terraforma.
- `infrastructure/terraform/locals.tf` — wszystkie stałe konfiguracyjne (project, region, table configs, ssm paths, lambda_artifacts_path, common tags). Zero `variable {}` w root.
- `infrastructure/terraform/main.tf` (+ tematyczne `lambda.tf`, `oidc.tf`, ...) — `data` + `resource` + `module` blocks.
- **Brak `variables.tf` / `outputs.tf` w root** dopóki nie ma drugiego env'a / cross-stack consumer'a outputu. Outputy z istniejących resources → `terraform state show` lub `aws iam get-role --query 'Role.Arn'`.
- Bootstrap (S3 state bucket + DDB lock + OIDC role) żyje osobno w `infrastructure/terraform/bootstrap/` z lokalnym state.

## Module structure
Each AWS service gets its own module under `infrastructure/terraform/modules/`:
- `api-gateway/` — HTTP API, routes, custom domain, stage
- `lambda/` — Functions, layers, IAM roles, CloudWatch log groups
- `dynamodb/` — Table, GSI, on-demand billing
- `s3/` — Bucket for FAISS embeddings + recipe data
- `eventbridge/` — Cron rules (daily advisor 21:00, weekly Sunday 20:00, training sync every 6h)
- `ssm/` — Parameter Store entries (API keys, allowed emails, Google SA key)

## Conventions
- Provider versions pinned in `config.tf` `required_providers` block
- Module variables have descriptions and type constraints (root workspace doesn't use `variables.tf` per ADR-003 — module contracts still do)
- Use `terraform-aws-modules` where it saves boilerplate (but not for simple resources)
- **Lambda source lives in `apps/api/handlers/{function_name}/` — NOT in `infrastructure/terraform/`** (see ADR-002)
- **Lambda packaging:** build script `apps/api/scripts/build.py` produces `apps/api/dist/{function_name}.zip` per Lambda. Terraform consumes via `aws_lambda_function.filename = var.source_zip` + `source_code_hash = filebase64sha256(var.source_zip)`. Path passed through root variable `lambda_artifacts_path = "${path.module}/../../apps/api/dist"`.
- **CI must run build before plan/apply:** GHA workflow does `setup-python` → `cd apps/api && python scripts/build.py` BEFORE `terraform plan/apply`.
- Tags on everything: `Project = "bodysync"`, `Environment = var.environment`
- State backend: S3 + DynamoDB lock table

## Lambda functions
| Function | Runtime | Trigger |
|---|---|---|
| google-auth | python3.12 arm64 | API GW POST /api/auth/google |
| health-webhook | python3.12 arm64 | API GW POST /api/health/webhook |
| training-plan-sync | python3.12 arm64 | EventBridge cron(0 */6 * * ? *) |
| strava-sync | python3.12 arm64 | API GW POST /api/sync/strava |
| strava-callback | python3.12 arm64 | API GW GET /api/strava/callback |
| ai-advisor-daily | python3.12 arm64 | EventBridge cron(0 19 * * ? *) (21:00 CET = 19:00 UTC) |
| ai-advisor-weekly | python3.12 arm64 | EventBridge cron(0 18 ? * SUN *) (20:00 CET Sunday) |
| ai-chat | python3.12 arm64 | API GW POST /api/ai/chat |
| recipe-search | python3.12 arm64 | API GW GET /api/recipes/search |
| api-read | python3.12 arm64 | API GW GET /api/* |

## DynamoDB schema
```
Table: bodysync
PK (String): USER#alice
SK (String): PROFILE | HEALTH#2026-05-06 | NUTRITION#2026-05-06 | WEIGHT#2026-05-06 | WORKOUT#2026-05-06#id | TRAINING#2026-05-06 | ADVICE#2026-05-06 | REPORT#2026-W19 | STRAVA_TOKEN
GSI-1: SK (PK) + PK (SK) — inverted index
Billing: PAY_PER_REQUEST
```

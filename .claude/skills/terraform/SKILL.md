# Skill: Terraform Infrastructure

## When to use
Any task involving AWS infrastructure, modules, variables, or deployment.

## Module structure
Each AWS service gets its own module under `terraform/modules/`:
- `api-gateway/` — HTTP API, routes, custom domain, stage
- `lambda/` — Functions, layers, IAM roles, CloudWatch log groups
- `dynamodb/` — Table, GSI, on-demand billing
- `s3/` — Bucket for FAISS embeddings + recipe data
- `eventbridge/` — Cron rules (daily advisor 21:00, weekly Sunday 20:00, training sync every 6h)
- `ssm/` — Parameter Store entries (API keys, allowed emails, Google SA key)

## Conventions
- Provider versions pinned in `versions.tf`
- Variables have descriptions and type constraints
- Use `terraform-aws-modules` where it saves boilerplate (but not for simple resources)
- Lambda source in `lambda-src/{function_name}/handler.py`
- Lambda packaging: zip per function, exclude tests
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

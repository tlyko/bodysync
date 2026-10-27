# bodysync.pl

A private health and training dashboard for two people. It brings data from **Apple Health**, **Strava** and **Google Sheets** into one place, and **Claude Haiku** gives diet and calorie advice in Polish.

- App: [bodysync.pl](https://bodysync.pl)
- API: `api.bodysync.pl`
- MCP server (Claude connector): `https://api.bodysync.pl/mcp`

## What it does

| Area | Source | What you get |
|---|---|---|
| Biometrics | Apple Health → [Health Auto Export](https://www.healthyapps.dev/) (webhook) | weight, body composition, sleep and sleep stages, steps, heart rate, kcal in/out, macros |
| Activities | Strava (OAuth + webhook + fetcher) | workout list, routes, training load |
| Training plan | Google Sheets (service account, read-only) | "Training Plan" tab, context for the assistant |
| Manual measurements | in-app form | circumferences (waist, hips, chest, biceps, thigh) |
| AI assistant | Anthropic Haiku 4.5 + RAG (139 recipes) | diet chat, diet review every 14 days, activity level suggestion for the TDEE calculator |
| MCP connector | custom OAuth 2.0 server + JSON-RPC | bodysync data available in Claude conversations, read-only |
| GDPR | `GET /api/me/export`, `DELETE /api/me/account` | export and erasure of all of a user's data |

Only Google accounts on a two-address allowlist can use the app. Everyone else sees a landing page with a waitlist.

## Architecture

```
 bodysync.pl (React, Cloudflare) ─┐
 Apple Health (HAE webhook) ──────┤
 Strava (OAuth, webhook) ─────────┼──► API Gateway HTTP ──► Lambdas (Python 3.12) ──┬──► DynamoDB bodysync-data
 Claude (MCP connector) ──────────┘    api.bodysync.pl                              ├──► S3 (raw data, FAISS)
                                                                                    ├──► Google Sheets (plan)
                                                                                    ├──► Anthropic API
                                                                                    └──► SSM (secrets)
```

- **Frontend:** React 19 + Vite + TypeScript on Cloudflare Workers + Static Assets (deployed from `main`)
- **Backend:** Python 3.12 on AWS Lambda ARM64, one handler per Lambda (`apps/api/handlers/*`)
- **Database:** DynamoDB single-table, `PK = USER#{id}`, PITR enabled
- **Files:** S3 for raw HAE payloads, Strava streams and the recipe FAISS index
- **Login:** Google Sign-In (with nonce) → JWT in an HttpOnly cookie, double-submit CSRF
- **Secrets:** SSM Parameter Store SecureString
- **IaC:** Terraform (S3 backend), applied only from GitHub Actions via OIDC
- **Async:** DynamoDB Streams + a second Lambda (Strava fetcher), EventBridge for scheduled jobs
- **Alerts:** Anthropic cost alarm → SNS → Telegram bot

Architecture decisions live in [`docs/adr/`](docs/adr/):

| ADR | Topic |
|---|---|
| [001](docs/adr/ADR-001-stack-baseline.md) | Stack baseline |
| [002](docs/adr/ADR-002-lambda-packaging.md) | Lambda packaging |
| [003](docs/adr/ADR-003-terraform-conventions.md) | Terraform conventions |
| [006](docs/adr/ADR-006-advisor-on-demand-vs-cron.md) | Advisor on demand vs cron |
| [007](docs/adr/ADR-007-chat-assistant-rag.md) | Chat assistant with RAG |
| [008](docs/adr/ADR-008-adaptive-tdee-recalculation.md) | Adaptive TDEE recalculation |
| [009](docs/adr/ADR-009-llm-diet-review-pivot.md) | LLM diet review instead of TDEE recalculation |
| [010](docs/adr/ADR-010-mcp-server.md) | MCP server |

## Repository layout

```
bodysync/
├── apps/
│   ├── api/                 ← backend: handlers/<lambda>/, shared/, tests/, scripts/build.py
│   └── web/                 ← frontend: React + Vite
├── infrastructure/
│   └── terraform/           ← root workspace + modules/ + bootstrap/ (state backend, OIDC)
├── docs/                    ← ADRs, audits, plan, sprints
├── samples/                 ← local material (recipe PDFs), not in git
├── wrangler.jsonc           ← Cloudflare deploy config for the frontend
├── PROJECT-STATUS.md        ← current project state
└── CLAUDE.md                ← conventions and working rules
```

Module READMEs:

- [`apps/api/`](apps/api/README.md): Python environment, tests, building Lambda bundles
- [`apps/web/`](apps/web/README.md): dev server, build, Cloudflare config
- [`apps/api/handlers/mcp/`](apps/api/handlers/mcp/README.md): MCP server and connecting it in Claude
- [`infrastructure/terraform/bootstrap/`](infrastructure/terraform/bootstrap/README.md): one-time bootstrap of Terraform state and the OIDC role

## Running locally

Requirements: Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 22, Terraform 1.13+, AWS CLI (SSO).

### Backend

```bash
cd apps/api
uv venv --python 3.12
uv pip install -e ".[dev]"

uv run pytest                                # tests (moto instead of real DynamoDB)
uv run ruff check . && uv run ruff format --check .
uv run mypy shared handlers
uv run python scripts/build.py               # Lambda bundles → dist/{handler}.zip
```

### Frontend

```bash
cd apps/web
npm install
npm run dev          # http://localhost:5173
npm test             # vitest
npm run typecheck
npm run build
```

With `VITE_PREVIEW_MODE=true` the frontend replaces `fetch` with sample data, so it runs without a backend. Preview deployments work the same way.

## Deployment

| What | How |
|---|---|
| Frontend | Cloudflare builds every push. `main` goes to `bodysync.pl`, other branches to a preview URL |
| Infrastructure + Lambdas | `Terraform` workflow: `plan` on PRs, `apply` after merge to `main` (AWS OIDC, no long-lived keys) |
| Frontend CI | `Web` workflow: typecheck, vitest and build on changes in `apps/web/**` |

Locally we only run `terraform plan`. The exception is `bootstrap/`, which has local state and is applied by hand.

## Rules

The full list is in [`CLAUDE.md`](CLAUDE.md). The most important ones:

- Changes reach `main` only through PRs (`feat/*`, `fix/*`, `chore/*`), with conventional commits
- Every DynamoDB query has `PK = USER#{id}` in its condition, and tests always check isolation with two users
- Secrets live only in SSM, never in environment variables or the repo
- Pydantic validates every endpoint and webhook input
- GitHub Actions are pinned to a full SHA, not a tag
- New dependencies need a reason, because every megabyte of bundle adds to cold start

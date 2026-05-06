# SyncBody — Health & Fitness Dashboard

## Project overview
Personal health dashboard for 2 users. Aggregates data from Apple Health (via Health Auto Export webhook), Google Sheets (training plan), Strava, and recipe PDFs. AI advisor recommends daily calories and meal plans in Polish.

Domain: syncbody.pl | API: api.syncbody.pl

## Tech stack
- **IaC**: Terraform (AWS provider + Cloudflare provider)
- **Backend**: Python 3.12 Lambda (ARM64, 512MB), API Gateway HTTP
- **Frontend**: React + Vite, deployed to Cloudflare Pages
- **Database**: DynamoDB single-table (PK: `USER#id`, SK: `TYPE#date`)
- **LLM**: Anthropic API (Haiku 4.5), prompt caching enabled
- **Auth**: Google OAuth2 → JWT session (30d TTL), allowlist 2 emails in SSM
- **Secrets**: SSM Parameter Store (never Secrets Manager)

## Directory structure
```
syncbody/
├── CLAUDE.md
├── terraform/           # All infra
│   ├── main.tf
│   ├── modules/         # api-gateway, lambda, dynamodb, s3, eventbridge, ssm
│   └── lambda-src/      # Python handlers (one dir per function)
├── frontend/            # React + Vite
│   ├── src/
│   └── package.json
├── scripts/             # One-off: seed_recipes.py, create_user.py
├── docs/                # PROJECT_PLAN.md, architecture diagrams
└── tests/               # pytest for lambdas, vitest for frontend
```

## Commands
- `cd terraform && terraform init && terraform plan` — preview infra changes
- `cd terraform && terraform apply -auto-approve` — deploy infra
- `cd frontend && npm run dev` — local frontend
- `cd frontend && npm run build` — production build
- `cd terraform/lambda-src && pytest` — run lambda tests
- `cd frontend && npx vitest run` — run frontend tests

## Code style
- Python: ruff format + ruff check, type hints everywhere, docstrings on public functions
- TypeScript/React: prettier, ESM imports, named exports only
- Terraform: one module per service, variables.tf + outputs.tf per module
- No `print()` — use `logger.info()` / `logger.error()`
- No `any` type in TypeScript
- Commit messages: conventional commits (`feat:`, `fix:`, `infra:`, `docs:`)

## Architecture rules
- DynamoDB single-table: always use PK=`USER#{user_id}`, SK=`{TYPE}#{date}`
- Lambda handlers: thin — parse event, call service, return response
- All secrets from SSM Parameter Store via `boto3.client('ssm').get_parameter()`
- Anthropic API key in SSM at `/syncbody/anthropic-api-key`
- Google OAuth2 client ID in SSM at `/syncbody/google-client-id`
- Allowed emails in SSM at `/syncbody/allowed-emails` (comma-separated)
- CORS: allow only `https://syncbody.pl` in production
- Frontend env var: `VITE_API_URL` → `https://api.syncbody.pl`

## Prohibited
- No Cognito (we use direct Google OAuth2)
- No Bedrock (we use Anthropic API directly)
- No Secrets Manager (we use SSM Parameter Store — free)
- No RDS/Aurora (DynamoDB only)
- No localStorage for auth tokens (use httpOnly cookies or in-memory + refresh)
- No hardcoded secrets in code or .tf files
- No `terraform destroy` without explicit confirmation

## Testing approach
- Lambda: pytest + moto (DynamoDB mock) + responses (HTTP mock)
- Frontend: vitest + testing-library/react
- Integration: test webhook with sample Health Auto Export JSON payload
- Always test with both users (PK isolation)

## AI advisor context
- System prompt in `lambda-src/ai_advisor/system_prompt.txt` — cached via Anthropic prompt caching
- Daily advisor runs at 21:00 CET, weekly at Sunday 20:00 CET
- Output language: Polish
- Output format: JSON with fields: summary, tdee, target_kcal, target_macros, tomorrow_menu
- Training plan from Google Sheets passed AS-IS (raw text) — Haiku parses it

## Design system (frontend)
- Dark theme: bg `#0a0e17`, cards `#1a2332`, borders `#2a3548`
- Accent cyan `#22d3ee`, green `#10b981`, orange `#f59e0b`, red `#ef4444`, purple `#a78bfa`
- Fonts: JetBrains Mono (numbers/headers), Inter (body)
- Components: StatCard (sparkline), NutritionDonut, WeightChart, ActivityRow, RecipeCard
- Reference prototype: `docs/health-dashboard-prototype.jsx`

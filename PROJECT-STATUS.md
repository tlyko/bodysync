# Project status snapshot — bodysync.pl

Living document — overwritten when significant state changes. Read this first after `/clear`.

**Sprint roadmap:** [docs/SPRINTS.md](docs/SPRINTS.md). Sprint 0 zamykany (PR #7), Sprint 1 startuje po merge.

## Co to jest

Personal health + fitness dashboard dla pary (single-tenant initial; projektowane z możliwością otwarcia, ale **bez** przedwczesnej generalizacji). Agreguje:
- **Apple Health** via Health Auto Export webhook → biometry (HRV, sen, kroki, kcal, BPM)
- **Strava** OAuth + webhook → aktywności (training load, perceived effort)
- **Google Sheets** → owner-managed weekly training plan (read-only via service account)
- **Anthropic Haiku 4.5** → kcal + meal advisor (PL prompt)

Domena: `bodysync.pl` (frontend, Cloudflare Pages) + `api.bodysync.pl` (API Gateway HTTP).

## Stack

- **Backend:** Python 3.12 Lambda ARM64 512MB (advisor 1024MB / 30s)
- **Frontend:** React + Vite (SPA), Cloudflare Pages auto-deploy z main
- **DB:** DynamoDB single-table `bodysync-data`, PK=`USER#{id}`, SK=`{TYPE}#{date}` (PITR włączony)
- **Storage:** S3 dla raw payloads (Strava streams JSON, Health Auto Export raw)
- **IaC:** Terraform 1.13+ z `s3` backend + `use_lockfile`, AWS provider 6.x, Cloudflare provider
- **CI/CD:** GitHub Actions z AWS OIDC role assumption (no long-lived keys)
- **Auth:** Google OAuth → JWT cookie (HttpOnly, Secure, SameSite=Lax)
- **Sekrety:** SSM Parameter Store SecureString (Anthropic key, Strava client_secret, Health Auto Export webhook secret, Google service account JSON)

## Status implementacji

| Milestone | Status |
|---|---|
| Bootstrap Terraform state backend + GHA OIDC | ✅ shipped |
| `.claude/` setup (agents + commands + skills) | ✅ shipped (port ze sprawdzamszlak, frontmatter, ADR-001) |
| ADR-001 stack baseline | ✅ shipped (`docs/adr/ADR-001-stack-baseline.md`) |
| `apps/api/` Lambda scaffold (Python, Pydantic schemas, JWT) | ✅ shipped (per ADR-002, pytest 10/10, mypy strict) |
| `apps/web/` React+Vite scaffold | ✅ shipped (placeholder z dark theme) |
| DDB single-table + IAM | ✅ shipped (`bodysync-data` PK/SK + GSI-1, PITR, SSE, TTL) |
| API Gateway HTTP + custom domain | 🟡 endpoint live (`8pyf98ekt2.execute-api.eu-west-1.amazonaws.com`); custom domain `api.bodysync.pl` TODO |
| Cloudflare Workers binding + `bodysync.pl` custom domain | ✅ shipped |
| `/api/auth/google` endpoint | ✅ shipped (401 invalid / 400 Pydantic / 500 placeholders w SSM dopóki user nie wpisze) |
| Security hardening (audit 2026-05-07: 2 Critical + 6 High) | ✅ shipped (PR #25-32) |
| Apple Health webhook (signature verify + idempotency) | ❌ |
| Strava OAuth + webhook + fetcher (port wzorca ze sprawdzamszlak) | ❌ |
| Google Sheets read | ❌ |
| Anthropic advisor (prompt cache, prompt injection guard) | ❌ |
| Frontend dashboard | ❌ |

## Open PRs

`gh pr list` — TBD na razie nic.

## Active backlog

- **`syncbody` → `bodysync` rename (destructive)** — bootstrap state ma legacy literówkę: `Project=syncbody` tag, `syncbody-tfstate-{account_id}` bucket, `syncbody-tflock` DDB table, `syncbody-github-actions` IAM role. Rename = IAM role DELETE+CREATE (nowa ARN, GitHub variable `AWS_ROLE_ARN` reset) + bucket/table rename = state file move. Osobny PR z świadomą destrukcją. Zostawiamy "syncbody" do tej akcji.
- **Layout decision dla Step 2** — bootstrap obecnie zajmuje `infrastructure/terraform/`. Główny workspace nie może tam siedzieć (różne backendy). Decyzja: przenieść bootstrap do `infrastructure/terraform/bootstrap/` (preferowane per ADR-003) lub stworzyć główny w `infrastructure/terraform-app/`. Ruszanie state file = manualnie + `terraform init -migrate-state`.
- **Provider binaries w `infrastructure/terraform/hashicorp/`** — pusty katalog, nic w git ✓ (alarm fałszywy, do usunięcia z backlogu)
- **Open follow-upy z audytu 2026-05-06** — HAE auth scheme, OIDC tightening (rola IAM ma `*` z ABAC tagiem — do zacieśnienia), naming policy ADR (jeśli potrzebne)
- **Security audit follow-upy (Notes z 2026-05-07)** — accept lub planuj na otwarcie projektu:
  - SSM cache bez TTL (rotacja secret = cold restart Lambdy) → ADR jeśli zaczniemy rotować runtime
  - S3 deny-non-TLS bucket policy (Security Hub flaguje)
  - DDB CMK zamiast aws-managed key (compliance trigger)
  - `requirements.txt` bez `--require-hashes` — `pip-compile --generate-hashes` przed Sprint 3 jeśli dochodzi większy stack deps (Anthropic SDK, googleapiclient, faiss)
  - Logger `reason=str(e)` whitelistuj typy (zamiast surowego google-auth message) jeśli library zacznie loggować raw token
  - CSP `style-src 'unsafe-inline'` → migracja na nonce-based gdy dashboard scaffold (Sprint 7)

## Architectural commitments (do zapisania w ADRs)

- **ADR-001 stack baseline** ✅ shipped (`docs/adr/ADR-001-stack-baseline.md`)
- **ADR-002 lambda packaging** ✅ shipped (`docs/adr/ADR-002-lambda-packaging.md`)
- **ADR-003 terraform conventions** ✅ shipped (`docs/adr/ADR-003-terraform-conventions.md`)
- **ADR-004 (TBD)** — multi-user model: PK isolation `USER#{id}` + GSI on entity type for cross-user admin queries.
- **ADR-005 (TBD)** — sekrety: SSM SecureString hierarchy, rotacja, IAM scoping.

## SSM parameters (planowane)

| name | type | who writes | who reads |
|---|---|---|---|
| `/bodysync/anthropic/api_key` | SecureString | owner (CLI) | advisor Lambda |
| `/bodysync/strava/client_id` | String | owner (CLI) | api Lambda (oauth + fetcher) |
| `/bodysync/strava/client_secret` | SecureString | owner (CLI) | api Lambda |
| `/bodysync/strava/{user_id}/tokens` | SecureString | api Lambda (oauth callback + fetcher refresh) | fetcher Lambda |
| `/bodysync/strava/verify_token` | SecureString | strava:subscribe CLI | api Lambda (webhook handshake) |
| `/bodysync/health-auto-export/webhook_secret` | SecureString | owner (CLI) | api Lambda (signature verify) |
| `/bodysync/google/service_account_json` | SecureString | owner (CLI) | api Lambda (Sheets read) |
| `/bodysync/{user_id}/training-sheet-id` | String | owner (CLI) | api Lambda |
| `/bodysync/jwt/signing_secret` | SecureString | owner (CLI) | api Lambda (mint + verify) |

## Operational items still open

- TFC migration to S3+DDB — N/A (ten projekt od początku S3+DDB)
- Provider binaries w `infrastructure/terraform/hashicorp/` — nie commit-uj, dodaj `.terraform/` i `hashicorp/` do `.gitignore` jeśli brak
- Health Auto Export — owner musi wpisać webhook URL + secret na telefonie (manual, post-deploy)
- Strava webhook subskrypcja — manual `pnpm strava:subscribe` (lub odpowiednik Python) po deployu

## Repo

- `tlyko/bodysync` (private, monorepo)

## Live URLs (planowane)

- Frontend: `https://bodysync.pl` (Cloudflare Pages)
- API: `https://api.bodysync.pl` (API Gateway custom domain)
- Health webhook target: `https://api.bodysync.pl/health/webhook?user_id=<id>` (signature header)
- Strava webhook: `https://api.bodysync.pl/strava/webhook`
- OAuth callbacks: `https://api.bodysync.pl/strava/oauth/callback`, `https://api.bodysync.pl/auth/google/callback`

## Subagenci (referencja)

| agent | gdzie używać |
|---|---|
| `auditor` | first contact, "co tu mamy", read-only |
| `architect` | decyzje stackowe, ADR, granice modułów, schemat DDB |
| `aws-infra` | Terraform, Lambda, DDB, IAM, API GW |
| `security` | OAuth, sekrety, webhook signatures, prompt injection, IAM, CSP |
| `integrator` | Apple Health / Strava / Google Sheets / Anthropic |
| `frontend-designer` | UI/UX, dashboard, design tokens, motion |
| `reviewer` | diff review przed commitem |

## Slash commands

| command | co robi |
|---|---|
| `/audyt` | pełen audyt monorepo przez `auditor` |
| `/security-check` | sweep przez `security` (full lub scoped) |
| `/nowa-funkcja <opis>` | brief → architect → impl → review |
| `/release` | checklist przed deployem |

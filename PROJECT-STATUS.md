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
| Apple Health webhook (Bearer auth + 13 mapperów + idempotency) | ✅ shipped (PR #33/#34/#35; pending: SSM secrets + HAE iOS config) |
| Strava OAuth + webhook + fetcher (port wzorca ze sprawdzamszlak) | ❌ |
| Google Sheets read | ❌ |
| Anthropic advisor (prompt cache, prompt injection guard) | 🟡 in progress (Sprint 6 MVP — `POST /api/advisor/chat` z RAG per ADR-007, supersedes ADR-006; planned w `docs/TODO.md` Sprint 6) |
| Recipe pipeline (PDF → DDB + FAISS) | 🟡 merged into Sprint 6 per ADR-007 (Sprint 8 nie istnieje osobno) |
| Frontend dashboard | ❌ |

## Open PRs

`gh pr list` — żadnych otwartych w danej chwili.

## Aktywny sprint — Sprint 6 (per ADR-007)

Chat assistant + RAG. Refactor `advisor_dinner` → `advisor_chat`, multi-turn z 24h DDB TTL, plain POST + prompt caching, RAG przez FAISS+S3+OpenAI embeddings, persona "asystent dietetyczny z biblioteki Lidla/Biedronki" (~150-200 przepisów z 5 PDFów w `samples/recipes/`).

**Strategia delivery — 2 PRy incremental (owner zaakceptował 2026-05-07):**
- **PR1 — Sprint 6.1 — Chat refactor (~5h)** — chat działa bez RAG, generic Haiku knowledge
- **PR2 — Sprint 6.2 — RAG (seed + retrieval, ~9-10h)** — dodaje konkretne przepisy do prompt context

**Pre-req DONE:**
- ✅ Anthropic key w SSM `/bodysync/anthropic/api_key` (109 chars, `sk-ant-api03-...`)
- ✅ OpenAI key w SSM `/bodysync/openai/api_key` (do PR2)
- ✅ ADR-006 superseded by ADR-007 (PR #55)
- ✅ Sprint 8 (recipe pipeline) merged into Sprint 6
- ✅ Smoke test PR #50 endpoint live 2026-05-07: `POST https://api.bodysync.pl/api/advisor/dinner` → 200 z real Anthropic Haiku response (po hot fix #58 build.py kopiującym `system_prompt.txt`)

**Spec źródła:** `docs/adr/ADR-007-chat-assistant-rag.md`, `docs/TODO.md` Sprint 6.1+6.2 (PR #57).

**5 OPEN questions z ADR-007:** Strava/Sheets enrichment timing, conv_date forking, embedding refresh strategy, content logging policy (PII), frontend chat UI scope.

## Active backlog

- **Garmin Connect direct integration** — Apple Health → HAE → DDB pipeline serwuje kroki z **Garmin Connect Sync to Apple Health** który desync'uje (delay + miss). Owner zauważył live 2026-05-07 że steps z dziennego export'u są niższe niż realne. Plan: bezpośredni połączenie do Garmin Connect (`python-garminconnect` lib lub Garmin Connect IQ Web Services). Storage Garmin email/password w SSM SecureString per user (Garmin nie ma proper OAuth dla konsumenta), refresh tokenów. Zakres: steps + active calories (jako alternatywa dla HAE/Apple Health ścieżki dla tych metryk). Activity tracking nadal przez Strava (Sprint 4). Osobny sprint, prawdopodobnie po Sprint 4 (Strava) jako **Sprint 4.5 — Garmin Connect**.
- **Sleep historical backfill** — sleep rows dla 2026-05-01..05 (sprzed PR #46) mają `asleep=0` mimo że HAE wysyła `core+rem+deep`. Fallback `asleep = core+rem+deep` z PR #46 działa tylko przy zapisie. Backfill: jednorazowy script `scripts/recompute_sleep.py` — query DDB sleep rows z `asleep=0 AND inBed>0`, recompute, update. Niski priorytet — zacznie się samo poprawiać po HAE re-export historycznych dni.
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
- **ADR-006 advisor on-demand vs cron** ⚠️ Superseded by ADR-007 (`docs/adr/ADR-006-advisor-on-demand-vs-cron.md`) — single-shot dinner endpoint odrzucony po user feedback 2026-05-07 (chat + RAG zamiast button "kolacja"). PR #50 infra zachowane jako baseline refactoru.
- **ADR-007 chat assistant + RAG** ✅ shipped (`docs/adr/ADR-007-chat-assistant-rag.md`) — primary advisor feature: `POST /api/advisor/chat` (multi-turn, 24h TTL DDB history, RAG retrieval z FAISS+S3+OpenAI embeddings, recipes Lidla/Biedronki ~150-200 entries w DDB `RECIPES` PK, Anthropic Haiku 4.5 prompt cached, free-form polski text response). Supersedes ADR-006. Subsumes Sprint 8 (recipe pipeline merged into Sprint 6).

## SSM parameters (planowane)

| name | type | who writes | who reads |
|---|---|---|---|
| `/bodysync/anthropic/api_key` | SecureString | owner (CLI) | advisor Lambda + seed_recipes.py (Vision fallback) |
| `/bodysync/openai/api_key` | SecureString | owner (CLI) | advisor Lambda (per-turn embed query) + seed_recipes.py (batch embed) — NEW per ADR-007 |
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

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
| Anthropic advisor (prompt cache, prompt injection guard) | ✅ Sprint 6.1 + 6.2 live (PRy #59/#62/#63/#65/#66/#67) — `POST /api/advisor/chat` multi-turn z RAG retrieval (139 przepisów Lidla/Biedronki, k=5 cosine), used_recipes populated, system prompt + retrieved_recipes oba cached (~13956 tokens razem) |
| Recipe pipeline (PDF → DDB + FAISS) | ✅ Sprint 6.2 PR2 live (PR #65 + #67) — `seed_recipes.py` parsed 139 recipes z 5 PDFów; DDB `PK=RECIPES`; S3 `recipes/faiss-index.bin` (834KB) + `recipes-metadata.json` (21KB); embed cost ~$0.0003 |
| Frontend dashboard + chat UI | ✅ Sprint 7+8+9 shipped 2026-05-08 — sidebar 240px z 6 tabami (Dashboard/Aktywności/Ciało/Odżywianie/Przepisy AI/Ustawienia), tinted StatCardy z 11 SVG icons (HRV/sen/kroki/kcal/RHR/body fat/makro/waga), Sparkline + WeightChart, range toggle 1d/7d/30d, ProfileTargetsForm z PUT /api/profile/targets, multi-turn chat z RecipeCard+RecipeModal. 34 vitest. Live verified |

## Open PRs

`gh pr list` — żadnych otwartych w danej chwili.

## Aktywny sprint — żaden (Sprint 6 + 7 + 8 + 9 zamknięte 2026-05-08)

Cztery sprinty shipped end-to-end w ciągu jednego dnia (2026-05-08): chat advisor z RAG (Sprint 6) + frontend chat UI (Sprint 7) + biometry dashboard polish (Sprint 8) + profile targets endpoint + 1:1 prototype port (Sprint 9). Następny ruch z backlogu — Sprint 4 Strava (zaległy), Sprint 4.5 Garmin Connect, lub backlog items (#17 Telegram bot, #18 Restore test_rag.py, #19 frontend bundle code-split, #20 PDF hosting, #21 chat history GET endpoint).

**Sprint 8 — Biometry dashboard polish — DONE (PRy #78 + #79 + #80 + #81 + #82 + #83 + #84):**
- ✅ Sparkline (inline SVG, no deps) + StatCard z accent system per CLAUDE.md design tokens
- ✅ WeightChart line chart 30d z gradient fill area + Y/X axis labels + a11y
- ✅ `biometry.ts` — `buildSeries` per-metric extractors registry + `latestValue` + `trendPct` 7d-vs-7-14d
- ✅ Range selector segmented (Dziś / 7 dni / 30 dni). KISS: backend zwraca 30d, slice in-memory
- ✅ Visual polish anti-rainbow: drop kolorowych value styles (wartości białe), sizing tweaks
- ✅ Vitest 24 nowych testów (13 biometry.ts + 11 dashboard components)
- ✅ Sekcja Odżywianie (kcal_in + protein/fat/carbs makro)

**Sprint 9 — Profile targets + 1:1 prototype port — DONE (PRy #85 + #86 + #87 + #88 + #89):**
- ✅ Backend `GET + PUT /api/profile/targets` (PR #85) — JWT auth + Pydantic walidacja + DDB merge. 10 testów. Defaults zsynchronizowane z `advisor_chat/service.py` (kcal 2000, protein 130, fat 70, carbs 200) — chat i UI widzą ten sam fallback gdy owner jeszcze nie wpisał.
- ✅ Frontend Profil tab (PR #86) — `ProfileTargetsForm` z 4 inputami + banner is_default + PL hints dietetyczne. 5 testów.
- ✅ CORS PUT method fix (PR #87) — owner zgłosił "nie udaje się zapisać". `aws apigatewayv2 get-api ... CorsConfiguration.AllowMethods` miał `[POST, OPTIONS, GET]` — brak PUT, browser blokował preflight. Fix: `cors_allow_methods` default w api-gateway module.
- ✅ Inline SVG icons (PR #88) — 11 ikonek per metryk (flame/footprints/heart-pulse/moon/scale/utensils/egg/droplet/wheat/percent), zero deps, +2.7 KB raw.
- ✅ **1:1 prototype port (PR #89)** — owner: "tandetnie, oczekiwałem dokładnie jak mookup". Sidebar 240px z 6 tabami zamiast top-tabs. Tinted full-card StatCardy (drop circle ornament). Icon inline obok label. Gradient header h1. 6 tabów: Dashboard (overview 4 stats + Recovery 2×2 + Aktywności placeholder) / Aktywności (Strava placeholder) / Ciało (biometria + waga) / Odżywianie / Przepisy AI (chat) / Ustawienia (profile form). 34/34 testów.

**Sprint 9 metryki:**
- Backend: 1 nowy Lambda (profile_targets), 10 testów
- Frontend bundle: JS 598 → 611 KB raw / 144.51 → 148.30 KB gz, CSS 11.47 → 16.97 KB / 2.61 → 3.49 KB gz
- 5 PR-ów (#85/#86/#87/#88/#89), 1 dzień implementacji

**Sprint 9 process notes:**
- frontend-designer agent użyty 2 razy: pierwszy raz po "tandetnie" feedbacku rekomendował SKIP odważnych zmian z prototype (KISS-adaptive), drugi raz po "1:1 mookup" feedbacku zmienił rekomendację na pełen port (sidebar + tinted cards + reorganizacja tabów). Kontekst owner-acceptance koszt jest kluczowy.
- Owner zgłosił 4 issues w trakcie (kcal_in brak na dashboard, "skąd 2000 kcal", "nie udaje się zapisać" CORS, "tandetnie") — każdy fix < 30min od diagnozy do PR.



**Sprint 7 — Frontend chat UI — DONE (PRy #70 + #71 + #72 + #73 + #74 + #75 + #76, 7 stepów w jednej sesji):**
- ✅ Step 1 (PR #70) — `react-markdown` + `remark-gfm` + vitest infra + `--purple` token + chat types
- ✅ Step 2 (PR #71) — `api.ts`: `postAdvisorChat`, `postLogout`, `AbortController`, `chatErrorMessage` PL mapper (400/401/429/502 → readable banner)
- ✅ Step 3 (PR #72) — backend `auth_logout` Lambda 256MB/5s, `Set-Cookie` z `Max-Age=0`, idempotent, 4 testy. Mirror `google_auth` Domain/Path
- ✅ Step 4 (PR #73) — `export_recipes_frontend.py` z DDB `PK=RECIPES` → `apps/web/src/recipes.json` (324KB / 139 recipes, deterministic re-run)
- ✅ Step 5a (PR #74) — `ChatMessage`/`ChatInput`/`RecipeCard`/`RecipeModal` + 270 linii CSS (chat thread, markdown styling, recipe modal z 4-color macro grid, ESC/overlay close)
- ✅ Step 5b (PR #75) — `ChatScreen` orchestracja (state, AbortController cleanup, scroll-to-bottom, optimistic user bubble, error banner z retry-friendly UX), tab nav `biometry`/`chat` w Dashboard, `App.tsx` `postLogout` integration
- ✅ Step 6 (PR #76) — vitest config + 5 smoke testów (happy, 429, 401, pending disable, recipe modal open+ESC) — 5/5 pass w 0.8s
- ✅ Smoke test live w przeglądarce — owner verified "działa elegancko"

**Sprint 7 metryki:**
- Bundle: JS 198 → 592 KB raw / 62.74 → 142.56 KB gzip (akceptowalne; code-split do follow-up jeśli first paint zacznie boleć)
- CSS: 2.50 → 8.64 KB / 0.88 → 2.11 KB gzip
- Test coverage: ChatScreen 5 smoke testów. Vitest infra ready dla future component tests.

**Sprint 7 known limitations / follow-upy:**
- **PDF hosting** odłożone (PDFy 16-29MB każdy, 127MB total) — RecipeCard click pokazuje pełne dane z DDB (ingredients/instructions) bez linka do source PDF. Sprint 7.5 mini-decyzja jeśli owner chce.
- **Bundle >500KB warning** Vite (recipes.json 324KB raw) — code-split (`React.lazy(ChatScreen)` + dynamic `recipes.json` import) post-MVP follow-up
- **Conversation history persistence cross-session** — backend ma 24h TTL DDB, ale brak `GET /api/advisor/chat/history` endpointu. Refresh strony = lose UI state. ADR-007 OPEN-2 (post-MVP)
- **Streaming SSE** odłożone — single JSON + spinner OK dla 4-12s response



**Sprint 6.1 PR1 — chat refactor multi-turn — DONE (PRy #59 + #61 + #62 + #63):**
- ✅ `POST /api/advisor/chat` multi-turn z 24h DDB TTL (`CHAT#{date}#{turn_idx:04d}`)
- ✅ Rate limit 30 user turn/user/dzień → 429 `daily_quota`
- ✅ System prompt 9 sekcji PL (26KB / ~10800 tokens — over Haiku 4.5 minimum 4096) z anti-prompt-injection block
- ✅ Prompt injection guard (closing-tag breakout + history-line spoofing) via Pydantic validator
- ✅ TOCTOU silent overwrite guard (`put_item_idempotent` z retry)
- ✅ `AdvisorBackendError(reason, status_code)` z fixed vocabulary — SDK body NIE leakuje do logów (ADR-007 OPEN-4)
- ✅ Anthropic prompt cache verified — call 1 `cache_creation=10803`; call 2 `cache_read=10803` (~80-90% cost savings)
- ✅ Cost-guard CloudWatch alarm 1.5M tokens/dzień + SNS email subscription (Gmail unsub'uje — backlog #17 Telegram bot)

**Sprint 6.2 PR2 — RAG seed + retrieval — DONE (PRy #65 + #66 + #67):**
- ✅ `seed_recipes.py` — 139 recipes parsed z 5 PDFów (pdfplumber, NIE Vision YAGNI), 70 wersji kobiet + 69 mężczyzn jako osobne sluga
- ✅ OpenAI text-embedding-3-small batch embed (~$0.0003 jednorazowo); FAISS IndexFlatIP (cosine via L2)
- ✅ S3 `recipes/faiss-index.bin` (834KB) + `recipes-metadata.json` (21KB)
- ✅ DDB `PK=RECIPES, SK=RECIPE#{meal_type}#{slug}` z full attrs (name, kcal, makro, ingredients, instructions, source)
- ✅ `rag.retrieve(query, k=5)` runtime z lazy cold-start init (S3 download FAISS + metadata, ~500ms cold start regression akceptowalne)
- ✅ Multi-block content array w Anthropic call: system prompt + `<retrieved_recipes>` block oba `cache_control: ephemeral` (~13956 tokens cached razem)
- ✅ Graceful degradation: `RAGUnavailableError` (S3/OpenAI/index missing) → handler 200 + `used_recipes=[]` + log warning
- ✅ Lambda zip raw 35MB compressed / 96MB uncompressed (50/250MB limits) — Layer NIE potrzebny
- ✅ IAM minimal: S3 `GetObject recipes/*` + SSM `openai/api_key` + DDB Query/GetItem (cross-PK; defense-in-code w `rag.py` literalne `PK=RECIPES`)
- ✅ Smoke test live verified: `used_recipes: Array(5)`, Haiku cytuje DOKŁADNIE name z biblioteki ("Bajgiel z jajkiem, awokado i halloumi"), `chat_turn_complete` log ma `retrieved_count: 5` + `retrieved_slugs: [...]`

**Wybrane bugfixes / lessons learned (chronologicznie):**
- PR #61 — bootstrap OIDC missing `iam:ListInstanceProfilesForRole` (AWS provider 5.x delete prereq)
- PR #62 — system_prompt 7KB → 26KB (Haiku 4.5 cache minimum 4096 tokens — pre-fix cache silently dropped)
- PR #63 — SNS topic + email subscription do cost-guard alarm (Gmail auto-unsubscribe'uje — backlog Telegram replacement)
- PR #66 — `terraform import` SSM `/bodysync/openai/api_key` (owner stworzył ręcznie pre-PR65, conflict)
- PR #67 — bump `openai==1.50.*` → `openai>=1.55,<2.0` (httpx 0.28 incompat: `TypeError: 'proxies' kwarg`)

**Spec źródła:** `docs/adr/ADR-007-chat-assistant-rag.md`, `docs/TODO.md` Sprint 6.1+6.2.

**Backlog post-Sprint 6+7+8+9 (do TaskList):**
- **#17 Telegram bot subscriber** — replacement Gmail email który auto-unsub'uje SNS notifications (cost-guard alarm musi dzwonić)
- **#18 Restore test_rag.py** — investigate faiss-cpu + pytest segfault na macOS aarch64 + Linux GHA. Granular RAG unit tests skipped
- **#19 Frontend bundle code-split** — `React.lazy(ChatScreen)` + dynamic `recipes.json` import. Aktualnie 611KB raw / 148.30KB gzip
- **#20 PDF hosting decision** — Sprint 7.5 mini-sprint jeśli owner chce link do source PDF z RecipeCard (R2/S3 public/CF Pages assets, 127MB)
- **#21 Conversation history GET endpoint** — chat history fetch z backend (24h TTL DDB już ma). Refresh page lose-state UX
- **#22 Aktywności tab — Strava integration** — Sprint 4 zaległy, frontend sidebar już ma placeholder z CTA
- **API GW per-second throttle** — burst attack z valid JWT może przebić 30/dzień quotę. CloudWatch alarm jako backstop działa
- **`requirements.txt` bez `--require-hashes`** — `pip-compile --generate-hashes` przed kolejnym sprintem z native deps

**5 OPEN questions z ADR-007 (post-MVP):** Strava/Sheets enrichment timing, conv_date forking, embedding refresh strategy, content logging policy (PII), frontend chat UI scope.

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

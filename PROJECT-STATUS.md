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
| Strava OAuth + webhook + fetcher (port wzorca ze sprawdzamszlak) | ✅ Sprint 4 shipped 2026-05-08/09 (PRy #91-#102) — OAuth start+callback z athlete-to-user mapping w SSM, webhook handler (handshake + idempotent events), DDB Streams `filter_criteria PK=EVENT#strava` → fetcher Lambda (token refresh, activity+streams, S3 raw), GET /api/activities, frontend Aktywności tab z Strava connect CTA + 10 ostatnich z `strava_backfill.py` |
| Google Sheets read (training plan) | ✅ Sprint 5 shipped 2026-05-09 (PRy #107/#112/#113/#116/#117/#119/#120/#121/#122/#123/#124) — `GET /api/plan` z service account JSON read-only, 15min DDB cache `PLAN#current` z stale fallback, frontend "Plan Treningowy" tab z parserem (split na Trening A/B/C/D + sekcje Rozgrzewka/Trening) + dropdown z weeks per group, advisor injekcja `<training_plan>` w prompt z STRICT no-guessing rule |
| Anthropic advisor (prompt cache, prompt injection guard) | ✅ Sprint 6.1 + 6.2 live (PRy #59/#62/#63/#65/#66/#67) + Sprint 5 PR #4 (#119) advisor injekcja training_plan + #126/#127 STRICT anti-halucynacja — `POST /api/advisor/chat` multi-turn z RAG retrieval (139 przepisów Lidla/Biedronki, k=5 cosine) + training_plan block z DDB cache, used_recipes populated, system prompt + retrieved_recipes + training_plan ephemerally cached |
| Recipe pipeline (PDF → DDB + FAISS) | ✅ Sprint 6.2 PR2 live (PR #65 + #67) — `seed_recipes.py` parsed 139 recipes z 5 PDFów; DDB `PK=RECIPES`; S3 `recipes/faiss-index.bin` (834KB) + `recipes-metadata.json` (21KB); embed cost ~$0.0003 |
| Frontend dashboard + chat UI | ✅ Sprint 7+8+9 shipped 2026-05-08 — sidebar 240px z 6 tabami (Dashboard/Aktywności/Ciało/Odżywianie/Przepisy AI/Ustawienia), tinted StatCardy z 11 SVG icons (HRV/sen/kroki/kcal/RHR/body fat/makro/waga), Sparkline + WeightChart, range toggle 1d/7d/30d, ProfileTargetsForm z PUT /api/profile/targets, multi-turn chat z RecipeCard+RecipeModal. 34 vitest. Live verified |
| Mobile UX (iPhone bottom nav, kcal_in today=0, dashboard symetria, NutritionDonut, Spalone kalorie) | ✅ shipped 2026-05-09 (PRy #109/#110/#114/#115/#128) — bottom navigation pattern dla iPhone 14/17 (Weronika), kcal_in/makro pokazują 0 dla dzisiaj jeśli HAE nie wysłał (zamiast wczoraj), NutritionDonut donut chart 1:1 prototype, Spalone kalorie = active+basal TDEE |
| Logo pack + preview mock mode | ✅ shipped 2026-05-09 (PRy #108/#118) — bodysync brand pack (favicon + sidebar header + login screen), `VITE_PREVIEW_MODE=true` env w CF Workers Builds → window.fetch override z mock data dla preview branch deployments |
| Plan Treningowy frontend tab (Sprint 5 PR #3 + follow-upy) | ✅ shipped 2026-05-09 (PRy #116/#117/#120-#124) — sidebar 7-y tab "Plan Treningowy", parser raw 2D rows → Training[] z sekcji Rozgrzewka+Trening, tabs po unique base names (Trening A/B/C), dropdown weeks per group (najnowszy default), STRICT no-guess advisor rule po halucynacji "wykonałeś Trening B zamiast C" |
| Sprint 11 prep (Telegram pipeline + advisor activities + clear chat) | ✅ shipped 2026-05-10/11 (PRy #130/#143/#144/#145/#146) — cost-guard alarm → Telegram (smoke verified ALARM 🚨 + OK ✅ delivery), advisor widzi `<recent_activities>` z Strava 7d w prompt, button "Wyczyść rozmowę" + DELETE /api/advisor/chat/history (idempotent, PK isolation), network error message proper handling |

## Open PRs

`gh pr list` — żadnych otwartych (5 PR-ów merged w sesji 2026-05-10 → 11).

## Aktywny sprint — żaden (Sprint 11 prep zamknięty 2026-05-11)

**Sesja 2026-05-10 → 11 (post-Sprint 10) — 5 PR-ów merged, Telegram pipeline verified end-to-end:**

- ✅ **PR #130** — `telegram_notifier` Lambda backend (170 LOC handler.py, stdlib `urllib` only, 11KB zip). SNS event → CloudWatch alarm payload → Telegram POST. HTML escape `<>&` w name/reason. Best-effort delivery (4xx/5xx/timeout → log warning, return ok). 9 testów + lazy-import handler fixture pattern (collection-time `boto3.client("ssm")` bez AWS_REGION env crashował CI).
- ✅ **PR #143** — Telegram IaC + drop email subscription. `module "telegram_notifier"` w `cloudwatch.tf` (256MB/5s, IAM SSM read na bot_token + chat_id), `aws_sns_topic_subscription cost_guard_telegram` (protocol=lambda), `aws_lambda_permission` dla SNS principal. Drop `cost_guard_owner_email` + `local.owner_email`. SSM placeholders `/bodysync/telegram/bot_token` (SecureString) + `/bodysync/telegram/chat_id` (String).
- ✅ **PR #144** — Advisor `<recent_activities>` injekcja. `load_recent_activities(user_id, today, days=7)` query `ACTIVITY#` + filter `start_date >= today-6d` + sort desc + cap 15. `RecentActivity` Pydantic (date, sport_type, name (≤80 chars), distance_km, duration_min, avg_hr, max_hr, kcal). Block `<recent_activities>` w `build_chat_messages` z `cache_control: ephemeral`, format 1-linia per activity `YYYY-MM-DD SportType "Name" Xkm/Ymin/HR avg Z (max M)/N kcal`. System prompt: nowa sekcja "DANE WEJŚCIOWE — `<recent_activities>`" + HR zones heuristic + anti-injection clause + 6-blok lista w forbidden tags. +13 testów. **Pre-req dla Sprint 11 Daily Brief.**
- ✅ **PR #145** — "Wyczyść rozmowę". Backend: `DELETE /api/advisor/chat/history` (`_history_handler.handle_delete_history`, JWT required, idempotent), `shared/dynamo.batch_delete` helper (boto3 batch_writer), `service.delete_chat_history(user_id, today)` z boundary Warsaw + PK isolation. IaC: nowa route + IAM `DeleteItem` + `BatchWriteItem` z LeadingKeys=USER#*, CORS `allow_methods` += DELETE. Frontend: button w `.chat-header` (visible gdy thread niepusty), `window.confirm` + DELETE call + `setMessages([])`. +5 pytest + 3 vitest. **Bug post-merge:** owner kliknął clear gdy Terraform apply jeszcze trwał (route nie istniał) → 404 bez CORS headers → fetch TypeError → "Nieoczekiwany błąd" message.
- ✅ **PR #146** — fix(web) hotfix dla post-#145 race. `request()` opakowuje `TypeError` jako `ApiError(-1, 'network')`, `chatErrorMessage` ma case `-1` → "Brak połączenia z serwerem — spróbuj za chwilę". +2 regression testy. Chroni też future scenariusze: DNS down, CORS regression, cold-start timeout.

**Telegram smoke test (2026-05-11 07:41-07:42 UTC) — pipeline LIVE:**
1. Owner: BotFather `/newbot` → `bodysync_123_bot` → token (46 chars) → `/start` w prywatnym chacie → chat_id=`1476210457`
2. SSM put-parameter × 2: bot_token (SecureString), chat_id (String)
3. CloudWatch `set-alarm-state ALARM` → Lambda invoke 386ms (cold start) + 388ms init → `telegram_sent status_code: 200` → 🚨 wiadomość w chacie ownera
4. CloudWatch `set-alarm-state OK` → warm Lambda ~30ms → ✅ recovery message

End-to-end pipeline: `CloudWatch alarm → SNS → Lambda → Telegram POST → chat`. Cost-guard alarm reaguje, Sprint 11 Daily Brief odblokowany (ten sam bot_token reusable).

**Audyt 2026-05-11 (auditor agent, post-sesja):**

3 najpilniejsze rzeczy (po dzisiejszych 5 PR):
1. **Extract `_post_handler.py`** z `advisor_chat/handler.py` (369 LOC, asymetria z `_history_handler.py` 113 LOC) → `@architect` + `@implementer`. Przed Sprint 11.
2. **`telegram_notifier` moduł do `main.tf`** lub split `cloudwatch.tf` (ADR-003 konwencja "Lambdas w main.tf") → `@aws-infra`. ~30 min.
3. **Frontend component tests** dla RecipeCard / ChatInput / RecipeModal / WeightChart → `@tester` + `@frontend-designer`.

Pozytywne sygnały z audytu: security clean (sekrety nigdy w git), IAM PK isolation defense-in-depth, 100% handler test coverage (14/14), anti-injection schema sync OK po PR #144 (regex i system prompt synced), `apps/web/src/api.ts` jeden helper `request()` → fix #146 dostał free coverage dla wszystkich endpointów.

Open questions z audytu (do decyzji przy następnej sesji):
- Czy import blocks w `main.tf:7-10` + `:16-19` można już usunąć (apply był OK po wszystkich sprintach)?
- `RECENT_ACTIVITIES_MAX=15` realny dla 7-day window (typowo 5-10/tydzień)?
- `ACTIVITY#` query bez SK range — wystarczy dla 2-user MVP, ale przy >100 activities/user cost rośnie (~5 RCU per chat turn). Multi-year retention plans?
- Sprint 11 `<recent_activities>` w Daily Brief: ten sam schema raw vs aggregate (7d totals + top 3)?

**Strategiczny backlog post-Sprint 9 (nocna analiza 2026-05-10):**
- 📊 [`docs/backlog-2026-05-10.md`](docs/backlog-2026-05-10.md) — master backlog z 45+ feature ideas, priorytetyzowanymi w 4 tier-y (Quick wins / Sprint candidates / Strategic / Parking lot), value/effort scoring
- 🔍 [`docs/audit-functional-2026-05-10.md`](docs/audit-functional-2026-05-10.md) — current state map per 7 domain (Auth/Biometry/Activities/Plan/Advisor/Profil/Mobile UX)
- 🌐 [`docs/research-competitive-2026-05-10.md`](docs/research-competitive-2026-05-10.md) — feature gaps vs Whoop/Oura/Strava Premium/MyFitnessPal/Hevy/MacroFactor/Apple Fitness, 10 kategorii, cross-cutting themes
- 🎨 [`docs/ux-gaps-2026-05-10.md`](docs/ux-gaps-2026-05-10.md) — friction + delight per tab dashboardu, 10 obszarów

**Rekomendowane następne 4 sprinty (z `backlog-2026-05-10.md`):**
- **Sprint 10 — "TDEE foundation + Insights"** (~12-16h) — A0 TDEE calculator (Mifflin-St Jeor, body profile wzrost/wiek/płeć/activity) + comparison vs target Odżywianie, chat history GET, tenant switcher, suggested prompts, smoothed weight EMA, today's workout hint
- **Sprint 11 — "Recovery Score + Daily Brief"** (~10-14h) — composite Recovery score Dashboard + cron 07:00 Telegram morning brief (reuse PR #130 infra)
- **Sprint 12 — "Workout logbook + Weekly recap"** (~12-16h) — pierwszy input UX surface + niedzielny narrative recap przez LLM
- **Sprint 13 — "Energy balance + Adaptive TDEE"** (~10-14h) — TDEE-aware undereating/overeating alerts (push Telegram gdy 7d kcal_in -500/+300 vs TDEE+treningi) + MacroFactor-style adaptive TDEE rekalkulacja co 14d z waga+kcal_in trend

**Strategiczne pytania dla owner'a** (per `backlog-2026-05-10.md` sekcja "Strategiczne decyzje"): formuła Recovery score, Telegram-only vs in-app push, logbook scope (minimal vs Hevy), per-meal logging, PWA inwestycja, couples-emphasis priority.

**Sprint 5 — Google Sheets training plan + advisor injekcja — DONE (11 PRy #107-#128 spread over 1 dzień, ~5h pracy):**
- ✅ PR #107 — `apps/api/handlers/plan/` service module: Google Sheets API readonly fetch z cred from SSM, jagged row padding, fixed-vocabulary errors (invalid_credentials_json/format, sheet_not_found_or_no_access, permission_denied, sheets_api_error), DDB cache load/save z 15min freshness check
- ✅ PR #112 (re-target main z #111 base bug) — `handler.py` GET /api/plan z JWT auth + cache-or-fetch flow + stale fallback (Google API down + cache → 200 stale fresh=False) + Terraform module plan + IAM `LeadingKeys USER#*` + 3 SSM placeholders z `lifecycle.ignore_changes`
- ✅ PR #113 — hotfix `terraform import` block dla `/bodysync/google/service_account_json` (owner stworzył ręcznie pre-PR #112, ParameterAlreadyExists)
- ✅ PR #116 — frontend Plan Treningowy tab: PlanScreen z 4 error states (not_configured/permission_denied/sheet_not_found/sheets_api_error friendly PL), parseErrorMessage fix dla `{"error": "string"}` shape (handler.py używa raw string)
- ✅ PR #117 — rename "Plan" → "Plan Treningowy" w sidebar + TAB_TITLES
- ✅ PR #119 — advisor RAG plan injection: `load_training_plan(user_id)` + `<training_plan>` block w prompt z `cache_control: ephemeral`, system_prompt.txt extended z anti-injection clause dla planu
- ✅ PR #120 — Plan tab Opcja 2 (trainings tabs): heurystyczny parser raw → Training[] z `parseTrainings`, secondary nav A/B/C/D, drop Link/Ból, drop empty cols
- ✅ PR #121 — skip duplicate header rows w środku bloku (trener powtarza header między rozgrzewką a głównym treningiem)
- ✅ PR #122 — sections (Rozgrzewka + Trening) + default newest tab + `Section` type w parser, `disambiguateNames` z #N suffix
- ✅ PR #123 — fix block z multiple Trening X (parser splituje "rozgrzewka A + Trening A + rozgrzewka B + Trening B" jak osobne tabs zamiast mergować)
- ✅ PR #124 — week dropdown per group: tabs po base name (Trening A | B | C), dropdown z weeks gdy >1 (najnowszy default), drop #N suffix

**Sprint 5 hot-fixes (post-deploy):**
- PR #125 — advisor 500: cross-handler import `from handlers.plan.schemas import CachedPlan` crashował Lambda runtime (build per-handler zip nie zawiera innych handlerów). Inline `CachedPlan` w `advisor_chat/schemas.py`.
- PR #126 → #127 (escalating strictness) — advisor halucynował "wykonałeś Trening B" gdy owner robił C. v1 (#126) decision tree z logbook detection — Haiku ignorowało, bo logbook entries są z różnych tygodni (brak timestampów). v2 (#127) STRICT: drop logbook detection, "ZAWSZE PYTAJ który trening" gdy user nie wskazał wprost.

**Sprint 5 metryki:**
- Backend: 1 nowy Lambda (plan), 28 testów (17 service + 11 handler) + 4 testy advisor injekcji
- Frontend: nowy tab + parser z 130 LOC + 30+ testów (planParser.test.ts + PlanScreen.test.tsx + biometry.test.ts updates)
- DDB single-table extensions: `PLAN#current` SK
- IaC: 1 module + 1 route + 3 SSM placeholders z `ignore_changes` (owner manualne wartości)
- 11 main PRs + 3 hot-fixów + 1 re-target = 15 wystawionych w 1 dniu

**Owner ręczne kroki podczas deploy:**
1. GCP Console: stwórz service account `bodysync-sheets-reader` + JSON key
2. SSM: `aws ssm put-parameter --name /bodysync/google/service_account_json --type SecureString --value file://sa-key.json --overwrite`
3. Google Sheets: Share → wpisz SA email jako Viewer
4. SSM: `/bodysync/tomek/training-sheet-id` (z URL Google Sheets) + `/bodysync/tomek/training-sheet-tab` (np. "Arkusz5")

**Mid-sprint UX fixy 2026-05-09 (poza Sprint 5):**
- PR #109/#110 — NutritionDonut + Aktywności (tydzień) + symetria boxów Dashboard overview (port 1:1 prototype)
- PR #114 — mobile UX bottom nav (iPhone 14/17 viewport, sidebar fixed bottom, content padding-bottom + safe-area-inset-bottom, ActivityRow stack, stat-grid 2-col na 390px+, section-header smaller)
- PR #115 — `valueForDate` helper, `TodayMetricStatCard` component → kcal_in/makro pokazują 0 dla dzisiaj jeśli HAE nie wysłał (zamiast wczorajszej wartości — mylące)
- PR #128 — `Spalone kalorie` = `sumSeries(kcal_active, kcal_basal)` Garmin/Apple TDEE, replace "Kcal aktywne" w Dashboard + Ciało

**Mid-sprint security 2026-05-09:**
- PR #104 — S3 bucket policy `Deny aws:SecureTransport=false` dla data + tf-state buckets (W5 hardening)
- PR #105 — API GW throttling default 50 req/s + advisor chat override 5 req/s (W3 hardening)
- PR #106 — athlete map conflict guard (W1 hardening, raise zamiast silent overwrite)
- PR #108 — bodysync logo pack integration (favicon + sidebar header + login screen)
- PR #118 — preview mock mode dla CF Workers Builds branch deployments (`VITE_PREVIEW_MODE=true` env z dashboard, dynamic-import preview-mock.ts override window.fetch dla `/api/*`)

**Sprint 4 — Strava integration — DONE (12 PRy #91-#102, ~1.5 dnia):**
- ✅ Step 1 (PR #91) — `shared/strava.py` Pydantic schemas (StravaTokens, StravaWebhookEvent, StravaActivity z `extra='ignore'` ~80 fieldów Strava); SSM placeholders (athlete-to-user, subscription_id)
- ✅ Step 2 (PR #92) — `strava_oauth_start` handler: JWT cookie auth → DDB CSRF state PK=`STRAVA_OAUTH_STATE#{state}` z TTL 10 min → 302 do strava.com/oauth/authorize z scope `read,activity:read_all`
- ✅ Step 3 (PR #93) — `strava_oauth_callback`: atomic state delete (single-use nonce) + httpx token exchange + tokens persist do per-user SSM SecureString + athlete→user map update; **fixed-vocabulary error reasons**, audit log `does_not_log_token_or_code`
- ✅ Step 4 (PR #94) — `strava_webhook` handler (GET handshake `hmac.compare_digest`, POST event idempotent PutItem `EVENT#strava`); Terraform 3 Lambda modules + 4 routes + IAM least-privilege
- ✅ Step 5 (PR #95) — `strava_fetcher` Lambda (DDB Streams trigger z `filter_criteria PK=EVENT#strava` — CRITICAL bo single-table) + token refresh + `fetch_activity` (404 deletion race) + `fetch_streams` best-effort + S3 raw + DDB ACTIVITY. Plus `activities_list` GET endpoint
- ✅ Step 6 (PR #96) — Frontend "Aktywności" tab: Strava connect CTA (orange brand gradient) → empty state, lub list 20 ostatnich z sport icons (33 emojis), distance/duration/pace/HR/kcal monospace, Polish relative dates ("Dziś"/"Wczoraj"/"5 dni temu"/"12 kwietnia")
- ✅ Step 7 (PR #99) — `strava_subscribe.py` CLI: `subscribe`/`unsubscribe`/`list` subcommands; jednorazowo po deploy zarejestrowuje webhook URL w Strava + verify_token + subscription_id w SSM
- ✅ Step 7.5 (PR #100) — `strava_backfill.py` CLI: po Authorize ingest 10 ostatnich activities (synthetic events `subscription_id=999999` → DDB Stream → fetcher) — UX bonus, owner widzi historię natychmiast
- ✅ Bonus #101 — RecentActivitiesPanel w DashboardOverview (top 3 + link "Wszystkie →" do tab Aktywności)
- ✅ Bonus #102 — timezone fix `api_read/service.py` UTC → `Europe/Warsaw` + frontend dynamic 1d label ("Dziś" / "Wczoraj (8 maja)" / "Najnowsze: X maja")

**Sprint 4 hot-fixes (po deploy):**
- PR #97 — `strava_oauth_start` requirements.txt missing pydantic (skeleton z Step 1 nie zaktualizowany w Step 2 → Runtime.ImportModuleError)
- PR #98 — strava_oauth_start missing PyJWT (verify_jwt path, defensive audit innych handlerów)

**Owner ręczne kroki podczas deploy:**
1. Skasował stary Strava app sprawdzamszlak, stworzył nowy "bodysync" z callback domain `api.bodysync.pl`
2. Wpisał `client_id` + `client_secret` do SSM (post Step 1 deploy)
3. Po Step 7 ship: `python scripts/strava_subscribe.py subscribe --force` (force bo stary sprawdzamszlak subscription nadal w Strava — `unsubscribe` automatycznie)
4. Po Step 7.5 ship: `python scripts/strava_backfill.py --user-id tomek --count 10` → 10 activities w DDB w ~5-30s

**Sprint 4 metryki:**
- Backend: 5 nowych Lambdas (oauth_start, oauth_callback, webhook, fetcher, activities_list) + 2 CLIs (subscribe, backfill)
- Frontend: tab Aktywności + RecentActivitiesPanel w DashboardOverview
- Tests: ~50 nowych (228 total, 6 skipped)
- DDB Streams enabled na main table (NEW_IMAGE) z `filter_criteria PK=EVENT#strava`



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

**Backlog post-Sprint 4+5+6+7+8+9 (do TaskList):**
- ~~**#17 Telegram bot subscriber**~~ ✅ DONE 2026-05-10/11 (PR #130 handler + #143 IaC; smoke test live verified end-to-end ALARM 🚨 + OK ✅ delivery)
- **#18 Restore test_rag.py** — investigate faiss-cpu + pytest segfault na macOS aarch64 + Linux GHA. Granular RAG unit tests skipped
- **#19 Frontend bundle code-split** — `React.lazy(ChatScreen)` + dynamic `recipes.json` import. Aktualnie ~624KB raw / ~152KB gzip (wzrost z 611KB po Sprint 5 + dropdown weeks + Spalone kalorie)
- **#20 PDF hosting decision** — Sprint 7.5 mini-sprint jeśli owner chce link do source PDF z RecipeCard (R2/S3 public/CF Pages assets, 127MB)
- **#21 Conversation history GET endpoint** — chat history fetch z backend (24h TTL DDB już ma). Refresh page lose-state UX
- ~~**#22 Aktywności tab — Strava integration**~~ ✅ DONE 2026-05-08/09 (Sprint 4)
- ~~**API GW per-second throttle**~~ ✅ DONE 2026-05-09 (PR #105 W3 hardening — 50 req/s default + 5 req/s advisor)
- **`requirements.txt` bez `--require-hashes`** — `pip-compile --generate-hashes` przed kolejnym sprintem z native deps
- **#23 Backend training_plan logbook timestamps** — gdy trener doda kolumnę z datą per ćwiczenie / refreshe owner manualne, advisor mógłby auto-detect "wykonany dziś" zamiast pytać. Aktualnie advisor STRICT zawsze pyta (PR #127). Future: backend preprocesuje training_plan → `<training_status>` block z heurystyką per training (`Trening A: 6/8 logbook recently filled, najnowszy`).

**5 OPEN questions z ADR-007 (post-MVP):** Strava/Sheets enrichment timing, conv_date forking, embedding refresh strategy, content logging policy (PII), frontend chat UI scope.

## Active backlog

- **Garmin Connect direct integration** — Apple Health → HAE → DDB pipeline serwuje kroki z **Garmin Connect Sync to Apple Health** który desync'uje (delay + miss). Owner zauważył live 2026-05-07 że steps z dziennego export'u są niższe niż realne. Plan: bezpośredni połączenie do Garmin Connect (`python-garminconnect` lib lub Garmin Connect IQ Web Services). Storage Garmin email/password w SSM SecureString per user (Garmin nie ma proper OAuth dla konsumenta), refresh tokenów. Zakres: steps + active calories (jako alternatywa dla HAE/Apple Health ścieżki dla tych metryk). Activity tracking nadal przez Strava (Sprint 4). Osobny sprint, prawdopodobnie po Sprint 4 (Strava) jako **Sprint 4.5 — Garmin Connect**.
- **Sleep historical backfill** — sleep rows dla 2026-05-01..05 (sprzed PR #46) mają `asleep=0` mimo że HAE wysyła `core+rem+deep`. Fallback `asleep = core+rem+deep` z PR #46 działa tylko przy zapisie. Backfill: jednorazowy script `scripts/recompute_sleep.py` — query DDB sleep rows z `asleep=0 AND inBed>0`, recompute, update. Niski priorytet — zacznie się samo poprawiać po HAE re-export historycznych dni.
- **`syncbody` → `bodysync` rename (destructive)** — bootstrap state ma legacy literówkę: `Project=syncbody` tag, `syncbody-tfstate-{account_id}` bucket, `syncbody-tflock` DDB table, `syncbody-github-actions` IAM role. Rename = IAM role DELETE+CREATE (nowa ARN, GitHub variable `AWS_ROLE_ARN` reset) + bucket/table rename = state file move. Osobny PR z świadomą destrukcją. Zostawiamy "syncbody" do tej akcji.
- **Layout decision dla Step 2** — bootstrap obecnie zajmuje `infrastructure/terraform/`. Główny workspace nie może tam siedzieć (różne backendy). Decyzja: przenieść bootstrap do `infrastructure/terraform/bootstrap/` (preferowane per ADR-003) lub stworzyć główny w `infrastructure/terraform-app/`. Ruszanie state file = manualnie + `terraform init -migrate-state`.
- **Provider binaries w `infrastructure/terraform/hashicorp/`** — pusty katalog, nic w git ✓ (alarm fałszywy, do usunięcia z backlogu)
- **Open follow-upy z audytu 2026-05-06** — HAE auth scheme, OIDC tightening (rola IAM ma `*` z ABAC tagiem — do zacieśnienia), naming policy ADR (jeśli potrzebne)
- **Security audit follow-upy (Notes z 2026-05-07 + 2026-05-09 sweep):**
  - SSM cache bez TTL (rotacja secret = cold restart Lambdy) → ADR jeśli zaczniemy rotować runtime
  - ~~S3 deny-non-TLS bucket policy~~ ✅ DONE 2026-05-09 (PR #104 W5)
  - DDB CMK zamiast aws-managed key (compliance trigger)
  - `requirements.txt` bez `--require-hashes` — `pip-compile --generate-hashes` przed kolejnym sprintem z native deps
  - Logger `reason=str(e)` whitelistuj typy (zamiast surowego google-auth message) jeśli library zacznie loggować raw token
  - CSP `style-src 'unsafe-inline'` → migracja na nonce-based gdy dashboard scaffold (post-MVP)
  - ~~API GW per-second throttle~~ ✅ DONE 2026-05-09 (PR #105 W3)
  - ~~Athlete map silent overwrite race~~ ✅ DONE 2026-05-09 (PR #106 W1 — raise zamiast overwrite gdy conflict)

## Architectural commitments (do zapisania w ADRs)

- **ADR-001 stack baseline** ✅ shipped (`docs/adr/ADR-001-stack-baseline.md`)
- **ADR-002 lambda packaging** ✅ shipped (`docs/adr/ADR-002-lambda-packaging.md`)
- **ADR-003 terraform conventions** ✅ shipped (`docs/adr/ADR-003-terraform-conventions.md`)
- **ADR-004 (TBD)** — multi-user model: PK isolation `USER#{id}` + GSI on entity type for cross-user admin queries.
- **ADR-005 (TBD)** — sekrety: SSM SecureString hierarchy, rotacja, IAM scoping.
- **ADR-006 advisor on-demand vs cron** ⚠️ Superseded by ADR-007 (`docs/adr/ADR-006-advisor-on-demand-vs-cron.md`) — single-shot dinner endpoint odrzucony po user feedback 2026-05-07 (chat + RAG zamiast button "kolacja"). PR #50 infra zachowane jako baseline refactoru.
- **ADR-007 chat assistant + RAG** ✅ shipped (`docs/adr/ADR-007-chat-assistant-rag.md`) — primary advisor feature: `POST /api/advisor/chat` (multi-turn, 24h TTL DDB history, RAG retrieval z FAISS+S3+OpenAI embeddings, recipes Lidla/Biedronki ~150-200 entries w DDB `RECIPES` PK, Anthropic Haiku 4.5 prompt cached, free-form polski text response). Supersedes ADR-006. Subsumes Sprint 8 (recipe pipeline merged into Sprint 6).

## SSM parameters

| name | type | who writes | who reads | status |
|---|---|---|---|---|
| `/bodysync/anthropic/api_key` | SecureString | owner (CLI) | advisor Lambda + seed_recipes.py | ✅ live |
| `/bodysync/openai/api_key` | SecureString | owner (CLI) | advisor Lambda (per-turn embed query) + seed_recipes.py (batch embed) | ✅ live (per ADR-007) |
| `/bodysync/strava/client_id` | String | owner (CLI) | api Lambda (oauth + fetcher) | ✅ live |
| `/bodysync/strava/client_secret` | SecureString | owner (CLI) | api Lambda | ✅ live |
| `/bodysync/strava/{user_id}/tokens` | SecureString | api Lambda (oauth callback + fetcher refresh) | fetcher Lambda | ✅ live |
| `/bodysync/strava/verify_token` | SecureString | strava:subscribe CLI | api Lambda (webhook handshake) | ✅ live |
| `/bodysync/strava/athlete-to-user` | String | api Lambda (oauth callback) | strava_webhook + fetcher | ✅ live |
| `/bodysync/strava/subscription_id` | String | strava:subscribe CLI | strava_webhook (verify event) | ✅ live |
| `/bodysync/health-auto-export/webhook_secret_{user_id}` | SecureString | owner (CLI) | health_webhook (Bearer constant-time compare) | ✅ live (tomek + weronika) |
| `/bodysync/google/service_account_json` | SecureString | owner (CLI) | plan Lambda (Sheets read) | ✅ live (Sprint 5) |
| `/bodysync/{user_id}/training-sheet-id` | String | owner (CLI) | plan Lambda | ✅ live (Sprint 5) |
| `/bodysync/{user_id}/training-sheet-tab` | String | owner (CLI) | plan Lambda (np. "Arkusz5") | ✅ live (Sprint 5) |
| `/bodysync/google/oauth_client_id` | String | owner (CLI) | google_auth (audience verify) | ✅ live |
| `/bodysync/auth/allowed_emails` | String (JSON list) | owner (CLI) | google_auth (allowlist 2 emaili) | ✅ live |
| `/bodysync/jwt/signing_secret` | SecureString | owner (CLI) | api Lambda (mint + verify) | ✅ live |
| `/bodysync/telegram/bot_token` | SecureString | owner (CLI) | telegram_notifier Lambda (SNS subscriber) | ✅ live (2026-05-11) |
| `/bodysync/telegram/chat_id` | String | owner (CLI) | telegram_notifier Lambda | ✅ live (`1476210457` Tomek private chat) |

## Operational items still open

- TFC migration to S3+DDB — N/A (ten projekt od początku S3+DDB)
- Provider binaries w `infrastructure/terraform/hashicorp/` — nie commit-uj, dodaj `.terraform/` i `hashicorp/` do `.gitignore` jeśli brak
- Health Auto Export — owner musi wpisać webhook URL + secret na telefonie (manual, post-deploy) ✅ tomek + weronika done
- Strava webhook subskrypcja — manual `python scripts/strava_subscribe.py subscribe` po deployu ✅ done
- Plan Treningowy SSM (Google service account JSON + sheet-id + sheet-tab) ✅ done 2026-05-09
- Cloudflare Workers Builds env var `VITE_PREVIEW_MODE=true` dla Preview environment (po PR #118 — daje preview branch URL z mock data zamiast 'Failed to fetch')

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

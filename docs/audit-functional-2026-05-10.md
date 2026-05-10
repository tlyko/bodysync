# Audyt funkcjonalny bodysync.pl — 2026-05-09

## Auth

**Co działa:** Google OAuth2 sign-in (`POST /api/auth/google`) z weryfikacją `id_token` przez audience `/bodysync/google/oauth_client_id`, allowlist 2 emaili z SSM `/bodysync/auth/allowed_emails`. Mintowanie JWT (HS256, 30d TTL) podpisanego sekretem z `/bodysync/jwt/signing_secret`, ustawianego w cookie HttpOnly+Secure+SameSite=Lax. Logout (`POST /api/auth/logout`) przez Lambdę `auth_logout` z `Set-Cookie: Max-Age=0` (idempotent, mirror Domain/Path z `google_auth`). Każdy chroniony handler waliduje JWT z cookie i wyciąga `user_id` (`tomek` / `weronika`). Frontend `LoginScreen.tsx` pokazuje brand + Google sign-in button.

**Otwarte follow-upy:** SSM cache bez TTL — rotacja JWT signing secret wymaga cold restart Lambd (Active backlog, Security audit follow-upy). CSP `style-src 'unsafe-inline'` migracja na nonce-based post-MVP. OIDC trust policy IAM rola ma `*` z ABAC tagiem do zacieśnienia.

**Test coverage:** `google_auth` + `auth_logout` mają testy (4 dla logout, więcej dla google_auth z mock SSM). Brak E2E auth flow w przeglądarce (vitest tylko unit).

## Biometry

**Co działa:** `POST /health/webhook?user_id={id}` — Health Auto Export Bearer-auth (`hmac.compare_digest` przeciw `/bodysync/health-auto-export/webhook_secret_{user_id}`), idempotency keys, raw payload do S3, normalizacja przez 13 mapperów (HRV, sen, kroki, kcal_active, kcal_basal, RHR, body_fat, waga, makro carbs/protein/fat, kcal_in, BPM). Dane do DDB jako `BIOMETRY#{date}#{metric}`. `GET /api/biometry?range=30d` zwraca 30d, frontend slice'uje per range toggle (Dziś/7d/30d). Frontend Dashboard tab `Ciało` (waga + body_fat + RHR + sen + HRV z Sparkline + WeightChart 30d), `Odżywianie` (kcal_in + makro NutritionDonut + makro StatCardy), Dashboard overview 4 stats + Recovery 2x2. `valueForDate` helper + `TodayMetricStatCard` — kcal_in/makro pokazują 0 dla dzisiaj jeśli HAE nie wysłał (PR #115). `Spalone kalorie` = kcal_active + kcal_basal (TDEE) per PR #128.

**Otwarte follow-upy:** **Sleep historical backfill** (Active backlog) — sleep rows 2026-05-01..05 mają `asleep=0`. **Garmin Connect direct integration** (Sprint 4.5) — Garmin → HAE → Apple Health desync'uje steps. SSM webhook secret cache bez rotacji.

**Test coverage:** 13 mapperów ma testy + handler tests. Frontend `biometry.ts` 13+ testów (buildSeries, latestValue, trendPct), 11 dashboard component testów. Gap: brak integracyjnego E2E z prawdziwym HAE payloadem w GHA.

## Activities

**Co działa:** Pełny Strava OAuth flow — `GET /api/strava/oauth/start` (CSRF state w DDB z 10min TTL) → 302 do Strava → `GET /api/strava/oauth/callback` (atomic state delete, token exchange, persist do per-user SSM `tokens` + `athlete-to-user` map). Webhook handler (`POST /strava/webhook`) z `hmac.compare_digest` handshake i idempotent `EVENT#strava` items (TTL 7d). DDB Streams trigger z `filter_criteria PK=EVENT#strava` → `strava_fetcher` Lambda (token refresh, `fetch_activity` z 404 deletion race, `fetch_streams` best-effort, S3 raw, DDB `ACTIVITY#{strava_id}`). `GET /api/activities` zwraca posortowane top-N. CLIs: `strava_subscribe.py` (subscribe/unsubscribe/list), `strava_backfill.py` (10 ostatnich przez synthetic events). Frontend tab `Aktywności` z connect CTA (orange brand gradient), 33 sport emoji icons, distance/duration/pace/HR/kcal monospace, polski relative dates ("Dziś"/"Wczoraj"/"5 dni temu"). `RecentActivitiesPanel` w DashboardOverview (top 3 + link "Wszystkie →"). Athlete map conflict guard (PR #106 — raise zamiast silent overwrite).

**Otwarte follow-upy:** Aktywności tab nie ma per-activity detail view (streams JSON w S3 nieskonsumowane przez UI). Brak retry queue dla failed fetches (DLQ na DDB Streams Lambda warto zmierzyć).

**Test coverage:** ~50 nowych testów w Sprint 4 (228 total, 6 skipped). OAuth + webhook + fetcher pokryte. Gap: brak testów `strava_backfill.py` CLI synthetic events flow E2E.

## Plan Treningowy

**Co działa:** `GET /api/plan` — Google Sheets API readonly z service account (`/bodysync/google/service_account_json` + `/bodysync/{user_id}/training-sheet-id` + `/bodysync/{user_id}/training-sheet-tab`). 15min DDB cache (`PLAN#current`) z stale fallback (Sheets API down + cache → 200 stale fresh=False). Fixed-vocabulary error reasons (invalid_credentials_json/format, sheet_not_found_or_no_access, permission_denied, sheets_api_error). Frontend `PlanScreen.tsx` z parserem (`planParser.ts` — 130 LOC heurystyczny: skip duplicate header rows, split na Trening A/B/C/D z sekcjami Rozgrzewka+Trening, `disambiguateNames` z #N suffix). Tabs A/B/C + dropdown weeks per group (najnowszy default, drop #N suffix). 4 friendly PL error states. Sidebar 7-y tab "Plan Treningowy" (PR #117 rename z "Plan").

**Otwarte follow-upy:** **#23 Backend training_plan logbook timestamps** (Active backlog) — gdy trener doda kolumnę z datą, advisor mógłby auto-detect "wykonany dziś" zamiast STRICT pytać.

**Test coverage:** 28 backend testów (17 service + 11 handler) + 30+ frontend (planParser.test.ts + PlanScreen.test.tsx). Solidnie pokryte.

## Advisor / Chat

**Co działa:** `POST /api/advisor/chat` — multi-turn z 24h DDB TTL (`CHAT#{date}#{turn_idx:04d}`), rate limit 30 turn/user/dzień (429 `daily_quota`). Anthropic Haiku 4.5 (`claude-haiku-4-5-20251001`) z prompt cache: system prompt 26KB (9 sekcji PL, anti-prompt-injection block) + `<retrieved_recipes>` block + `<training_plan>` block — wszystkie `cache_control: ephemeral` (~80-90% cost savings, verified `cache_creation` → `cache_read`). RAG: 139 przepisów Lidla/Biedronki w DDB `PK=RECIPES`, FAISS IndexFlatIP w S3 `recipes/faiss-index.bin` (834KB) + metadata.json (21KB), OpenAI text-embedding-3-small dla query (k=5 cosine), graceful degradation (`RAGUnavailableError` → 200 + `used_recipes=[]`). Training plan injection (PR #119) z DDB cache `PLAN#current` — STRICT no-guessing rule (PR #127, "ZAWSZE PYTAJ który trening"). Frontend `ChatScreen.tsx` orchestracja (AbortController, scroll-to-bottom, optimistic user bubble, error banner z PL mapper 400/401/429/502), `ChatMessage` z react-markdown+remark-gfm, `RecipeCard` + `RecipeModal` (4-color macro grid, ESC/overlay close). 139 recipes w `apps/web/src/recipes.json` (324KB) eksportowane przez `export_recipes_frontend.py`. Cost-guard CloudWatch alarm 1.5M tokens/dzień + SNS email.

**Otwarte follow-upy:** **#17 Telegram bot** (Gmail auto-unsub'uje SNS), **#21 Conversation history GET endpoint** (refresh strony lose state, 24h TTL DDB jest), **#20 PDF hosting** (RecipeCard bez linka do source PDF), **#19 frontend bundle code-split** (~624KB raw / 152KB gzip), **streaming SSE** odłożone.

**Test coverage:** Sprint 6 + 7 testy advisor service + 5 smoke ChatScreen testów. **Gap krytyczny: #18 `test_rag.py` skipped** — faiss-cpu + pytest segfault na macOS aarch64 + Linux GHA, granular RAG unit tests off.

## Profil

**Co działa:** `GET + PUT /api/profile/targets` — JWT auth + Pydantic walidacja + DDB merge (PR #85). Defaults zsynchronizowane z `advisor_chat/service.py` (kcal 2000, protein 130, fat 70, carbs 200) — chat i UI widzą ten sam fallback gdy owner jeszcze nie wpisał. Frontend `ProfileTargetsForm.tsx` (4 inputy kcal/protein/fat/carbs + banner is_default + PL hints dietetyczne). CORS PUT method fix (PR #87 — `cors_allow_methods` default w api-gateway module rozszerzony o PUT). Tab `Ustawienia` w sidebarze.

**Otwarte follow-upy:** Brak per-day targets (target jest globalny per user, nie per-date). Brak edycji weight goal / activity level / TDEE override (advisor liczy z biometrii + targets, ale nie ma "weight loss / maintain / gain" toggle).

**Test coverage:** 10 backend testów + 5 frontend testów. OK na obecny zakres.

## Operacje / Mobile UX

**Co działa:** **iPhone bottom navigation** (PR #114) — sidebar fixed bottom dla viewport <768px, content padding-bottom + safe-area-inset-bottom, ActivityRow stack, stat-grid 2-col na 390px+ (Weronika iPhone 14/17 verified). **Preview mock mode** (PR #118) — `VITE_PREVIEW_MODE=true` env w Cloudflare Workers Builds → dynamic-import `preview-mock.ts` override `window.fetch` dla `/api/*` z mock data dla preview branch deployments. **Brand pack** (PR #108) — bodysync favicon + sidebar header + login screen logo. **Sidebar 240px** z 7 tabami (Dashboard / Aktywności / Ciało / Odżywianie / Plan Treningowy / Przepisy AI / Ustawienia). **Telegram notifier** (handler `telegram_notifier/` — backlog #17 in-progress; ma replace SNS email który Gmail auto-unsub'uje dla cost-guard alarm). Cloudflare Pages auto-deploy z `main`, GHA OIDC role assumption (no long-lived keys).

**Otwarte follow-upy:** **#17 Telegram bot subscriber** (in-progress jako handler `telegram_notifier/`, status do potwierdzenia w PR #130). **`syncbody` → `bodysync` rename** (Active backlog, destructive) — bootstrap state ma legacy literówkę, IAM role DELETE+CREATE wymagane. **DDB CMK zamiast aws-managed key** (compliance trigger). **`requirements.txt` bez `--require-hashes`**.

**Test coverage:** Mobile UX zweryfikowany manualnie na urządzeniu (Weronika iPhone). Brak Playwright/E2E na różne viewporty. `telegram_notifier` coverage do potwierdzenia per stan PR #130.

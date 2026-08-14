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
| Waitlist landing wariant A | ✅ shipped 2026-05-12 (PRy #159/#160/#161/#162/#163) — POST /api/waitlist (no-auth, honeypot+RODO consent), Coming soon section w LoginScreen z gradient hero, privacy.html (RODO PL), DemoGallery z 4 mock screens (dashboard/chat/plan/cialo), fix mock ref personal "Anita" + rename "Odśwież z arkusza" → "Zsynchronizuj plan" |
| Dashboard Trendy (bar charts + hover tooltips) | ✅ shipped 2026-05-12/13 (PRy #164/#165/#166/#167/#168) — sekcja "Trendy" pełnej szerokości pod overview-grid, 3 stacked bar charts (Kalorie spożyte / Spalone kalorie / Kroki — kolejność po PR #173 swap), MetricChart `<rect>` per data point z gradient, ResizeObserver pattern dla typografii w obu chartach (MetricChart + WeightChart), hover state z solid bar + custom tooltip nad barem; WeightChart hover dots (raw green + EMA cyan) + pionowa linia + 3-line tooltip |
| Bilans kaloryczny dziś + sparkline 7d | ✅ shipped 2026-05-13 (PR #174) — KcalBalanceCard na Dashboard overview między grid a Trendami, today's saldo `kcal_in - (kcal_active + kcal_basal)` z +/− prefix, status DEFICYT/NADWYŻKA/BILANS (threshold ±100), breakdown row Spożyte/Spalone, 7-day mini-sparkline z per-day color |
| Manual body measurements | ✅ shipped 2026-05-14 (PR #176) — POST /api/measurements (JWT, Pydantic v2, model_validator wymaga ≥1 metric), 5 optional `*_cm` fields (waist/hips/chest/biceps/thigh), DDB SK `BIOMETRY#{date}#{metric}#manual` (suffix disambiguates z HAE), BodyMeasurementsCard w Ciało tab z 5 inputs + placeholdery latest + 5 mini-charts 30d, IaC module 256MB/5s + IAM `LeadingKeys=USER#*` |
| Asystent AI rename + non-food RAG skip | ✅ shipped 2026-05-12 (PR #169) — tab "Przepisy AI" → "Asystent AI" (SidebarNav + TAB_TITLES); backend `is_food_related(message)` ~50 PL keywords z strip diacritics, handler gates RAG retrieval gdy user pyta o wagę/trening → `used_recipes=[]` + log `rag_skipped_non_food_query`. Oszczędność embed cost + cleaner UX |
| Recent activities 3 → 5 + Trend swap + HRV drop + Jakość snu | ✅ shipped 2026-05-14/15 (PRy #173/#175/#177/#178) — Trendy reorder (in/spalone/kroki), Dashboard pokazuje 5 ostatnich aktywności, HRV drop z UI (Garmin nie wysyła do AH, 0 rows w DDB), nowy MiniStat "Jakość snu" `(deep+rem)/asleep × 100%` w Recovery 2×2 panel |
| HAE webhook scaling (Weronika onboarding) | ✅ shipped 2026-05-14 (PR #170) — bump memory 512MB → 1024MB i timeout 10s → 29s. Powód: Weronika initial export timeout'ował na 10s nawet dla `Date Range: Last 1 day`. 1024MB ≈ 2× vCPU (Lambda CPU proporcjonalna do memory), 29s = max API GW HTTP integration timeout |
| Strava OAuth mobile experiment (revert) | ⚠️ tested + reverted 2026-05-14 (PRy #171 → #172) — próbowaliśmy `/oauth/mobile/authorize` żeby otworzyć Strava app native na iPhone. Live test: Strava app rzuca "error" zaraz po Authorize → `/oauth/mobile/authorize` deprecated dla third-party developers (tylko Strava-owned partner apps). Revert do standard `/oauth/authorize` browser flow (iOS i tak pokazuje banner "Open in Strava" jeśli zalogowany) |
| Serwer MCP (custom connector dla Claude) | ✅ shipped 2026-08-14 (7 PRy #218-#224) — `https://api.bodysync.pl/mcp`, surowy JSON-RPC bez pydantica (881 ms cold / 2 ms warm), własny serwer OAuth 2.0 z DCR reużywający cookie `bodysync_session`, 4 narzędzia read-only (skład ciała / metryki dzienne / trendy / treningi siłowe), IAM `LeadingKeys` rozdzielony na odczyt `USER#*` i zapis `MCP_*`. Szczegóły w [ADR-010](docs/adr/ADR-010-mcp-server.md) i sekcji "Aktywny sprint" |
| Audit-driven sprint (frontend P0 + security P1 + tech debt P1) | ✅ shipped 2026-05-16/17 (14 PRy #180-#194) — szczegóły w sekcji "Aktywny sprint" niżej. Audyt 2026-05-16 ([`docs/audit-2026-05-16.md`](docs/audit-2026-05-16.md)) → 3 wyspecjalizowane agenty (security/frontend-designer/auditor) → 14-PR egzekucja. Bundle gzip 167→88 KB (-47%), 4 nowe security guards (nonce/Strava JWT/IAM deny/CSRF), -209 LOC duplikacji w handlerach, frontend CI gating, DDB SK range optimization |

## Open PRs

`gh pr list` — **brak otwartych PR**. Ostatni zmergowany: PR #224 (base64 body hotfix MCP).

## Aktywny sprint

**Sesja 2026-08-14 — 7 PR-ów merged (#218-#224), serwer MCP dla danych zdrowotnych:**

Cel: wystawić dane bodysync jako custom connector w Claude, żeby model czytał je bezpośrednio w rozmowie. Tylko odczyt. Wykonane 1 step = 1 PR per memory `feedback_pr_workflow.md`.

| PR | Zakres |
|---|---|
| #218 | [ADR-010](docs/adr/ADR-010-mcp-server.md) — cztery decyzje poparte pomiarem |
| #219 | Refaktor: agregacja biometrii → `shared/biometry.py` |
| #220 | Rdzeń MCP: JSON-RPC + 4 narzędzia + testy zgodności |
| #221 | Serwer autoryzacji OAuth 2.0 z DCR |
| #222 | Terraform: Lambda 1024 MB, 7 tras, IAM least-privilege |
| #223 | Fix: import istniejącego sekretu SSM do stanu |
| #224 | Hotfix: dekodowanie body base64 z API Gateway |

### Decyzje i ich uzasadnienie (pomiary, nie szacunki)

**Surowy JSON-RPC zamiast FastMCP.** Zmierzone na naszym koncie: `pydantic` kosztuje ~490 ms cold startu (`activities-list` 13.9 MB → 684 ms vs `api-read` 16.3 MB → 1177 ms), a FastMCP go wymusza. Init nie skaluje się z megabajtami — 16.3→36.6 MB to tylko +260 ms. Na API Gateway nie ma response streamingu, więc `stateless_http` + `json_response` i tak wyłączają główną przewagę FastMCP. Bundle 13.9 MB zamiast 22 MB.

**Zmierzony cold start produkcyjny: 881 ms** (predykcja w ADR mówiła ~700 ms — poprawione, patrz ADR-010). Warm: **2 ms**. Pamięć: 82 MB z 1024 MB — płacimy za vCPU, nie RAM.

**OAuth 2.0 DCR zamiast sekretu w URL.** Pierwotna propozycja (sekret w ścieżce) była błędna — spec autoryzacji MCP zabrania tokenów w URL. Zweryfikowane w UI Claude: dialog `Add custom connector` ma pod Advanced settings wyłącznie OAuth Client ID i Secret, **żadnej sekcji Request headers**, więc `static_headers` (beta) odpada. `/authorize` sprawdza istniejące cookie `bodysync_session` → reużywa Google OAuth i allowlistę 2 maili, zero drugiego systemu tożsamości.

**Zakres: 4 narzędzia, bez Stravy.** Scan tabeli potwierdził **zero wierszy `hrv` i `body_battery`** — Garmin nie wysyła ich do Apple Health (spójne z PR #177). Strava wycięta, bo owner ma osobny Strava MCP; wartością bodysync jest złączenie treningu siłowego ze składem ciała, nie surowe streamy.

### Co jest live

```
POST /mcp                                     JSON-RPC, wymaga Bearer
GET  /.well-known/oauth-protected-resource    RFC 9728
GET  /.well-known/oauth-authorization-server  RFC 8414
POST /mcp/register                            RFC 7591 DCR
GET/POST /mcp/authorize                       ekran zgody
POST /mcp/token                               kod / refresh
```

Zweryfikowane curlem: discovery zwraca 200, `POST /mcp` bez tokenu zwraca 401 z poprawnym `WWW-Authenticate`, allowlista `redirect_uri` odrzuca obce hosty. **Pełny flow konektora end-to-end nie został jeszcze potwierdzony po hotfixie #224** — do sprawdzenia przy następnym podejściu.

### Dwa błędy z tej sesji warte zapamiętania

**Osierocony lock Terraforma blokował CI od 8 czerwca** — dwa miesiące. `terraform.tfstate.tflock`, `OperationTypePlan`, z przerwanego runa. Dependabot PR z 27 lipca failował tak samo i nikt nie zauważył. Usunięty ręcznie po weryfikacji, że żaden run nie jest aktywny. **To argument za odłożonym z audytu alarmem na czerwony workflow.**

**API Gateway HTTP v2 koduje `application/x-www-form-urlencoded` w base64**, a `application/json` przekazuje wprost. Handler czytał `event["body"]` bez sprawdzania `isBase64Encoded`, więc DCR (JSON) działał, a formularz zgody po cichu parsował się do pustego dicta → `brak request_token` po kliknięciu „Zezwalam". Testy tego nie złapały, bo fixture budował body jako czysty `urlencode` — czyli tak, jak wygodnie, a nie jak realnie przysyła API Gateway.

### Metryki sesji

- **Backend testów**: 468 → **550 pass** (+82)
- **Nowe moduły**: `shared/biometry.py`, `handlers/mcp/` (7 plików)
- **Nowy bundle Lambdy**: `mcp.zip` 13.97 MB, 1024 MB pamięci
- **DDB extensions**: `MCP_CLIENT#*`, `MCP_CODE#*`, `MCP_REFRESH#*` (wszystkie z TTL)
- **SSM**: `/bodysync/mcp/token_signing_secret` — świadomie osobny od `jwt/signing_secret`
- **Nowa zależność dev**: `mcp` w `[project.optional-dependencies].dev` (testy zgodności, nigdy w bundlu)

### Do dokończenia

- Potwierdzić pełny flow konektora po hotfixie #224 (dodać connector → „Zezwalam" → wywołanie narzędzia)
- README z instrukcją podłączenia konektora
- Alarm na czerwony workflow na `main` (patrz błąd z lockiem wyżej)
- Rozważyć eksperyment 512 MB vs 1024 MB dla Lambdy MCP — użycie pamięci to 82 MB, więc 1024 MB kupujemy wyłącznie dla vCPU

---

**Poprzednia sesja 2026-05-16 → 17 — 14 PR-ów merged (#180-#194), audit-driven sprint (frontend P0 + security P1 + tech debt P1):**

Wykonana po audycie 2026-05-16 ([`docs/audit-2026-05-16.md`](docs/audit-2026-05-16.md)) trzech wyspecjalizowanych agentów (security / frontend-designer / auditor — równoległe wywołanie). Audyt zidentyfikował zero P0 critical security ale liczne P0 frontend (fonty nieładujące się, mobile UX bugs) + 4 P1 security + 4 P1 dług techniczny. Sprint wykonany sekwencyjnie 1 step = 1 PR per memory `feedback_pr_workflow.md`.

### Sprint #1 — frontend P0 visible polish (PRy #180-#185)

- ✅ **PR #180** — self-hosted Inter + JetBrains Mono (subset Latin Extended). `index.css` referował fonty w 30+ miejscach ale brak `@font-face` → wszystko leciało na system fallback (`ui-monospace`). 4 woff2 (~80KB raw / ~30KB gzip) w `apps/web/public/fonts/`, preload weight 600/700 dla heading bez FOUT. CSP `font-src 'self'` bez zmian.
- ✅ **PR #181** — `100vh` → `100dvh` w 6 miejscach. iOS Safari `100vh` ≠ visible viewport (URL bar collapses/expands); chat-screen overflowował pod bottom nav. Browser support 96%+ (Safari 15.4+ / Chrome 108+ / Firefox 101+).
- ✅ **PR #182** — touch tooltipy w MetricChart + WeightChart. Dotąd tylko `onMouseEnter` — iOS Safari emulował hover dopiero za 2-im tap. Dodane `onTouchStart` (z `preventDefault` blokującym syntetyczne mouse events) + global `touchstart` listener dla tap-outside dismiss. +2 testy. Desktop hover bez zmian.
- ✅ **PR #183** — sidebar `position: sticky` w grid item → `position: fixed`. Znany W3C quirk: sticky nie działa w `display: grid` parent → przy długim Dashboard scrollu sidebar zjeżdżał. `.app-shell` bez grid, `.app-content { margin-left: 240px }`, mobile override z `width: auto` żeby bottom nav full width.
- ✅ **PR #184** — modal body scroll lock + `aria-modal`. Nowy hook `apps/web/src/hooks/useBodyScrollLock.ts` (`document.body.style.overflow = 'hidden'` + restore). `RecipeModal` + `DemoGallery` używają. `RecipeModal` dorzucone `aria-modal="true"` + `aria-labelledby={useId()}` powiązane z `<h2>`. +3 testy.
- ✅ **PR #185** — lazy-load `ChatScreen` + `recipes.json`. Bundle initial: 167.25 → **88.69 KB gzip (-47%)**. Vite warning >500KB zniknął. `React.lazy()` + `<Suspense fallback>` w Dashboard; Rollup automatycznie tworzy osobny chunk z recipes.json (324 KB raw / 78.77 KB gzip lazy). Tested manually: initial Dashboard → zero requestów do ChatScreen/recipes, klik Asystent AI → 3 requesty.

### Sprint #2 — security P1 (PRy #187-#190)

- ✅ **PR #187** — nonce w Google Sign-In (replay protection). Frontend `LoginScreen.tsx` generuje `crypto.randomUUID()` w useRef, wstrzykuje do `google.accounts.id.initialize({nonce})`, wysyła w body /api/auth/google. Backend `google_auth/service.login` sprawdza `idinfo['nonce'] == req.nonce` (mismatch → 401) + atomic single-use DDB `NONCE#{value}` z TTL 5min (replay → 401). Pydantic `LoginRequest` z `nonce: str = Field(min_length=16, max_length=128)`. IAM `DDBWriteNonce` statement z `LeadingKeys=NONCE#*`. +4 testy.
- ✅ **PR #188** — Strava OAuth callback wymaga JWT cookie. Defense-in-depth: do tej pory state nonce w DDB wystarczał, atakujący z wykradzionym state mógł zakończyć OAuth z własną Stravą pod cudzym user_id (athlete map conflict guard łapał TYLKO same-athlete attempts). Nowo: JWT check **przed** state delete (atomic — anonim nie spala legit state) + porównanie `state.user_id == jwt.user_id` (mismatch → redirect `state_user_mismatch`). IAM dodane `ssm:GetParameter` na `/bodysync/jwt/signing_secret`. +3 testy.
- ✅ **PR #189** — OIDC role deny expensive AI services. GHA `PowerUserAccess` managed policy pozwalała na `bedrock:* sagemaker:* comprehend:* rekognition:* transcribe:* polly:* lex:* kendra:* translate:* textract:* personalize:*`. Compromise OIDC tokenu (zlec PR z konta z write access, supply-chain action) → max szkoda nieograniczona w short window (Bedrock model invoke = miliony $/godz). Explicit `Deny` w nowej inline policy `deny-expensive-ai-services` przewyższa wszystkie `Allow`. Bootstrap workspace ma local backend — owner ręcznie zaapplyował `terraform apply` po merge.
- ✅ **PR #190** — CSRF token double-submit (zamiast SameSite=Strict). Owner zdecydował zostać przy `SameSite=Lax` (Strict zepsuje Strava OAuth callback cross-site redirect z `https://www.strava.com`). Zamiast tego nowy `shared/csrf.py` z `verify_csrf(event)` (hmac.compare_digest cookie vs header). Frontend `api.ts` auto-inject `X-CSRF-Token` header dla non-safe methods. Apply do 5 handlerów: `advisor_chat` (POST + DELETE), `activity_suggestion`, `measurements`, `profile_targets` (POST/PUT), `tdee_recalc`. CORS allow_headers += `x-csrf-token`. +12 testów (6 shared/csrf unit + 6 per-handler "missing csrf → 403").

### Sprint #3 — dług techniczny P1 (PRy #191-#194)

- ✅ **PR #191** — Terraform import bloki cleanup. `main.tf:7-19` miało 2 leftover `import {}` bloki (weronika webhook secret + google service_account_json) utworzone ręcznie pre-IaC. Po pierwszym apply były no-op. Usunięte: -18 LOC.
- ✅ **PR #192** — frontend CI workflow `.github/workflows/web.yml`. Dotąd broken TS w `apps/web/` leciał do prod (Cloudflare Pages auto-deploy z main bez gating); 192 vitest casy istniały tylko dla lokalnego `npm test`. Nowo: paths-filter `apps/web/**`, Node 22, `npm ci → typecheck → vitest → build`. SHA pinning per CLAUDE.md.
- ✅ **PR #193** — `shared/http.py` extract z 9 handlerów. `_extract_session_cookie` + `_response` powtarzane w ~30 LOC każde × 9 plików. Nowo: `shared/http.py` z `extract_session_cookie` + `response`. `activities_list` zostaje lokalny `response` bo używa `_decimal_safe` serializer (DDB Decimal → JSON number, frontend wymaga `number`). Lokalne zmienne `response = SomeResponse(...)` w 5 handlerach renamed do `result = ` żeby nie shadowować shared funkcji. Net **-209 LOC**, +7 testów (shared/test_http.py). 18 zip-ów rebuild (każdy zawiera całe `shared/` per build.py — owner zaakceptował koszt).
- ✅ **PR #194** — SK range query dla BIOMETRY zamiast pełnego prefix scan + Python filter. `api_read.get_biometry` + `advisor_chat._query_snapshots_in_range` pobierały WSZYSTKIE BIOMETRY rows usera od początku historii (1MB Query cap silent truncation risk przy długiej historii). Nowo: `shared/dynamo.query_by_pk_sk_range(pk, sk_start, sk_end)` z DDB `BETWEEN`. `BIOMETRY#{cutoff}` do `BIOMETRY#~` (tilde sorts po `#` + digits). +3 testy (inclusive bounds, category isolation, PK isolation).

### Sesja 2026-05-16 → 17 — metryki

- **14 PR-ów merged** (#180-#194 minus #186 audit doc PR, czyli 14 code + 1 docs)
- **Backend testów**: 391 → **420 pass** (+29 nowych z 4 sprintów security i shared modules)
- **Frontend testów**: 187 → **192 pass** (+5 z PR #182 touch + PR #184 modal a11y)
- **Bundle gzip**: **-47% initial** (167 → 88 KB), warning >500KB rozwiązany przez lazy load
- **Nowe shared modules**: `shared/http.py`, `shared/csrf.py`, `apps/web/src/hooks/useBodyScrollLock.ts`
- **DDB extensions**: `NONCE#*` PK (Google Sign-In nonces z TTL 5min)
- **IAM zmiany**: `DDBWriteNonce` w `google_auth`, `ssm:GetParameter jwt_signing_secret` w `strava_oauth_callback`, `Deny expensive AI services` w bootstrap OIDC role
- **CORS**: `x-csrf-token` w allow_headers
- **LOC delta**: -209 w handlerach (shared/http extract) -18 (TF import bloki) + nowe testy + dwa nowe shared moduli

### Co zostało odłożone (z audytu, świadomie skip w tym sprincie)

**Tier A featury** (wymóg prawny + must-have MVP-pary):
- 🚧 **GDPR endpointy** — `GET /api/me/export` (ZIP wszystkich `USER#{id}` rows) + `DELETE /api/me/account` (cascade DDB + S3 raw + SSM Strava tokens + athlete-to-user map cleanup). `privacy.html` zapowiada RODO 24mc retention bez technicznego enforcement. Wymóg prawny UE.
- 🚧 **Recovery Score 0-100** — composite z asleep h + deep+rem quality + RHR delta vs 14d baseline. Owner zaakceptował koncepcję w 2026-05-15, jeszcze nie ruszyliśmy.
- 🚧 **Manual kcal/macro entry** — fallback gdy HAE offline (rozszerzenie `POST /api/measurements` lub osobny endpoint). Dziś dashboard pokazuje 0 jeśli HAE nie wysłał.
- 🚧 **Comparisons user_a vs user_b** — couples accountability. Architektura DDB single-table pozwala (GSI-1 inverted index), brak read path.
- 🚧 **CloudWatch error/latency alarms** — dziś tylko Anthropic cost-guard. Ślepi na 5xx storm, p95 spikes, DDB throttling.

**A11y baseline P1**:
- 🚧 `--text-dim` kontrast (#5a6f8e na bg = 4.04:1, fail WCAG AA → bump na #7a8ca8)
- 🚧 focus outlines (`outline: 2px solid var(--cyan)` zamiast border swap w 7 inputach)
- 🚧 `@media (prefers-reduced-motion)` global
- 🚧 `<label className="sr-only">` na ChatInput

**Operational gaps** (nie pilne dla 2-user MVP):
- 🚧 X-Ray tracing na Lambdach
- 🚧 DLQ na strava_fetcher (DDB Stream record fail = log+skip dziś)
- 🚧 Deploy rollback doc
- 🚧 Onboarding doc dla nowego usera (kroki rozproszone w PROJECT-STATUS)

---

## Poprzednia sesja — Weronika onboarding (częściowo) + Strava limit ticket pending

**Sesja 2026-05-12 → 15 — 20 PR-ów merged (#159-#178), waitlist landing + dashboard polish + body measurements + onboarding Weroniki:**

### Waitlist landing (PR #159/#160/#161/#162/#163)

- ✅ **PR #159** — backend POST /api/waitlist (no-auth public), Pydantic schema z `EmailStr` + `consent: bool must True` + honeypot `must empty` + `interest: str | None max 500`. DDB PK=WAITLIST, SK={iso_ts_us}#{email_lower} + attrs (email/interest/ip_hash sha256/referrer/created_at). Honeypot path → 200 SILENTLY (NIE 422 — anti-bot pattern). Email + IP w logach jako sha256[:16] fingerprint (privacy). IaC: Lambda 256MB/5s + route + IAM Condition `LeadingKeys=WAITLIST` (separate od USER#*). 10 testów, ruff zielony.
- ✅ **PR #160** — frontend Coming soon + privacy.html + vitest. LoginScreen split: hero (logo + gradient h1 "Osobisty asystent AI dla treningu i diety" + value pitch PL) → `<WaitlistForm />` → `<DemoGallery />` → Google OAuth schowany za toggle "Mam już konto → Zaloguj". WaitlistForm z email + interest textarea (max 500 + counter X/500) + RODO consent + honeypot (`<input name="phone">` off-screen via CSS, NIE `display:none`). PL error mapper (422/-1/5xx). privacy.html RODO PL static (administrator/dane/cel/24mc retention/AWS eu-west-1/prawa). 8 vitest.
- ✅ **PR #161** — DemoGallery na landing — 4 mock screens (`apps/web/public/demo/dashboard.png` + `chat.png` + `plan.png` + `cialo.png`) z Playwright + preview-mock. Sekcja "Zobacz, co dostaniesz" między hero a form, grid 2-col desktop / stack mobile, click → lightbox modal. Plus dedicated `/api/advisor/chat/history` handler w `preview-mock.ts` (wcześniej wildcard catchował history → frontend crashował `res.messages.map`).
- ✅ **PR #162** — fix mock PLAN: drop "Ciężar (Anita)" personal ref (Anita = imię trenerki, nieadekwatne dla landing demo). Re-screen plan.png.
- ✅ **PR #163** — rename button "Odśwież z arkusza" → "Zsynchronizuj plan" (user-facing intent vs technical detail). PlanScreen + test update + re-screen.

### Dashboard polish — Trendy bar charts + hover (PR #164/#165/#166/#167/#168)

- ✅ **PR #164** — sekcja "Trendy" pełnej szerokości pod overview-grid. 3 stacked MetricChart (uogólnienie WeightChart) z `<rect>` per data point gradient fill. Reuse `buildSeries` + `sumSeries` + `latestValue` z biometry.ts.
- ✅ **PR #165** — owner feedback "bars zamiast linii" (dane discrete per-day, NIE continuous). MetricChart line → bary, Y zaczyna od 0 (proportional comparison), rounded top corners (rx=3), drop "last point dot" + drop empty state "1 point". WeightChart NIETKNIĘTY (waga continuous, line OK).
- ✅ **PR #166** — owner feedback "tekst rozciągnięty". Root cause: viewBox 600px + `preserveAspectRatio="none"` + container ~1100px = horizontal stretch 1.83×. Fix: ResizeObserver pattern w obu chartach — `viewBox=${width}` matchuje pixel width → SVG internal coords = pixel coords → brak stretchu.
- ✅ **PR #167** — owner feedback "hover żeby pokazać dokładną liczbę". Hovered bar: solid color fill (drop gradient) z 100ms transition. HTML tooltip absolute-positioned nad barem z `pointer-events: none` (NIE blokuje sąsiednich). Drop natywny `<title>` (brzydki delayed browser tooltip).
- ✅ **PR #168** — owner feedback "waga też hover bullety". WeightChart: invisible hit-area rects per data point (slotW × plotH) → green dot na raw + cyan dot na EMA + pionowa linia dashed łącząca + 3-line tooltip (data / raw kg / wygładzona X kg). Last point dot ukrywany gdy hover aktywny. CSS shared `.chart-tooltip*` (rename z `.metric-chart-tooltip*`).

### Body measurements + KcalBalanceCard + tab cleanup (PR #169/#170/#173/#174/#175/#176/#177/#178)

- ✅ **PR #169** — rename "Przepisy AI" → "Asystent AI" (już nie tylko przepisy). Backend `is_food_related(message)` z ~50 PL keywords (śniadan/obiad/przepis/kcal/makro/białk/deficyt/owsianka/...) z `_strip_diacritics()` ("zjeść" → "zjesc"). Handler gate: non-food query → skip RAG retrieve + log `rag_skipped_non_food_query`. +19 parametrized testów.
- ✅ **PR #170** — HAE webhook bump 512MB/10s → 1024MB/29s. Weronika initial export timeout'ował na 10s nawet dla 1-day Range. Lambda CPU proporcjonalna do memory (512MB ≈ 0.3 vCPU). 29s = max API GW HTTP integration timeout.
- ✅ **PR #171 → #172 (revert)** — `/oauth/mobile/authorize` deprecated dla third-party. Live test Weroniki: red "error" w Strava app + log `user_denied access_denied`. Revert do `/oauth/authorize`.
- ✅ **PR #173** — Trendy reorder: Kalorie spożyte / **Spalone kalorie** / Kroki (in/out razem, kroki na końcu).
- ✅ **PR #174** — KcalBalanceCard. Today's `kcal_in - (kcal_active + kcal_basal)`, big saldo z +/− prefix (U+2212 dla typografii), status DEFICYT (green) / NADWYŻKA (red) / BILANS (cyan) z threshold ±100 kcal (HAE noise tolerance). Breakdown row Spożyte/Spalone. 7-day sparkline z per-day color (height proporcjonalna do max abs, min 8%). Insertion: między overview-grid a sekcją Trendy. 7 vitest.
- ✅ **PR #175** — Dashboard recent activities 3 → 5 (1-line `getActivities(3)` → `getActivities(5)`).
- ✅ **PR #176** — manual body measurements. Backend POST /api/measurements (JWT, Pydantic v2, model_validator wymaga ≥1 metric), 5 optional `*_cm` fields. DDB SK `BIOMETRY#{date}#{metric}#manual` (suffix disambiguates z HAE samples). BodyMeasurementsCard w Ciało tab pod WeightChart: 5 inputs (Talia/Biodra/Klatka/Biceps/Udo, step 0.1, placeholder z latest value), submit disabled gdy wszystkie puste, success/error banners, 5 mini-charts 30d (MetricChart height 120). 11 backend + 8 frontend testów. IaC: Lambda 256MB/5s + route + IAM `LeadingKeys=USER#*`.
- ✅ **PR #177** — HRV drop z UI (Garmin nie wysyła HRV do Apple Health — diagnostyka: 0 rows w DDB przez 7 dni). Drop MiniStat HRV z Recovery panel + MetricStatCard HRV z BodyView + unused `hrvSeries` consts + `HeartPulseIcon` import. Backend mapper + advisor system_prompt zostają (future-proof gdy Apple Watch lub Garmin Connect direct).
- 🟡 **PR #178** (czeka na merge) — MiniStat "Jakość snu" w Recovery panel (4th slot po HRV drop). `sleepQualityPercent()` helper: `(deep + rem) / asleep × 100%` z guard div-by-zero. Recovery teraz 2×2 grid: Sen / RHR / Body fat / Jakość snu.

### Onboarding Weroniki (operational learnings)

- ✅ **Cleanup pollution** 2026-05-12 — 140+ steps rows z Weroniki iPhone (Bearer Tomka skopiowany na jej HAE pre-PR #157) wycofane z USER#tomek (komenda z TODO 2026-05-12 zakończona).
- ✅ **SSM allowlist** Weronika dodana wcześniej (pre-sesja).
- 🟡 **HAE Aggregation requirement** 2026-05-14 — Weronika initial export wpadł z 4486 BIOMETRY rows (per-minute raw samples z 2 devices Apple Watch + iPhone = double counting → dashboard pokazywał 17k kroków przy realnych 8800). Cleanup: parallel delete xargs -P 20 wszystkich `BIOMETRY#` z USER#weronika (~30s). Wymaganie: **Aggregation: Hour** w HAE settings na iPhone (operational, brak server-side enforcement na razie).
- 🟡 **Strava 1-athlete limit** 2026-05-14 — Strava app na Tomku → Authorize Weroniki = "przekroczono limit podłączonych sportowców" (app w single-player mode, default 1 athlete). Wymaga **ticket do Strava developer support** o increase do 99 athletes (auto-approved 1-3 dni). **Form wypełniony i wysłany 2026-05-14** — czekamy na odpowiedź. Bez approval Weronika nie ma activities, ale ma biometry/plan/advisor/odżywianie.

### Operational decisions w sesji

- 🚫 **Telegram Daily Brief odrzucony** (owner: "nie interesuje mnie wgl" 2026-05-15) — nie pracujemy nad cron morning brief / weekly recap auto-deliver przez Telegram. Telegram pipeline (PR #130/#143) zostaje dla cost-guard CloudWatch alarmów, nie autonomicznych powiadomień.
- 🚫 **Garmin Connect direct integration** wciąż w backlog (Sprint 4.5) ale **nie priorytetowe** — Apple Watch (capex) lub czekanie na Strava approval to dobre alternatywy.
- ✅ **Recovery Score sleep+RHR-based** proposed (bez HRV bo Garmin nie wysyła) — composite z (asleep h, deep+rem quality, RHR delta vs baseline). Owner zatwierdził koncepcję ale jeszcze nie ruszyliśmy z implementacją.

### Sesja 2026-05-12 → 15 — metryki

- **20 PR-ów merged** (#159-#177, plus #178 wystawiony) + 1 revert pair (#171→#172)
- **Backend**: 2 nowe Lambdas (waitlist, measurements), +1 modyfikacja (HAE webhook bump memory/timeout), +19 testów (`is_food_related`)
- **Frontend**: 6 nowych komponentów (WaitlistForm, DemoGallery, MetricChart, TrendCharts, KcalBalanceCard, BodyMeasurementsCard) + 4 modyfikacje (LoginScreen, WeightChart, Dashboard, biometry.ts)
- **Testy**: 187/187 frontend (z 161 początkowych, +26 nowych), 391/391 backend (z 369 początkowych, +22 nowe), 6 skipped (faiss RAG, pre-existing)
- **Bundle delta**: +~14 KB raw / ~+3.5 KB gz przez całą sesję (waitlist + demo gallery + trend charts + kcal balance + body measurements)
- **DDB extensions**: `WAITLIST` PK (separate prefix), `BIOMETRY#{date}#{metric}#manual` SK suffix dla manual measurements
- **SSM**: brak nowych parameters (waitlist no-auth public)

---

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

**Audyt 2026-05-11 (auditor agent, post-sesja, raport pełny:** [`docs/audit-2026-05-11.md`](docs/audit-2026-05-11.md)**):**

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

- **Strava 99-athlete approval pending** — ticket wysłany 2026-05-14 (client_id 235187). Auto-approved 1-3 dni. Bez tego Weronika nie ma Strava connect (Tomek zajmuje 1/1 slot). Po approval: Weronika authorize jednym kliknięciem.
- **Recovery Score (sleep+RHR-based)** — bez HRV bo Garmin nie wysyła. Composite: asleep h + (deep+rem)/asleep quality + RHR delta vs 14d baseline. Card w Dashboard overview z 0-100 score + ZREGENEROWANY/UMIARKOWANY/WYPOCZYNEK label + 7-day sparkline. ~10h. Owner zaakceptował koncepcję, czeka na implementację.
- **Garmin Connect direct integration** — Apple Health → HAE → DDB pipeline serwuje kroki z **Garmin Connect Sync to Apple Health** który desync'uje (delay + miss). Owner zauważył live 2026-05-07 że steps z dziennego export'u są niższe niż realne. **Dodatkowo:** Garmin celowo NIE wysyła HRV ani pełnych workout streams do AH (premium insights trzymane w Garmin Connect). Plan: bezpośredni połączenie do Garmin Connect (`python-garminconnect` lib lub Garmin Connect IQ Web Services). Storage Garmin email/password w SSM SecureString per user (Garmin nie ma proper OAuth dla konsumenta), refresh tokenów. Zakres: steps + active calories + HRV + body battery + sleep stages szczegółowe. Activity tracking nadal przez Strava (Sprint 4). Osobny sprint, **Sprint 4.5 — Garmin Connect**. NIE priorytetowy — Apple Watch alternatywa lub Strava approval wystarczy MVP.
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

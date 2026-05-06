# HealthHub — Project plan

## 1. Kontekst projektu

**Cel:** Domowa aplikacja do monitorowania zdrowia i fitness dla dwóch osób (para), z AI advisorem rekomendującym kalorykę i jadłospisy na podstawie zebranych danych.

**Użytkownicy:**

| | User A (Ty) | User B (dziewczyna) |
|---|---|---|
| Telefon | iPhone 17 | iPhone 14 |
| Zegarek | Garmin (własny) | Garmin (własny) |
| Waga | Xiaomi S400 (wspólna) | Xiaomi S400 (wspólna) |
| Tracking jedzenia | Fitatu | Fitatu |
| Cel zdrowotny | Redukcja tkanki tłuszczowej | Do ustalenia per profil |

**Kluczowe wymagania:**
- Zero ręcznej roboty po jednorazowym setupie
- Wszystko ląduje na dashboardzie automatycznie
- AI advisor: dzienne cele kaloryczne, sugestie jadłospisu, tygodniowe raporty
- Wszystko po polsku
- Minimalne koszty operacyjne

---

## 2. Źródła danych — finalny pipeline

### 2.1 Główna ścieżka: Apple Health hub

```
Garmin (zegarek)  ──sync──→  Garmin Connect  ──sync──→  Apple Health
Fitatu (jedzenie) ────────────────────────sync──→  Apple Health
Xiaomi S400 (waga) ──BT──→  Mi Home  ──────sync──→  Apple Health
Apple Watch (opcja) ─────────────────────native──→  Apple Health
                                                         │
                                                         ▼
                                              Health Auto Export
                                              (apka iOS, ~$6 lifetime)
                                                         │
                                                  POST JSON webhook
                                                         │
                                                         ▼
                                             API Gateway → Lambda
                                             /api/health/webhook
```

**Metryki z webhooka:**

| Kategoria | Metryka | Źródło pierwotne |
|---|---|---|
| Żywienie | dietary_energy, dietary_protein, dietary_carbohydrates, dietary_fat_total | Fitatu |
| Aktywność | step_count, active_energy, apple_exercise_time, distance_walking_running | Garmin |
| Serce | heart_rate, resting_heart_rate, heart_rate_variability | Garmin |
| Ciało | body_mass, body_fat_percentage, body_mass_index, lean_body_mass | Xiaomi S400 |
| Sen | sleep_analysis | Garmin |

### 2.2 Ścieżka Strava (osobna)

```
Strava (apka) ──OAuth2 API──→ Lambda /api/sync/strava
```

Strava dostarcza bogatsze dane o treningach niż to co trafia do Apple Health: trasy GPS, segmenty, tempo, elevation, splits. Warto mieć obie ścieżki.

### 2.3 Wspólna waga — rozpoznawanie usera

Xiaomi S400 rozpoznaje do 36 userów po wadze (±2kg). Mi Home App przypisuje pomiar do profilu. Apple Health na każdym iPhonie dostaje tylko pomiary danej osoby. Health Auto Export z każdego iPhona wysyła z osobnym Bearer tokenem — dane się nie mieszają.

### 2.4 Plan treningowy z Google Sheets

```
Trenerka aktualizuje plan w Google Sheets
         ↓
Lambda (cron co 6h)
         ↓ Google Sheets API v4 (read-only)
Pobiera surowy tekst z aktualnego tygodnia
         ↓
DynamoDB: TRAINING#2026-05-06
         ↓
Dashboard: widok "Dzisiejszy trening"
         ↓
AI advisor: uwzględnia plan w rekomendacji kaloryki
```

**Struktura spreadshita (przeanalizowany):**
- 3 sheety, ~29 tygodni danych, 4 treningi/tydzień (A: dół, B: góra, C: dół, D: góra)
- Każdy trening: rozgrzewka + pliometria + ćwiczenia główne (A-F)
- Kolumny: Ćwiczenie, Link YT, Serie×powt., Intensywność (RIR/RPE), Tempo, Przerwa, Ciężar zalecany, Ciężar wykonany + notatki
- Komentarze trenerki pod każdym tygodniem

**Strategia parsowania (Opcja A — pragmatyczna):**
Lambda pobiera surowy tekst z Google Sheets i zapisuje w DynamoDB. AI advisor dostaje go AS-IS w kontekście — Haiku sam parsuje "120kg x 3 x 8 RIR3". Zero ręcznego parsowania edge case'ów. Ewentualna migracja do strukturalnego JSONa (Opcja B) po walidacji MVP.

### 2.5 Przepisy z PDFów dietetycznych

```
PDFy od dietetyków (~1000 przepisów)
         ↓
scripts/seed_recipes.py
         ↓ PDF extract → LLM parsuje na JSON
{name, ingredients, kcal, protein, carbs, fat, tags}
         ↓
DynamoDB: RECIPES + embeddingi → S3 (FAISS index)
```

Przepisy pochodzą od dietetyków z którymi współpracowałeś — realne makro, sprawdzone proporcje, polskie składniki. Pipeline jednorazowy: extract text z PDF → Haiku parsuje każdy przepis na ustrukturyzowany JSON → embeddingi Titan → FAISS index na S3.

---

## 3. Architektura AWS

### 3.1 Serwisy

| Warstwa | Serwis | Uzasadnienie |
|---|---|---|
| Frontend | Cloudflare Pages | Darmowe, szybkie CDN, deploy z GitHub |
| API | API Gateway HTTP | Tańszy od REST API, wystarczający, custom domain |
| Compute | Lambda (Python, ARM64) | Pay-per-use, free tier, zero utrzymania |
| Baza danych | DynamoDB (on-demand) | Single-table, pay-per-request, free tier |
| LLM | Anthropic API (Haiku 4.5) | Bezpośrednio, bez Bedrock. $1/$5 per 1M tokens, prompt caching -90% |
| RAG storage | S3 + FAISS w Lambda | Embeddingi jako plik w S3, ładowane do pamięci Lambda |
| Secrets | SSM Parameter Store | Darmowy (w odróżnieniu od Secrets Manager — $0.40/secret/mies) |
| IaC | Terraform | Zgodnie z preferencjami |
| CI/CD | GitHub Actions | Darmowe dla publicznych repo |

### 3.2 DynamoDB — single-table design

```
PK                    SK                           Dane
─────────────────────────────────────────────────────────────────
USER#alice            PROFILE                      {name, age, height, sex, goal, ...}
USER#alice            HEALTH#2026-05-06            {steps, hr, calories, sleep, ...}
USER#alice            NUTRITION#2026-05-06         {kcal, protein, carbs, fat}
USER#alice            WEIGHT#2026-05-06            {weight, body_fat, bmi, ...}
USER#alice            WORKOUT#2026-05-06#abc123    {name, type, distance, duration}
USER#alice            TRAINING#2026-05-06          {week, day_type, exercises_raw, coach_notes}
USER#alice            ADVICE#2026-05-06            {tdee, target_kcal, macros, menu}
USER#alice            REPORT#2026-W19              {weekly analysis from LLM}
USER#alice            STRAVA_TOKEN                 {access, refresh, expires_at}
RECIPES               RECIPE#001                   {name, kcal, protein, tags, embedding_ref}
```

**GSI-1:** `SK` (PK) + `PK` (SK) — odwrócony indeks do query po dacie across users.

### 3.3 Lambda functions

| Funkcja | Trigger | Opis |
|---|---|---|
| `google-auth` | API GW POST /api/auth/google | Walidacja Google ID token, allowlist check, wydaj session |
| `health-webhook` | API GW POST /api/health/webhook | Parsuje payload z Health Auto Export, zapisuje do DynamoDB |
| `training-plan-sync` | EventBridge cron (co 6h) | Czyta Google Sheets API, zapisuje TRAINING# do DynamoDB |
| `strava-sync` | API GW POST /api/sync/strava | OAuth2 refresh + pobierz aktywności |
| `strava-callback` | API GW GET /api/strava/callback | OAuth2 callback |
| `ai-advisor-daily` | EventBridge cron (21:00) | Generuj dzienną kalorykę + jadłospis na jutro |
| `ai-advisor-weekly` | EventBridge cron (niedziela 20:00) | Generuj tygodniowy raport |
| `ai-chat` | API GW POST /api/ai/chat | Chat on-demand z kontekstem usera |
| `recipe-search` | API GW GET /api/recipes/search | FAISS similarity search w pamięci |
| `api-read` | API GW GET /api/* | Odczyt danych dla dashboardu |

### 3.4 Estymacja kosztów

| Serwis | Użycie/mies (2 userów) | Koszt |
|---|---|---|
| Lambda | ~2000 invocations × 512MB × 2s | $0.00 (free tier) |
| API Gateway HTTP | ~2000 requests | $0.00 (free tier) |
| DynamoDB on-demand | ~10K WCU + 20K RCU | $0.02 |
| S3 (embeddingi + backup) | ~100 MB | $0.00 |
| Anthropic API (Haiku 4.5) | ~60-90 calls × ~2-3K tokens | $0.30-0.80 |
| Prompt caching (Anthropic) | System prompt cached | -90% na input |
| SSM Parameter Store | 4-6 params | $0.00 |
| EventBridge | 2 reguły cron | $0.00 |
| CloudWatch Logs | Minimalne | $0.00 |
| **Cloudflare Pages** | unlimited | $0.00 |
| **ŁĄCZNIE** | | **~$0.50-1.00/mies** |

Jednorazowe: Health Auto Export × 2 = ~$12, domena ~$10/rok.

---

## 4. AI advisor — design

### 4.1 Profil użytkownika (DynamoDB PROFILE)

```json
{
  "name": "Mateusz",
  "age": 28,
  "height_cm": 178,
  "sex": "male",
  "goal": "fat_loss",
  "goal_rate": "0.5kg/week",
  "activity_level": "moderate",
  "dietary_preferences": ["brak laktozy"],
  "excluded_foods": ["orzechy"],
  "target_weight_kg": 78,
  "current_weight_kg": 84.2
}
```

### 4.2 Codzienny advisor (Lambda: ai-advisor-daily, cron 21:00)

**Input do LLM (Haiku 4.5 via Anthropic API):**
1. System prompt (cached — 90% tańszy po pierwszym call):
   - Rola: polski dietetyk sportowy
   - Zasady: oblicz TDEE, uwzględnij aktywność, cel redukcji
   - Format odpowiedzi: JSON z polami tdee, target_kcal, macros, meals
2. User context (zmienny):
   - Profil usera
   - Dzisiejsze metryki: kroki, aktywne minuty, treningi, spalone kcal
   - Dzisiejsze żywienie: zjedzone kcal, B/W/T
   - Ostatnie 7 dni wagi (trend)
   - Dostępne przepisy z RAG (top 20 pasujących do kaloryki)

**Output (zapisany w DynamoDB ADVICE#date):**
```json
{
  "date": "2026-05-06",
  "summary": "Dziś zjadłeś 2150 kcal przy celu 1850. Nadwyżka +300 kcal. Ale trening biegowy spalił dodatkowe 520 kcal, więc bilans OK.",
  "tdee": 2450,
  "target_kcal": 1950,
  "target_macros": {"protein": 156, "carbs": 195, "fat": 65},
  "tomorrow_menu": {
    "breakfast": {"recipe": "Owsianka proteinowa z jagodami", "kcal": 380, "protein": 32},
    "lunch": {"recipe": "Kurczak z ryżem i brokułami", "kcal": 520, "protein": 45},
    "dinner": {"recipe": "Tatar z łososia", "kcal": 320, "protein": 28},
    "snack": {"recipe": "Sernik proteinowy", "kcal": 280, "protein": 28}
  },
  "tomorrow_total": {"kcal": 1500, "protein": 133, "carbs": 148, "fat": 52},
  "note": "Dodaj ~450 kcal z własnych posiłków lub zwiększ porcje. Cel białka: min 150g."
}
```

### 4.3 Tygodniowy raport (Lambda: ai-advisor-weekly, niedziela 20:00)

**Input do LLM:**
- 7 dni metryk (waga, kcal, makro, aktywność, sen)
- Trend wagowy (średnia, delta)
- Porównanie: cel vs realizacja
- Poprzedni raport (dla kontynuacji)

**Output:**
- Analiza trendów wagowych
- Średni deficyt/nadwyżka kaloryczna
- Co poszło dobrze, co poprawić
- Korekta celów na następny tydzień (jeśli potrzebna)
- Motywacja / kontekst

### 4.4 Chat on-demand

User pisze w dashboardzie: "Zamień obiad na wegetariański" albo "Ile mogę zjeść po treningu?"

**Input:** pytanie + profil + dzisiejsze dane + historia (ostatnie 7 dni).
**Output:** odpowiedź po polsku, z konkretnymi liczbami i przepisami z RAG.

### 4.5 Optymalizacja kosztów LLM

| Technika | Oszczędność |
|---|---|
| Prompt caching (system prompt + profil) | -90% input tokens |
| Haiku 4.5 zamiast Sonnet | -66% vs Sonnet |
| JSON output mode | Mniej output tokens |
| Batch API (Anthropic) | -50% (jeśli tolerancja 24h) |
| Routing: Haiku daily, Sonnet weekly | Lepsze raporty za grosze więcej |

---

## 5. Frontend — Cloudflare Pages

### 5.1 Stack

- React + Vite
- Własny design system (dark theme, patrz 5.4)
- Deploy: `git push` → Cloudflare Pages auto-build
- Env var: `API_URL` → API Gateway custom domain (api.bodysync.pl)

### 5.2 Widoki

| Widok | Dane | Źródło |
|---|---|---|
| Dashboard | Dzisiejsze: kcal, kroki, waga, tętno, sen | GET /api/health/today |
| Aktywności | Lista treningów (Strava + Apple Health) | GET /api/activities |
| Ciało | Progres wagowy, skład ciała, trend | GET /api/weight/history |
| Odżywianie | Kcal + makro dzienne, donuts chart | GET /api/nutrition/today |
| AI advisor | Rekomendacja dnia, jadłospis, chat | GET /api/advice/today + POST /api/ai/chat |
| Raport tygodniowy | Analiza LLM, wykresy trendów | GET /api/report/latest |
| Przepisy | Szukanie semantyczne, filtry makro | GET /api/recipes/search |
| Trening dnia | Plan z Google Sheets: ćwiczenia, ciężary, linki YT, notatki trenerki | GET /api/training/today |
| Ustawienia | Profil, cel, preferencje, tokeny | GET/POST /api/profile |

### 5.3 Auth — Google OAuth2 (bez Cognito)

```
User klika "Zaloguj przez Google" w React
         ↓
Google Sign-In (JS library) → ID token
         ↓
POST /api/auth/google {id_token}
         ↓
Lambda: google-auth
  1. Waliduje ID token z Google (google-auth-library)
  2. Sprawdza email na allowlist (SSM: /healthhub/allowed-emails)
  3. Jeśli OK → generuje session token (JWT, TTL 30 dni)
  4. Zwraca: {session_token, user_id, name, email}
         ↓
Frontend zapisuje session_token → Authorization: Bearer <session>
```

Allowlist 2 emaili w SSM Parameter Store. Zero Cognito, zero kosztu. Session token z expiry 30 dni — bezpieczniejsze niż statyczny token na zawsze.

### 5.4 UX/UI — design system

Docelowy wygląd wzorowany na prototypie dashboard z fazy planowania (plik: `health-dashboard.jsx`). Kluczowe elementy:

**Motyw:** Dark theme — tło `#0a0e17`, karty `#1a2332`, bordery `#2a3548`

**Paleta kolorów:**
- Cyan `#22d3ee` — akcent główny (kroki, tętno, AI)
- Green `#10b981` — waga, skład ciała, pozytywne zmiany
- Orange `#f59e0b` — kalorie, żywienie, ostrzeżenia
- Red `#ef4444` — tętno, negatywne zmiany
- Purple `#a78bfa` — przepisy, RAG
- Pink `#f472b6` — tłuszcze

**Typografia:**
- Nagłówki + liczby: JetBrains Mono (monospace, bold 700-800)
- Tekst body: Inter (sans-serif)
- Uppercase + letter-spacing na labelkach

**Komponenty:**
- StatCard — duża liczba + unit + sparkline + trend (▲/▼%)
- NutritionDonut — donut SVG z makro (B/W/T) + kcal w środku
- WeightChart — bar chart z gradientem, 30 dni
- ActivityRow — ikona typu + nazwa + dystans/czas + kcal
- SourceBadge — status integracji (zielona/szara/pomarańczowa/czerwona kropka)
- RecipeCard — nazwa + opis + pill badges (kcal, białko, tagi)

**Layout:**
- Sidebar 240px (logo + nawigacja z ikonami SVG)
- Main content max-width 1200px, padding 32px
- Grid: auto-fit, minmax(220px, 1fr) na StatCards
- 2-kolumnowy layout na dashboard (aktywności | makro + Garmin)
- Responsive: na mobile sidebar chowa się, grid → 1 kolumna

**Interakcje:**
- Hover na kartach (brightness 1.1)
- Toast notifications (slide-in, auto-dismiss 3s)
- Sparkline SVG z gradient fill
- Transition 0.2s ease na kartach

Plik referencyjny: `/mnt/user-data/outputs/health-dashboard.jsx` — pełny prototyp React z demo danymi, do wykorzystania jako baza w fazie 2.

---

## 6. Bezpieczeństwo

| Warstwa | Mechanizm |
|---|---|
| Transport | HTTPS (API GW + Cloudflare) |
| Auth dashboard | Google OAuth2 → JWT session token (TTL 30 dni) |
| Auth webhook | Bearer token w header (Health Auto Export → API GW) |
| Allowlist | 2 emaile w SSM Parameter Store — tylko te mogą się zalogować |
| Token storage | SSM Parameter Store (encrypted) |
| Data isolation | DynamoDB PK per user — brak cross-user access |
| Strava tokens | Encrypted w DynamoDB (KMS) |
| Google Sheets | Service account (read-only) — klucz w SSM |
| Rate limiting | API GW throttling (domyślne limity wystarczą) |

---

## 7. Struktura repo — backend + IaC

> Pełna decyzja architektoniczna: [ADR-002 lambda packaging](adr/ADR-002-lambda-packaging.md). Sekcja 7 to skrót.

**Reguła:** `infrastructure/terraform/` = TYLKO IaC. Kod Pythona Lambdy żyje w `apps/api/`. Build script `apps/api/scripts/build.py` produkuje `apps/api/dist/{fn}.zip`, Terraform konsumuje przez `aws_lambda_function.filename`.

```
apps/api/                              # Python 3.12 backend (cały kod Lambd)
├── pyproject.toml                     # dev deps (pytest, moto, ruff, mypy, pydantic)
├── shared/                            # importowane przez wszystkie handlery
│   ├── ssm.py                         # get_param(name) z module-level cache
│   ├── dynamo.py                      # get_item / put_item / query_by_pk_sk_prefix
│   ├── auth.py                        # verify_jwt, verify_webhook_token
│   ├── anthropic_client.py            # wrapper + prompt caching
│   └── logging.py                     # structured logger
├── handlers/
│   ├── google_auth/{handler,schemas,service}.py + requirements.txt
│   ├── health_webhook/...
│   ├── training_plan_sync/...
│   ├── strava_sync/...
│   ├── ai_advisor/...                 # daily + weekly + chat
│   ├── recipe_search/...              # FAISS loader
│   └── api_read/...                   # GET /api/* dashboard reads
├── tests/
│   ├── conftest.py                    # dynamodb_table (moto) + ssm_params fixtures
│   ├── shared/test_*.py
│   └── handlers/{fn}/test_handler.py  # happy + auth + invalid + PK isolation
├── scripts/
│   ├── build.py                       # produkuje dist/{fn}.zip per handler
│   ├── seed_recipes.py                # PDF extract → LLM parse → DDB + embeddingi
│   └── create_user.py                 # CLI do tworzenia profilu usera
└── dist/                              # gitignored — build artefakty (Terraform input)

infrastructure/terraform/              # TYLKO IaC, zero kodu Pythona
├── main.tf                            # wywołania modułów + routing API GW
├── variables.tf                       # m.in. lambda_artifacts_path = "../../apps/api/dist"
├── outputs.tf
└── modules/
    ├── api-gateway/                   # HTTP API + routes + (later) custom domain
    ├── lambda/                        # generic moduł parametryzowany source_zip
    ├── dynamodb/                      # bodysync table + GSI-1
    ├── s3/                            # bucket na embeddingi + raw payloads
    ├── eventbridge/                   # cron rules
    └── ssm/                           # parameter store entries
```

**Dependencies:** każdy handler ma własny `requirements.txt` (cold start tax). Shared kopiowany do każdego zip per build (~5KB nadmiaru, pomijalne). Bez Lambda layera (YAGNI dla 7 Lambd dzielących 5KB Pythona).

---

## 8. Plan realizacji — fazy (zrewidowany)

### Faza 0: Infrastruktura (weekend 1)
- [ ] Terraform: API GW + Lambda + DynamoDB + S3 + SSM + EventBridge
- [ ] Google Cloud Console: OAuth2 client ID + service account (Sheets read-only)
- [ ] SSM: allowed-emails, Google SA key, webhook tokens
- [ ] Lambda: google-auth (Google OAuth2 → JWT session)
- [ ] Test: login przez Google działa, JWT wraca

### Faza 1: Data ingestion (weekend 2)
- [ ] Lambda: health-webhook (parsowanie Health Auto Export JSON)
- [ ] Lambda: api-read (odczyt danych dla frontu)
- [ ] Lambda: training-plan-sync (Google Sheets → DynamoDB)
- [ ] Setup: Health Auto Export na obu iPhonach → webhook URL
- [ ] Test: dane z Fitatu/Garmin/S400 lądują w DynamoDB + plan treningowy się synchronizuje

### Faza 2: Frontend dashboard (weekend 3-4)
- [ ] React + Vite na Cloudflare Pages
- [ ] Google Sign-In login
- [ ] Widoki: dashboard, aktywności, ciało, odżywianie, trening dnia
- [ ] Charts: recharts / Chart.js dla trendów
- [ ] Responsive mobile (widok na iPhonie)

### Faza 3: AI advisor (weekend 5)
- [ ] scripts/seed_recipes.py: PDF extract → LLM parse → DynamoDB + embeddingi
- [ ] Lambda: ai-advisor-daily (cron 21:00, Anthropic API Haiku, kontekst: metryki + plan treningowy)
- [ ] Lambda: ai-chat (on-demand z kontekstem usera)
- [ ] Frontend: widok AI advisor + jadłospis + chat
- [ ] MVP na start bez RAG: przepisy w prompcie (max 100). FAISS dodać gdy 500+

### Faza 4: Rozszerzenia (weekend 6+)
- [ ] Lambda: strava-sync + callback (OAuth2) — bogatsze dane GPS
- [ ] Lambda: ai-advisor-weekly (niedziela 20:00) + widok raport tygodniowy
- [ ] Lambda: recipe-search (FAISS) — gdy przepisów > 500
- [ ] Porównanie userów (wspólny widok pary)
- [ ] Notyfikacje push (opcjonalnie)
- [ ] Export raportów PDF

**Realny timeline: MVP działający end-to-end w 5 weekendów.** Po weekendzie 2 już widzisz dane w DynamoDB. Po weekendzie 4 masz dashboard z danymi. Strava i weekly raporty przesunięte do fazy 4 żeby nie blokować MVP.

---

## 9. Otwarte pytania / decyzje do podjęcia

Brak — wszystkie decyzje podjęte. Gotowe do kodowania.

### Rozwiązane decyzje
- ✅ **Domena** → bodysync.pl (kupiona)
- ✅ **Przepisy** → PDFy od dietetyków (~1000 przepisów), pipeline: PDF → LLM parse → DynamoDB + embeddingi
- ✅ **Auth** → Google OAuth2 bezpośrednio, allowlist 2 emaili, JWT session 30 dni, zero Cognito
- ✅ **LLM** → Anthropic API bezpośrednio (nie Bedrock). Te same ceny ($1/$5 per MTok), prostsze (1 API key vs IAM + Bedrock config), prompt caching działa
- ✅ **IaC** → Terraform
- ✅ **Język AI** → Polski
- ✅ **Plan treningowy** → Google Sheets API (read-only, cron co 6h), opcja A (surowy tekst do LLM)
- ✅ **Strava** → przesunięte do fazy 4, Apple Health wystarczy na MVP
- ✅ **Notyfikacje** → pomijamy na razie
- ✅ **Shared view** → nie potrzebne

# bodysync.pl

Prywatny dashboard zdrowia i treningu dla dwóch osób. Zbiera dane z **Apple Health**, **Stravy** i **Google Sheets** w jednym miejscu, a **Claude Haiku** doradza w sprawie diety i kalorii po polsku.

- Aplikacja: [bodysync.pl](https://bodysync.pl)
- API: `api.bodysync.pl`
- Serwer MCP (konektor dla Claude): `https://api.bodysync.pl/mcp`

## Co robi

| Obszar | Źródło | Co daje |
|---|---|---|
| Biometria | Apple Health → [Health Auto Export](https://www.healthyapps.dev/) (webhook) | waga, skład ciała, sen i jego fazy, kroki, tętno, kcal spożyte/spalone, makro |
| Aktywności | Strava (OAuth + webhook + fetcher) | lista treningów, trasy, obciążenie |
| Plan treningowy | Google Sheets (service account, tylko odczyt) | zakładka „Plan Treningowy”, kontekst dla asystenta |
| Pomiary ręczne | formularz w aplikacji | obwody (talia, biodra, klatka, biceps, udo) |
| Asystent AI | Anthropic Haiku 4.5 + RAG (139 przepisów) | czat dietetyczny, przegląd diety co 14 dni, sugestia poziomu aktywności dla kalkulatora TDEE |
| Konektor MCP | własny serwer OAuth 2.0 + JSON-RPC | dane bodysync dostępne w rozmowie z Claude, tylko odczyt |
| RODO | `GET /api/me/export`, `DELETE /api/me/account` | eksport i usunięcie wszystkich danych użytkownika |

Dostęp do aplikacji ma wyłącznie konto Google z allowlisty dwóch adresów. Osoby z zewnątrz widzą landing z listą oczekujących (waitlist).

## Architektura

```
 bodysync.pl (React, Cloudflare) ─┐
 Apple Health (HAE webhook) ──────┤
 Strava (OAuth, webhook) ─────────┼──► API Gateway HTTP ──► Lambdy (Python 3.12) ──┬──► DynamoDB bodysync-data
 Claude (konektor MCP) ───────────┘    api.bodysync.pl                             ├──► S3 (surowe dane, FAISS)
                                                                                   ├──► Google Sheets (plan)
                                                                                   ├──► Anthropic API
                                                                                   └──► SSM (sekrety)
```

- **Frontend:** React 19 + Vite + TypeScript, Cloudflare Workers + Static Assets (deploy z `main`)
- **Backend:** Python 3.12 na AWS Lambda ARM64, jeden handler = jedna Lambda (`apps/api/handlers/*`)
- **Baza:** DynamoDB single-table, `PK = USER#{id}`, PITR włączony
- **Pliki:** S3 na surowe payloady HAE i streamy Stravy oraz indeks FAISS przepisów
- **Logowanie:** Google Sign-In (z nonce) → JWT w cookie HttpOnly, CSRF metodą double-submit
- **Sekrety:** SSM Parameter Store SecureString
- **IaC:** Terraform (backend S3), apply wyłącznie przez GitHub Actions z OIDC
- **Asynchroniczność:** DynamoDB Streams + druga Lambda (fetcher Stravy), EventBridge do zadań cyklicznych
- **Alerty:** alarm kosztów Anthropic → SNS → bot Telegram

Decyzje architektoniczne są opisane w [`docs/adr/`](docs/adr/):

| ADR | Temat |
|---|---|
| [001](docs/adr/ADR-001-stack-baseline.md) | Bazowy stack |
| [002](docs/adr/ADR-002-lambda-packaging.md) | Pakowanie Lambd |
| [003](docs/adr/ADR-003-terraform-conventions.md) | Konwencje Terraform |
| [006](docs/adr/ADR-006-advisor-on-demand-vs-cron.md) | Doradca na żądanie czy z crona |
| [007](docs/adr/ADR-007-chat-assistant-rag.md) | Czat z RAG |
| [008](docs/adr/ADR-008-adaptive-tdee-recalculation.md) | Adaptacyjne przeliczanie TDEE |
| [009](docs/adr/ADR-009-llm-diet-review-pivot.md) | Przegląd diety przez LLM zamiast TDEE |
| [010](docs/adr/ADR-010-mcp-server.md) | Serwer MCP |

## Struktura repo

```
bodysync/
├── apps/
│   ├── api/                 ← backend: handlers/<lambda>/, shared/, tests/, scripts/build.py
│   └── web/                 ← frontend: React + Vite
├── infrastructure/
│   └── terraform/           ← root workspace + modules/ + bootstrap/ (state backend, OIDC)
├── docs/                    ← ADR-y, audyty, plan, sprinty
├── samples/                 ← lokalne materiały (PDF-y z przepisami), poza gitem
├── wrangler.jsonc           ← konfiguracja deployu frontendu na Cloudflare
├── PROJECT-STATUS.md        ← bieżący stan projektu
└── CLAUDE.md                ← konwencje i zasady pracy
```

Szczegółowe README modułów:

- [`apps/api/`](apps/api/README.md) — środowisko Pythona, testy, budowanie paczek Lambd
- [`apps/web/`](apps/web/README.md) — dev server, build, konfiguracja Cloudflare
- [`apps/api/handlers/mcp/`](apps/api/handlers/mcp/README.md) — serwer MCP i podłączenie konektora w Claude
- [`infrastructure/terraform/bootstrap/`](infrastructure/terraform/bootstrap/README.md) — jednorazowy bootstrap stanu Terraform i roli OIDC

## Uruchomienie lokalne

Wymagania: Python 3.12 z [uv](https://docs.astral.sh/uv/), Node 22, Terraform 1.13+, AWS CLI (SSO).

### Backend

```bash
cd apps/api
uv venv --python 3.12
uv pip install -e ".[dev]"

uv run pytest                                # testy (moto zamiast prawdziwego DynamoDB)
uv run ruff check . && uv run ruff format --check .
uv run mypy shared handlers
uv run python scripts/build.py               # paczki Lambd → dist/{handler}.zip
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

Z `VITE_PREVIEW_MODE=true` frontend podmienia `fetch` na dane przykładowe, więc działa bez backendu. Tak działają też preview deploymenty.

## Deploy

| Co | Jak |
|---|---|
| Frontend | Cloudflare buduje każdy push. `main` trafia na `bodysync.pl`, pozostałe branche na preview URL |
| Infrastruktura + Lambdy | workflow `Terraform`: `plan` na PR, `apply` po merge do `main` (AWS OIDC, bez stałych kluczy) |
| CI frontendu | workflow `Web`: typecheck, vitest i build przy zmianach w `apps/web/**` |

Lokalnie uruchamiamy tylko `terraform plan`. Wyjątkiem jest `bootstrap/`, który ma lokalny stan i jest aplikowany ręcznie.

## Zasady

Pełna lista jest w [`CLAUDE.md`](CLAUDE.md). Najważniejsze:

- Zmiany trafiają do `main` tylko przez PR (`feat/*`, `fix/*`, `chore/*`), commity w stylu conventional
- Każde zapytanie do DynamoDB ma `PK = USER#{id}` w warunku, a testy zawsze sprawdzają izolację na dwóch użytkownikach
- Sekrety są wyłącznie w SSM, nigdy w zmiennych środowiskowych ani w repo
- Pydantic waliduje każde wejście endpointu i webhooka
- Akcje GitHub są przypięte do pełnego SHA, nie do tagu
- Nową zależność trzeba uzasadnić, bo każdy megabajt paczki wydłuża cold start

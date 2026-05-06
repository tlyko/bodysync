# ADR-001 — Stack baseline

**Status:** Accepted (2026-05-06)
**Owner:** Tomek (`tlyko94@gmail.com`)
**Decyzja podjęta przed istnieniem ADRs**, spisana ex-post. Każda zmiana stack-baseline wymaga nowego ADR.

## Kontekst

bodysync.pl to single-user (para userów initial) personal health + fitness dashboard. Agreguje dane z 4 zewnętrznych źródeł (Apple Health webhook, Strava OAuth+webhook, Google Sheets read-only, Anthropic Haiku) i serwuje dashboard frontendowy + automatic advisor (kcal + meals).

Charakterystyka:
- **Skala:** 2 userów, ~200 events/tydzień (Apple Health 2-3 webhook payloads/dzień × 2 + Strava 1-5 aktywności/tydzień × 2)
- **Koszt-target:** <$5/miesiąc całkowity (LLM + AWS + Cloudflare). Free-tier-first.
- **DX:** solo dev, mała powierzchnia, kod ma być czytelny po 3 miesiącach przerwy
- **Kompozytor:** account AWS `214598715232` współdzielony z `sprawdzamszlak` — patrz memory `feedback_shared_aws_account_resources.md` (account-wide singletons jak OIDC provider należą do jednego projektu, drugi używa data source).

## Rozważane alternatywy

### Opcja A — AWS serverless + Cloudflare Pages (wybrana)
- Backend: Python 3.12 Lambda ARM64 + API Gateway HTTP v2
- DB: DynamoDB single-table z PITR
- Storage: S3 + lifecycle dla raw payloads
- Frontend: React + Vite SPA na Cloudflare Pages
- DNS: Cloudflare (managed by owner manualnie, Terraform tylko placeholder)
- IaC: Terraform 1.13+ z `s3` backend (`use_lockfile`, bez DDB lock — deprecated)
- CI/CD: GitHub Actions z AWS OIDC role assumption
- LLM: Anthropic API direct (Haiku 4.5)
- Auth: Google OAuth2 → JWT cookie

### Opcja B — VPS + Postgres + Express
- Hetzner / Fly / Railway, jeden VPS €5/mc
- Postgres + Drizzle / SQLAlchemy
- Plus: prostsze, bez cold starts, normalne SQL
- Minus: zarządzanie serwerem, fixed cost, brak free tier, scale-up to $$$
- **Skala 2 userów nie uzasadnia fixed cost VPS.**

### Opcja C — hybryda (Vercel + Neon + AWS Lambda)
- Frontend Vercel, Postgres Neon, backend Lambda
- Plus: każdy provider best-in-class
- Minus: 3 płatności, 3 dashboards, 3 status pages, więcej rzeczy do monitorowania
- **Niepotrzebna złożoność dla 2 userów.**

## Decyzja

**Opcja A — AWS serverless + Cloudflare Pages.**

Konkretnie:

| warstwa | wybór | uzasadnienie |
|---|---|---|
| **Lambda runtime** | Python 3.12 ARM64 | ARM64 ~20% taniej niż x86, Pydantic ekosystem dla schemas, integracje (Health Auto Export, Strava, Anthropic SDK) wszystkie po Pythonie |
| **Lambda memory** | API: 512MB / 10s; advisor: 1024MB / 30s | API endpoint thin (parse → DDB → response), advisor robi LLM call |
| **DB** | DynamoDB single-table | PAY_PER_REQUEST = free tier forever na naszej skali; PITR za $0.20/m polisa anty-`drop-manual-seeds`; access patterns proste (`USER#{id}` + SK prefix) |
| **PK/SK design** | PK=`USER#{id}`, SK=`{TYPE}#{date}` lub `{TYPE}#{id}` | Per-user isolation by default; query `begins_with(SK, 'BIOMETRY#')` dla biometry, `'ACTIVITY#'` dla aktywności; nigdy `Scan` |
| **Storage** | S3 dla raw payloads | Strava streams JSON (~50KB/aktywność), Health Auto Export raw (~10KB/payload). Lifecycle: glacier po 90d. |
| **API Gateway** | HTTP API v2 | Tańszy + szybszy niż REST; CORS native; payload format 2.0 |
| **Frontend host** | Cloudflare Pages | Free, auto-deploy z `main`, custom domain free, edge cache |
| **DNS** | Cloudflare (manual by owner) | Owner zarządza DNS sam — patrz memory `project_cloudflare_ownership.md`. Terraform NIE provisionuje DNS records. |
| **IaC** | Terraform 1.13+ z `s3` backend | `use_lockfile` (bez DDB lock — deprecated od TF 1.10); single state file `bodysync/terraform.tfstate` |
| **CI/CD** | GHA OIDC | No long-lived AWS keys; trust scope: `repo:tlyko/bodysync:ref:refs/heads/main` (apply) + `:pull_request` (plan-only) |
| **Sekrety** | SSM Parameter Store SecureString | Free dla <10k requests/m; kmsdefault; vs. Secrets Manager $0.40/secret/m |
| **Auth** | Google OAuth2 → JWT cookie | Brak Cognito (overkill dla 2 userów); HttpOnly Secure SameSite=Lax 30d TTL; signing secret rotates via SSM |
| **LLM** | Anthropic API direct (`claude-haiku-4-5-20251001`) | Brak Bedrock (markup + slower); prompt caching dla system prompt (5min TTL); structured output via `tool_use` |

## Konsekwencje

### Pozytywne
- **Koszt:** target <$5/m totalny achievable. AWS free tier dla Lambda (1M req) + DDB on-demand (25 RCU/WCU) + API GW (1M calls) wystarczy z naprę. Anthropic input/output tokens ~$0.20/m przy 2 userach × daily call. CF Pages free.
- **Cold start:** Python 3.12 ARM64 init ~250ms, akceptowalne dla dashboard load (nie webhook-first).
- **Dług:** mały — solo dev wraca po 3 miesiącach i wszystko jest jednym `terraform apply` away.
- **Re-use:** wzorzec sprawdzamszlak (DDB single-table + Streams + async fetcher Lambda) bezpośrednio portowalny dla Strava webhook → fetcher.

### Negatywne
- **Cold start tax** dla Apple Health webhook (real-time-ish). Akceptowalny: webhook nie ma SLA, payload ~10KB nie kazi.
- **Single AZ implicit** — Lambda + DDB w eu-west-1, jeden region. Disaster scenario: region down → frontend działa (cached), API down. Akceptowalne dla personal app.
- **Vendor lock-in** AWS dla backendu — eject jest możliwy (Lambda → FastAPI on Fly, DDB → Postgres) ale wymaga refactoru.
- **Provider sprawl:** AWS + Cloudflare + Anthropic + Google = 4 providers, 4 status pages. Mitigation: consolidacja gdzie możliwe (np. `boto3` zamiast `aws-sdk` w Lambdzie nawet dla rzeczy które dałoby się dorobić w Cloudflare Worker, dla simplicity).

### Re-evaluation triggers

Stack do przemyślenia gdy:
- Skala >100 userów → DDB read multiplexing, scan unfit for cross-user analytics → ADR o GSI lub Postgres
- Koszt >$20/m bez wzrostu funkcji → wymiar inny niż przewidywałem (LLM tokens? Lambda time? S3 egress?) → ADR o redesign
- Latency p95 >2s na dashboard load → cold start lub DDB scan; ADR o warming strategy lub schema redesign
- Wybijemy się z free tier DDB → ADR o switch na Postgres lub provisioned + auto-scaling

## Bibliografia / patterns

- Single-table design: Alex DeBrie, "The DynamoDB Book"
- AWS Lambda Python ARM64: https://aws.amazon.com/blogs/aws/aws-lambda-functions-powered-by-aws-graviton2-processor-run-your-functions-on-arm-and-get-up-to-34-better-price-performance/
- Anthropic prompt caching: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
- Sprawdzamszlak port źródło: `~/repos/sprawdzamszlak/docs/adr/ADR-001-stack-and-monorepo.md`

# bodysync — TODO

## Task: Faza 0 — Infrastruktura bazowa
Phase: 0
Estimated effort: 8–10h (jeden weekend)

**Cel fazy:** działający pipeline `PR → terraform plan → merge → terraform apply` w AWS `eu-west-1`, z bazowymi modułami (DynamoDB, S3, SSM, EventBridge, API GW, Lambda) i pierwszym konkretnym endpointem `/api/auth/google` zwracającym JWT.

**Założenia z pamięci projektowej:**
- Region: `eu-west-1`
- State: S3 + DynamoDB lock od dnia pierwszego
- CI/CD: GitHub Actions, plan-on-PR (komentarz) + apply-on-main, OIDC do AWS (bez kluczy w secrets)
- Cloudflare DNS / Pages — user ogarnia sam, w tej fazie pomijamy custom domain na API GW (zostawiamy default `*.execute-api`)

---

### Step 1: Bootstrap state backend + GitHub OIDC → `infrastructure/terraform/` ✅ shipped
- **Tworzy:**
  - `infrastructure/terraform/main.tf` — S3 bucket `bodysync-tfstate-{account_id}` (versioning + encryption + public-block), DynamoDB table `bodysync-tflock` (PAY_PER_REQUEST, PK=`LockID`)
  - `infrastructure/terraform/oidc.tf` — `aws_iam_openid_connect_provider` dla `token.actions.githubusercontent.com` + IAM role `bodysync-github-actions` z trust policy ograniczoną do repo (`repo:tlyko/bodysync:*`) i polityką pozwalającą na pełny dostęp do tabeli locków, bucketa state oraz `*` na resource'ach z tagiem `Project=bodysync` (najprostszy ABAC do iteracji)
  - `infrastructure/terraform/variables.tf` — `aws_region` (default `eu-west-1`), `github_owner`, `github_repo`
  - `infrastructure/terraform/outputs.tf` — `state_bucket`, `lock_table`, `gh_actions_role_arn`
  - `infrastructure/terraform/versions.tf` — pin AWS provider `~> 5.x`, terraform `~> 1.9`
  - `infrastructure/terraform/README.md` — krótka instrukcja: `terraform init && terraform apply` ręcznie raz, potem nie ruszać
- **State:** lokalny (`terraform.tfstate` zignorowany w `.gitignore`) — bootstrap nie może być w S3 zanim S3 nie istnieje
- **Depends on:** nic (potrzebne creds do AWS lokalnie — pierwsze i ostatnie ręczne odpalenie)
- **Test:**
  - `cd infrastructure/terraform && terraform validate && terraform plan`
  - po apply: `aws s3 ls | grep bodysync-tfstate` i `aws dynamodb describe-table --table-name bodysync-tflock`
  - `aws iam get-role --role-name bodysync-github-actions` zwraca trust policy z `token.actions.githubusercontent.com`
- **Acceptance:** bucket i tabela istnieją, role ARN zapisane w `docs/infra-outputs.json` (manualny `terraform output -json > ../../docs/infra-outputs.json`), `.gitignore` chroni state plik

---

### Step 2: Terraform główny workspace (S3 backend, providery, tagging)

**Layout zgodnie z [ADR-003 terraform conventions](adr/ADR-003-terraform-conventions.md):** `config.tf` + `locals.tf` + `main.tf`. Bez `versions.tf`, `variables.tf`, `outputs.tf`.

> ⚠️ **Pre-req: layout decision** — bootstrap obecnie zajmuje `infrastructure/terraform/`. Główny workspace nie może siedzieć w tym samym katalogu (różne backendy: bootstrap = local state, główny = S3). Decyzja przed startem: przenieść bootstrap do `infrastructure/terraform/bootstrap/` + główny żyje w `infrastructure/terraform/`, ALBO zostawić bootstrap i stworzyć główny w `infrastructure/terraform-app/`. Ta sama decyzja dotyczy migracji state pliku bootstrap (kopiowanie + `terraform init -migrate-state` przy zmianie ścieżki).

- **Tworzy** (zakładając przeniesienie bootstrap → `infrastructure/terraform/bootstrap/`):
  - `infrastructure/terraform/config.tf` — `terraform { required_version, required_providers (aws ~> 6.43, archive), backend "s3" { bucket="syncbody-tfstate-{account_id}", key="bodysync/terraform.tfstate", region="eu-west-1", encrypt=true, use_lockfile=true (TF 1.10+ S3 .tflock zamiast DDB) } }` + `provider "aws" { region = local.aws_region, default_tags { tags = local.tags } }`
  - `infrastructure/terraform/locals.tf` — `project = "bodysync"`, `aws_region = "eu-west-1"`, `tags = { Project = local.project, ManagedBy = "terraform" }`. Per-table configs (DDB main + Strava events) i SSM param paths dochodzą w Step 4.
  - `infrastructure/terraform/main.tf` — pusty (resources dochodzą od Step 4)
- **Depends on:** Step 1 (bucket + lock table muszą istnieć), layout decision z pre-req
- **Test:** `cd infrastructure/terraform && terraform init` (S3 backend), `terraform validate`, `terraform plan` → "No changes"
- **Acceptance:** `terraform plan` zwraca zero zmian, S3 .tflock działa (drugi `plan` w drugim terminalu czeka), default tagi widoczne w `plan`

---

### Step 3: GitHub Actions — plan na PR, apply na main → `.github/workflows/`
- **Tworzy:**
  - `.github/workflows/terraform-plan.yml` — trigger: `pull_request` na `main`, paths `infrastructure/terraform/**`. Steps: checkout → setup-terraform → `aws-actions/configure-aws-credentials@v4` z `role-to-assume=${{ vars.AWS_ROLE_ARN }}` → `terraform fmt -check` → `terraform init` → `terraform plan -no-color -out=plan.tfplan` → `actions/github-script` posta plan jako komentarz w PR (skróć jeśli > 65k znaków)
  - `.github/workflows/terraform-apply.yml` — trigger: `push` na `main`, paths `infrastructure/terraform/**`. Steps: checkout → setup-terraform → OIDC creds → `terraform init` → `terraform apply -auto-approve`
  - `permissions:` na poziomie workflowa: `id-token: write`, `contents: read`, `pull-requests: write` (tylko w plan)
  - W repo settings (manualnie, poza Terraformem): GitHub variable `AWS_ROLE_ARN` = output z Step 1
- **Depends on:** Step 1 (rola IAM), Step 2 (musi być co planować — minimum providery)
- **Test:** otwórz dummy PR (np. zmiana komentarza w `infrastructure/terraform/main.tf`) → workflow `terraform-plan` zielony → komentarz z planem na PR → merge → workflow `terraform-apply` zielony → `terraform plan` lokalnie nadal "No changes" (state spójny)
- **Acceptance:** dwa workflowy działają, komentarz z planem widoczny na PR, apply na merge nie wybucha, OIDC działa bez statycznych kluczy

---

### Step 4: Moduły bazowe (DynamoDB, S3, SSM, EventBridge) → `infrastructure/terraform/modules/`
- **Tworzy:**
  - `infrastructure/terraform/modules/dynamodb/` — tabela `bodysync`: PK `PK` (S), SK `SK` (S), GSI-1 (`SK` jako PK, `PK` jako SK), `BillingMode = PAY_PER_REQUEST`, `point_in_time_recovery = true`, `server_side_encryption = enabled`
  - `infrastructure/terraform/modules/s3/` — bucket `bodysync-data-{account_id}`: versioning on, public access block, SSE-S3, lifecycle rule (delete noncurrent versions po 90 dniach)
  - `infrastructure/terraform/modules/ssm/` — zasoby `aws_ssm_parameter` z `lifecycle { ignore_changes = [value] }`: `/bodysync/anthropic-api-key`, `/bodysync/google-client-id`, `/bodysync/google-client-secret`, `/bodysync/allowed-emails`, `/bodysync/jwt-secret`, `/bodysync/google-sa-key`, `/bodysync/webhook-token-tomek`, `/bodysync/webhook-token-partner` (typ `SecureString`, value=`"PLACEHOLDER"` — wartości wpiszemy ręcznie konsolą AWS)
  - `infrastructure/terraform/modules/eventbridge/` — 3 reguły (na razie bez targetów, te dodamy w Fazie 1+):
    - `bodysync-training-sync`: `cron(0 */6 * * ? *)`
    - `bodysync-ai-advisor-daily`: `cron(0 19 * * ? *)` (21:00 CET)
    - `bodysync-ai-advisor-weekly`: `cron(0 18 ? * SUN *)` (20:00 CET)
  - Każdy moduł ma `main.tf`, `variables.tf`, `outputs.tf`
  - `infrastructure/terraform/main.tf` — wywołania modułów + outputy (table_name, bucket_name, role_arn)
- **Depends on:** Step 2, Step 3 (apply przez Actions)
- **Test:** PR z modułami → plan pokazuje ~12-15 nowych zasobów → merge → apply przechodzi → `aws dynamodb describe-table --table-name bodysync` pokazuje GSI-1, `aws ssm get-parameters-by-path --path /bodysync --recursive` zwraca wszystkie placeholdery
- **Acceptance:** wszystkie zasoby utworzone i otagowane `Project=bodysync`, drugi `terraform plan` = "No changes", `ignore_changes` na SSM pozwala ręcznie ustawić wartości bez driftu

---

### Step 5: API Gateway + moduł Lambda + funkcja `google-auth` → pierwszy endpoint

**Layout zgodnie z [ADR-002 lambda packaging](adr/ADR-002-lambda-packaging.md):** kod w `apps/api/`, IaC w `infrastructure/terraform/`, build script `apps/api/scripts/build.py` produkuje `apps/api/dist/{fn}.zip` konsumowany przez Terraform.

- **Tworzy:**
  - `apps/api/pyproject.toml` — PEP 621 metadata, `[project.optional-dependencies] dev = [pytest, moto, responses, ruff, mypy, pydantic]`. Single venv pod `apps/api/.venv`.
  - `apps/api/shared/` — `__init__.py`, `ssm.py` (cache w module-level dict, `get_param(name)`), `dynamo.py` (`get_item`, `put_item`, `query_by_pk_sk_prefix` używając `boto3.resource('dynamodb')`), `auth.py` (`verify_jwt(token)` → user_id albo raise; używa secret z SSM), `logging.py` (structured logger z `request_id` + `user_id`)
  - `apps/api/handlers/google_auth/` — `handler.py` (parsuje `id_token` z body via Pydantic, waliduje przez `google.oauth2.id_token.verify_oauth2_token`, sprawdza email na allowliście z SSM, generuje JWT z `PyJWT`, zwraca `{session_token, user_id, name, email}`), `schemas.py` (Pydantic input/output), `service.py` (logika osobno od `handler` dla testowalności), `requirements.txt` (`google-auth==2.35.*`, `pyjwt==2.9.*`, `pydantic==2.x`)
  - `apps/api/tests/conftest.py` — fixtures `dynamodb_table` (moto) i `ssm_params`
  - `apps/api/tests/handlers/google_auth/test_handler.py` — pytest+moto+responses: happy path, brak tokenu → 400, email spoza listy → 403, zły token Google → 401, **PK isolation: user_a nie widzi sesji user_b**
  - `apps/api/scripts/build.py` — buduje `dist/{fn}.zip` per handler: `pip install -r handlers/{fn}/requirements.txt --target dist/_build/{fn}/ --platform manylinux2014_aarch64 --only-binary=:all:`, kopiuje `handlers/{fn}/*.py` + `shared/` do `_build/{fn}/`, zip deterministyczny (sortowane pliki, fixed mtime)
  - `apps/api/.gitignore` — `.venv/`, `dist/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`
  - `infrastructure/terraform/modules/api-gateway/` — `aws_apigatewayv2_api` (HTTP), `cors_configuration` (`allow_origins = ["https://bodysync.pl", "http://localhost:5173"]`, methods, headers), default `$default` stage z auto-deploy. **Bez** custom domain (czeka na Cloudflare)
  - `infrastructure/terraform/modules/lambda/` — generic moduł parametryzowany: `function_name`, `source_zip` (path do `apps/api/dist/{fn}.zip`), `handler` (default `handler.handler`), `memory_size` (512), `timeout` (10), `environment` (map), `extra_iam_statements` (list). Tworzy `aws_lambda_function` (python3.12, arm64) z `filename = var.source_zip` + `source_code_hash = filebase64sha256(var.source_zip)`, `aws_cloudwatch_log_group` z 14d retention, `aws_iam_role` z basic execution + `extra_iam_statements`
  - `infrastructure/terraform/variables.tf` — dodać `lambda_artifacts_path = "${path.module}/../../apps/api/dist"`
  - `infrastructure/terraform/main.tf` — wpięcie API GW + `aws_apigatewayv2_integration` + route `POST /api/auth/google` → `module "google_auth"` (source `./modules/lambda`, `source_zip = "${var.lambda_artifacts_path}/google_auth.zip"`, `extra_iam_statements` z `dynamodb:GetItem/PutItem` na table_arn + `ssm:GetParameter` na `arn:aws:ssm:*:*:parameter/bodysync/*`)
  - `.github/workflows/terraform-plan.yml` + `terraform-apply.yml` — dodać step `setup-python@v5` + `cd apps/api && python scripts/build.py` PRZED `terraform plan/apply`
- **Depends on:** Step 4 (DynamoDB + SSM muszą istnieć)
- **Test:**
  - `cd apps/api && python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`
  - `cd apps/api && pytest -v` — wszystkie testy zielone (z testem PK isolation)
  - `cd apps/api && ruff check . && ruff format --check . && mypy shared/ handlers/`
  - `cd apps/api && python scripts/build.py` — produkuje `dist/google_auth.zip`, sprawdź `unzip -l dist/google_auth.zip` zawiera `handler.py`, `shared/`, deps Google
  - PR → GHA build + plan → komentarz na PR → merge → apply
  - `curl -X POST $API_URL/api/auth/google -d '{"id_token":"invalid"}'` → 401
  - (po ręcznym ustawieniu prawdziwych wartości w SSM + Google OAuth client w Cloud Console) flow z prawdziwym tokenem → 200 + JWT
- **Acceptance:** pytest zielony (z PK isolation test), build script deterministyczny (drugi `build.py` produkuje identyczny hash), `terraform plan` = "No changes" po apply, endpoint odpowiada 401 na zły token bez exception, log group w CloudWatch ma wpisy z `logger.info`, JWT można zdekodować i ma `user_id`+`exp` 30 dni

---

## Co NIE jest w Fazie 0 (świadomie odłożone)

- Custom domain `api.bodysync.pl` na API GW → po skonfigurowaniu Cloudflare przez usera
- Lambdy `health-webhook`, `training-plan-sync`, `api-read` → Faza 1
- Frontend (React/Vite) → Faza 2
- AI advisor + recipe pipeline → Fazy 3 i 4
- Strava → Faza 4
- Targety EventBridge (rules są, ale puste — dodajemy gdy lambdy istnieją)

---

## Pre-requirements (user musi zrobić ręcznie zanim ruszymy ze Step 1)

1. `aws sso login` lokalnie — sprawdzić aktywne creds: `aws sts get-caller-identity`
2. GitHub repo `tlyko/bodysync` istnieje + zpushowany pierwszy commit z aktualnym stanem (CLAUDE.md, docs/, .claude/)
3. Po Step 1: ręcznie ustawić `AWS_ROLE_ARN` jako GitHub variable (nie secret — ARN nie jest wrażliwy) w settings repo

Cloudflare side (równolegle, niezależnie):
- Domena `bodysync.pl` w Cloudflare
- Cloudflare Pages projekt (na razie pusty — frontend dojdzie w Fazie 2)

---

## Sprint 3.5 — HAE cumulative metrics fix + unit conversion + sleep audit + S3 raw archive
Phase: 1A.5 (hotfix Sprint 3)
Estimated effort: ~3.5h (Steps 1-3: ~2h, Step 3.5 unit conversion: ~30min, Step 3.6 sleep audit: ~30min, Steps 4-5: ~30min)
Branch base: `main` (po cleanup `debug/hae-auth-prefix`)

**Driving use case (właściciel):**
> Wieczorem o zmiennej godzinie wbijam się w dashboard i chcę dostać od LLM dinner suggestion na bazie cumulative kcal_in/kcal_active/steps z dzisiaj. Read-time aggregation MUSI być dokładne o dowolnej porze.

**Problem (zaobserwowany w prod DDB po Sprint 3 #33-#35):**
1. **Last-writer-wins na cumulative metrics:** HAE iOS wysyła `Aggregation: Hour` → wartości **godzinowe** (delta tej godziny). 7 mapperów scalar (steps, kcal_active, kcal_basal, kcal_in, protein, fat, carbs) ma SK `BIOMETRY#{date}#{metric}` bez timestamp → ostatnia godzina nadpisuje całość. W prod: `steps=232` zamiast paru tysięcy, `kcal_in=388` zamiast ~1500.
2. **Unit conversion bug (krytyczny):** HAE iOS eksportuje energię w **kJ** (HealthKit SI base unit), nie kcal. Match potwierdzony na live DDB 2026-05-07: `kcal_in = 3594.89` zapisane jako "kcal" → po dzieleniu / 4.184 = **859 kcal** = exactly to co user widzi w Apple Health. Schema `HAEScalarPoint` ignoruje field `units` (siedzi na poziomie `HAEMetric`, ale mapper go nie czyta), zapis raw `qty` jako "kcal".
3. **Sleep `asleep=0` regression:** live DDB pokazuje wszystkie sleep rows z `asleep=0` mimo że `inBed=8.13h` / `awake`/`inBedEnd` są sensowne. Schema `HAESleepPoint` może nie czytać poprawnego field z faktycznego HAE payload (możliwe `asleepCore`/`asleepREM`/`asleepDeep` zamiast `core`/`rem`/`deep`/`asleep`).
4. **Open question — basal_energy 5x identyczne `8518.624`** (2026-05-01..05-05). Po unit conversion ≈2036 kcal/dzień (sensowne), ale identyczność 5 dni sugeruje HAE export quirk lub Apple Health stałą. Investigation post-deploy S3 archive.

**Strategia (decyzja własna planner-a, eskalacja do `architect` jeśli reviewer kwestionuje):**
- **Read-time aggregation, brak materialized view** — sumy są czytane on-demand przez `sum_metric_today` (Query z `begins_with(SK, "BIOMETRY#{date}#{metric}#")`), bez denormalizowanego `BIOMETRY#{date}#steps#TOTAL` który wymagałby UpdateItem ADD lub atomic counter. Decyzja cache'owania na poziomie ADR-006 (advisor on-demand endpoint, równoległy tor) — gdy znamy traffic patterns.
- **Single-point zostaje** dla snapshot metrics: `weight_body_mass`, `body_fat_percentage`, `resting_heart_rate`, `sleep_analysis` (HAE wysyła sumaryczny punkt po pomiarze — replay = overwrite OK).
- **Brak data migration** — DDB sflushowane (96 BIOMETRY usunięte ręcznie 2026-05-07), nowy schemat zacznie napływać po deploy.

**Cumulative metrics (multi-point + timestamp w SK):**

| HAE metric | service.py mapper | nowy SK suffix | value_attr |
|---|---|---|---|
| `step_count` | `_ingest_steps` | `#steps#{ts}` | `count` |
| `active_energy` | `_make_scalar_cumulative("kcal_active","kcal")` | `#kcal_active#{ts}` | `kcal` |
| `basal_energy_burned` | `_make_scalar_cumulative("kcal_basal","kcal")` | `#kcal_basal#{ts}` | `kcal` |
| `dietary_energy` | `_make_scalar_cumulative("kcal_in","kcal")` | `#kcal_in#{ts}` | `kcal` |
| `protein` | `_make_scalar_cumulative("protein","g")` | `#protein#{ts}` | `g` |
| `total_fat` | `_make_scalar_cumulative("fat","g")` | `#fat#{ts}` | `g` |
| `carbohydrates` | `_make_scalar_cumulative("carbs","g")` | `#carbs#{ts}` | `g` |

---

### Step 1: Mappers refactor → cumulative factory + steps update → modyfikuje `apps/api/handlers/health_webhook/service.py`
- **Modyfikuje:**
  - `_ingest_steps` → SK `BIOMETRY#{date}#steps#{point.date.isoformat()}`, attrs `{count: int(point.qty), ...}`, użyj `put_item_idempotent` (replay = noop, jak HRV). Zwraca bool.
  - **Dodaj** factory `_make_scalar_cumulative(short_name, value_key)` — analog do `_make_scalar_upsert` ale: (a) SK z timestamp `#{point.date.isoformat()}`, (b) `put_item_idempotent` zamiast `put_item`, (c) zwraca bool z idempotent op.
  - `_make_scalar_upsert` zostaje bez zmian — używana dla snapshot metrics.
  - `METRIC_HANDLERS` registry — przepiąć 6 scalar mapperów (`active_energy`, `basal_energy_burned`, `dietary_energy`, `protein`, `total_fat`, `carbohydrates`) z `_make_scalar_upsert` na `_make_scalar_cumulative`. **Zostają na upsert:** `resting_heart_rate`, `weight_body_mass`, `body_fat_percentage`.
  - Docstring modułu: zaktualizuj nagłówek o cumulative-vs-snapshot model (zastąp przestarzały komentarz o "PR A obsługuje 2 metryki...").
- **Depends on:** nic (czysty refactor)
- **Test:** `cd apps/api && pytest tests/handlers/health_webhook/test_mappers.py -v`
- **Acceptance:**
  - 7 cumulative mapperów zapisuje SK z timestamp (np. `BIOMETRY#2026-05-07#steps#2026-05-07T14:00:00+02:00`)
  - 4 snapshot mapperów (`weight`, `body_fat`, `resting_hr`, `sleep`) bez timestamp w SK — bez zmian
  - Replay tego samego point dla cumulative → `stored=False` (idempotent)

---

### Step 2: DDB read helpers `sum_metric_today` + `sum_metric_in_range` → modyfikuje `apps/api/shared/dynamo.py`
- **Modyfikuje** (dodaje 2 helpery):
  - `sum_metric_today(user_id: str, metric_short: str, *, value_attr: str, today: date) -> Decimal` — `Query` na `PK = USER#{user_id} AND begins_with(SK, "BIOMETRY#{today.isoformat()}#{metric_short}#")`, sum `Decimal(item[value_attr])` po wszystkich items, zwraca `Decimal(0)` dla pustego setu. Type hint `Decimal` (DDB stored as Decimal, sum precision).
  - `sum_metric_in_range(user_id: str, metric_short: str, *, value_attr: str, start: date, end: date) -> dict[str, Decimal]` — pętla po dniach `[start..end]` wywołuje `sum_metric_today`, zwraca dict `{date_iso: total}`. **Decyzja:** prosty per-day loop > single Query z range filter — DDB Query nie ma `between` na fragment SK, pre-filter w aplikacji jest jaśniejszy (max 7 dni dla weekly = 7 Query × ~3ms — pomijalne).
  - Importy: `from datetime import date, timedelta`, `from decimal import Decimal`.
  - Update docstring modułu o "read aggregations dla cumulative metrics".
- **Depends on:** Step 1 (testowane razem)
- **Test:** `cd apps/api && pytest tests/shared/test_dynamo.py -v`
- **Acceptance:**
  - Happy: 3 hourly steps points (300, 500, 200) → `sum_metric_today(...) == Decimal("1000")`
  - Empty: brak rows tego dnia → `Decimal("0")`
  - Range: 5-day window z różnymi sumami → dict z 5 kluczami
  - PK isolation: user_b nie widzi danych user_a (regression test z 2 userami)

---

### Step 3: Tests update — mappers + handler replay + dynamo helpers → modyfikuje `apps/api/tests/...`
- **Modyfikuje:**
  - `tests/handlers/health_webhook/test_mappers.py` — przeparametryzuj testy 7 cumulative mapperów: assercja że SK kończy się timestampem, multi-point storage (3 calls = 3 items), idempotent replay (drugi call → False). 4 snapshot mapperów zostają jak były.
  - `tests/handlers/health_webhook/test_handler.py` `test_replay_*` — replay full payload → asercja: 7 cumulative metrics `stored=0` po replay, 4 snapshot metrics `stored=count` (overwrite). Update aggregate count assertion.
  - `tests/handlers/health_webhook/fixtures/hae_payload_full.json` — zweryfikować/dodać 2-3 hourly buckets per cumulative metric (deterministyczne ISO timestamps żeby test był reproducible).
  - **Nowy plik** `tests/shared/test_dynamo.py` — testy `sum_metric_today` (happy / empty / 2-user PK isolation) + `sum_metric_in_range` (5-day window).
- **Depends on:** Step 1, Step 2
- **Test:** `cd apps/api && pytest -q` → 41+ pass (28 obecnie + ~6 nowych w test_dynamo + zaktualizowane test_mappers/test_handler)
- **Acceptance:**
  - `pytest -q`: zielone, ≥41 testów
  - `ruff check + ruff format --check + mypy --strict shared/ handlers/`: clean
  - Coverage cumulative path: replay 13 metrics → `stored=0` dla 7 cumulative

---

### Step 3.5: Unit conversion (kJ→kcal) + units validation → modyfikuje `apps/api/handlers/health_webhook/{schemas,service}.py` + tests

**Driving evidence:** live DDB 2026-05-07 `kcal_in=3594.89` (raw kJ od HAE) / 4.184 = **859 kcal** = match na Apple Health UI. HAE iOS używa **HealthKit SI units** dla energii (kJ), nie kcal. Schema obecnie ignoruje `units`.

- **Modyfikuje `apps/api/handlers/health_webhook/schemas.py`:**
  - `HAEMetric.units` jest już `str | None` — nie ruszamy (units siedzi na poziomie metric, nie point — jeden metric = jedna jednostka per payload)
  - **Walidacja per-metric** w service layer (nie w schemas — luźny `extra="allow"` zostaje, fail-fast w mapperze przy nieoczekiwanej jednostce)
- **Modyfikuje `apps/api/handlers/health_webhook/service.py`:**
  - Nowy helper `_convert_energy_to_kcal(qty: float, units: str | None) -> float`:
    - `units in {"kcal","kilocalorie",None}` → `qty` (passthrough; `None` defaultuje do kcal dla backward-compat z fixtures)
    - `units in {"kJ","kilojoule"}` → `qty / 4.184`
    - inne → `raise ValueError(f"unsupported energy units: {units}")`
  - `_make_scalar_cumulative` factory dla 3 energy mapperów (`active_energy`, `basal_energy_burned`, `dietary_energy`) konsumuje `metric.units` z parent `HAEMetric` i wywołuje `_convert_energy_to_kcal` przed zapisem. Storage zawsze w **kcal**.
  - Nowy helper `_validate_units(units: str | None, allowed: set[str], *, metric_name: str)` — wywołany w mapperach dla forward-compat:
    - `step_count` → `{"count", None}`
    - `heart_rate_variability` → `{"ms", None}`
    - `heart_rate`, `resting_heart_rate` → `{"count/min","bpm",None}`
    - `protein`, `total_fat`, `carbohydrates` → `{"g","gram","grams",None}` — fail-loud przy "oz"/"lb" (wykryjemy gdy HAE zmieni format)
    - `weight_body_mass` → `{"kg",None}` (zostawiamy lb fail-loud — Polska metric only)
    - `body_fat_percentage` → `{"%",None}`
  - Sygnatura `_make_scalar_cumulative(short_name, value_key, *, allowed_units, energy_conversion=False)` — energy mapper ustawia `energy_conversion=True`.
- **Modyfikuje `tests/handlers/health_webhook/test_mappers.py`:**
  - Dodaj testy per energy metric (3 metryki × 2 cases):
    - `units="kJ"` payload `qty=3594.89` → DDB row `kcal == 859.0` (rounded ±0.1)
    - `units="kcal"` payload `qty=487.3` → DDB row `kcal == 487.3` (passthrough)
  - Negative test: `protein` z `units="oz"` → `ValidationError` / `ValueError` w mapperze (nie zapisywane)
  - Negative test: `active_energy` z `units="watts"` → `ValueError`
- **Modyfikuje `tests/handlers/health_webhook/fixtures/hae_payload_full.json`:**
  - Zmień `active_energy` na `units="kJ"` z odpowiednio przeskalowanym `qty` żeby docelowy kcal wyszedł sensowny (sanity check że konwersja działa w fixture; protein/fat/carbs zostają `g`)
- **Depends on:** Step 1 (factory exist), Step 3 (test infra)
- **Test:** `cd apps/api && pytest tests/handlers/health_webhook/test_mappers.py -v -k 'units or kJ or convert'`
- **Acceptance:**
  - Energy z `kJ` → DDB w kcal (matematyka: `qty / 4.184` w 4 dec places)
  - Energy z `kcal` → DDB bez zmian
  - Macro z `oz` → ValidationError, payload nie ląduje w DDB (zachowanie partial-write spójne z resztą metryk — całość metryki failuje, inne metryki dalej leca)
  - Replay tego samego payload z `kJ` → idempotent (drugi call `stored=False` mimo konwersji)

---

### Step 3.6: Sleep schema audit + regression test → modyfikuje `apps/api/handlers/health_webhook/schemas.py` + tests

**Driving evidence:** live DDB 2026-05-01..05-07 wszystkie sleep rows mają `asleep=0` mimo `inBed=8.13h` + sensowne `inBedStart`/`inBedEnd`. Mapper coś nie czyta. Hipotezy: (a) HAE wysyła `asleepCore`/`asleepREM`/`asleepDeep` zamiast `core`/`rem`/`deep`/`asleep`, (b) `asleep` jest computed od mappera jako `core+rem+deep` ale fields nie matchują, (c) inny field name (`totalAsleep`, `asleep_total`).

- **Diagnostic step (best-effort, pre-implementation):**
  - Sprawdź `apps/api/tests/fixtures/hae_payload_full.json` — confirmed: używa `asleep`/`core`/`rem`/`deep` (zgodnie ze schemas). Jeśli prod payload faktycznie inne — fixture był wymyślony, nie z prawdziwego HAE.
  - Search w repo: `grep -r "asleepCore\|asleepREM\|asleep_total" apps/` → potwierdzić że nigdzie nie ma alternatywnych nazw
  - **Po deployu Step 4-5 (S3 archive):** `aws s3 cp s3://bodysync-data-{account}/raw/health-auto-export/tomek/2026/05/.../...json` → otworzyć i zobaczyć faktyczny shape `sleep_analysis.data[*]`. Update `HAESleepPoint` z prawdziwymi field names.
- **Modyfikuje `apps/api/handlers/health_webhook/schemas.py`:**
  - `HAESleepPoint` — dodać Field aliases dla wszystkich znanych wariantów (HAE iOS może mieć kilka):
    - `asleep` z aliasem `total_asleep` / `asleepTotal` (TBD po inspect)
    - `core` z aliasem `asleepCore`
    - `rem` z aliasem `asleepREM`
    - `deep` z aliasem `asleepDeep`
    - `awake` z aliasem `awakeMinutes` (jeśli wykryjemy)
  - Użyj `Field(default=None, validation_alias=AliasChoices("asleep", "total_asleep", "asleepTotal"))` żeby Pydantic spróbował każdego po kolei
  - **Computed fallback:** jeśli `asleep is None and (core or rem or deep)` → `asleep = (core or 0) + (rem or 0) + (deep or 0)` w mapperze (nie w schema — schema tylko parsuje raw)
- **Modyfikuje `apps/api/handlers/health_webhook/service.py`:**
  - `_ingest_sleep` — po parsie HAESleepPoint, jeśli `asleep is None or asleep == 0` ale jest `inBed > 0` i jest co najmniej jeden z `core/rem/deep > 0` → log `logger.warning("sleep_asleep_fallback_computed")` + zapisz computed sum. Jeśli wszystko None → log error i skip storage (broken payload).
- **Modyfikuje `tests/handlers/health_webhook/test_mappers.py`:**
  - Test 1 (regression dla bug): payload z `asleepCore=4.32`, `asleepREM=1.85`, `asleepDeep=1.04` (alias variant) + brak `asleep` field → DDB row `asleep ≈ 7.21` (sum)
  - Test 2 (current happy path): payload z `asleep=8.21` (direct field) → DDB row `asleep == 8.21`
  - Test 3 (broken): `inBed=8.0`, brak wszystkich asleep/core/rem/deep → log error, brak DDB row
  - Test 4 (live data shape): payload z `inBed=8.13`, `awake=0.59`, sensowne `inBedStart`/`inBedEnd`, ale `asleep=0` w raw → fallback computed > 0 (regression na live bug)
- **Action item w TODO post-deploy:**
  - [ ] **Po pierwszym S3 archive object od HAE iOS:** download raw JSON, sprawdzić faktyczny shape `sleep_analysis.data[*]`, jeśli mismatch z naszymi aliasami — zaktualizować `AliasChoices` w `HAESleepPoint` w follow-up PR
- **Depends on:** Step 4 (S3 archive musi być deployed żeby zobaczyć raw payload — pierwszy iteracja schema z best-guess aliases, potem follow-up)
- **Test:** `cd apps/api && pytest tests/handlers/health_webhook/test_mappers.py -v -k sleep`
- **Acceptance:**
  - 4 nowe sleep tests pass (regression + happy + broken + live shape)
  - Live data simulation (Test 4) — `asleep > 0` dla nocy z `inBed > 4h`
  - Computed fallback log emitted gdy raw `asleep` brakuje
  - Schema aliases udokumentowane komentarzem z linkiem do tego TODO

---

### Step 3.7: Open question — basal_energy identyczne 5 dni → action item (no fix this PR)

**Evidence:** DDB 2026-05-01..05-05 wszystkie `kcal_basal = 8518.624` (raw kJ → ~2036 kcal/dzień po Step 3.5 conversion). Wartość per-day OK, ale identyczność 5 dni = fishy.

**Hipotezy:**
- HAE export setting "previous days" wysyła ten sam aggregate cumulative dla każdego z N dni (export quirk, nie bug w naszym kodzie)
- Apple Health na danym device zwraca stałą (np. starszy estymator basal calculation, nie dynamic)
- Bug w HAE iOS app

- [ ] **Action item (post-deploy, manual):** po pierwszym webhook w prod z S3 archive:
  - `aws s3 ls s3://bodysync-data-{account}/raw/health-auto-export/tomek/2026/05/...` — sprawdź payload za N kolejnych dni
  - Jeśli HAE wysyła **te same `qty` per dzień w surowym JSON** → HAE quirk, nie bug u nas. Decyzja: accept jako limitation + log warning gdy N kolejnych dni ma identyczny basal_energy → możliwe że LLM advisor ignoruje basal jeśli stale.
  - Jeśli HAE wysyła **różne `qty` ale my zapisujemy te same** → bug w mapper / SK collision; eskalacja do `architect` dla follow-up PR
  - Jeśli stała wartość per device → zgłosić do HAE dev (niski priorytet) lub accept

**Effort budget:** ~10min na inspect, fix tylko jeśli bug u nas.

---

### Step 4: S3 raw archive w handler.py → modyfikuje `apps/api/handlers/health_webhook/handler.py` + nowy `apps/api/shared/s3.py`
- **Tworzy:**
  - `apps/api/shared/s3.py` — `archive_raw_payload(bucket: str, key: str, body: bytes, *, content_type: str = "application/json") -> None`. Lazy boto3 client init (cold start budget). **Brak kompresji** (decyzja: KISS — S3 lifecycle do IA/Glacier robi koszt znikomy; gzip dodaje deps complexity i wymagałby per-key Content-Encoding).
- **Modyfikuje:**
  - `apps/api/handlers/health_webhook/handler.py` — po pomyślnym `_extract_bearer` + `resolve_user_from_bearer` (znamy `user_id`) i przed `ingest()`: zapis raw body do S3 pod kluczem `raw/health-auto-export/{user_id}/{YYYY}/{MM}/{DD}/{ingested_at_iso}.json`.
  - **Best-effort, nie blokujący** — wrap w `try/except Exception`, log `logger.warning("s3_archive_failed", extra={...})`. Webhook zwraca normalne 200 nawet gdy S3 padł (HAE retry storm gdy 5xx > stracone payloady przez S3 outage).
  - Bucket name z env `RAW_BUCKET_NAME` (Lambda env z TF). Jeśli env brak → log error + skip (nie crashuj handlera).
  - Import: `from shared.s3 import archive_raw_payload`.
- **Depends on:** Step 1-3 (test infra istnieje)
- **Test:** `cd apps/api && pytest tests/handlers/health_webhook/test_handler.py::test_s3_archive -v`
  - moto S3 mock (fixture `s3_bucket` w `conftest.py` — dodaj jeśli nie ma)
  - `test_s3_archive_on_success` — assert object exists pod expected key, content == raw body bytes
  - `test_s3_archive_failure_does_not_block_ingest` — `mock_s3_client.put_object.side_effect = Exception("network")` → handler i tak zwraca 200, log warning emitted
- **Acceptance:**
  - Object widoczny pod `raw/health-auto-export/{user_id}/2026/05/07/2026-05-07T14:00:00+00:00.json`
  - S3 outage = 200 + warning, nie 5xx
  - Oba testy zielone

---

### Step 5: Terraform IAM + S3 lifecycle dla raw → modyfikuje `infrastructure/terraform/main.tf` (+ ewentualnie `s3.tf` jeśli osobno)
- **Modyfikuje:**
  - `module "health_webhook"` — dodaj do `extra_iam_statements`:
    ```hcl
    {
      Sid      = "S3ArchiveRawHaePayloads"
      Effect   = "Allow"
      Action   = ["s3:PutObject"]
      Resource = "${aws_s3_bucket.data.arn}/raw/health-auto-export/*"
    }
    ```
  - `environment` w `module "health_webhook"` — dodaj `RAW_BUCKET_NAME = aws_s3_bucket.data.id`.
  - **S3 lifecycle rule** (rozszerz istniejący `aws_s3_bucket_lifecycle_configuration` lub stwórz):
    - `rule { id = "hae-raw-archive"; filter { prefix = "raw/health-auto-export/" } }`
    - Transition `STANDARD_IA` po 30 dniach
    - Transition `GLACIER` po 90 dniach
    - Expiration po 365 dniach
    - Komentarz: "Raw HAE payloads — post-mortem retention, IA/Glacier dla niskiego kosztu"
- **Depends on:** Step 4 (kod konsumuje env)
- **Test:**
  - `cd infrastructure/terraform && terraform fmt -check && terraform validate`
  - PR → terraform-plan workflow → komentarz w PR pokazuje: 1 IAM statement update na lambda role, 1 lifecycle rule, env var update na health-webhook
  - Po merge → terraform-apply → `aws s3api get-bucket-lifecycle-configuration --bucket bodysync-data-{account}` zawiera nowy prefix rule
- **Acceptance:**
  - `terraform plan` po apply = "No changes"
  - Po pierwszym webhook po deploy: object pojawia się w S3, CloudWatch log Lambdy nie ma `AccessDenied`
  - Lifecycle rule active (`aws s3api get-bucket-lifecycle-configuration` JSON pokazuje 3 transitions + expiration)

---

### Step 6: Acceptance smoke + DDB inspect po deploy → manual user action
- **Akcje (post-merge, manualne):**
  - Pierwszy webhook od HAE iOS (telefon Tomka): "Run Now" w HAE app
  - `aws dynamodb query --table-name bodysync-data --key-condition-expression "PK = :pk AND begins_with(SK, :sk)" --expression-attribute-values '{":pk":{"S":"USER#tomek"},":sk":{"S":"BIOMETRY#2026-05-07#steps#"}}'`  → zwraca multiple items
  - `aws s3 ls s3://bodysync-data-{account}/raw/health-auto-export/tomek/2026/05/07/` → lista plików
  - Replay tego samego payload (HAE manual re-trigger) → drugi response `stored=0` dla 7 cumulative
  - **Sanity check:** suma `count` z hourly steps items powinna match `step_count` na zegarku Apple Watch o tym samym czasie (±100 kroków tolerancji)
- **Depends on:** Step 1-5 deployed
- **Test:** manual smoke
- **Acceptance:**
  - Multi-point items w DDB widoczne (≥3 items per metric per dzień, hourly buckets)
  - S3 object widoczny
  - Replay → `stored=0`, log w CloudWatch potwierdza idempotent
  - Daily sum z `sum_metric_today` (lokalny REPL z prod creds) match Apple Watch (±5%)

---

### Decyzja: 1 PR czy 2?

**Rekomendacja: 1 PR** (rozszerzony scope, nadal ~400-500 LOC). Steps 1-3 + 3.5 (units) + 3.6 (sleep) są ze sobą sprzężone: wszystkie modyfikują `service.py` mapper layer + tests, atomic deploy = spójny stan DDB. Step 3.7 to tylko TODO action item (no code). Steps 4-5 (S3 archive) logicznie odrębne ale potrzebne dla Step 3.6 follow-up (raw payload inspection) — best deploy razem.

**Backup plan: 2 PRy** jeśli reviewer kwestionuje scope:
- **PR B1 (Sprint 3.5a):** Steps 1-3 + 3.5 + 3.6 — mappers + units + sleep + helpers + tests (~3h, ~400 LOC)
- **PR B2 (Sprint 3.5b):** Steps 4-5 — S3 archive + IAM + lifecycle (~30min, ~80 LOC)

### Ryzyka i mitygacje
- **R1:** DDB Query z `begins_with` na fragment SK ma większy RCU cost niż GetItem. **M:** dla N≤24 items/dzień/metric = ~1 RCU per Query (DDB rounds). Pomijalne. Jeśli urośnie → ADR-006 zarekomenduje materialized view.
- **R2:** ISO 8601 timestamp w SK — sortowanie lexicographic = chronologic? **TAK** dla fixed-format ISO 8601 z timezone (`...T14:00:00+02:00` < `...T15:00:00+02:00` lex).
- **R3:** S3 outage blokuje webhook. **M:** best-effort `try/except` w handler.py, log warning. HAE retry storm by gorszy.
- **R4:** Migration concern dla istniejących rows ze schematem `BIOMETRY#{date}#steps` — **brak**, owner sflushował 96 items 2026-05-07.
- **R5 (NEW):** Unit conversion fail-loud na `oz`/`lb` może blokować webhook gdy HAE zmieni format w przyszłej wersji iOS. **M:** fail-loud preferred nad silent corruption — ValueError zatrzyma metric w danym payloadzie ale handler `_safe_ingest_metric` (już istnieje) izoluje exception na poziomie pojedynczej metric, inne metryki dalej leca. Webhook zwraca 200 z `partial_failed` count.
- **R6 (NEW):** Sleep schema aliases best-guess bez prawdziwego HAE payload — ryzyko że `AliasChoices` nie matchuje wszystkich wariantów. **M:** Step 3.7 manual inspect S3 archive po deployu + follow-up PR. Computed fallback w mapperze (sum core+rem+deep) zabezpiecza przed `asleep=0` regression nawet jeśli main field name jest inny.
- **R7 (NEW):** Forward-compat units validation może być zbyt strict — np. HAE może wysłać `kJ ` (trailing space) lub `KCal` (mixed case). **M:** w `_validate_units` zrobić `units.strip().lower()` przed lookup w `allowed` set (dodać lowercase wersje do allowed sets w Step 3.5).

### Eskalacja do `architect`
**Nie potrzebne na ten PR.** Decyzja "read-time aggregation vs materialized view" siedzi w kontekście **ADR-006 (advisor on-demand endpoint)** — równoległy tor. Sprint 3.5 odkłada cache'owanie do ADR-006 (gdy znamy traffic patterns dashboardu). Single-table read-time = **default w CLAUDE.md** ("Bez warstw enterprise dla 2 userów").

**Trigger eskalacji:** jeśli reviewer zauważy że >50 items/dzień/metric w DDB (=>1 Query per metric kosztuje 4+ RCU) — wtedy do `architect` dla ADR-006 i potencjalnie GSI/materialized view.

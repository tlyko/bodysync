# ADR-002 — Lambda packaging & layout

**Status:** Accepted (2026-05-06)
**Owner:** Tomek (`tlyko94@gmail.com`)
**Supersedes:** layout w `PROJECT_PLAN.md` sekcja 7 (legacy `terraform/lambda-src/`).
**Blokował:** TODO Step 5 (`/api/auth/google` — pierwsza Lambda).

## Kontekst

CLAUDE.md mówi `infrastructure/terraform/` = TYLKO IaC; kod Lambdy w `apps/api/`. PROJECT_PLAN sekcja 7 i wcześniejsze TODO Step 5 trzymały się starszego wzorca z sprawdzamszlak (`terraform/lambda-src/{fn}/handler.py`). Pierwszy endpoint blokuje się na rozstrzygnięciu — implementer nie może ruszyć bez decyzji gdzie kłaść pliki, jak je pakować i jak Terraform je znajdzie.

Wymagania:
- Python 3.12 ARM64, 7 docelowych Lambd (różne deps: `google-auth`, `gspread`, `anthropic`, `faiss`)
- Cold start tax — bundle size matters; **monorepo zip dla 7 lambd** = 50+ MB i 1.5s init = NIE
- Solo dev "wracający po 3 miesiącach" — czytelność > chwytliwość
- KISS — bez build systemów typu Bazel / serverless framework / CDK
- Sekrety przez SSM (nie env vars), Pydantic dla każdego endpointu, pytest + moto dla testów
- CI/CD: GitHub Actions z OIDC, `terraform apply` na merge

## Rozważane alternatywy

### Opcja A — Per-Lambda folder w `apps/api/handlers/`, build script + `archive_file` (wybrana)

```
apps/api/
├── pyproject.toml              # dev deps (pytest, moto, ruff, mypy) + workspace
├── README.md
├── shared/                     # importowane przez wszystkie handlery
│   ├── __init__.py
│   ├── ssm.py                  # cache w module dict, get_param(name)
│   ├── dynamo.py               # get_item / put_item / query_by_pk_sk_prefix
│   ├── auth.py                 # verify_jwt, verify_webhook_token
│   ├── anthropic_client.py     # wrapper + prompt caching
│   └── logging.py              # structured logger (request_id, user_id)
├── handlers/
│   ├── google_auth/
│   │   ├── handler.py          # def handler(event, context)
│   │   ├── schemas.py          # Pydantic models (input/output)
│   │   ├── service.py          # business logic (testowalne bez event/context)
│   │   └── requirements.txt    # google-auth==2.x, pyjwt==2.x, pydantic==2.x
│   ├── health_webhook/
│   │   ├── handler.py
│   │   ├── schemas.py
│   │   ├── service.py
│   │   └── requirements.txt    # pydantic==2.x (lekko)
│   └── ...
├── tests/
│   ├── conftest.py             # global fixtures: dynamodb_table (moto), ssm_params
│   ├── shared/
│   │   ├── test_dynamo.py
│   │   └── test_auth.py
│   └── handlers/
│       ├── google_auth/
│       │   └── test_handler.py
│       └── ...
├── scripts/
│   └── build.py                # buduje dist/{fn}.zip per handler
└── dist/                       # gitignored, output build.py — input dla Terraform
    ├── google_auth.zip
    └── ...
```

**Build flow (`apps/api/scripts/build.py`):**
1. Dla każdego folderu w `handlers/`:
   1. `pip install -r handlers/{fn}/requirements.txt --target dist/_build/{fn}/ --platform manylinux2014_aarch64 --only-binary=:all:`
   2. Skopiuj `handlers/{fn}/*.py` do `dist/_build/{fn}/`
   3. Skopiuj `shared/` do `dist/_build/{fn}/shared/`
   4. `zip -r dist/{fn}.zip dist/_build/{fn}/.` → `apps/api/dist/{fn}.zip`
2. Skrypt deterministyczny (stałe mtime) — `archive_file` mógłby się unieważnić co commit, ale `dist/` jest gitignored i regenerowane w GHA.

**Terraform integracja (`infrastructure/terraform/modules/lambda/main.tf`):**

```hcl
# variables.tf
variable "function_name"      { type = string }                 # "google-auth"
variable "source_zip"         { type = string }                 # path do apps/api/dist/google_auth.zip
variable "handler"            { type = string default = "handler.handler" }
variable "memory_size"        { type = number default = 512 }
variable "timeout"            { type = number default = 10 }
variable "environment"        { type = map(string) default = {} }
variable "extra_iam_statements" { type = list(any) default = [] }

# main.tf
resource "aws_lambda_function" "this" {
  function_name    = "bodysync-${var.function_name}"
  filename         = var.source_zip
  source_code_hash = filebase64sha256(var.source_zip)
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = var.handler
  memory_size      = var.memory_size
  timeout          = var.timeout
  role             = aws_iam_role.this.arn
  environment      { variables = var.environment }
}

resource "aws_cloudwatch_log_group" "this" {
  name              = "/aws/lambda/bodysync-${var.function_name}"
  retention_in_days = 14
}

resource "aws_iam_role" "this" {
  name = "bodysync-${var.function_name}-exec"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

resource "aws_iam_role_policy_attachment" "basic" {
  role       = aws_iam_role.this.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "extra" {
  count  = length(var.extra_iam_statements) > 0 ? 1 : 0
  role   = aws_iam_role.this.id
  policy = jsonencode({ Version = "2012-10-17", Statement = var.extra_iam_statements })
}
```

**Wywołanie w root `main.tf`:**

```hcl
module "google_auth" {
  source        = "./modules/lambda"
  function_name = "google-auth"
  source_zip    = "${path.module}/../../apps/api/dist/google_auth.zip"
  environment   = { TABLE_NAME = module.dynamodb.table_name }
  extra_iam_statements = [
    { Effect = "Allow", Action = ["dynamodb:GetItem","dynamodb:PutItem"], Resource = module.dynamodb.table_arn },
    { Effect = "Allow", Action = ["ssm:GetParameter"], Resource = "arn:aws:ssm:*:*:parameter/bodysync/*" },
  ]
}
```

**GHA flow:**
1. `terraform-plan.yml` (PR): setup-python → `cd apps/api && python scripts/build.py` → `cd infrastructure/terraform && terraform plan`
2. `terraform-apply.yml` (main): build → apply
3. `apps/api/dist/` w `.gitignore` — build artefakty nigdy nie wpadają do gita

**Plus:**
- Czytelność: solo dev otwiera `apps/api/handlers/google_auth/` i widzi handler + schemas + service + deps + test obok — wszystko jednego miejsca
- Cold start: per-handler bundle = tylko deps który handler używa (`google-auth` Lambda ~3MB, `health-webhook` ~500KB, `ai-advisor` ~5MB z anthropic)
- Refaktor: kod backendu nie wie nic o Terraformie i odwrotnie — można jutro przepisać Lambdy na ECS Fargate / Fly bez ruszania struktury Pythona
- KISS: jeden `build.py`, jeden `pyproject.toml` na cały backend, brak monorepo tooling
- Test: `cd apps/api && pytest` z root projektu po `pip install -e .` z `pyproject.toml`

**Minus:**
- `build.py` musi być solidny i deterministyczny (cache hash invalidation = redeploy każdej Lambdy mimo braku zmian → akceptowalne, deploy <30s)
- Terraform ścieżki względne `${path.module}/../../apps/api/dist/` — kruche jeśli ktoś przeniesie folder. Mitigacja: zmienna `lambda_artifacts_path` na poziomie root.

### Opcja B — Lambda kod w `infrastructure/terraform/lambda-src/` (legacy)

- Plus: jedna ścieżka, Terraform `archive_file` bez build scriptu
- Minus: łamie CLAUDE.md ("infrastructure/terraform/ = TYLKO IaC"), Python ekosystem (pyproject, ruff, mypy, pytest) musi siedzieć obok IaC, refaktor backendu na nie-Terraform target = przeniesienie tysięcy linii

### Opcja C — Monolithic single Lambda function `apps/api/main.py` z wewnętrznym routerem

- Plus: jeden zip, jeden `archive_file`, jeden Lambda — najprostsze
- Minus: cold start tax — każdy handler ładuje wszystkie deps (anthropic + faiss + gspread + google-auth = 50MB+); jedna Lambda = jeden IAM role (nie da się dać `health-webhook` tylko prawa do PUT, a `api-read` tylko do GET); jeden CloudWatch log group dla wszystkiego = trudniejszy debug
- **Decydujące:** narusza least privilege i cold start budget

### Opcja D — Wspólny Lambda Layer dla shared + per-Lambda zip dla handler

- Plus: shared/ raz w layer, handlery są małe
- Minus: dodatkowa abstrakcja; layer attached do Lambda = wersjonowanie layera, deploy w 2 krokach; layer ma 250MB hard limit razem z funkcją — niewiele zyskujemy bo `shared/` to ~5KB
- **Decydujące:** YAGNI dla 7 Lambd które dzielą 5KB Pythona

## Decyzja

**Opcja A — per-Lambda folder w `apps/api/handlers/{fn}/`, build script `apps/api/scripts/build.py`, Terraform konsumuje `apps/api/dist/{fn}.zip`.**

Konkretnie, decyzja per punkt z briefu:

| # | Pytanie | Decyzja |
|---|---|---|
| 1 | Lokalizacja kodu | `apps/api/` (handlery + shared + testy + build script). `infrastructure/terraform/` zostaje TYLKO IaC. |
| 2 | Layout `apps/api/` | `apps/api/handlers/{fn}/{handler.py, schemas.py, service.py, requirements.txt}` + `apps/api/shared/{ssm,dynamo,auth,anthropic_client,logging}.py` + `apps/api/tests/` + `apps/api/scripts/build.py` |
| 3 | Zip packaging | Build script `apps/api/scripts/build.py` (Python, deterministyczny) → `apps/api/dist/{fn}.zip`. Terraform `aws_lambda_function.filename` + `source_code_hash = filebase64sha256(...)`. Bez `archive_file` — bo musimy wcześniej `pip install` deps do zip. |
| 4 | Dependencies | Per-Lambda `requirements.txt`. Pin minor wersji (`google-auth==2.35.*`). Cold start tax = bundle size; nie chcemy `anthropic` w `health-webhook`. Dev deps (pytest/moto/ruff) w `apps/api/pyproject.toml` (nie idą do zipa). |
| 5 | Shared moduły | `apps/api/shared/` — zwykłe Python modules. Build script kopiuje `shared/` do każdego per-Lambda zipa. Import `from shared.auth import verify_jwt`. Brak Lambda layera. |
| 6 | Testy | `apps/api/tests/{shared,handlers/{fn}}/test_*.py`. Global `apps/api/tests/conftest.py` z fixturami `dynamodb_table` (moto) i `ssm_params`. **Każdy test handler pokrywa: happy path, missing auth, invalid payload, error path.** PK isolation test (user_a vs user_b) wymagany dla każdego handlera czytającego DDB. |
| 7 | Local dev | `apps/api/pyproject.toml` z PEP 621 metadata, `[project.optional-dependencies] dev = [pytest, moto, ruff, mypy, pydantic]`. Single venv: `cd apps/api && python -m venv .venv && pip install -e ".[dev]"`. Komendy: `pytest`, `ruff format`, `ruff check`, `mypy shared/ handlers/`. |
| 8 | Terraform | Generic moduł `infrastructure/terraform/modules/lambda/` parametryzowany (`function_name`, `source_zip`, `handler`, `memory_size`, `timeout`, `environment`, `extra_iam_statements`). Tworzy `aws_lambda_function` (python3.12, arm64), `aws_cloudwatch_log_group` (14d retention), `aws_iam_role` (basic exec + extra). Wywołanie w root: `module "google_auth" { source = "./modules/lambda"; source_zip = "${path.module}/../../apps/api/dist/google_auth.zip"; ... }`. |

## Konsekwencje

### Pozytywne

- **Czytelność dla solo deva:** jedna ścieżka do "wszystko o Lambda X" → `apps/api/handlers/X/`
- **Cold start budget zachowany:** per-Lambda bundle ≤ używanych deps. `google-auth` ~3MB init <300ms; `ai-advisor` ~5MB init <500ms.
- **Least privilege:** każda Lambda ma własny IAM role z `extra_iam_statements` (np. `health-webhook` ma tylko PutItem, `api-read` tylko GetItem/Query).
- **Test coverage:** lokalne pytest + moto + responses działa bez AWS, GHA gating na PR.
- **Refaktorowalność:** Lambda kod nie ma żadnej zależności od Terraformu — eject na FastAPI / ECS / Fly = zmiana `build.py` + nowy moduł IaC, ale handlery i shared zostają.
- **Zgodność z CLAUDE.md:** authoritative source spełniony, brak konfliktu.

### Negatywne

- **Build step w GHA:** każdy `terraform plan/apply` wymaga `python build.py` zanim. Czas: ~20s dla 7 Lambd (parallel pip install). Akceptowalne.
- **`source_code_hash`:** każdy build → nowy hash → Terraform widzi diff → redeploy Lambdy. Mitigacja: build deterministyczny (sortowanie plików w zip, fixed mtime). W praktyce: redeploy jest tani (~5s/Lambda).
- **Ścieżki względne w Terraform:** `${path.module}/../../apps/api/dist/...` jest fragile. Mitigacja: jedna zmienna `var.lambda_artifacts_path` na poziomie root, wszystkie moduły referencują ją.
- **Duplikacja `shared/` w każdym zipie:** ~5KB × 7 = 35KB nadmiaru. Pomijalne wobec deps (~3-5MB).
- **`pyproject.toml` w `apps/api/` zarządza tylko dev deps** — production deps są w per-handler `requirements.txt`. Lekka redundancja (pydantic występuje w obu), ale klarowny rozdział "co idzie do Lambdy" vs "co potrzebne do testów".

### Re-evaluation triggers

ADR do przemyślenia gdy:
- Bundle size powyżej 50MB dla jakiejkolwiek Lambdy → ADR o rozważenie Lambda layer dla heavy deps (`anthropic`, `faiss`)
- Build time w GHA >2 min → ADR o cache `pip wheel` lub matrix build
- 3+ Lambdy mają ten sam `requirements.txt` → ADR o common requirements file z `-r ../common.txt`
- Testów >100 i `pytest` >30s → ADR o `pytest-xdist` parallel albo split testów per Lambda

## Referencje

- AWS Lambda deployment package limits: https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html (250MB unzipped, 50MB zipped)
- ARM64 wheels (`--platform manylinux2014_aarch64`): https://docs.aws.amazon.com/lambda/latest/dg/python-package.html#python-package-create-dependencies
- ADR-001 stack baseline (kontekst architektoniczny)
- CLAUDE.md "Struktura katalogów" + "Filozofia pracy"

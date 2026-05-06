# ADR-003 — Terraform file conventions

**Status:** Accepted (2026-05-06)
**Owner:** Tomek (`tlyko94@gmail.com`)
**Refactor target:** `infrastructure/terraform/` (bootstrap + przyszłe Steps 2-5).

## Kontekst

`terraform/` w stylu "enterprise template" (versions.tf + variables.tf z defaultami + outputs.tf) generuje boilerplate który dla solo deva z jednym envem niesie wyłącznie szum:

- **`variables.tf` z defaultami** — parametryzacja "na zapas" gdy nie ma drugiego env'a do podstawienia. Wartości i tak są hardkodowane przez default. `local.X` jest czytelniejsze niż `var.X` z domyślną wartością.
- **`outputs.tf`** — generuje outputy "bo tak" mimo że nikt ich nie konsumuje. ARN role'a do GHA można dostać z `terraform state show aws_iam_role.X` lub `aws iam get-role`. Outputs mają sens tylko gdy są naprawdę używane (cross-module, GHA workflow, manualny copy-paste).
- **`versions.tf` osobno od provider config** — dwa pliki na coś co zawsze idzie razem.

Konwencja zapożyczona ze sprawdzamszlak workspace, gdzie ten układ przeszedł próbę kilku iteracji.

## Decyzja

Każdy Terraform workspace (bootstrap + główny w Step 2) używa **trzech plików konfiguracyjnych**:

| Plik | Zawiera |
|---|---|
| `config.tf` | `terraform {}` blok (`required_version` + `required_providers` + opcjonalnie `backend`) **plus** `provider "aws" {}` z `default_tags`. Wszystko co konfiguruje runtime Terraforma w jednym miejscu. |
| `locals.tf` | Wszystkie **stałe konfiguracyjne** projektu — nazwa projektu, region, github owner/repo, mapy konfigów per-table/lambda, common tags, computed names. **Zero `variable {}`** dopóki nie istnieje drugi env. |
| `main.tf` (+ tematyczne pliki, np. `oidc.tf`, `lambda.tf`) | `data` blocks i `resource` blocks. Bez `provider`, bez `terraform`, bez `locals`. |

**Brak `outputs.tf` chyba że output jest faktycznie konsumowany** — krzykiem deklarowany w PR: "ten output jest używany przez X". Bez konsumenta = nie istnieje.

**Brak `variables.tf` chyba że pojawi się drugi environment** (staging, dev). Dziś jeden env (prod), defaulty zhardkodowane w `locals` — mniej ceremonii, jaśniejszy kod.

### Przykład `config.tf` (główny workspace, Step 2)

```hcl
terraform {
  required_version = "~> 1.9"

  backend "s3" {
    bucket       = "syncbody-tfstate-214598715232"
    key          = "bodysync/terraform.tfstate"
    region       = "eu-west-1"
    encrypt      = true
    use_lockfile = true   # TF 1.10+, S3 .tflock zamiast DDB
  }

  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 6.43.0" }
    archive = { source = "hashicorp/archive", version = "~> 2.7.0" }
  }
}

provider "aws" {
  region = local.aws_region

  default_tags {
    tags = local.tags
  }
}
```

### Przykład `locals.tf`

```hcl
locals {
  project    = "bodysync"
  aws_region = "eu-west-1"

  tags = {
    Project   = local.project
    ManagedBy = "terraform"
  }

  ddb_table = {
    name         = "${local.project}-data"
    billing_mode = "PAY_PER_REQUEST"
    hash_key     = "PK"
    range_key    = "SK"
    attributes = [
      { name = "PK", type = "S" },
      { name = "SK", type = "S" },
    ]
  }

  ssm_params = [
    "anthropic/api_key",
    "google/oauth_client_id",
    "google/oauth_client_secret",
    # ...
  ]
}
```

## Konsekwencje

### Pozytywne

- **Mniej plików** = mniej miejsc do sprawdzenia gdzie żyje konfiguracja
- **Każda stała w `locals.tf`** — solo dev wie gdzie szukać "co tu jest skonfigurowane"
- **`config.tf` to single point of truth** dla runtime'u Terraforma — backend, providery, default_tags razem
- **Brak outputów na zapas** = brak kuszenia "może kiedyś się przyda" → mniej szumu

### Negatywne

- **Lokalny override = zmiana kodu** (nie zmienna z env'a). Akceptowalne dziś (jeden env). Gdy pojawi się drugi (staging) — refactor `local → variable` per case, nie z góry.
- **Brak outputów wymusza `terraform state show`** dla rzeczy typu IAM role ARN. Wystarczy `aws iam get-role --role-name X --query 'Role.Arn' --output text` — jednorazowa akcja przy setupie.
- **Niespójność z dominującą konwencją open-source modułów Terraform** (które mają variables.tf + outputs.tf z definicji). Nie używamy zewnętrznych modułów na poziomie root, więc nie boli.

## Re-evaluation triggers

ADR do przemyślenia gdy:
- Pojawi się drugi environment (staging / dev) → wprowadzamy `variable` per różniąca się rzecz
- Workspace zaczyna konsumować outputy z innego workspace'a (cross-stack) → `outputs.tf` wraca, ale **tylko z konsumowanymi outputami**
- `locals.tf` przekracza ~100 linii albo robi się nieczytelny → split na `locals_X.tf` per domena (np. `locals_lambda.tf`)
- Module pattern (`modules/`) wymaga `variables.tf`/`outputs.tf` per moduł — to OK i nie sprzeczne z ADR; reguła dotyczy **root workspace'u**, nie modułów.

## Referencje

- ADR-001 stack baseline (kontekst architektoniczny)
- Inny projekt `tlyko/sprawdzamszlak` używa tej samej konwencji od ~6 miesięcy bez friction

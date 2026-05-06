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

### Step 1: Bootstrap state backend + GitHub OIDC → `terraform/bootstrap/`
- **Tworzy:**
  - `terraform/bootstrap/main.tf` — S3 bucket `bodysync-tfstate-{account_id}` (versioning + encryption + public-block), DynamoDB table `bodysync-tflock` (PAY_PER_REQUEST, PK=`LockID`)
  - `terraform/bootstrap/oidc.tf` — `aws_iam_openid_connect_provider` dla `token.actions.githubusercontent.com` + IAM role `bodysync-github-actions` z trust policy ograniczoną do repo (`repo:tlyko/bodysync:*`) i polityką pozwalającą na pełny dostęp do tabeli locków, bucketa state oraz `*` na resource'ach z tagiem `Project=bodysync` (najprostszy ABAC do iteracji)
  - `terraform/bootstrap/variables.tf` — `aws_region` (default `eu-west-1`), `github_owner`, `github_repo`
  - `terraform/bootstrap/outputs.tf` — `state_bucket`, `lock_table`, `gh_actions_role_arn`
  - `terraform/bootstrap/versions.tf` — pin AWS provider `~> 5.x`, terraform `~> 1.9`
  - `terraform/bootstrap/README.md` — krótka instrukcja: `terraform init && terraform apply` ręcznie raz, potem nie ruszać
- **State:** lokalny (`terraform.tfstate` zignorowany w `.gitignore`) — bootstrap nie może być w S3 zanim S3 nie istnieje
- **Depends on:** nic (potrzebne creds do AWS lokalnie — pierwsze i ostatnie ręczne odpalenie)
- **Test:**
  - `cd terraform/bootstrap && terraform validate && terraform plan`
  - po apply: `aws s3 ls | grep bodysync-tfstate` i `aws dynamodb describe-table --table-name bodysync-tflock`
  - `aws iam get-role --role-name bodysync-github-actions` zwraca trust policy z `token.actions.githubusercontent.com`
- **Acceptance:** bucket i tabela istnieją, role ARN zapisane w `docs/infra-outputs.json` (manualny `terraform output -json > ../../docs/infra-outputs.json`), `.gitignore` chroni state plik

---

### Step 2: Terraform root + remote state + providery + tagging → `terraform/`
- **Tworzy:**
  - `terraform/versions.tf` — terraform `~> 1.9`, AWS `~> 5.x`, Cloudflare `~> 4.x` (placeholder — provider zadeklarowany ale jeszcze nieużywany)
  - `terraform/backend.tf` — `backend "s3"` z bucket/table z kroku 1
  - `terraform/main.tf` — providery (AWS w eu-west-1, Cloudflare z tokenem z env), `default_tags { Project = "bodysync", Environment = var.environment, ManagedBy = "terraform" }`
  - `terraform/variables.tf` — `environment` (default `prod`), `aws_region`, `domain_name` (default `bodysync.pl`)
  - `terraform/locals.tf` — `name_prefix = "bodysync"`, common tags
  - `terraform/outputs.tf` — pusty na razie
  - `.gitignore` na poziomie repo (`.terraform/`, `*.tfstate*`, `.terraform.lock.hcl` zostawiamy w repo)
- **Depends on:** Step 1 (bucket + lock table muszą istnieć)
- **Test:** `cd terraform && terraform init` (powinien się połączyć z S3 backendem), `terraform validate`, `terraform plan` → "No changes"
- **Acceptance:** `terraform plan` w czystym repo zwraca zero zmian, lock działa (drugi `plan` w drugim terminalu czeka), default tagi widoczne w `plan` jako "would be applied to all resources"

---

### Step 3: GitHub Actions — plan na PR, apply na main → `.github/workflows/`
- **Tworzy:**
  - `.github/workflows/terraform-plan.yml` — trigger: `pull_request` na `main`, paths `terraform/**`. Steps: checkout → setup-terraform → `aws-actions/configure-aws-credentials@v4` z `role-to-assume=${{ vars.AWS_ROLE_ARN }}` → `terraform fmt -check` → `terraform init` → `terraform plan -no-color -out=plan.tfplan` → `actions/github-script` posta plan jako komentarz w PR (skróć jeśli > 65k znaków)
  - `.github/workflows/terraform-apply.yml` — trigger: `push` na `main`, paths `terraform/**`. Steps: checkout → setup-terraform → OIDC creds → `terraform init` → `terraform apply -auto-approve`
  - `permissions:` na poziomie workflowa: `id-token: write`, `contents: read`, `pull-requests: write` (tylko w plan)
  - W repo settings (manualnie, poza Terraformem): GitHub variable `AWS_ROLE_ARN` = output z Step 1
- **Depends on:** Step 1 (rola IAM), Step 2 (musi być co planować — minimum providery)
- **Test:** otwórz dummy PR (np. zmiana komentarza w `terraform/main.tf`) → workflow `terraform-plan` zielony → komentarz z planem na PR → merge → workflow `terraform-apply` zielony → `terraform plan` lokalnie nadal "No changes" (state spójny)
- **Acceptance:** dwa workflowy działają, komentarz z planem widoczny na PR, apply na merge nie wybucha, OIDC działa bez statycznych kluczy

---

### Step 4: Moduły bazowe (DynamoDB, S3, SSM, EventBridge) → `terraform/modules/`
- **Tworzy:**
  - `terraform/modules/dynamodb/` — tabela `bodysync`: PK `PK` (S), SK `SK` (S), GSI-1 (`SK` jako PK, `PK` jako SK), `BillingMode = PAY_PER_REQUEST`, `point_in_time_recovery = true`, `server_side_encryption = enabled`
  - `terraform/modules/s3/` — bucket `bodysync-data-{account_id}`: versioning on, public access block, SSE-S3, lifecycle rule (delete noncurrent versions po 90 dniach)
  - `terraform/modules/ssm/` — zasoby `aws_ssm_parameter` z `lifecycle { ignore_changes = [value] }`: `/bodysync/anthropic-api-key`, `/bodysync/google-client-id`, `/bodysync/google-client-secret`, `/bodysync/allowed-emails`, `/bodysync/jwt-secret`, `/bodysync/google-sa-key`, `/bodysync/webhook-token-tomek`, `/bodysync/webhook-token-partner` (typ `SecureString`, value=`"PLACEHOLDER"` — wartości wpiszemy ręcznie konsolą AWS)
  - `terraform/modules/eventbridge/` — 3 reguły (na razie bez targetów, te dodamy w Fazie 1+):
    - `bodysync-training-sync`: `cron(0 */6 * * ? *)`
    - `bodysync-ai-advisor-daily`: `cron(0 19 * * ? *)` (21:00 CET)
    - `bodysync-ai-advisor-weekly`: `cron(0 18 ? * SUN *)` (20:00 CET)
  - Każdy moduł ma `main.tf`, `variables.tf`, `outputs.tf`
  - `terraform/main.tf` — wywołania modułów + outputy (table_name, bucket_name, role_arn)
- **Depends on:** Step 2, Step 3 (apply przez Actions)
- **Test:** PR z modułami → plan pokazuje ~12-15 nowych zasobów → merge → apply przechodzi → `aws dynamodb describe-table --table-name bodysync` pokazuje GSI-1, `aws ssm get-parameters-by-path --path /bodysync --recursive` zwraca wszystkie placeholdery
- **Acceptance:** wszystkie zasoby utworzone i otagowane `Project=bodysync`, drugi `terraform plan` = "No changes", `ignore_changes` na SSM pozwala ręcznie ustawić wartości bez driftu

---

### Step 5: API Gateway + moduł Lambda + funkcja `google-auth` → pierwszy endpoint
- **Tworzy:**
  - `terraform/modules/api-gateway/` — `aws_apigatewayv2_api` (HTTP), `cors_configuration` (`allow_origins = ["https://bodysync.pl", "http://localhost:5173"]`, methods, headers), default `$default` stage z auto-deploy. **Bez** custom domain (czeka na Cloudflare)
  - `terraform/modules/lambda/` — generic moduł parametryzowany: `function_name`, `source_dir`, `handler`, `environment`, `extra_iam_statements`. Buduje zip (`archive_file`), tworzy `aws_lambda_function` (python3.12, arm64, 512MB, 30s timeout), CloudWatch log group z 14d retention, IAM role z basic execution + `extra_iam_statements`
  - `terraform/lambda-src/shared/` — `__init__.py`, `ssm.py` (cache w module-level dict), `dynamo.py` (helper `get_item`/`put_item` używający `boto3.resource`), `auth.py` (`verify_jwt(token)` → user_id albo raise; używa secret z SSM)
  - `terraform/lambda-src/google_auth/` — `handler.py` (parsuje `id_token` z body, waliduje przez `google.oauth2.id_token.verify_oauth2_token`, sprawdza email na allowliście z SSM, generuje JWT z `PyJWT`, zwraca `{session_token, user_id, name, email}`), `requirements.txt` (`google-auth`, `pyjwt`), `test_handler.py` (pytest+moto+responses: happy path, brak tokenu → 400, email spoza listy → 403, zły token Google → 401)
  - `terraform/main.tf` — wpięcie API GW + integracja `aws_apigatewayv2_integration` + route `POST /api/auth/google` → moduł lambda
  - `tests/conftest.py` — fixtures `dynamodb_table` i `ssm_params` (kopia ze SKILL.md `tester.md`)
- **Depends on:** Step 4 (DynamoDB + SSM muszą istnieć)
- **Test:**
  - `cd terraform/lambda-src && pytest -v` — wszystkie testy zielone
  - `ruff check terraform/lambda-src && ruff format --check terraform/lambda-src`
  - PR → plan → merge → apply
  - `curl -X POST $API_URL/api/auth/google -d '{"id_token":"invalid"}'` → 401
  - (po ręcznym ustawieniu prawdziwych wartości w SSM + Google OAuth client w Cloud Console) flow z prawdziwym tokenem → 200 + JWT
- **Acceptance:** pytest zielony, `terraform plan` = "No changes" po apply, endpoint odpowiada 401 na zły token bez exception, log group w CloudWatch ma wpisy z `logger.info`, JWT można zdekodować i ma `user_id`+`exp` 30 dni

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

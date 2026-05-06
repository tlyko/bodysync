---
description: Checklist przed deployem produkcyjnym
---

Lecimy z release na bodysync.pl. Przejdź checklistę:

## 1. Stan kodu
- [ ] Branch `main` aktualny, brak niezmergowanych branchy
- [ ] Backend: `pytest apps/api/` zielony
- [ ] Frontend: `pnpm -F web test` / `pnpm -F web typecheck` / `pnpm -F web lint` zielone
- [ ] `pip-audit` / `pnpm audit` — brak high/critical (lub świadoma decyzja)

## 2. Security sweep
Wywołaj `security` z zakresem: zmiany od ostatniego release. Jeśli są ⚠️/🚨 — STOP, naprawiamy.

## 3. Terraform
- [ ] `terraform plan` z poziomu `infrastructure/terraform/` pokazany
- [ ] Plan wygląda jak oczekiwany (żadnych nieoczekiwanych destroy/replace)
- [ ] Backup tfstate zrobiony (S3 versioning włączony? jeśli tak — OK)
- [ ] **`aws-infra` review** planu

## 4. Storage / DB
- [ ] DynamoDB: nowe atrybuty / GSI — sprawdzić że nie blokuje istniejących odczytów
- [ ] PK isolation: każda nowa query ma `USER#{id}` w PK condition
- [ ] Backup strategy aktualny (PITR włączony)

## 5. Config
- [ ] `.env.example` aktualny
- [ ] Sekrety w SSM Parameter Store SecureString (Anthropic key, Strava client secret, Health Auto Export webhook secret, Google service account)
- [ ] CSP, CORS, cookies — pod produkcyjne domeny (`bodysync.pl`, `api.bodysync.pl`)

## 6. Integracje
- [ ] Strava webhook URL — produkcyjny endpoint
- [ ] Strava OAuth redirect URIs — prod w app settings
- [ ] Health Auto Export — webhook URL na telefonie wskazuje prod
- [ ] Google Sheets — service account ma read-only access do prawdziwego sheet ID
- [ ] Anthropic API rate limit headroom OK
- [ ] Strava `X-RateLimit-Usage` z ostatnich dni

## 7. Frontend
- [ ] Bundle size — nie urosło >20% bez powodu
- [ ] Lighthouse > 90 perf, > 95 a11y
- [ ] Test na realnych device'ach: iPhone (Health Auto Export source), laptop

## 8. Lambda-specific (Python ARM64)
- [ ] Bundle size sensowny (<5MB unzipped)
- [ ] Memory / timeout: API ~512MB / 10s, advisor (Anthropic) ~1024MB / 30s
- [ ] CloudWatch log groups istnieją z retention 14d
- [ ] Cold start: Python 3.12 + slim deps

## 9. Rollback plan
- [ ] Wiemy jak cofnąć (git tag poprzedniej wersji)
- [ ] Wiemy jak cofnąć Lambdy (Lambda versions / aliases lub redeploy)
- [ ] Wiemy jak cofnąć Terraform (tfstate w S3 versioning, lub git revert + apply)

## 10. Po deployu
- [ ] Smoke test: landing, Google login, dashboard, Strava connect, Anthropic advisor odpowiedź
- [ ] CloudWatch logs z pierwszych 30 min — wyłapanie błędów
- [ ] Sentry / monitoring uruchomiony

Pokaż checklistę, czekaj na potwierdzenie każdego punktu lub świadomy skip.

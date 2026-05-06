---
description: Workflow dla nowej funkcji - od briefu do reviewu
argument-hint: "<krótki opis funkcji>"
---

Realizujemy nową funkcję: **$ARGUMENTS**

## 1. Brief
Zadaj 2-4 pytania doprecyzowujące jeśli opis jest niejasny:
- Co jest deliverable (UI? endpoint? infra change? wszystkie?)
- Edge cases / co MUSI działać
- Co jest poza scope tej iteracji
- Per-user czy dla pary (oboje userzy mają widoczność?)

**Czekaj na odpowiedź właściciela.**

## 2. Plan
Wywołaj `architect` z briefem. Niech zaproponuje:
- Gdzie w strukturze idą zmiany (`apps/api`, `apps/web`, `infrastructure`)
- Czy potrzebny ADR
- Schemat danych (PK/SK pattern w DDB single-table)
- Granice z innymi modułami

Pokaż plan właścicielowi. **Czekaj na akceptację.**

## 3. Specjaliści (równolegle, jeśli plan tego wymaga)
- Funkcja dotyka **AWS / Terraform** → `aws-infra` planuje konkretne zmiany IaC
- Funkcja dotyka **auth / webhooks / sekrety / IAM / prompt injection** → `security` daje wymagania
- Funkcja dotyka **Apple Health / Strava / Google Sheets / Anthropic** → `integrator`
- Funkcja dotyka **UI / dashboard / wizualizacji** → `frontend-designer`

## 4. Implementacja
Sam (główny Claude) lub odpowiedni subagent:
- Mała, recenzowalna zmiana — jeśli funkcja jest duża, rozbij na PR-y
- Testy razem z kodem (pytest dla Lambdy, vitest dla frontu)
- `.env.example` aktualny
- Nowe Terraform variables — opisane
- Dokumentacja inline gdzie złożona logika (biased: WHY, nie WHAT)

## 5. Review
Wywołaj `reviewer` na diff. Zaaplikuj fixy.
- Jeśli były zmiany security-relevant → drugi przebieg `security` na finalnym kodzie
- Jeśli były zmiany w Terraformie → `aws-infra` confirm że plan jest czysty (`terraform plan`)

## 6. Commit
Tylko po LGTM. Konwencjonalny commit message. Branch `feat/<nazwa>`.

## 7. Deploy (jeśli dotyczy)
- Frontend → standardowy proces (Cloudflare Pages auto-deploy z main)
- Backend (Lambda) → build + Terraform apply (przez GHA OIDC, nie lokalnie)
- **Terraform apply zawsze świadomie** — `aws-infra` pokazuje plan, właściciel akceptuje przez merge do main

---
description: Pełen audyt monorepo bodysync (apps + infrastructure) przez agenta auditor
---

Wywołaj subagenta `auditor` żeby zrobił pełen audyt repo bodysync.pl.

Zakres:
- `apps/api/` (Python 3.12 Lambda — Health Auto Export webhook, Strava, Google Sheets, Anthropic API integration)
- `apps/web/` (React + Vite, Cloudflare Pages)
- `infrastructure/terraform/` (AWS — Lambda, DynamoDB single-table, API Gateway, IAM)
- `docs/` (PROJECT_PLAN, TODO, ADRs jeśli już są)

Po otrzymaniu raportu od auditora:
1. Pokaż raport w całości
2. Wskaż **3 najpilniejsze rzeczy** do zaadresowania, w kolejności
3. Dla każdej zaproponuj który subagent powinien wejść (`architect`, `security`, `aws-infra`, `frontend-designer`, `integrator`)
4. **Nie zaczynaj implementacji.** Czekaj na decyzję właściciela.

Sugeruj jako naturalny next step:
- `@architect` — gdy decyzja stackowa / strukturalna jeszcze niedomknięta (ADR brakuje)
- `/security-check` — dla weryfikacji ryzyk security z audytu
- `@integrator` — dla planowania integracji (Apple Health webhook, Strava OAuth, Google Sheets read, Anthropic Haiku call)

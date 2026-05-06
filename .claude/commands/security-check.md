---
description: Sweep bezpieczeństwa przez agenta security
argument-hint: "[opcjonalnie: ścieżka lub obszar np. 'auth', 'webhooks', 'iam', 'health-import']"
---

Wywołaj subagenta `security` żeby przeszedł przez kod i znalazł potencjalne problemy bezpieczeństwa.

Zakres: $ARGUMENTS (jeśli puste — pełen sweep `apps/` + `infrastructure/`)

Szczególnie krytyczne dla bodysync:
- **Health Auto Export webhook signature** — czy weryfikacja shared secret jest stała-czasowa? Czy webhook URL nie wycieka?
- **Strava OAuth + token rotation** — refresh flow, storage w SSM SecureString, scope minimal (`activity:read_all`)
- **Google Sheets read scope** — `https://www.googleapis.com/auth/spreadsheets.readonly` only
- **Anthropic API key** — w SSM SecureString, nie w Lambda env vars, nie w git
- **DDB PK isolation** — query nigdy bez `USER#{id}` w PK condition (cross-user data leakage)
- **JWT cookie** — HttpOnly, Secure, SameSite=Lax, signed with rotating secret
- **Prompt injection** — user-supplied content (np. plan z Sheets) NIE jest w system prompt advisora bez sanity check

Po otrzymaniu raportu:
1. Wyświetl raport
2. Jeśli są findings 🚨 Critical — zaproponuj fix dla każdego po kolei, czekaj na akceptację przed zmianami
3. Jeśli tylko ⚠️ / ℹ️ — zapytaj czy wprowadzać zmiany teraz czy zapisać jako issues do późniejszego rozwiązania

Pamiętaj: dla zmian dotyczących IAM / Terraform / DynamoDB encryption koordynuj z `aws-infra`.

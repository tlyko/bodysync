# Serwer MCP — dane zdrowotne bodysync w rozmowie z Claude

Wystawia dane bodysync jako custom connector w Claude. **Wyłącznie odczyt.**
Decyzje projektowe i ich uzasadnienie: [ADR-010](../../../../docs/adr/ADR-010-mcp-server.md).

## Jak podłączyć

1. W Claude: **Customize → Connectors → `+` → Add custom connector**
2. **Name:** dowolna, np. `bodysync`
3. **Remote MCP server URL:** `https://api.bodysync.pl/mcp`
4. **Advanced settings:** oba pola OAuth zostaw **puste** — Claude zarejestruje
   się sam przez DCR
5. Kliknij **Add**, potem połącz konektor
6. Na ekranie zgody sprawdź, czy zgadza się mail konta, i kliknij **Zezwalam**

Jeśli nie masz aktywnej sesji na `bodysync.pl`, `/authorize` przekieruje Cię
najpierw na login Google i wróci tutaj. Dostęp dostaje wyłącznie konto z
allowlisty 2 maili — tej samej, której używa aplikacja.

## Narzędzia

| Narzędzie | Zwraca | Domyślny zakres |
|---|---|---|
| `get_body_composition` | waga, BMI, % tłuszczu, beztłuszczowa masa, obwody | 90 dni |
| `get_daily_health_metrics` | kcal in/active/basal + bilans, makro, kroki, fazy snu, tętno | dzisiaj |
| `get_health_trends` | jedna metryka w czasie + podsumowanie (first/last/change/min/max/avg) | 30 dni |
| `get_workouts` | ćwiczenia, serie, ciężary, RIR, pogrupowane w sesje | 30 dni |

`get_health_trends` powyżej **60 dni** przełącza się na średnie tygodniowe —
pół roku wartości dziennych zalałoby kontekst modelu. Twardy limit okna: 730 dni.

### Czego tu nie ma

- **Aktywności ze Stravy** — osobny konektor Strava pokrywa to lepiej
- **HRV i Body Battery** — Garmin nie wysyła ich do Apple Health, więc te dane
  nie istnieją w bazie. Nie da się ich dodać bez integracji z Garmin Connect
- **Cokolwiek zapisującego** — serwer nie ma endpointów mutujących, a IAM Lambdy
  nie zawiera `PutItem` na `USER#*`

Instrukcje serwera (`protocol.INSTRUCTIONS`) mówią to modelowi wprost, żeby nie
szukał tych danych i nie brał braku wyniku za zero.

## Architektura

Jedna Lambda (`bodysync-mcp`, 1024 MB) obsługuje siedem tras:

```
POST /mcp                                     JSON-RPC 2.0, wymaga Bearer
GET  /.well-known/oauth-protected-resource    RFC 9728
GET  /.well-known/oauth-authorization-server  RFC 8414
POST /mcp/register                            RFC 7591 DCR
GET  /mcp/authorize                           ekran zgody
POST /mcp/authorize                           wydanie kodu
POST /mcp/token                               wymiana kodu / refresh
```

Zmierzone na produkcji: **881 ms cold start, 2 ms warm**, bundle 13.97 MB.

Protokół pisany ręcznie, bez FastMCP — uzasadnienie i pomiary w ADR-010.
Zgodności ze spec pilnują testy w `tests/handlers/mcp/test_conformance.py`,
walidujące odpowiedzi modelami oficjalnego SDK. **Pakiet `mcp` jest zależnością
wyłącznie dev** — dwa testy-strażniki pilnują, żeby nigdy nie trafił do bundla
Lambdy razem ze swoim `pydantikiem`.

## Bezpieczeństwo

- PKCE **S256** wymagane, `plain` odrzucane
- `redirect_uri` musi być dokładnie zarejestrowanym, a jego host należeć do
  allowlisty (`claude.ai`, `claude.com` przez https; loopback dla Claude Code).
  DCR jest z definicji otwarty — to allowlista decyduje, że kod nie trafi do
  osoby trzeciej
- Kod autoryzacyjny jednorazowy (atomowy delete), TTL 60 s, związany z
  `client_id` + `redirect_uri` + `code_challenge`
- Refresh tokeny rotowane przy każdym użyciu, trzymane jako SHA-256
- Access token podpisany **osobnym** sekretem niż cookie sesyjne — gdyby
  dzieliły klucz, token read-only przeszedłby jako sesja aplikacji i dałby
  pełny zapis

## Sekret

`/bodysync/mcp/token_signing_secret` (SecureString, min. 32 bajty). Terraform
zakłada placeholder; wartość wpisuje owner **po** udanym apply:

```sh
aws ssm put-parameter --name /bodysync/mcp/token_signing_secret \
  --value "$(openssl rand -base64 48)" --type SecureString --overwrite --region eu-west-1
```

Kolejność ma znaczenie: wpisanie wartości **przed** apply kończy się
`ParameterAlreadyExists` i wywala cały apply (patrz ADR-010, sekcja pułapek).

Rotacja sekretu unieważnia wszystkie wydane tokeny — konektor trzeba wtedy
połączyć ponownie.

## Diagnostyka

```sh
# Czy discovery żyje
curl -s https://api.bodysync.pl/.well-known/oauth-protected-resource | jq

# Czy handshake 401 jest poprawny
curl -si -X POST https://api.bodysync.pl/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | grep -i www-authenticate

# Czy parsowanie formularzy działa (regresja base64 z PR #224)
curl -s -X POST https://api.bodysync.pl/mcp/token \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'grant_type=refresh_token&refresh_token=testowy'
# oczekiwane: invalid_grant. `grant_type: None` = body nie dociera do parsera
```

Logi: `/aws/lambda/bodysync-mcp`. Zdarzenia do szukania — `mcp_client_registered`,
`mcp_authorize_granted`, `mcp_token_issued`, `mcp_tool_ok`, `mcp_oauth_error`.

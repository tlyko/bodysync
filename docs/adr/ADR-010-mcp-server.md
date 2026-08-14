# ADR-010 — Serwer MCP dla danych zdrowotnych

**Status:** Accepted (2026-08-14)
**Owner:** Tomek (`tlyko94@gmail.com`)
**Target:** `apps/api/handlers/mcp/` + `infrastructure/terraform/mcp.tf`

## Kontekst

Chcemy wystawić dane bodysync przez Model Context Protocol, żeby Claude czytał je
bezpośrednio w rozmowie (custom connector w ustawieniach Claude). Zakres: **tylko
odczyt**, żadnych operacji zapisu.

Cztery decyzje wymagały rozstrzygnięcia: implementacja protokołu, sposób dostępu do
danych, uwierzytelnienie i zakres narzędzi. Wszystkie cztery poparte pomiarem na
naszym koncie, nie szacunkiem — bo intuicja w dwóch miejscach okazała się błędna.

## Decyzja 1 — surowy JSON-RPC zamiast FastMCP

FastMCP (`mcp.server.fastmcp`) jest de facto standardem w Pythonie, ale jest zbudowany
wokół ASGI i zakłada long-running proces. Na Lambdzie za API Gateway trzeba go zmusić
do `stateless_http=True` + `json_response=True`, bo **API Gateway nie wspiera response
streamingu** — czyli wyłączamy dokładnie te części FastMCP, które są jego przewagą
(sesje, SSE). Zostaje generowanie schematów z type hintów.

Zmierzone bundle (ARM64, `manylinux2014_aarch64`, `--only-binary=:all:` — identycznie
jak `scripts/build.py`):

| Bundle | zip |
|---|---|
| `PyJWT` + `boto3` | **15 MB** |
| `mcp` + `mangum` + `PyJWT` + `boto3` | **22 MB** (+`pydantic` 8.4 MB, +`mcp` 1.5 MB, +`anyio` 1.3 MB, +`jsonschema` 1.1 MB, +`uvicorn` 780 KB, +`click`, +`rpds`, +`starlette`) |

Zmierzone cold starty naszych Lambd (CloudWatch, 30 dni, `eu-west-1`):

| Lambda | bundle | mem | init p50 | warm p50 |
|---|---|---|---|---|
| `activities-list` (PyJWT+boto3) | 13.9 MB | 256 | **684 ms** | 445 ms |
| `api-read` (+pydantic) | 16.3 MB | 512 | **1177 ms** | 12 ms |
| `plan` (+google-api-client) | 30.7 MB | 512 | **1385 ms** | 2733 ms |
| `advisor-chat` (+faiss/numpy/openai) | 36.6 MB | 1024 | **1437 ms** | 6595 ms |

**Init nie skaluje się z megabajtami, tylko z tym, co się importuje.** Skok
13.9→16.3 MB to +493 ms (dochodzi `pydantic`), a 16.3→36.6 MB to tylko +260 ms.
Czyli `pydantic` sam kosztuje ~490 ms — a FastMCP go **wymusza**, bo to fundament SDK.

Surowy handler może `pydantica` nie mieć w ogóle: walidacja inputu MCP to cztery pola
typu string/int, `isinstance` wystarczy. Powierzchnia protokołu dla stateless serwera
read-only to pięć metod: `initialize`, `notifications/initialized`, `tools/list`,
`tools/call`, `ping`. `resources/list` i `prompts/list` odpowiadamy `-32601`, co jest
zgodne ze spec, skoro nie deklarujemy tych capabilities.

**Decyzja:** surowy JSON-RPC 2.0, bez `pydantica`, Lambda 1024 MB (~2× vCPU, ta sama
sztuczka co PR #170). Cel: **~700 ms cold, ~15 ms warm, bundle 15 MB.**

**Mitygacja głównego minusa (dryf względem spec):** testy zgodności pisane **oficjalnym
klientem `mcp`** w `requirements-dev.txt`. SDK weryfikuje handshake, ale nie ląduje
w bundlu Lambdy — pewność zbliżona do FastMCP przy zerowym koszcie cold startu.
Gdy spec się ruszy: bump `mcp` w devach, testy pokażą co się zepsuło.

**Kiedy tę decyzję zrewidować:** jeśli MCP urośnie do kilkunastu narzędzi, dojdą tools
zapisujące, `resources`, `prompts`, elicitation albo sampling — wtedy generowanie
schematów i gotowa obsługa protokołu zwracają się z nawiązką, a 500 ms staje się szumem.

## Decyzja 2 — bezpośredni odczyt z DynamoDB

Rozważane: (a) bezpośrednio DDB, (b) MCP mintuje JWT sekretem z SSM i woła
`api.bodysync.pl`, (c) nowy PAT + nagłówek Bearer w API.

Warianty (b) i (c) płacą **dwa cold starty na jedno wywołanie narzędzia** (MCP + docelowa
Lambda) — przy zmierzonych ~700 ms daje to ~1.4 s, czyli kasuje całą przewagę surowego
JSON-RPC. Wariant (b) dodatkowo tworzy serwis mintujący cudze sesje, co jest grubym celem.

**Decyzja:** bezpośredni `Query` na `bodysync-data` z IAM `dynamodb:LeadingKeys = USER#{id}`.
S3 nie jest potrzebny (Strava poza zakresem — patrz Decyzja 4).

**Koszt:** druga ścieżka odczytu obok REST. Mitygacja: agregacja biometrii wyjeżdża
z `handlers/api_read/service.py` do `shared/biometry.py` i jest współdzielona przez oba
handlery — zero duplikacji logiki (mirror wzorca `shared/http.py` z PR #193).

## Decyzja 3 — OAuth 2.0 DCR, nie sekret w URL

**Pierwotna propozycja — sekret w ścieżce URL — została odrzucona i to słusznie.**
Dokumentacja connectorów mówi wprost, że credential w URL to podatność (URL-e lądują
w logach serwerów, proxy i historii przeglądarki), a spec autoryzacji MCP **zabrania**
tokenów dostępu w query stringu. Wariant ze ścieżką zamiast query to ta sama klasa
problemu.

Wspierane typy auth: `oauth_dcr` i `oauth_cimd` (out of the box), `static_headers`
(**beta**, wg dokumentacji wprowadzany przez administratora organizacji; zgłoszenia
anthropics/claude-ai-mcp #10, #110, #644, #685 raportują, że dialog "Add custom connector"
na planach indywidualnych pokazuje tylko OAuth Client ID/Secret), `none`.

Na Pro/Max realnie zostaje OAuth.

**Decyzja:** własny authorization server w tej samej Lambdzie:

| Endpoint | Rola |
|---|---|
| `POST /mcp` bez tokenu | `401` + `WWW-Authenticate: Bearer resource_metadata="..."` |
| `/.well-known/oauth-protected-resource` | wskazuje na authorization server |
| `/.well-known/oauth-authorization-server` | RFC 8414, `code_challenge_methods_supported: ["S256"]` |
| `POST /register` | RFC 7591 Dynamic Client Registration |
| `GET /authorize` | **sprawdza istniejące cookie `bodysync_session`**; brak → redirect na login Google |
| `POST /token` | `application/x-www-form-urlencoded`, PKCE S256, rotacja refresh tokenów |

Kluczowe: `/authorize` **nie implementuje własnego logowania** — reużywa działający
Google OAuth i allowlistę 2 maili w SSM. Dzięki temu OAuth kosztuje nas pięć endpointów,
a nie własny system tożsamości. Bez nowych zależności (`PyJWT` + `boto3` wystarczą),
więc bundle zostaje 15 MB.

Kody autoryzacyjne i refresh tokeny w DDB z TTL (`PK=MCP_AUTH#{code}`, mirror wzorca
`NONCE#*` z PR #187). Redirect URI: `https://claude.ai/api/mcp/auth_callback`.

**Budżet czasu:** Claude czeka max **10 s** na endpointy OAuth discovery/registration/token
i 30 s na refresh — przy ~700 ms cold starcie mamy zapas.

**Defense in depth:** ruch wychodzący Anthropica pochodzi z `160.79.104.0/21` — można
zawęzić do tego zakresu.

## Decyzja 4 — cztery narzędzia, bez Stravy

Inwentarz `bodysync-data` (scan ~3000 rekordów, 2026-08-14) — co faktycznie mamy:

```
1283  kcal_active      62  resting_hr        19  body_fat
 834  steps            60  kcal_basal        19  lean_body_mass
  72  carbs            53  sleep              3  waist
  72  fat              24  weight             1  biceps
  71  kcal_in          21  bmi                1  chest
  71  protein          82  ACTIVITY          40  WORKOUT
  63  hr
```

**Zero wierszy `hrv`, zero `body_battery`** — nie ma nawet mappera w `health_webhook`.
Garmin nie wysyła HRV ani Body Battery do Apple Health (potwierdza PR #177, który
wyrzucił HRV z UI). Jedyna droga to osobna integracja z Garmin Connect — poza zakresem.

Właściciel ma **osobny MCP ciągnący prosto ze Stravy**, więc dublowanie aktywności
i streamów w bodysync byłoby czystym YAGNI. Wartością bodysync jest złączenie treningu
siłowego ze składem ciała i danymi zdrowotnymi, nie surowe streamy.

**Decyzja — cztery narzędzia, wyłącznie odczyt:**

| Narzędzie | Zwraca |
|---|---|
| `get_body_composition(date_from, date_to)` | waga, BMI, % tłuszczu, lean body mass, obwody manualne |
| `get_daily_health_metrics(date)` | kcal in/active/basal, makro, kroki, sen, tętno spoczynkowe |
| `get_health_trends(metric_name, date_from, date_to)` | dowolna metryka w czasie |
| `get_workouts(date_from, date_to)` | siłownia: ćwiczenie, sety, reps, kg, RIR |

Poza zakresem: Strava, streamy (moc/kadencja), HRV, Body Battery, plan treningowy.

## Konsekwencje

**Pozytywne**

- Cold start na poziomie najszybszej istniejącej Lambdy (~700 ms), warm ~15 ms.
- Zero nowych zależności w bundlu produkcyjnym.
- OAuth reużywa istniejący Google OAuth i allowlistę — brak drugiego systemu tożsamości.
- Zasada PK isolation utrzymana: token OAuth mapuje na `user_id`, IAM wymusza `LeadingKeys`.

**Negatywne / dług**

- Sami absorbujemy zmiany w spec MCP. Mitygacja: testy zgodności oficjalnym klientem.
- Własny authorization server to kod w ścieżce auth — wymaga review przez agenta `security`
  przed mergem (PKCE, rotacja refresh tokenów, TTL kodów, `redirect_uri` allowlist).
- Druga ścieżka odczytu obok REST. Mitygacja: `shared/biometry.py`.
- `static_headers` może wyjść z bety i uprościć całość — wtedy OAuth zostaje jako
  poprawniejszy wariant, ale warto to odnotować przy rewizji.

## Odrzucone alternatywy

| Alternatywa | Powód odrzucenia |
|---|---|
| FastMCP + Mangum na Lambdzie | +490 ms wymuszonego `pydantica` za funkcje wyłączone przez brak SSE w API Gateway |
| FastMCP + Lambda Function URL | Function URL wspiera streaming, więc SSE działa — ale kosztem własnej domeny przez CloudFront zamiast gotowego `api.bodysync.pl` |
| FastMCP na kontenerze always-on | Nowy dostawca + pipeline + ~$5/mies; darmowe tiery (Render/Fly) śpią po 15 min i budzą się 30–60 s, czyli gorzej niż Lambda |
| Sekret w ścieżce/query URL | Zabronione przez spec autoryzacji MCP, niezalecane przez dokumentację connectorów |
| Pełny OAuth z własnym logowaniem | Duplikacja działającego Google OAuth; `/authorize` na cookie jest tańsze |
| MCP przez REST + mintowany JWT | Dwa cold starty na wywołanie (~1.4 s); serwis mintujący cudze sesje = gruby cel |

# ADR-008 — Adaptive TDEE recalculation

**Status:** Accepted (2026-05-11)
**Owner:** Tomek (`tlyko94@gmail.com`)
**Sprint:** 11 (pivot ze Sprint 13 w `docs/backlog-2026-05-10.md` C5; owner odrzucił Daily Brief / Telegram push jako primary feature następnego sprintu)
**Powiązane:** ADR-001 (stack), Sprint 10 baseline TDEE (commit `6758fa5`, `apps/api/handlers/profile_targets/`)

## Kontekst

Sprint 10 dał nam **statyczny TDEE baseline** (Mifflin-St Jeor + activity multiplier + goal modifier — `calculate_bmr` / `calculate_tdee` / `calculate_target_kcal` w `apps/api/handlers/profile_targets/service.py:138-164`). Wartość liczona raz przy onboardingu, persistowana w PROFILE row jako `kcal_target`/`protein_target_g`/`fat_target_g`/`carbs_target_g` + 5 attrs `body_profile` (`height_cm`/`age`/`sex`/`activity_level`/`goal`).

Problem: **multiplier aktywności jest zgadywany** ("moderate 1.55" = 3-5 dni/tydzień). Realny TDEE owner'a może być ±300 kcal od formuły zależnie od NEAT, termogenezy posiłków, retencji wody, real lean mass. MacroFactor zbudował killer feature wokół **adaptacji TDEE do faktycznej waga drift vs kcal_in** — formuła "ile naprawdę spalasz" dominuje formułę "ile statystyczny człowiek twojej wagi spala".

Mamy wszystkie wejścia w DDB:
- `kcal_in` per dzień: SK `BIOMETRY#{date}#kcal_in#{ts}` (cumulative hourly buckets, sum przez `shared.dynamo.sum_metric_today`) — `apps/api/handlers/health_webhook/service.py:386-392`
- `weight` per dzień: SK `BIOMETRY#{date}#weight` (snapshot, last-writer-wins) — `service.py:408-410`
- TDEE baseline w PROFILE: read przez `get_targets()` — `profile_targets/service.py:49-75`

Brakuje: pętli zwrotnej waga drift → korekta TDEE → updated `kcal_target`. Dlatego ten ADR.

**Dlaczego teraz:** owner wpisuje sumiennie wagę i kcal_in od ~Sprint 3 (4+ tygodnie historii = ≥2 okna 14d gotowe). Bez adaptive TDEE comparison vs target z A2 Sprint 10 to porównanie do statycznej liczby — pierwsza iteracja korekty da realistyczny ground truth.

## Decyzja

### 1. Algorytm

```
kcal_in_avg = winsorized_mean(kcal_in last 14d, 10% top + 10% bottom drop)
waga_now    = latest weight in last 3d
waga_then   = closest weight to (today - 14d), within ±2d window
waga_delta_kg = waga_now - waga_then

expected_delta_kcal = (kcal_in_avg - tdee_current) * 14
actual_delta_kcal   = waga_delta_kg * 7700
# Interpretacja: jeśli schudłem MNIEJ niż wynika z deficytu → TDEE niższe niż myślałem
adjustment = (expected_delta_kcal - actual_delta_kcal) / 14
adjustment = clamp(adjustment, -150, +150)              # safety per iteration
tdee_new   = tdee_current + adjustment
tdee_new   = clamp(tdee_new, baseline * 0.7, baseline * 1.5)  # absolute safety
```

Uwaga znak `adjustment`: jeśli `actual_delta < expected_delta` (schudłem mniej / utuczyłem się bardziej niż formuła przewidywała), TDEE current było **przeszacowane** → adjustment dodatni nie ma sensu, lepiej **obniżyć**. Stąd `(expected - actual)` zamiast `(actual - expected)` z briefu — owner łaskawie potwierdzi tę inwersję podczas review (jeden test case w sprintcie).

`1 kg = 7700 kcal` to **przybliżenie fat-only** (real value 7200-7800 dla pure fat loss; lean mass loss to ~1800 kcal/kg). Akceptujemy nieprecyzyjność — i tak `clamp(±150)` chroni przed propagacją błędu.

**Winsorize 10% top/bottom** zamiast raw mean dla `kcal_in_avg` — chroni przed efektem cheat day i dnia z brakującym logiem (kcal_in=200 bo dzień niedoszedł do HAE). Dla 14 dni = drop 1 najwyższego + 1 najniższego, mean z pozostałych 12.

### 2. Cadence

**Dual trigger:**
- **EventBridge cron** co 14d (`rate(14 days)`) — auto, bez user akcji
- **Manual button "Przelicz teraz"** w Settings — `POST /api/tdee/recalc` z JWT

Ten sam handler obsługuje oba — EventBridge event ma kształt `{users: [...]}` (cron iteruje po hardcoded liście 2 userów), HTTP POST single-user z JWT.

### 3. Minimum data quality guard

Przed kalkulacją sprawdź:
- `≥10 dni z kcal_in` w window 14d (drop dni z `kcal_in < 500` jako brakujące)
- `≥10 wag` w window 14d

Jeśli któryś warunek niespełniony → **skip iteration**, persist `tdee_last_recalc = {date, skipped: true, reason: "insufficient_data"}`, return 200 z `skipped=true` (NIE 400 — to nie błąd, to oczekiwane przy onboardingu).

### 4. Storage — rozszerzenie PROFILE entity (NIE osobny TDEE_STATE)

**Decyzja:** dodać 4 nowe attrs do PROFILE row (nie nowy entity type).

| attr | typ | opis |
|---|---|---|
| `tdee_baseline` | int | Mifflin × activity_multiplier (immutable per body_profile change) |
| `tdee_adaptive` | int | current effective TDEE — używany w UI/comparisons |
| `tdee_last_recalc` | map | `{date, before, after, kcal_in_avg, waga_delta_kg, adjustment, capped, skipped, reason}` |
| `tdee_history` | list | append-only audit, **cap 20 entries** (FIFO drop oldest), schema = `tdee_last_recalc` |

**Dlaczego PROFILE, nie osobny TDEE_STATE:**
- Jeden read profilu = wszystko co potrzebne (kcal_target, body_profile, tdee_*). Aktualnie `get_targets()` robi 1 GetItem — adding TDEE_STATE = 2 GetItems w każdym chat turn / dashboard load.
- Skala: `tdee_history[]` × 20 entries × ~150 bytes = 3KB. PROFILE row z attrs = ~5KB max. DDB item limit 400KB — jesteśmy 80× pod limitem.
- Multi-tenant ready: PK `USER#{id}` + SK `PROFILE` już zachowuje izolację, zero migration.

**Trade-off przyjęty:** chart "TDEE evolution" (post-MVP follow-up) ma cap 20 wpisów = ~280 dni historii (20 × 14d). Wystarczy dla 9-miesięcznego okna, dłuższa historia wymagałaby osobnego entity — to świadomie odłożone do momentu kiedy ktoś zechce 2-letni chart.

**Co NIE robimy:** brak osobnego `BIOMETRY#{date}#tdee` snapshotu per dzień. Jeden `tdee_adaptive` w PROFILE = single source of truth, nie ma race conditions z 14-day cron.

### 5. Module boundary

Nowy handler: `apps/api/handlers/tdee_recalc/`
```
tdee_recalc/
├── __init__.py
├── handler.py    # HTTP POST /api/tdee/recalc + EventBridge cron event dispatcher
├── service.py    # pure: recalculate_tdee(profile, biometry_window) -> RecalcResult
└── schemas.py    # RecalcResult, RecalcHistoryEntry
```

Czemu nowy handler a nie rozszerzenie `profile_targets/`:
- Single Responsibility: `profile_targets/` to CRUD + jednorazowy TDEE wizard (Mifflin); `tdee_recalc/` to ongoing pętla zwrotna z BIOMETRY queries.
- EventBridge cron: `profile_targets/` jest HTTP-only, dorzucanie cron event router do tego samego handlera = entanglement.
- Test isolation: `service.py` jako pure function `(profile, weights, kcals) -> RecalcResult` da się testować bez moto (reuse w testach baseline'owych).

**Reuse z `profile_targets/`:**
- `service.update_targets()` do persistowania nowych `kcal_target` + macros (po `recalculate_tdee` callujemy ten sam path = spójność).
- `get_latest_weight_kg()` jako utility — można wynieść do `shared/biometry.py` w follow-up.

### 6. Body profile change — reset czy zachować historię?

**Decyzja: zachować `tdee_history`**, ale zresetować `tdee_baseline` i `tdee_adaptive`:

```
on_body_profile_change(new_profile):
    new_baseline = calculate_tdee(new_profile)          # Mifflin recalc
    profile["tdee_baseline"] = new_baseline
    profile["tdee_adaptive"] = new_baseline             # restart pętli
    profile["tdee_last_recalc"] = None                  # next cron startuje od zera
    # tdee_history zachowane jako audit trail
    profile["tdee_history"].append({
        "date": today,
        "event": "body_profile_change",
        "new_baseline": new_baseline,
    })
```

**Argument:** continuity istnieje w `tdee_history` (badge "TDEE evolved 2280 → 2400 over 60d" ma dane). Stare adjustment values z poprzedniego baseline'u jako **adaptive value** byłyby szkodliwe — owner zmienił aktywność z `moderate` na `heavy` (nowy baseline 2400), zachowanie adaptive 2200 anulowałoby intent zmiany.

### 7. Edge cases

| Sytuacja | Zachowanie |
|---|---|
| Pierwsze 14d po włączeniu — brak historii | `skipped=true`, reason `"insufficient_data"` |
| Brak waga w ±2d window dla `today-14d` | `skipped=true`, reason `"weight_anchor_missing"` |
| `\|waga_delta\| > 3 kg w 14d` | Loguj warning (likely measurement error / hydration anomaly) ale liczy się — clamp ±150 chroni |
| HAE outage (kcal_in=0 przez 3 dni) | Te dni dropowane przez `< 500 kcal` filter, jeśli zostaje <10 dni → skip |
| Body profile change tego samego dnia co cron | Cron read profile po update — używa nowego baseline, history zachowana |
| `kcal_in_avg < 1000` (głodówka / broken data) | Skip + log error `"kcal_in_avg_unrealistic"` (sanity guard, nie korygujemy TDEE bo dane są broken) |

### 8. Macros sync po recalc

Po update `tdee_adaptive`:
1. Apply `goal_modifier` (z body_profile.goal) → nowy `kcal_target`
2. Re-run `suggest_macros(weight_kg, kcal_target)` z `profile_targets/service.py:167`
3. Persist 4 attrs makro (protein/fat/carbs unchanged formula z 1.8 g/kg + 0.9 g/kg, carbs = remainder)

To znaczy: adaptive TDEE auto-aktualizuje cele makro. Owner widzi w UI że "kcal_target zmienił się 2200 → 2280" — w `tdee_history` ma audit dlaczego.

## Konsekwencje

### Pozytywne
- Realny TDEE zamiast formuły populacyjnej — comparison vs target z A2 Sprint 10 staje się ground truth
- MacroFactor-grade feature dla 2 userów za $0 dodatkowy (DDB free tier headroom, brak nowego serwisu)
- Foundation pod B13 Energy balance alerts (Sprint 12+) — alerty operują na `tdee_adaptive` zamiast baseline, dokładniejsze
- Audit trail w `tdee_history` daje data dla future "TDEE evolution chart" widget bez zmian schema
- Dual trigger (cron + manual button) — owner może forsować recalc po długim weekendzie, niedzielne fasting itp.

### Negatywne
- Wymaga **dyscypliny pomiaru** (≥10/14 wag i kcal_in). Real-life dropy = `skipped=true` toast w UI = friction. Mitigacja: skip jest informational nie błąd, frontend pokazuje "następna próba: za 3 dni"
- Retencja wody / weekend overeat false positives mimo `clamp(±150)` — over 90 dni efekt się uśrednia ale w pojedynczej iteracji owner może zobaczyć "TDEE -150 kcal po cheat weekend" mimo że to woda
- Zwiększa złożoność advisor context: `tdee_baseline` vs `tdee_adaptive` w prompt — wymaga update prompt template w `apps/api/handlers/advisor_chat/system_prompt.txt` + decyzja który feed do LLM (rekomendacja: tylko `tdee_adaptive`, baseline jako "diagnostic" dla owner UI tylko)
- 2 nowe IAM permissions dla `tdee_recalc` Lambda (`Query` na BIOMETRY range, `UpdateItem` na PROFILE) — zwiększa terraform footprint o ~30 LOC

### Koszty (DDB free tier headroom)
- Cron co 14d × 2 userów × ~30 RCU per recalc (Query 14d biometry × 2 metryki) = **~4 RCU/dzień średnio**
- Manual button: max 1 click/dzień × 2 userów = **~30 RCU peak/dzień**
- Total: <50 RCU/dzień, 0.0% free tier (DDB on-demand free tier 25 GB + 200M req/m for the free tier)
- Lambda: ~1s execution × 2 cron + ~5 manual/mies = **<1 min compute/mies** = $0

## Alternatywy rozważane

### A. EMA-only weight smoothing (zamiast adaptive TDEE)
- Tylko liczyć `true_weight = EMA(weight, α=0.1)` i pokazać trend
- **Plus:** szybsze, bez korekty TDEE = bez ryzyka false positive
- **Minus:** nie odpowiada na pytanie "ile faktycznie spalam" — zostawia owner'a z populacyjną formułą i nadzieją że pasuje
- **Decyzja:** A5 z Sprint 10 backlog robi to (post-MVP), ortogonalne do tego ADR. Adaptive TDEE używa raw weights z anchor matching, nie EMA — anchor 14d temu vs dziś jest już de-facto smoothing.

### B. Reverse-engineer Whoop/Oura algorithm
- Złożone modele (HRV + sen + RHR jako predictors recovery → wpływ na TDEE)
- **Minus:** brak public spec, każdy producent ma own secret sauce, kalibracja vs Whoop reference niemożliwa bez Whoop
- **Decyzja:** outside scope. 7700 kcal/kg jest peer-reviewed approximation good enough.

### C. Per-day TDEE update (zamiast 14d window)
- Codzienne `tdee_new = tdee_old + (kcal_in_yesterday - tdee_old - waga_delta_yesterday * 7700)`
- **Plus:** szybszy feedback loop
- **Minus:** noise → chaos. Day-to-day waga waha ±0.5 kg z hydration = ±3850 kcal "signal" które jest 90% szum. 14d window jest w MacroFactor docs jako sweet spot.

### D. Osobny entity type `TDEE_STATE#{user_id}`
- PK `USER#{id}`, SK `TDEE_STATE`
- **Plus:** mniej attrs per item w PROFILE, łatwiej zarządzać `tdee_history` (osobny SK per entry: `TDEE_STATE#{date}`)
- **Minus:** każdy chat turn / dashboard load = +1 GetItem (PROFILE + TDEE_STATE), zwiększa cold start tax + RCU. Chart "TDEE evolution" mógłby Query `begins_with(SK, "TDEE_STATE#")` co jest miłe — ale post-MVP kiedy tego potrzebujemy, łatwo zmigrować z PROFILE.history[] do osobnych SK.
- **Decyzja:** PROFILE extension wygrywa dziś. Re-evaluate w ADR-XXX gdy `tdee_history` przekroczy 50 entries lub dojdzie chart widget.

## Open questions (post-MVP)

1. **Premiowanie consistency** — jeśli owner ma >90% dni z log kcal_in przez 30d, czy pozwolić cap ±200 zamiast ±150? Nagroda za dyscyplinę ale dodatkowy state machine. Defer do real usage data.
2. **Chart "TDEE evolution"** — sparkline w Settings tab po 5+ recalc events. Wymaga frontend komponent + endpoint `GET /api/tdee/history` (już mamy w PROFILE.tdee_history, tylko expose).
3. **Weronika onboarding flow** — jak komunikować "skip iteration insufficient_data" w UI bez frustracji? Może toast "Zbieram dane — pierwsza korekta TDEE za X dni" + countdown.
4. **Cross-validation z Strava `kcal_active`** — jeśli `tdee_adaptive` się drastycznie różni od `Mifflin_BMR + sum(kcal_active 14d)/14`, log warning. Cross-check że Strava nie zmienił metryki / HAE nie zaczął wysyłać duplicate kcal.
5. **Macro split static po recalc** — dziś `suggest_macros` używa stałych 1.8 g/kg / 0.9 g/kg. Future: różne split per goal (cut vs bulk vs maintenance) — outside ADR-008 scope.

---

## Podsumowanie decyzji dla `planner` (5 zdań)

1. **Nowy handler `apps/api/handlers/tdee_recalc/`** z `service.recalculate_tdee()` jako pure function (testowalna bez moto) i `handler.py` z dual triggerem `POST /api/tdee/recalc` (manual button) + EventBridge cron `rate(14 days)` iterującym po hardcoded user list.
2. **Storage: extend PROFILE row** o 4 attrs (`tdee_baseline`, `tdee_adaptive`, `tdee_last_recalc`, `tdee_history` cap 20) — zero nowych entity types, zero migracji, jeden GetItem nadal pokrywa cały kontekst profilu.
3. **Algorithm:** winsorized mean kcal_in 14d (drop top/bottom 10%) + waga anchor matching ±2d window + clamp adjustment ±150 kcal/iter + absolute safety `[baseline × 0.7, baseline × 1.5]`; data quality guard ≥10 wag i ≥10 kcal_in/14d → skip z `reason` zamiast 400.
4. **Auto-sync makro:** po każdym recalc reuse `profile_targets.service.suggest_macros()` + `update_targets()` żeby `kcal_target` i 3 makro pola zawsze odpowiadały `tdee_adaptive` (advisor i UI dostają spójne wartości).
5. **Body profile change reset:** `tdee_baseline` i `tdee_adaptive` reset do nowego Mifflin, `tdee_history` zachowana z event marker — continuity audit + brak fałszywej propagacji starych adjustments.

**PR breakdown sugerowany (planner doprecyzuje):**
- PR 1: schemas + pure `service.recalculate_tdee()` + unit testy (15+ test cases edge'ów)
- PR 2: handler.py HTTP POST + IAM (`Query` BIOMETRY + `UpdateItem` PROFILE) + integration test z moto
- PR 3: EventBridge cron + Lambda invoke permission + Terraform module
- PR 4: macros sync hook + reset logic w `profile_targets.update_targets()` (gdy `body_profile` zmieniony)
- PR 5: frontend button "Przelicz teraz" w Settings + display `tdee_adaptive` vs `tdee_baseline` w body_profile section

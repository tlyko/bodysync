# Research konkurencyjny — co fajne aplikacje health/fitness mają, a bodysync.pl jeszcze nie

Data: 2026-05-10
Scope: 10 kategorii × 2-3 features = mapa białych plam względem stanu po Sprint 5+9.
Bazowane na pamięci modelu (Whoop, Oura, Garmin, Strava, MFP, Cronometer, MacroFactor, Hevy, TrainHeroic, TrainingPeaks, Withings, Renpho, Apple Fitness/Health). NIE roadmap, NIE prioritization — samo mapowanie.

## 1. Recovery / Readiness

- **Whoop** — codzienny "Recovery score" 0-100% liczony z HRV nocnego, RHR, snu i poprzedniego strain; ekran rano "ile masz w baku". Bodysync ma HRV + RHR + sen w DDB — mógłby liczyć analogiczny score 0-100 jako pojedynczy stat na Dashboard zamiast trzech osobnych StatCardów.
- **Oura** — "Readiness" agreguje sleep score, body temperature deviation, HRV balance i activity balance, plus "contributors" tooltip który tłumaczy DLACZEGO score jest taki. Bodysync mógłby dodać prosty rozkład "co obniżyło score dziś" (np. "krótszy sen -8, wyższy RHR -5") w expanded card.
- **Garmin Body Battery** — kontinuum 0-100 ładowane snem i odpoczynkiem, drenowane stresem i aktywnością; intra-day chart pokazuje energy curve. Bodysync raczej nie ma intra-day HR variability, ale podobny "battery" liczony 1×/dzień z HRV+sleep+yesterday's TSS jest dostępny.

## 2. Activity insights

- **Strava Premium / Fitness & Freshness** — CTL (Chronic Training Load 42d EWMA), ATL (Acute 7d), TSB = CTL−ATL ("form"); ujemny TSB = zmęczenie, dodatni = świeżość. Bodysync ma activities w DDB — może liczyć CTL/ATL/TSB z `relative_effort` lub HR-based TRIMP i pokazywać "forma" gauge w Aktywności.
- **Garmin Training Status** — klasyfikuje load jako Productive/Maintaining/Overreaching/Detraining + recovery time hours po treningu. Bodysync mógłby wyświetlać heurystyczną klasyfikację (np. "ostatnie 7d load 30% wyższy niż 28d avg → Overreaching") jako advisor hint.
- **VO2max trend** — Garmin/Apple Health estymuje VO2max z HR-pace correlation w bieganiu; trend miesięczny pokazuje aerobic fitness up/down. Apple Health wysyła już `vo2Max` przez HAE — bodysync mógłby ekstraktować i pokazywać 90d sparkline w Ciało tab.



## 3. Nutrition logging

- **MyFitnessPal** — barcode scanner + ogromna baza produktów + szybkie quick-add ostatnio jedzonych posiłków, plus copy-from-yesterday. Bodysync ma kcal_in z HAE (Apple Health) ale brak per-meal logging UI — mógłby dodać prosty "co jadłeś" log z wpisaniem przepisu z biblioteki RAG (139 entries jest gotowe).
- **Cronometer** — micronutrients (witaminy, minerały, omega-3) per posiłek, daily target % na 30+ wartości, nie tylko makro. Bodysync logguje tylko protein/fat/carbs — recipe pipeline mógłby wyciągnąć też mikro z source PDF i pokazać deficyty w Odżywianie tab.
- **MacroFactor** — adaptive TDEE, codziennie rekalkuluje expenditure z waga + kcal_in trend (zamiast statycznej formuły Mifflin), plus "energy availability" alert. Bodysync ma waga z HAE + kcal_in — mógłby liczyć rolling 14d TDEE = (kcal_in_avg − weight_change × 7700/14) i pokazywać jako dynamiczny target zamiast advisor hardcode.

## 4. Training planning

- **Hevy** — set-by-set logbook treningu siłowego (waga × reps × RPE), historia per ćwiczenie, auto-progression suggestions. Bodysync ma plan z Google Sheets (read-only) — mógłby dodać `POST /api/workout/log` z wpisaniem actual sets vs planned, persistencja w DDB jako `WORKOUT_LOG#{date}#{exercise}`.
- **TrainHeroic** — coach assignuje workouty per dzień, klient odhacza i dostaje feedback; calendar view "dziś masz Trening B". Bodysync ma plan A/B/C/D w sheet ale brak per-day assignment — owner sam wybiera. Mógłby dodać "today's workout" hint na Dashboard wyliczony z heurystyki (ostatni done + rotacja).
- **TrainingPeaks / PR tracking** — automatyczny PR detect (najlepszy 5k, 10k, 1RM bench), badge celebration, lifetime PR list. Bodysync ma Strava activities — może liczyć fastest distance per route, longest ride, plus siłowe PR jeśli logbook (#4 powyżej) by powstał.



## 5. Body composition trends

- **Withings / Renpho smart scale** — bio-impedance pomiar body fat %, muscle mass, water %, visceral fat per ważenie + auto-sync do Apple Health. Bodysync ma `bodyFatPercentage` w HAE pipeline — mógłby pokazać body fat sparkline + lean mass = weight × (1 − bf%) chart obok WeightChart.
- **MacroFactor "real trend" filter** — exponential smoothing zamiast raw daily weight, eliminuje noise z hydratacji/sodu/glikogenu; pokazuje 7d EMA jako "true weight" dla decyzji deficyt/nadwyżka. Bodysync ma WeightChart 30d raw — mógłby dodać overlay smoothed line (EMA α=0.1) i pokazać "trend +0.2 kg/tydzień" pod chartem.
- **Withings comparison view** — split lewa/prawa noga muscle balance, neck-to-waist ratio, age estimation; nieco gimmicky ale daje powody do otwarcia appki. Bodysync raczej skip (nie ma sensorów) — ale "lean mass progress" + "waist circumference manual entry" są w zasięgu z minimalnym wysiłkiem.

## 6. AI coaching

- **Whoop Coach** — proaktywne notyfikacje "Twoje recovery 38%, sugeruję easy day" + chat gdzie pyta "ile masz energii?"; reaguje na zmianę score'u sam. Bodysync ma chat z Haiku ale tylko reactive — mógłby dodać daily push (cron 07:00 CET) który push'uje w czat morning briefing wykorzystując RAG i Strava context.
- **Strava Athlete Intelligence** — beta feature: po treningu generuje natural-language summary "Twój 10k w sobotę był 12% szybszy niż średnia ostatnich 6 tygodni, HR niższy o 4 bpm — duży postęp". Bodysync ma activities + Haiku — mógłby dodać `POST /api/activities/{id}/summary` który raz wywołuje LLM i cache'uje per activity.
- **Apple Coach (watchOS 26)** — sugeruje workout per dzień based on Activity rings progress + recovery proxy; presents "Today's plan" tile. Bodysync mógłby exposed analogiczny tile na Dashboard "Sugestia advisora na dziś" z 1-zdaniowym output Haiku z cached morning brief.



## 7. Goals / streaks

- **Apple Fitness rings** — Move (kcal active) / Exercise (min) / Stand (h) trzy circles, "close all 3" daily streak z badge progressów (7d, 30d, perfect month). Bodysync ma kcal_active i kroki — mógłby pokazać 2-3 ring widget na Dashboard z user-set targets z `/api/profile/targets` i streak counter w DDB `STREAK#daily`.
- **Strava annual goals** — ustaw cel "1000 km biegania w 2026" → progress bar + projected completion date based on current pace + miesięczne breakdown. Bodysync ma activities — może agregować distance per sport_type per year i pokazać annual goal tracking na Aktywności tab.
- **Milestone celebrations** — "Twój 100ty trening!", "10 000 km lifetime", konfetti animation + share card. Bodysync może dodać proste DDB counter `MILESTONE#{type}` + frontend toast notification gdy crossed.

## 8. Weekly / monthly recap

- **Whoop Monthly Performance Assessment** — automatycznie generowany raport z mean recovery, sleep consistency, training strain trend, recommendations na następny miesiąc; PDF download + in-app view. Bodysync mógłby dodać EventBridge cron 1ego dnia miesiąca → Lambda generuje markdown raport z poprzedniego miesiąca + wsadza do DDB `RECAP#{YYYY-MM}`, frontend tab "Recaps".
- **Strava Year in Sport** — rocznie animowane podsumowanie z top stats, longest activity, kraje odwiedzone, share-friendly graphics; viral marketing. Bodysync mógłby zrobić prosty `/api/recap/year/{year}` z ascii-art-tier grafiką (bez aspirację Pinterest).
- **Anomaly detection** — "Twoja waga skoczyła +1.2 kg w tygodniu, normalnie waha się ±0.4" lub "RHR ostatnie 3 dni 8 bpm wyżej niż baseline — choroba?". Bodysync ma sequence biometryczne — może liczyć Z-score per metryk i push alert gdy >2σ.



## 9. Couples / shared

- **Apple Activity sharing** — invite partner → ujrzysz jego ringi, ostatnie treningi i bicie kierunkowe ("Twoja Move 280, partnerka 410 — dorównaj"); opcjonalna competition 7-dniowa head-to-head. Bodysync jest 2-tenantowy z założenia para — mógłby dodać tab "Razem" agregujący ostatnie 7d obu userów (kroki, treningi, sen) + delta między partnerami w mini-stats.
- **Strava clubs / shared streaks** — grupa znajomych widzi nawzajem aktywności + comment/kudos; "Wspólne wyzwanie miesiąca: 100 km biegania". Bodysync para mógłby mieć prosty `STREAK#daily#both_logged_workout` counter — "5-dniowa seria razem" + powiadomienie przy złamaniu.
- **Encouragement signals (Apple)** — "Partner zamknął wszystkie 3 ringi 7 dni z rzędu" notyfikacja; lekka grywalizacja bez konkurencji. Bodysync może wysyłać Telegram message gdy partner przekroczy weekly steps target lub wykonał trening dzisiaj.

## 10. Mobile delight

- **Strava share-card export** — po treningu jeden tap → szablon karty PNG z route map, distance, time, HR, gotowe do Stories/Telegrama; viral hook. Bodysync mógłby wygenerować weekly recap card (Canvas API frontend, bez backendowego renderingu) z 5 top stats + bodysync logo, download PNG.
- **watchOS complications + Apple widgets** — kluczowa metryka (recovery score, dziś planowany trening, kcal pozostałe) wprost na watchface lub iOS lock screen, no-tap glance. Bodysync nie ma natywnej app — ale może wystawić proste read-only iOS Shortcuts (per `https://api.bodysync.pl/api/widget/today`) które user wstawia w Apple Shortcuts widget z polling 1×/h.
- **Pull-to-refresh + swipe between tabs + haptics** — natywny mobile feel: pull od góry refresh, swipe lewo/prawo nawiguje między 7 tabami, haptic tick przy każdym tap StatCard. Bodysync ma React SPA — `react-use-gesture` + `navigator.vibrate(10)` to ~50 LOC dla tego całego UX.
- **Auto dark/light mode + system font scale** — respekt iOS Settings → Display → Text Size + Dark Mode Auto. Bodysync ma hardcoded dark — `prefers-color-scheme` media + `rem`-based sizing to relatively cheap upgrade dla a11y.

## Cross-cutting themes

Patterny które powtarzają się przez wiele kategorii i sygnalizują białe plamy w bodysync:

- **Composite scores zamiast raw metryk** — Whoop Recovery, Oura Readiness, Garmin Body Battery, Strava Form/Fitness; wszyscy zwijają 5-10 metryk w jeden 0-100 stat który user ogarnia w 2 sekundy. Bodysync pokazuje raw HRV, RHR, sen osobno — user musi sam syntetyzować "czy dziś pchać czy odpocząć". **Largest single UX delta dostępna z istniejącymi danymi.**

- **Active vs passive consumption (proaktywne push)** — Whoop Coach push "Twoje recovery 38%, easy day", Strava Athlete Intelligence summary po każdym workoucie, Apple Coach "Today's plan" tile. Bodysync ma chat reactive — owner musi otworzyć appkę i zapytać. Daily morning brief 07:00 z Telegram push (#17 telegram bot infra już in-progress) zmienia model konsumpcji.

- **Trends > snapshots** — MacroFactor "true weight" EMA, VO2max trend, CTL/ATL/TSB form, weekly/monthly recap, anomaly detection Z-score; wszyscy patrzą na pochodną i delta nie bezwzględną wartość. Bodysync pokazuje sparkline'y + `trendPct` 7d ale brak długoterminowych trends, baselines, anomaly alerts.

- **Logging UX = retention driver** — MyFitnessPal barcode scan, Hevy set logger, Withings auto-sync, Strava upload z zegarka. Każda fryczna z input = drop-off. Bodysync ma read-only przepływy (HAE webhook, Strava webhook, Sheets read) — brak input UX poza ProfileTargets. **Dodanie nawet jednego logging surface (workout actuals lub meal log) zwiększyłoby stickiness.**

- **Couples-specific feature underexplored** — single-tenant para to unique selling point (vs Strava social-network, vs Apple solo-first). Apple Activity sharing to ledwo zaczyna terenu — bodysync jako "shared dashboard pary z porównaniami i wspólnymi celami" jest niche w którym praktycznie nikt nie konkuruje.

- **Mobile-first delight tax** — dziś bodysync to dashboard responsive (działający na iPhonie), nie "native-feel" app. Pull-to-refresh, swipes, haptics, share cards, widgets — to są low-effort polish items które różnicują "pet project" od "appki której się chce używać codziennie".

- **AI summarization wszechobecna** — Whoop, Strava AI, Apple — każdy LLM context "summary po treningu / monthly recap". Bodysync ma Haiku + RAG ale używa go tylko do reactive Q&A. Same model, wiele cron'owych endpointów (workout summary, weekly recap, anomaly explanation) = ~$0.50/m więcej, dużo więcej value.

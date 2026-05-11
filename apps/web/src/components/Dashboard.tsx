import { type ReactNode, useEffect, useMemo, useState } from 'react';
import { getActivities, getBiometry, getProfileTargets } from '../api';
import {
  buildSeries,
  extractLatestSleepStages,
  latestValue,
  sumSeries,
  trendPct,
  valueForDate,
  type SeriesPoint,
} from '../biometry';
import type { Activity, BiometryDay, Me, ProfileTargets } from '../types';
import { ChatScreen } from './chat/ChatScreen';
import { ActivitiesView } from './dashboard/ActivitiesView';
import { ActivityRow } from './dashboard/ActivityRow';
import {
  DropletIcon,
  EggIcon,
  FlameIcon,
  FootprintsIcon,
  HeartIcon,
  HeartPulseIcon,
  MoonIcon,
  PercentIcon,
  RunIcon,
  ScaleIcon,
  UtensilsIcon,
  WheatIcon,
} from './dashboard/icons';
import { NutritionDonut } from './dashboard/NutritionDonut';
import { PlanScreen } from './dashboard/PlanScreen';
import { ProfileTargetsForm } from './dashboard/ProfileTargetsForm';
import { TDEEAdaptiveCard } from './dashboard/TDEEAdaptiveCard';
import { RangeToggle, type Range } from './dashboard/RangeToggle';
import { SidebarNav, type AppTab } from './dashboard/SidebarNav';
import { SleepStagesCard } from './dashboard/SleepStagesCard';
import { StatCard } from './dashboard/StatCard';
import { TDEECalculatorWizard } from './dashboard/TDEECalculatorWizard';
import { WeightChart } from './dashboard/WeightChart';
import { WorkoutPlanCard } from './dashboard/WorkoutPlanCard';

type Props = {
  me: Me;
  onLogout: () => void;
};

const FETCH_DAYS = 30;

const RANGE_DAYS: Record<Range, number> = { '1d': 1, '7d': 7, '30d': 30 };
const RANGE_TREND_WINDOW: Record<Range, number | null> = { '1d': null, '7d': 3, '30d': 7 };

const PL_DATE = new Intl.DateTimeFormat('pl-PL', {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
  year: 'numeric',
});

const PL_DATE_SHORT = new Intl.DateTimeFormat('pl-PL', {
  day: 'numeric',
  month: 'long',
});

function localTodayIso(): string {
  // Lokalna data użytkownika (browser timezone). Używamy do labelowania
  // "Dziś"/"Wczoraj" względem najnowszego BIOMETRY day.
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, '0');
  const d = String(now.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

function latestDate(days: BiometryDay[]): string | null {
  if (days.length === 0) return null;
  // days może nie być sortowany — bierzemy max po date string (ISO leksyko OK).
  let max = days[0].date;
  for (const d of days) {
    if (d.date > max) max = d.date;
  }
  return max;
}

function rangeLabel(range: Range, latest: string | null): string {
  if (range === '7d') return 'Ostatni tydzień';
  if (range === '30d') return 'Ostatnie 30 dni';
  // 1d view — pokazujemy aktualną datę żeby user wiedział czy widzi dziś
  // (HAE webhook może być opóźniony, najnowszy bucket może być wczorajszy).
  if (!latest) return 'Dziś';
  const today = localTodayIso();
  if (latest === today) return 'Dziś';
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  const yIso = `${yesterday.getFullYear()}-${String(yesterday.getMonth() + 1).padStart(2, '0')}-${String(yesterday.getDate()).padStart(2, '0')}`;
  if (latest === yIso) return `Wczoraj (${PL_DATE_SHORT.format(new Date(latest))})`;
  return `Najnowsze: ${PL_DATE_SHORT.format(new Date(latest))}`;
}

export function Dashboard({ me, onLogout }: Props) {
  const [activeTab, setActiveTab] = useState<AppTab>('overview');
  const [days, setDays] = useState<BiometryDay[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Sprint 10 A2 — targets fetched once na top-level, pass do biometry sections.
  // Brak fetcha = StatCardy renderują bez progress bar (graceful degradation).
  const [targets, setTargets] = useState<ProfileTargets | null>(null);

  useEffect(() => {
    if (days !== null) return;
    if (
      activeTab === 'recipes' ||
      activeTab === 'settings' ||
      activeTab === 'activities' ||
      activeTab === 'plan'
    ) {
      // chat / settings / activities nie wymagają biometry — odłóż fetch
      // jeśli user nigdy nie wejdzie na tab Body/Nutrition/Overview.
      return;
    }
    getBiometry(FETCH_DAYS)
      .then((res) => setDays(res.days))
      .catch((e) => setError(e instanceof Error ? e.message : 'fetch failed'));
  }, [activeTab, days]);

  // Targets fetch — niezależny od tab, mała payload (~6 fields), best-effort
  // (404 brak profile = null = StatCardy bez progress bar).
  useEffect(() => {
    if (targets !== null) return;
    if (
      activeTab === 'recipes' ||
      activeTab === 'settings' ||
      activeTab === 'activities' ||
      activeTab === 'plan'
    ) {
      return;
    }
    getProfileTargets()
      .then(setTargets)
      .catch(() => {
        // Cicho — bez targets dashboard działa jak Sprint 9.
      });
  }, [activeTab, targets]);

  const userLabel = me.name ?? me.email;
  // Sprint 10 A6 — greeting + time-of-day prefix w subtitle.
  // Time-of-day buckets dopasowane do typowego dnia: rano (5-12), popołudnie
  // (12-18), wieczór (18-22), późno (22-5). Greeting na imię (z Me.name)
  // lub fallback email — owner preferuje "Tomek" niż "tlyko94@gmail.com".
  const greeting = useMemo(() => {
    const hour = new Date().getHours();
    let salutation: string;
    if (hour >= 22 || hour < 5) salutation = 'Dobranoc';
    else if (hour < 12) salutation = 'Dzień dobry';
    else if (hour < 18) salutation = 'Cześć';
    else salutation = 'Dobry wieczór';
    // me.name z Google OAuth ma format "Imię Nazwisko" — bierzemy first token
    // żeby dropować nazwisko (greeting bardziej osobiste).
    const firstName = (me.name ?? me.email).split(/[\s@]/)[0];
    return `${salutation}, ${firstName}`;
  }, [me.name, me.email]);
  const todayLabel = useMemo(() => {
    const formatted = PL_DATE.format(new Date());
    return formatted.charAt(0).toUpperCase() + formatted.slice(1);
  }, []);

  return (
    <div className="app-shell">
      <SidebarNav
        active={activeTab}
        onSelect={setActiveTab}
        userLabel={userLabel}
        onLogout={onLogout}
      />
      <main className="app-content">
        <header className="app-content-header">
          <div>
            <h1 className="app-content-title">{TAB_TITLES[activeTab]}</h1>
            <p className="app-content-subtitle">
              {/* Sprint 10 A6 — greeting tylko na overview tab (główny ekran).
                  Inne taby skupione na konkretnym widoku, greeting by się
                  powtarzał i robił szum. */}
              {activeTab === 'overview' && (
                <>
                  <span className="app-content-greeting">{greeting}</span>
                  <span className="app-content-subtitle-sep"> · </span>
                </>
              )}
              {todayLabel}
            </p>
          </div>
        </header>
        <div className="app-content-body">
          {(activeTab === 'overview' || activeTab === 'body' || activeTab === 'nutrition') && (
            <BiometrySection
              tab={activeTab}
              days={days}
              error={error}
              userLabel={userLabel}
              targets={targets}
              onSelectTab={setActiveTab}
            />
          )}
          {activeTab === 'activities' && <ActivitiesView />}
          {activeTab === 'plan' && <PlanScreen />}
          {activeTab === 'recipes' && <ChatScreen />}
          {activeTab === 'settings' && (
            <SettingsView onLogout={onLogout} />
          )}
        </div>
      </main>
    </div>
  );
}

const TAB_TITLES: Record<AppTab, string> = {
  overview: 'Dashboard',
  activities: 'Aktywności',
  plan: 'Plan Treningowy',
  body: 'Ciało',
  nutrition: 'Odżywianie',
  recipes: 'Przepisy AI',
  settings: 'Ustawienia',
};

// ─── Settings view — TDEE wizard + targets form + logout (mobile) ──────

function SettingsView({ onLogout }: { onLogout: () => void }) {
  // refreshKey przycina ProfileTargetsForm po success w wizardzie — wymusza
  // re-fetch celów (wizard PUT-uje, form pokazuje fresh values bez F5).
  const [refreshKey, setRefreshKey] = useState(0);
  return (
    <>
      <TDEECalculatorWizard onTargetsUpdated={() => setRefreshKey((k) => k + 1)} />
      <ProfileTargetsForm key={refreshKey} />
      <TDEEAdaptiveCard key={`tdee-${refreshKey}`} />
      {/* Mobile fallback — sidebar foot z "Wyloguj" jest hidden na mobile
          (bottom nav nie ma miejsca). Settings tab to logiczne miejsce
          na konto/account actions. */}
      <button type="button" className="settings-logout-button" onClick={onLogout}>
        Wyloguj
      </button>
    </>
  );
}

// ─── Biometry section dispatcher ────────────────────────────────────────

type BiometrySectionProps = {
  tab: 'overview' | 'body' | 'nutrition';
  days: BiometryDay[] | null;
  error: string | null;
  userLabel: string;
  targets: ProfileTargets | null;
  onSelectTab: (tab: AppTab) => void;
};

function BiometrySection({ tab, days, error, targets, onSelectTab }: BiometrySectionProps) {
  const [range, setRange] = useState<Range>('30d');

  const sliced = useMemo<BiometryDay[]>(() => {
    if (!days) return [];
    const sorted = [...days].sort((a, b) => a.date.localeCompare(b.date));
    return sorted.slice(-RANGE_DAYS[range]);
  }, [days, range]);

  if (error) return <p className="error">Błąd: {error}</p>;
  if (!days) return <p>Wczytywanie…</p>;
  if (days.length === 0) {
    return (
      <div className="empty">
        <p>
          Brak danych w bazie. Skonfiguruj <strong>Health Auto Export</strong> na telefonie i
          wyślij pierwszy webhook.
        </p>
      </div>
    );
  }

  const trendWindow = RANGE_TREND_WINDOW[range];

  if (tab === 'overview') {
    return (
      <DashboardOverview
        days={sliced}
        range={range}
        onRangeChange={setRange}
        trendWindow={trendWindow}
        targets={targets}
        onSelectTab={onSelectTab}
      />
    );
  }
  if (tab === 'body') {
    return (
      <BodyView days={sliced} range={range} onRangeChange={setRange} trendWindow={trendWindow} />
    );
  }
  return (
    <NutritionView
      days={sliced}
      range={range}
      onRangeChange={setRange}
      trendWindow={trendWindow}
      targets={targets}
    />
  );
}

// ─── Dashboard overview tab (4 top stats + 2-col mid) ───────────────────

type ViewProps = {
  days: BiometryDay[];
  range: Range;
  onRangeChange: (r: Range) => void;
  trendWindow: number | null;
};

type OverviewProps = ViewProps & {
  onSelectTab: (tab: AppTab) => void;
  targets: ProfileTargets | null;
};

function DashboardOverview({
  days,
  range,
  onRangeChange,
  trendWindow,
  targets,
  onSelectTab,
}: OverviewProps) {
  // "Spalone kalorie" = active + basal (Garmin/Apple Total Daily Energy
  // Expenditure). Owner: "nie interesuje mnie kcal aktywne, chce sumę".
  const kcalActiveSeries = buildSeries(days, 'kcal_active');
  const kcalBasalSeries = buildSeries(days, 'kcal_basal');
  const kcalBurned = sumSeries(kcalActiveSeries, kcalBasalSeries);
  const kcalIn = buildSeries(days, 'kcal_in');
  const stepsSeries = buildSeries(days, 'steps');
  const weightSeries = buildSeries(days, 'weight');
  const hrvSeries = buildSeries(days, 'hrv');
  const sleepSeries = buildSeries(days, 'sleep');
  const restingHrSeries = buildSeries(days, 'resting_hr');
  const bodyFatSeries = buildSeries(days, 'body_fat');

  const today = localTodayIso();

  return (
    <>
      <SectionHeader title={`Podsumowanie · ${rangeLabel(range, latestDate(days))}`}>
        <RangeToggle value={range} onChange={onRangeChange} />
      </SectionHeader>

      <div className="stat-grid">
        <MetricStatCard
          label="Spalone kalorie"
          series={kcalBurned}
          unit="kcal"
          accent="orange"
          icon={<FlameIcon />}
          fmt={(v) => Math.round(v).toLocaleString('pl-PL')}
          trendWindow={trendWindow}
        />
        <TodayMetricStatCard
          label="Kcal spożyte"
          series={kcalIn}
          unit="kcal"
          accent="cyan"
          icon={<UtensilsIcon />}
          fmt={(v) => Math.round(v).toLocaleString('pl-PL')}
          trendWindow={trendWindow}
          today={today}
          target={targets?.kcal_target}
        />
        <WeeklyActivitiesCard />
        <MetricStatCard
          label="Kroki"
          series={stepsSeries}
          accent="green"
          icon={<FootprintsIcon />}
          fmt={(v) => Math.round(v).toLocaleString('pl-PL')}
          trendWindow={trendWindow}
        />
        <MetricStatCard
          label="Waga"
          series={weightSeries}
          unit="kg"
          accent="purple"
          icon={<ScaleIcon />}
          fmt={(v) => v.toFixed(1)}
          trendWindow={trendWindow}
        />
      </div>

      <div className="overview-grid">
        <RecentActivitiesPanel onSeeAll={() => onSelectTab('activities')} />

        <div className="overview-right-stack">
          <WorkoutPlanCard onSeePlan={() => onSelectTab('plan')} />

          {/* Sprint 10 A12 — NutritionDonut przeniesiony do NutritionView
              tab (semantic location: makro = Odżywianie). Overview pokazuje
              WorkoutPlanCard + Recovery — bardziej "co teraz" focus zamiast
              "co już zjadłem". */}

          <SectionPanel title="Recovery">
            <div className="mini-stat-grid">
              <MiniStat
                label="HRV"
                value={latestValue(hrvSeries)?.value.toFixed(1) ?? '—'}
                unit="ms"
                accent="cyan"
                icon={<HeartPulseIcon />}
              />
              <MiniStat
                label="Sen"
                value={latestValue(sleepSeries)?.value.toFixed(1) ?? '—'}
                unit="h"
                accent="purple"
                icon={<MoonIcon />}
              />
              <MiniStat
                label="RHR"
                value={
                  latestValue(restingHrSeries)
                    ? Math.round(latestValue(restingHrSeries)!.value).toString()
                    : '—'
                }
                unit="bpm"
                accent="red"
                icon={<HeartIcon />}
              />
              <MiniStat
                label="Body fat"
                value={latestValue(bodyFatSeries)?.value.toFixed(1) ?? '—'}
                unit="%"
                accent="muted"
                icon={<PercentIcon />}
              />
            </div>
          </SectionPanel>
        </div>
      </div>
    </>
  );
}

// "Aktywności (tydzień)" — count z getActivities filtered last 7 days.
// Strava brand orange, brak sparkline (single liczba). Klikalne → zakładka
// Aktywności (przekazujemy onSelectTab via context byłoby over-engineering;
// zostawiamy jako visual-only, owner kliknie tab w sidebar).
function WeeklyActivitiesCard() {
  const [count, setCount] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    getActivities(20)
      .then((res) => {
        if (cancelled) return;
        const cutoffMs = Date.now() - 7 * 24 * 3600 * 1000;
        const recent = res.items.filter((a) => Date.parse(a.start_date) >= cutoffMs);
        setCount(recent.length);
      })
      .catch(() => {
        if (cancelled) return;
        setCount(0);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <StatCard
      label="Aktywności (tydzień)"
      value={count ?? '—'}
      unit={count === 1 ? 'trening' : 'treningów'}
      accent="orange"
      icon={<RunIcon />}
    />
  );
}

function RecentActivitiesPanel({ onSeeAll }: { onSeeAll: () => void }) {
  const [activities, setActivities] = useState<Activity[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    getActivities(3)
      .then((res) => {
        if (cancelled) return;
        setActivities(res.items);
      })
      .catch(() => {
        if (cancelled) return;
        setActivities([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section className="section-panel">
      <div className="section-panel-head">
        <h3 className="section-panel-title">Ostatnie aktywności</h3>
        {activities && activities.length > 0 && (
          <button type="button" className="section-panel-link" onClick={onSeeAll}>
            Wszystkie →
          </button>
        )}
      </div>
      <div>
        {activities === null && <p className="placeholder-text">Wczytywanie…</p>}
        {activities && activities.length === 0 && (
          <div className="recent-activities-empty">
            <p className="placeholder-text">
              Brak aktywności. Połącz konto Strava w zakładce <strong>Aktywności</strong>.
            </p>
            <button type="button" className="section-panel-link" onClick={onSeeAll}>
              Idź do Aktywności →
            </button>
          </div>
        )}
        {activities && activities.length > 0 && (
          <div className="activity-list">
            {activities.map((a) => (
              <ActivityRow key={a.strava_id} activity={a} />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

// ─── Body tab (waga + biometria) ────────────────────────────────────────

function BodyView({ days, range, onRangeChange, trendWindow }: ViewProps) {
  const hrvSeries = buildSeries(days, 'hrv');
  const sleepSeries = buildSeries(days, 'sleep');
  const stepsSeries = buildSeries(days, 'steps');
  const kcalActiveSeries = buildSeries(days, 'kcal_active');
  const kcalBasalSeries = buildSeries(days, 'kcal_basal');
  const kcalBurnedSeries = sumSeries(kcalActiveSeries, kcalBasalSeries);
  const restingHrSeries = buildSeries(days, 'resting_hr');
  const bodyFatSeries = buildSeries(days, 'body_fat');
  const weightSeries = buildSeries(days, 'weight');

  return (
    <>
      <SectionHeader title={`Biometria · ${rangeLabel(range, latestDate(days))}`}>
        <RangeToggle value={range} onChange={onRangeChange} />
      </SectionHeader>

      <div className="stat-grid">
        <MetricStatCard
          label="HRV (avg ms)"
          series={hrvSeries}
          unit="ms"
          accent="cyan"
          icon={<HeartPulseIcon />}
          fmt={(v) => v.toFixed(1)}
          trendWindow={trendWindow}
        />
        <MetricStatCard
          label="Sen"
          series={sleepSeries}
          unit="h"
          accent="purple"
          icon={<MoonIcon />}
          fmt={(v) => v.toFixed(1)}
          trendWindow={trendWindow}
        />
        <MetricStatCard
          label="Kroki"
          series={stepsSeries}
          accent="green"
          icon={<FootprintsIcon />}
          fmt={(v) => Math.round(v).toLocaleString('pl-PL')}
          trendWindow={trendWindow}
        />
        <MetricStatCard
          label="Spalone kalorie"
          series={kcalBurnedSeries}
          unit="kcal"
          accent="orange"
          icon={<FlameIcon />}
          fmt={(v) => Math.round(v).toLocaleString('pl-PL')}
          trendWindow={trendWindow}
        />
        <MetricStatCard
          label="Resting HR"
          series={restingHrSeries}
          unit="bpm"
          accent="red"
          icon={<HeartIcon />}
          fmt={(v) => Math.round(v).toString()}
          trendWindow={trendWindow}
        />
        <MetricStatCard
          label="Body fat"
          series={bodyFatSeries}
          unit="%"
          accent="muted"
          icon={<PercentIcon />}
          fmt={(v) => v.toFixed(1)}
          trendWindow={trendWindow}
        />
      </div>

      {/* Sprint 10 A11 — sleep stages breakdown z najnowszej nocy z danymi.
          HAE wysyła deep/rem/core/awake tylko gdy Apple Watch noszony w nocy.
          Empty state gdy brak żadnego sub-stage. */}
      <SleepStagesCard stages={extractLatestSleepStages(days)} />

      <SectionHeader title="Waga" />
      <WeightChart data={weightSeries.map((p) => ({ date: p.date, weight: p.value }))} />
      <div className="stat-grid">
        <WeightSummaryCards series={weightSeries} rangeLabel={rangeLabel(range, latestDate(days))} />
      </div>
    </>
  );
}

// ─── Nutrition tab ──────────────────────────────────────────────────────

type NutritionProps = ViewProps & { targets: ProfileTargets | null };

function NutritionView({
  days,
  range,
  onRangeChange,
  trendWindow,
  targets,
}: NutritionProps) {
  const kcalInSeries = buildSeries(days, 'kcal_in');
  const proteinSeries = buildSeries(days, 'protein');
  const fatSeries = buildSeries(days, 'fat');
  const carbsSeries = buildSeries(days, 'carbs');
  const today = localTodayIso();

  // Sprint 10 A12 — NutritionDonut centralnie u góry tab Odżywianie
  // (semantic location, owner widzi visual makro split przed numerami).
  const kcalInToday = valueForDate(kcalInSeries, today)?.value ?? 0;
  const proteinToday = valueForDate(proteinSeries, today)?.value ?? 0;
  const fatToday = valueForDate(fatSeries, today)?.value ?? 0;
  const carbsToday = valueForDate(carbsSeries, today)?.value ?? 0;

  return (
    <>
      <SectionHeader title={`Makroskładniki · ${rangeLabel(range, latestDate(days))}`}>
        <RangeToggle value={range} onChange={onRangeChange} />
      </SectionHeader>

      <section className="section-panel nutrition-donut-panel">
        <NutritionDonut
          kcal={kcalInToday}
          proteinG={proteinToday}
          fatG={fatToday}
          carbsG={carbsToday}
          kcalTarget={targets?.kcal_target ?? null}
        />
      </section>

      <div className="stat-grid">
        <TodayMetricStatCard
          label="Kcal spożyte"
          series={kcalInSeries}
          unit="kcal"
          accent="cyan"
          icon={<UtensilsIcon />}
          fmt={(v) => Math.round(v).toLocaleString('pl-PL')}
          trendWindow={trendWindow}
          today={today}
          target={targets?.kcal_target}
        />
        <TodayMetricStatCard
          label="Białko"
          series={proteinSeries}
          unit="g"
          accent="green"
          icon={<EggIcon />}
          fmt={(v) => Math.round(v).toString()}
          trendWindow={trendWindow}
          today={today}
          target={targets?.protein_target_g}
        />
        <TodayMetricStatCard
          label="Tłuszcz"
          series={fatSeries}
          unit="g"
          accent="orange"
          icon={<DropletIcon />}
          fmt={(v) => Math.round(v).toString()}
          trendWindow={trendWindow}
          today={today}
          target={targets?.fat_target_g}
        />
        <TodayMetricStatCard
          label="Węgle"
          series={carbsSeries}
          unit="g"
          accent="pink"
          icon={<WheatIcon />}
          fmt={(v) => Math.round(v).toString()}
          trendWindow={trendWindow}
          today={today}
          target={targets?.carbs_target_g}
        />
      </div>
    </>
  );
}

// ─── Helper components ──────────────────────────────────────────────────

function SectionHeader({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="section-header">
      <h2>{title}</h2>
      {children}
    </div>
  );
}

function SectionPanel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="section-panel">
      <h3 className="section-panel-title">{title}</h3>
      <div>{children}</div>
    </section>
  );
}

type MiniStatProps = {
  label: string;
  value: string;
  unit: string;
  accent: 'cyan' | 'green' | 'orange' | 'purple' | 'red' | 'pink' | 'muted';
  icon: ReactNode;
};

function MiniStat({ label, value, unit, accent, icon }: MiniStatProps) {
  return (
    <div className={`mini-stat mini-stat-accent-${accent}`}>
      <span className="mini-stat-icon">{icon}</span>
      <div className="mini-stat-text">
        <span className="mini-stat-label">{label}</span>
        <span className="mini-stat-value">
          {value} <span className="mini-stat-unit">{unit}</span>
        </span>
      </div>
    </div>
  );
}

type MetricStatCardProps = {
  label: string;
  series: SeriesPoint[];
  unit?: string;
  accent: 'cyan' | 'green' | 'orange' | 'purple' | 'red' | 'pink' | 'muted';
  fmt: (v: number) => string;
  trendWindow: number | null;
  icon?: ReactNode;
};

function MetricStatCard({
  label,
  series,
  unit,
  accent,
  fmt,
  trendWindow,
  icon,
}: MetricStatCardProps) {
  const last = latestValue(series);
  const sparkData = trendWindow === null ? undefined : series.map((p) => p.value);
  const trend = trendWindow === null ? null : trendPct(series, trendWindow);
  return (
    <StatCard
      label={label}
      value={last ? fmt(last.value) : null}
      unit={unit}
      accent={accent}
      icon={icon}
      sparkData={sparkData}
      change={trend}
    />
  );
}

// Wariant MetricStatCard dla manualnych metryk (kcal_in + makro) — pokazuje
// wartość TYLKO jeśli mamy entry dla `today`, inaczej 0. Owner: jeśli HAE
// nie wysłał kcal_in dla dzisiaj, "0 kcal" lepsze niż wczorajsza wartość
// (która myli — wygląda jak dziś już wpisałeś).
type TodayMetricStatCardProps = MetricStatCardProps & {
  today: string;
  target?: number;
};

function TodayMetricStatCard({
  label,
  series,
  unit,
  accent,
  fmt,
  trendWindow,
  icon,
  today,
  target,
}: TodayMetricStatCardProps) {
  const todayPoint = valueForDate(series, today);
  const value = todayPoint?.value ?? 0;
  const sparkData = trendWindow === null ? undefined : series.map((p) => p.value);
  // Trend hide gdy brak today data — "spadek do 0" jest mylący semantycznie.
  // Plus: gdy target podany, progress bar zastępuje sparkline + trend, więc
  // pomijamy je explicit żeby StatCard renderował clean target layout.
  const trend =
    todayPoint && trendWindow !== null && target === undefined
      ? trendPct(series, trendWindow)
      : null;
  return (
    <StatCard
      label={label}
      value={fmt(value)}
      unit={unit}
      accent={accent}
      icon={icon}
      sparkData={target === undefined ? sparkData : undefined}
      change={trend}
      target={target}
      targetValueRaw={target !== undefined ? value : undefined}
    />
  );
}

type WeightSummaryProps = { series: SeriesPoint[]; rangeLabel: string };

function WeightSummaryCards({ series, rangeLabel }: WeightSummaryProps) {
  const deltaLabel = `Zmiana (${rangeLabel.toLowerCase()})`;
  if (series.length === 0) {
    return (
      <>
        <StatCard
          label="Aktualna waga"
          value={null}
          unit="kg"
          accent="green"
          icon={<ScaleIcon />}
        />
        <StatCard label={deltaLabel} value={null} unit="kg" accent="muted" />
        <StatCard label="Średnia" value={null} unit="kg" accent="muted" />
      </>
    );
  }
  const first = series[0].value;
  const last = series[series.length - 1].value;
  const delta = last - first;
  const avg = series.reduce((a, p) => a + p.value, 0) / series.length;
  return (
    <>
      <StatCard
        label="Aktualna waga"
        value={last.toFixed(1)}
        unit="kg"
        accent="green"
        icon={<ScaleIcon />}
      />
      <StatCard
        label={deltaLabel}
        value={`${delta >= 0 ? '+' : ''}${delta.toFixed(1)}`}
        unit="kg"
        accent="muted"
      />
      <StatCard label="Średnia" value={avg.toFixed(1)} unit="kg" accent="muted" />
    </>
  );
}

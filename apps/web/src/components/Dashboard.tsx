import { type ReactNode, useEffect, useMemo, useState } from 'react';
import { getBiometry } from '../api';
import { buildSeries, latestValue, trendPct, type SeriesPoint } from '../biometry';
import type { BiometryDay, Me } from '../types';
import { ChatScreen } from './chat/ChatScreen';
import {
  DropletIcon,
  EggIcon,
  FlameIcon,
  FootprintsIcon,
  HeartIcon,
  HeartPulseIcon,
  MoonIcon,
  PercentIcon,
  ScaleIcon,
  UtensilsIcon,
  WheatIcon,
} from './dashboard/icons';
import { ProfileTargetsForm } from './dashboard/ProfileTargetsForm';
import { RangeToggle, type Range } from './dashboard/RangeToggle';
import { SidebarNav, type AppTab } from './dashboard/SidebarNav';
import { StatCard } from './dashboard/StatCard';
import { WeightChart } from './dashboard/WeightChart';

type Props = {
  me: Me;
  onLogout: () => void;
};

const FETCH_DAYS = 30;

const RANGE_LABELS: Record<Range, string> = {
  '1d': 'Dziś',
  '7d': 'Ostatni tydzień',
  '30d': 'Ostatnie 30 dni',
};
const RANGE_DAYS: Record<Range, number> = { '1d': 1, '7d': 7, '30d': 30 };
const RANGE_TREND_WINDOW: Record<Range, number | null> = { '1d': null, '7d': 3, '30d': 7 };

const PL_DATE = new Intl.DateTimeFormat('pl-PL', {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
  year: 'numeric',
});

export function Dashboard({ me, onLogout }: Props) {
  const [activeTab, setActiveTab] = useState<AppTab>('overview');
  const [days, setDays] = useState<BiometryDay[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (days !== null) return;
    if (activeTab === 'recipes' || activeTab === 'settings' || activeTab === 'activities') {
      // chat / settings / activities nie wymagają biometry — odłóż fetch
      // jeśli user nigdy nie wejdzie na tab Body/Nutrition/Overview.
      return;
    }
    getBiometry(FETCH_DAYS)
      .then((res) => setDays(res.days))
      .catch((e) => setError(e instanceof Error ? e.message : 'fetch failed'));
  }, [activeTab, days]);

  const userLabel = me.name ?? me.email;
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
            <p className="app-content-subtitle">{todayLabel}</p>
          </div>
        </header>
        <div className="app-content-body">
          {(activeTab === 'overview' || activeTab === 'body' || activeTab === 'nutrition') && (
            <BiometrySection
              tab={activeTab}
              days={days}
              error={error}
              userLabel={userLabel}
            />
          )}
          {activeTab === 'activities' && <ActivitiesPlaceholder />}
          {activeTab === 'recipes' && <ChatScreen />}
          {activeTab === 'settings' && <ProfileTargetsForm />}
        </div>
      </main>
    </div>
  );
}

const TAB_TITLES: Record<AppTab, string> = {
  overview: 'Dashboard',
  activities: 'Aktywności',
  body: 'Ciało',
  nutrition: 'Odżywianie',
  recipes: 'Przepisy AI',
  settings: 'Ustawienia',
};

// ─── Biometry section dispatcher ────────────────────────────────────────

type BiometrySectionProps = {
  tab: 'overview' | 'body' | 'nutrition';
  days: BiometryDay[] | null;
  error: string | null;
  userLabel: string;
};

function BiometrySection({ tab, days, error }: BiometrySectionProps) {
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

function DashboardOverview({ days, range, onRangeChange, trendWindow }: ViewProps) {
  const kcalActive = buildSeries(days, 'kcal_active');
  const kcalIn = buildSeries(days, 'kcal_in');
  const stepsSeries = buildSeries(days, 'steps');
  const weightSeries = buildSeries(days, 'weight');
  const hrvSeries = buildSeries(days, 'hrv');
  const sleepSeries = buildSeries(days, 'sleep');
  const restingHrSeries = buildSeries(days, 'resting_hr');
  const bodyFatSeries = buildSeries(days, 'body_fat');

  return (
    <>
      <SectionHeader title={`Podsumowanie · ${RANGE_LABELS[range]}`}>
        <RangeToggle value={range} onChange={onRangeChange} />
      </SectionHeader>

      <div className="stat-grid">
        <MetricStatCard
          label="Kcal aktywne"
          series={kcalActive}
          unit="kcal"
          accent="orange"
          icon={<FlameIcon />}
          fmt={(v) => Math.round(v).toString()}
          trendWindow={trendWindow}
        />
        <MetricStatCard
          label="Kcal spożyte"
          series={kcalIn}
          unit="kcal"
          accent="cyan"
          icon={<UtensilsIcon />}
          fmt={(v) => Math.round(v).toLocaleString('pl-PL')}
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

        <SectionPanel title="Ostatnie aktywności">
          <p className="placeholder-text">
            Strava jeszcze nie zintegrowana — pojawi się tu lista treningów.
          </p>
        </SectionPanel>
      </div>
    </>
  );
}

// ─── Body tab (waga + biometria) ────────────────────────────────────────

function BodyView({ days, range, onRangeChange, trendWindow }: ViewProps) {
  const hrvSeries = buildSeries(days, 'hrv');
  const sleepSeries = buildSeries(days, 'sleep');
  const stepsSeries = buildSeries(days, 'steps');
  const kcalActiveSeries = buildSeries(days, 'kcal_active');
  const restingHrSeries = buildSeries(days, 'resting_hr');
  const bodyFatSeries = buildSeries(days, 'body_fat');
  const weightSeries = buildSeries(days, 'weight');

  return (
    <>
      <SectionHeader title={`Biometria · ${RANGE_LABELS[range]}`}>
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
          label="Kcal aktywne"
          series={kcalActiveSeries}
          unit="kcal"
          accent="orange"
          icon={<FlameIcon />}
          fmt={(v) => Math.round(v).toString()}
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

      <SectionHeader title="Waga" />
      <WeightChart data={weightSeries.map((p) => ({ date: p.date, weight: p.value }))} />
      <div className="stat-grid">
        <WeightSummaryCards series={weightSeries} rangeLabel={RANGE_LABELS[range]} />
      </div>
    </>
  );
}

// ─── Nutrition tab ──────────────────────────────────────────────────────

function NutritionView({ days, range, onRangeChange, trendWindow }: ViewProps) {
  const kcalInSeries = buildSeries(days, 'kcal_in');
  const proteinSeries = buildSeries(days, 'protein');
  const fatSeries = buildSeries(days, 'fat');
  const carbsSeries = buildSeries(days, 'carbs');

  return (
    <>
      <SectionHeader title={`Makroskładniki · ${RANGE_LABELS[range]}`}>
        <RangeToggle value={range} onChange={onRangeChange} />
      </SectionHeader>
      <div className="stat-grid">
        <MetricStatCard
          label="Kcal spożyte"
          series={kcalInSeries}
          unit="kcal"
          accent="cyan"
          icon={<UtensilsIcon />}
          fmt={(v) => Math.round(v).toLocaleString('pl-PL')}
          trendWindow={trendWindow}
        />
        <MetricStatCard
          label="Białko"
          series={proteinSeries}
          unit="g"
          accent="green"
          icon={<EggIcon />}
          fmt={(v) => Math.round(v).toString()}
          trendWindow={trendWindow}
        />
        <MetricStatCard
          label="Tłuszcz"
          series={fatSeries}
          unit="g"
          accent="orange"
          icon={<DropletIcon />}
          fmt={(v) => Math.round(v).toString()}
          trendWindow={trendWindow}
        />
        <MetricStatCard
          label="Węgle"
          series={carbsSeries}
          unit="g"
          accent="pink"
          icon={<WheatIcon />}
          fmt={(v) => Math.round(v).toString()}
          trendWindow={trendWindow}
        />
      </div>
    </>
  );
}

// ─── Activities placeholder ─────────────────────────────────────────────

function ActivitiesPlaceholder() {
  return (
    <SectionPanel title="Aktywności">
      <p className="placeholder-text">
        Integracja Strava jest w backlogu (Sprint 4 zaległy). Po jej shipowaniu
        zobaczysz tu listę ostatnich treningów + statystyki tygodnia.
      </p>
    </SectionPanel>
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

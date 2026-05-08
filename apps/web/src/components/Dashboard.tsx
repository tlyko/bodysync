import { useEffect, useMemo, useState } from 'react';
import { getBiometry } from '../api';
import { buildSeries, latestValue, trendPct, type SeriesPoint } from '../biometry';
import type { BiometryDay, Me } from '../types';
import { ChatScreen } from './chat/ChatScreen';
import { ProfileTargetsForm } from './dashboard/ProfileTargetsForm';
import { RangeToggle, type Range } from './dashboard/RangeToggle';
import { StatCard } from './dashboard/StatCard';
import { WeightChart } from './dashboard/WeightChart';

type Props = {
  me: Me;
  onLogout: () => void;
};

type Tab = 'biometry' | 'chat' | 'profile';

const FETCH_DAYS = 30;

const RANGE_LABELS: Record<Range, string> = {
  '1d': 'Dziś',
  '7d': 'Ostatni tydzień',
  '30d': 'Ostatnie 30 dni',
};
const RANGE_DAYS: Record<Range, number> = { '1d': 1, '7d': 7, '30d': 30 };
// Trend window per range: 30d → 7d vs 7-14d ago, 7d → 3d vs 3-6d ago, 1d → brak.
const RANGE_TREND_WINDOW: Record<Range, number | null> = { '1d': null, '7d': 3, '30d': 7 };

export function Dashboard({ me, onLogout }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>('biometry');
  const [days, setDays] = useState<BiometryDay[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (activeTab !== 'biometry') return;
    if (days !== null) return;
    getBiometry(FETCH_DAYS)
      .then((res) => setDays(res.days))
      .catch((e) => setError(e instanceof Error ? e.message : 'fetch failed'));
  }, [activeTab, days]);

  return (
    <div className="dashboard">
      <header>
        <h1>bodysync</h1>
        <nav className="dashboard-tabs" aria-label="Sekcje">
          <button
            type="button"
            className={`dashboard-tab ${activeTab === 'biometry' ? 'active' : ''}`}
            onClick={() => setActiveTab('biometry')}
          >
            Biometria
          </button>
          <button
            type="button"
            className={`dashboard-tab ${activeTab === 'chat' ? 'active' : ''}`}
            onClick={() => setActiveTab('chat')}
          >
            Chat
          </button>
          <button
            type="button"
            className={`dashboard-tab ${activeTab === 'profile' ? 'active' : ''}`}
            onClick={() => setActiveTab('profile')}
          >
            Profil
          </button>
        </nav>
        <div className="user-info">
          <span>{me.name ?? me.email}</span>
          <button onClick={onLogout} type="button">
            Wyloguj
          </button>
        </div>
      </header>

      <main>
        {activeTab === 'biometry' && <BiometryView days={days} error={error} />}
        {activeTab === 'chat' && <ChatScreen />}
        {activeTab === 'profile' && <ProfileTargetsForm />}
      </main>
    </div>
  );
}

type BiometryProps = {
  days: BiometryDay[] | null;
  error: string | null;
};

function BiometryView({ days, error }: BiometryProps) {
  const [range, setRange] = useState<Range>('30d');

  // Slice 30d → ostatnie N dni (sortuj po date żeby slice trafił poprawnie).
  // Wszystkie series budujemy z tego zakresu — sparkline + trend reagują
  // automatycznie bez round-trip do backendu.
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

  const hrvSeries = buildSeries(sliced, 'hrv');
  const sleepSeries = buildSeries(sliced, 'sleep');
  const stepsSeries = buildSeries(sliced, 'steps');
  const kcalActiveSeries = buildSeries(sliced, 'kcal_active');
  const restingHrSeries = buildSeries(sliced, 'resting_hr');
  const bodyFatSeries = buildSeries(sliced, 'body_fat');
  const kcalInSeries = buildSeries(sliced, 'kcal_in');
  const proteinSeries = buildSeries(sliced, 'protein');
  const fatSeries = buildSeries(sliced, 'fat');
  const carbsSeries = buildSeries(sliced, 'carbs');
  const weightSeries = buildSeries(sliced, 'weight');

  return (
    <>
      <div className="section-header">
        <h2>{RANGE_LABELS[range]}</h2>
        <RangeToggle value={range} onChange={setRange} />
      </div>
      <div className="stat-grid">
        <MetricStatCard
          label="HRV (avg ms)"
          series={hrvSeries}
          unit="ms"
          accent="cyan"
          fmt={(v) => v.toFixed(1)}
          trendWindow={trendWindow}
        />
        <MetricStatCard
          label="Sen"
          series={sleepSeries}
          unit="h"
          accent="purple"
          fmt={(v) => v.toFixed(1)}
          trendWindow={trendWindow}
        />
        <MetricStatCard
          label="Kroki"
          series={stepsSeries}
          accent="green"
          fmt={(v) => Math.round(v).toLocaleString('pl-PL')}
          trendWindow={trendWindow}
        />
        <MetricStatCard
          label="Kcal aktywne"
          series={kcalActiveSeries}
          unit="kcal"
          accent="orange"
          fmt={(v) => Math.round(v).toString()}
          trendWindow={trendWindow}
        />
        <MetricStatCard
          label="Resting HR"
          series={restingHrSeries}
          unit="bpm"
          accent="red"
          fmt={(v) => Math.round(v).toString()}
          trendWindow={trendWindow}
        />
        <MetricStatCard
          label="Body fat"
          series={bodyFatSeries}
          unit="%"
          accent="muted"
          fmt={(v) => v.toFixed(1)}
          trendWindow={trendWindow}
        />
      </div>

      <h2 style={{ marginTop: '2rem' }}>Odżywianie</h2>
      <div className="stat-grid">
        <MetricStatCard
          label="Kcal spożyte"
          series={kcalInSeries}
          unit="kcal"
          accent="cyan"
          fmt={(v) => Math.round(v).toLocaleString('pl-PL')}
          trendWindow={trendWindow}
        />
        <MetricStatCard
          label="Białko"
          series={proteinSeries}
          unit="g"
          accent="green"
          fmt={(v) => Math.round(v).toString()}
          trendWindow={trendWindow}
        />
        <MetricStatCard
          label="Tłuszcz"
          series={fatSeries}
          unit="g"
          accent="orange"
          fmt={(v) => Math.round(v).toString()}
          trendWindow={trendWindow}
        />
        <MetricStatCard
          label="Węgle"
          series={carbsSeries}
          unit="g"
          accent="purple"
          fmt={(v) => Math.round(v).toString()}
          trendWindow={trendWindow}
        />
      </div>

      <h2 style={{ marginTop: '2rem' }}>Waga</h2>
      <WeightChart data={weightSeries.map((p) => ({ date: p.date, weight: p.value }))} />
      <div className="stat-grid" style={{ marginTop: '1rem' }}>
        <WeightSummaryCards series={weightSeries} rangeLabel={RANGE_LABELS[range]} />
      </div>
    </>
  );
}

type MetricStatCardProps = {
  label: string;
  series: SeriesPoint[];
  unit?: string;
  accent: 'cyan' | 'green' | 'orange' | 'purple' | 'red' | 'muted';
  fmt: (v: number) => string;
  trendWindow: number | null;
};

function MetricStatCard({ label, series, unit, accent, fmt, trendWindow }: MetricStatCardProps) {
  const last = latestValue(series);
  // Pomijamy sparkline + trend dla "Dziś" view — pojedynczy punkt nie ma kształtu.
  const sparkData = trendWindow === null ? undefined : series.map((p) => p.value);
  const trend = trendWindow === null ? null : trendPct(series, trendWindow);
  return (
    <StatCard
      label={label}
      value={last ? fmt(last.value) : null}
      unit={unit}
      accent={accent}
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
        <StatCard label="Aktualna waga" value={null} unit="kg" accent="green" />
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
      <StatCard label="Aktualna waga" value={last.toFixed(1)} unit="kg" accent="green" />
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

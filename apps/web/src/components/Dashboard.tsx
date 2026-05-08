import { useEffect, useState } from 'react';
import { getBiometry } from '../api';
import { buildSeries, latestValue, trendPct, type SeriesPoint } from '../biometry';
import type { BiometryDay, Me } from '../types';
import { ChatScreen } from './chat/ChatScreen';
import { StatCard } from './dashboard/StatCard';
import { WeightChart } from './dashboard/WeightChart';

type Props = {
  me: Me;
  onLogout: () => void;
};

type Tab = 'biometry' | 'chat';

const BIOMETRY_DAYS = 30;

export function Dashboard({ me, onLogout }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>('biometry');
  const [days, setDays] = useState<BiometryDay[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (activeTab !== 'biometry') return;
    if (days !== null) return;
    getBiometry(BIOMETRY_DAYS)
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
      </main>
    </div>
  );
}

type BiometryProps = {
  days: BiometryDay[] | null;
  error: string | null;
};

function BiometryView({ days, error }: BiometryProps) {
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

  const hrvSeries = buildSeries(days, 'hrv');
  const sleepSeries = buildSeries(days, 'sleep');
  const stepsSeries = buildSeries(days, 'steps');
  const kcalActiveSeries = buildSeries(days, 'kcal_active');
  const restingHrSeries = buildSeries(days, 'resting_hr');
  const bodyFatSeries = buildSeries(days, 'body_fat');
  const weightSeries = buildSeries(days, 'weight');

  return (
    <>
      <h2>Ostatnie {BIOMETRY_DAYS} dni</h2>
      <div className="stat-grid">
        <MetricStatCard
          label="HRV (avg ms)"
          series={hrvSeries}
          unit="ms"
          accent="cyan"
          fmt={(v) => v.toFixed(1)}
        />
        <MetricStatCard
          label="Sen"
          series={sleepSeries}
          unit="h"
          accent="purple"
          fmt={(v) => v.toFixed(1)}
        />
        <MetricStatCard
          label="Kroki"
          series={stepsSeries}
          accent="green"
          fmt={(v) => Math.round(v).toLocaleString('pl-PL')}
        />
        <MetricStatCard
          label="Kcal aktywne"
          series={kcalActiveSeries}
          unit="kcal"
          accent="orange"
          fmt={(v) => Math.round(v).toString()}
        />
        <MetricStatCard
          label="Resting HR"
          series={restingHrSeries}
          unit="bpm"
          accent="red"
          fmt={(v) => Math.round(v).toString()}
        />
        <MetricStatCard
          label="Body fat"
          series={bodyFatSeries}
          unit="%"
          accent="muted"
          fmt={(v) => v.toFixed(1)}
        />
      </div>

      <h2 style={{ marginTop: '2rem' }}>Waga</h2>
      <WeightChart data={weightSeries.map((p) => ({ date: p.date, weight: p.value }))} />
      <div className="stat-grid" style={{ marginTop: '1rem' }}>
        <WeightSummaryCards series={weightSeries} />
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
};

function MetricStatCard({ label, series, unit, accent, fmt }: MetricStatCardProps) {
  const last = latestValue(series);
  const trend = trendPct(series);
  return (
    <StatCard
      label={label}
      value={last ? fmt(last.value) : null}
      unit={unit}
      accent={accent}
      sparkData={series.map((p) => p.value)}
      change={trend}
    />
  );
}

function WeightSummaryCards({ series }: { series: SeriesPoint[] }) {
  if (series.length === 0) {
    return (
      <>
        <StatCard label="Aktualna waga" value={null} unit="kg" accent="green" />
        <StatCard label={`Zmiana ${BIOMETRY_DAYS}d`} value={null} unit="kg" accent="cyan" />
        <StatCard label="Średnia" value={null} unit="kg" accent="purple" />
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
      />
      <StatCard
        label={`Zmiana ${BIOMETRY_DAYS}d`}
        value={`${delta >= 0 ? '+' : ''}${delta.toFixed(1)}`}
        unit="kg"
        accent="cyan"
      />
      <StatCard label="Średnia" value={avg.toFixed(1)} unit="kg" accent="purple" />
    </>
  );
}

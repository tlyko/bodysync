import { useEffect, useState } from 'react';
import { getBiometry } from '../api';
import type { BiometryDay, BiometryValue, Me } from '../types';

type Props = {
  me: Me;
  onLogout: () => void;
};

const METRIC_LABELS: Record<string, string> = {
  weight: 'Waga',
  body_fat: 'Tkanka tłuszcz.',
  steps: 'Kroki',
  hr: 'Tętno (min/avg/max)',
  resting_hr: 'Tętno spoczynkowe',
  hrv: 'HRV (ms)',
  kcal_active: 'Kcal aktywne',
  kcal_basal: 'Kcal bazowe',
  kcal_in: 'Kcal spożyte',
  protein: 'Białko (g)',
  fat: 'Tłuszcz (g)',
  carbs: 'Węgle (g)',
  sleep: 'Sen',
};

function formatValue(metric: string, value: BiometryValue | BiometryValue[]): string {
  if (Array.isArray(value)) {
    if (metric === 'hrv') {
      const values = value
        .map((p) => p.value_ms)
        .filter((v): v is number => typeof v === 'number');
      if (values.length === 0) return '—';
      const avg = values.reduce((a, b) => a + b, 0) / values.length;
      return `${avg.toFixed(1)} ms (${values.length} pomiarów)`;
    }
    if (metric === 'hr') {
      // Avg z avg_bpm wszystkich okien
      const avgs = value
        .map((p) => p.avg_bpm)
        .filter((v): v is number => typeof v === 'number');
      if (avgs.length === 0) return '—';
      const avg = avgs.reduce((a, b) => a + b, 0) / avgs.length;
      return `~${Math.round(avg)} bpm`;
    }
    return `${value.length} pomiarów`;
  }
  // Single value
  const v = value as BiometryValue;
  if (metric === 'weight') return `${v.kg} kg`;
  if (metric === 'body_fat') return `${v.pct}%`;
  if (metric === 'steps') return `${v.count}`;
  if (metric === 'resting_hr') return `${v.bpm} bpm`;
  if (metric === 'kcal_active' || metric === 'kcal_basal' || metric === 'kcal_in') return `${v.kcal} kcal`;
  if (metric === 'protein' || metric === 'fat' || metric === 'carbs') return `${v.g} g`;
  if (metric === 'sleep') {
    const asleep = typeof v.asleep === 'number' ? `${v.asleep.toFixed(1)} h` : '—';
    return `${asleep} (asleep)`;
  }
  // Fallback — pierwsza numeryczna wartość
  for (const [, val] of Object.entries(v)) {
    if (typeof val === 'number') return String(val);
  }
  return '—';
}

export function Dashboard({ me, onLogout }: Props) {
  const [days, setDays] = useState<BiometryDay[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getBiometry(7)
      .then((res) => setDays(res.days))
      .catch((e) => setError(e.message ?? 'fetch failed'));
  }, []);

  // Wszystkie metric_names obecne w response — kolumny tabeli
  const allMetrics = days
    ? Array.from(new Set(days.flatMap((d) => Object.keys(d.metrics))))
    : [];

  return (
    <div className="dashboard">
      <header>
        <h1>bodysync</h1>
        <div className="user-info">
          <span>
            {me.name ?? me.email} <small>({me.user_id})</small>
          </span>
          <button onClick={onLogout} type="button">
            Wyloguj
          </button>
        </div>
      </header>

      <main>
        <h2>Ostatnie 7 dni</h2>
        {error && <p className="error">Błąd: {error}</p>}
        {!days && !error && <p>Wczytywanie…</p>}
        {days && days.length === 0 && (
          <div className="empty">
            <p>
              Brak danych w bazie. Skonfiguruj <strong>Health Auto Export</strong>
              {' '}na telefonie i wyślij pierwszy webhook.
            </p>
          </div>
        )}
        {days && days.length > 0 && (
          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>Data</th>
                  {allMetrics.map((m) => (
                    <th key={m}>{METRIC_LABELS[m] ?? m}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {days.map((day) => (
                  <tr key={day.date}>
                    <td className="date">{day.date}</td>
                    {allMetrics.map((m) => (
                      <td key={m}>{day.metrics[m] ? formatValue(m, day.metrics[m]) : '—'}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </div>
  );
}

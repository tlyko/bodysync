// Sprint 12 — manualne pomiary obwodów ciała (talia/biodra/klatka/biceps/udo).
// User wpisuje raz w tygodniu, każdy input opcjonalny — wysyłamy tylko
// non-empty pola (backend Pydantic optional + at-least-one validator).
//
// Auto-refresh strategy: NIE dorzucamy refresh logic w MVP. Owner zrefreshuje
// page lub poczeka na następny dashboard mount (FETCH_DAYS=30 query). Komentarz
// w kodzie: success → next mount dostanie fresh data z `/api/biometry`.

import { type FormEvent, useState } from 'react';
import { measurementsErrorMessage, postMeasurements } from '../../api';
import { buildSeries, latestValue } from '../../biometry';
import type { BiometryDay, MeasurementsRequest } from '../../types';
import { MetricChart, type MetricChartColor } from './MetricChart';

type MetricKey = 'waist' | 'hips' | 'chest' | 'biceps' | 'thigh';

type MetricDef = {
  key: MetricKey;
  label: string;
  color: MetricChartColor;
  // Pydantic field name dla payloadu (matchuje schemas.MeasurementsRequest).
  payloadKey: `${MetricKey}_cm`;
};

const METRICS: MetricDef[] = [
  { key: 'waist', label: 'Talia', color: 'orange', payloadKey: 'waist_cm' },
  { key: 'hips', label: 'Biodra', color: 'purple', payloadKey: 'hips_cm' },
  { key: 'chest', label: 'Klatka', color: 'cyan', payloadKey: 'chest_cm' },
  { key: 'biceps', label: 'Biceps', color: 'green', payloadKey: 'biceps_cm' },
  { key: 'thigh', label: 'Udo', color: 'red', payloadKey: 'thigh_cm' },
];

type Props = {
  days: BiometryDay[];
  todayIso: string;
  // Opcjonalny callback po sukcesie — owner może użyć do refetch'a biometry.
  // Brak = MVP behavior (success message, user resfreshuje sam).
  onSaved?: () => void;
};

export function BodyMeasurementsCard({ days, todayIso, onSaved }: Props) {
  // Local form state per-metric. Trzymamy jako string (input type=number),
  // konwersja do float przy submit. Empty string = pole nie wypełnione.
  const [values, setValues] = useState<Record<MetricKey, string>>({
    waist: '',
    hips: '',
    chest: '',
    biceps: '',
    thigh: '',
  });
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string>('');

  const hasAnyValue = METRICS.some((m) => values[m.key].trim() !== '');

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!hasAnyValue || submitting) return;

    setSubmitting(true);
    setError('');
    setSuccess(false);

    // Build payload — tylko non-empty pola, każde parsed jako float.
    // Backend Pydantic Field(gt=0, lt=500) odrzuci invalid wartości.
    const payload: MeasurementsRequest = { date: todayIso };
    for (const m of METRICS) {
      const raw = values[m.key].trim();
      if (raw === '') continue;
      const parsed = Number.parseFloat(raw.replace(',', '.'));
      if (!Number.isFinite(parsed)) continue;
      payload[m.payloadKey] = parsed;
    }

    try {
      await postMeasurements(payload);
      // Clear inputs po sukcesie — user widzi że "zostało zapisane".
      setValues({ waist: '', hips: '', chest: '', biceps: '', thigh: '' });
      setSuccess(true);
      // Success message znika po 3s — user nie patrzy w UI cały czas.
      window.setTimeout(() => setSuccess(false), 3000);
      onSaved?.();
    } catch (err) {
      setError(measurementsErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="body-measurements-card">
      <header className="body-measurements-header">
        <h3>Pomiary obwodów</h3>
        <p>Wpisz raz w tygodniu — w cm. Tylko zmienione pola się zapisują.</p>
      </header>

      <form onSubmit={submit} className="body-measurements-form">
        {METRICS.map((m) => {
          const series = buildSeries(days, m.key);
          const last = latestValue(series);
          const placeholder = last !== null ? last.value.toFixed(1) : '—';
          return (
            <div key={m.key} className="body-measurements-field">
              <label htmlFor={`bm-${m.key}`}>{m.label}</label>
              <div className="body-measurements-input-wrap">
                <input
                  id={`bm-${m.key}`}
                  type="number"
                  step="0.1"
                  min="10"
                  max="200"
                  inputMode="decimal"
                  placeholder={placeholder}
                  value={values[m.key]}
                  onChange={(e) =>
                    setValues((prev) => ({ ...prev, [m.key]: e.target.value }))
                  }
                  disabled={submitting}
                />
                <span className="body-measurements-unit">cm</span>
              </div>
            </div>
          );
        })}

        <button
          type="submit"
          className="body-measurements-submit"
          disabled={!hasAnyValue || submitting}
        >
          {submitting ? 'Zapisuję…' : 'Zapisz pomiar'}
        </button>

        {success && (
          <div className="body-measurements-success" role="status">
            Pomiar zapisany — odśwież stronę aby zobaczyć trend.
          </div>
        )}
        {error && (
          <div className="body-measurements-error" role="alert">
            {error}
          </div>
        )}
      </form>

      <div className="body-measurements-charts">
        {METRICS.map((m) => {
          const series = buildSeries(days, m.key);
          // < 2 punkty = nie ma jeszcze trendu (MetricChart pokazałby
          // 1-bar wykres — bez sensu). Wymagamy ≥2 dla wartościowego
          // visualization. Empty stan info-text zachęca do dalszych pomiarów.
          if (series.length < 2) return null;
          const last = latestValue(series);
          return (
            <div key={m.key} className="body-measurements-chart">
              <h4>
                {m.label}{' '}
                {last && (
                  <span className="body-measurements-chart-last">
                    {last.value.toFixed(1)} cm
                  </span>
                )}
              </h4>
              <MetricChart
                data={series}
                label={m.label}
                unit="cm"
                color={m.color}
                height={120}
                formatValue={(v) => v.toFixed(1)}
              />
            </div>
          );
        })}
      </div>
    </section>
  );
}

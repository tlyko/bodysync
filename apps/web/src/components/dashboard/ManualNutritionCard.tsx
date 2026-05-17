// Manual nutrition entry — fallback gdy HAE offline lub uzupełnienie historii.
// Backend POST /api/measurements rozszerzony o kcal_in/protein_g/fat_g/carbs_g
// (post-Recovery sprint). Manual write nadpisuje HAE dla danego dnia
// (api_read service filtruje na source=="manual" przed sum).

import { type FormEvent, useState } from 'react';
import { measurementsErrorMessage, postMeasurements } from '../../api';
import { buildSeries, valueForDate } from '../../biometry';
import type { BiometryDay, MeasurementsRequest } from '../../types';

type NutritionKey = 'kcal_in' | 'protein' | 'fat' | 'carbs';

type FieldDef = {
  key: NutritionKey;
  label: string;
  unit: string;
  step: number;
  max: number;
  payloadKey: keyof MeasurementsRequest;
};

const FIELDS: FieldDef[] = [
  { key: 'kcal_in', label: 'Kcal spożyte', unit: 'kcal', step: 1, max: 10000, payloadKey: 'kcal_in' },
  { key: 'protein', label: 'Białko', unit: 'g', step: 1, max: 1000, payloadKey: 'protein_g' },
  { key: 'fat', label: 'Tłuszcz', unit: 'g', step: 1, max: 1000, payloadKey: 'fat_g' },
  { key: 'carbs', label: 'Węgle', unit: 'g', step: 1, max: 1000, payloadKey: 'carbs_g' },
];

type Props = {
  days: BiometryDay[];
  todayIso: string;
  onSaved?: () => void;
};

export function ManualNutritionCard({ days, todayIso, onSaved }: Props) {
  const [values, setValues] = useState<Record<NutritionKey, string>>({
    kcal_in: '',
    protein: '',
    fat: '',
    carbs: '',
  });
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string>('');

  const hasAnyValue = FIELDS.some((f) => values[f.key].trim() !== '');

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!hasAnyValue || submitting) return;

    setSubmitting(true);
    setError('');
    setSuccess(false);

    const payload: MeasurementsRequest = { date: todayIso };
    for (const f of FIELDS) {
      const raw = values[f.key].trim();
      if (raw === '') continue;
      const parsed = Number.parseFloat(raw.replace(',', '.'));
      if (!Number.isFinite(parsed)) continue;
      (payload[f.payloadKey] as number) = parsed;
    }

    try {
      await postMeasurements(payload);
      setValues({ kcal_in: '', protein: '', fat: '', carbs: '' });
      setSuccess(true);
      window.setTimeout(() => setSuccess(false), 3000);
      onSaved?.();
    } catch (err) {
      setError(measurementsErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="manual-nutrition-card">
      <header className="manual-nutrition-header">
        <h3>Wpisz spożycie ręcznie</h3>
        <p>Fallback gdy Apple Health nie wysłał danych. Nadpisuje wartości z HAE dla wybranego dnia.</p>
      </header>

      <form onSubmit={submit} className="manual-nutrition-form">
        {FIELDS.map((f) => {
          const series = buildSeries(days, f.key);
          const todayPoint = valueForDate(series, todayIso);
          // Placeholder z dzisiejszej HAE wartości (gdy istnieje) żeby user
          // widział od czego startuje — albo "—" gdy HAE jeszcze nie wysłał.
          const placeholder =
            todayPoint !== null ? Math.round(todayPoint.value).toString() : '—';
          return (
            <div key={f.key} className="manual-nutrition-field">
              <label htmlFor={`mn-${f.key}`}>{f.label}</label>
              <div className="manual-nutrition-input-wrap">
                <input
                  id={`mn-${f.key}`}
                  type="number"
                  step={f.step}
                  min="0"
                  max={f.max}
                  inputMode="numeric"
                  placeholder={placeholder}
                  value={values[f.key]}
                  onChange={(e) =>
                    setValues((prev) => ({ ...prev, [f.key]: e.target.value }))
                  }
                  disabled={submitting}
                />
                <span className="manual-nutrition-unit">{f.unit}</span>
              </div>
            </div>
          );
        })}

        <button
          type="submit"
          className="manual-nutrition-submit"
          disabled={!hasAnyValue || submitting}
        >
          {submitting ? 'Zapisuję…' : 'Zapisz spożycie'}
        </button>

        {success && (
          <div className="manual-nutrition-success" role="status">
            Spożycie zapisane — odśwież stronę aby zobaczyć update.
          </div>
        )}
        {error && (
          <div className="manual-nutrition-error" role="alert">
            {error}
          </div>
        )}
      </form>
    </section>
  );
}

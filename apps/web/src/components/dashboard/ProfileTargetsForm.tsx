import { type FormEvent, useEffect, useState } from 'react';
import { ApiError, getProfileTargets, putProfileTargets } from '../../api';
import type { ProfileTargets } from '../../types';

type FieldKey = 'kcal_target' | 'protein_target_g' | 'fat_target_g' | 'carbs_target_g';

type FieldDef = {
  key: FieldKey;
  label: string;
  unit: string;
  min: number;
  max: number;
  hint: string;
};

const FIELDS: FieldDef[] = [
  {
    key: 'kcal_target',
    label: 'Cel kaloryczny',
    unit: 'kcal/dzień',
    min: 1000,
    max: 5000,
    hint: 'Typowo 1800-2800 dla redukcji, 2500-3500 dla utrzymania/masy.',
  },
  {
    key: 'protein_target_g',
    label: 'Białko',
    unit: 'g/dzień',
    min: 30,
    max: 300,
    hint: 'Standard ~1.6-2.0 g/kg masy ciała (np. 80kg → 130-160 g).',
  },
  {
    key: 'fat_target_g',
    label: 'Tłuszcz',
    unit: 'g/dzień',
    min: 20,
    max: 200,
    hint: 'Min 0.8 g/kg dla hormonów, typowo 60-90 g.',
  },
  {
    key: 'carbs_target_g',
    label: 'Węgle',
    unit: 'g/dzień',
    min: 30,
    max: 500,
    hint: 'Reszta budżetu kcal po białku i tłuszczu.',
  },
];

type FormValues = Record<FieldKey, string>;

function targetsToForm(t: ProfileTargets): FormValues {
  return {
    kcal_target: String(t.kcal_target),
    protein_target_g: String(t.protein_target_g),
    fat_target_g: String(t.fat_target_g),
    carbs_target_g: String(t.carbs_target_g),
  };
}

function parseAndValidate(values: FormValues): {
  ok: true;
  parsed: { kcal_target: number; protein_target_g: number; fat_target_g: number; carbs_target_g: number };
} | { ok: false; errors: Partial<Record<FieldKey, string>> } {
  const errors: Partial<Record<FieldKey, string>> = {};
  const parsed: Record<string, number> = {};
  for (const f of FIELDS) {
    const raw = values[f.key].trim();
    const n = Number(raw);
    if (!raw || !Number.isFinite(n) || !Number.isInteger(n)) {
      errors[f.key] = 'Wpisz liczbę całkowitą';
      continue;
    }
    if (n < f.min || n > f.max) {
      errors[f.key] = `Zakres ${f.min}–${f.max}`;
      continue;
    }
    parsed[f.key] = n;
  }
  if (Object.keys(errors).length > 0) return { ok: false, errors };
  return {
    ok: true,
    parsed: parsed as { kcal_target: number; protein_target_g: number; fat_target_g: number; carbs_target_g: number },
  };
}

export function ProfileTargetsForm() {
  const [values, setValues] = useState<FormValues | null>(null);
  const [isDefault, setIsDefault] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<FieldKey, string>>>({});

  useEffect(() => {
    let cancelled = false;
    getProfileTargets()
      .then((t) => {
        if (cancelled) return;
        setValues(targetsToForm(t));
        setIsDefault(t.is_default);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof ApiError ? `Błąd ${e.status}: ${e.message}` : 'Nie udało się wczytać celów');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleChange = (key: FieldKey, raw: string) => {
    setValues((prev) => (prev ? { ...prev, [key]: raw } : prev));
    setFieldErrors((prev) => ({ ...prev, [key]: undefined }));
    setSuccess(null);
  };

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!values) return;
    const v = parseAndValidate(values);
    if (!v.ok) {
      setFieldErrors(v.errors);
      return;
    }
    setFieldErrors({});
    setPending(true);
    setError(null);
    setSuccess(null);
    try {
      const updated = await putProfileTargets(v.parsed);
      setValues(targetsToForm(updated));
      setIsDefault(updated.is_default);
      setSuccess('Zapisano. Asystent użyje tych wartości w następnym pytaniu.');
    } catch (e) {
      setError(e instanceof ApiError ? `Błąd ${e.status}: ${e.message}` : 'Nie udało się zapisać');
    } finally {
      setPending(false);
    }
  };

  if (!values && error) return <p className="error">{error}</p>;
  if (!values) return <p>Wczytywanie…</p>;

  return (
    <form className="profile-form" onSubmit={handleSubmit} noValidate>
      {isDefault && (
        <div className="profile-form-banner">
          Używasz wartości domyślnych (2000/130/70/200). Wpisz swoje cele, żeby asystent
          doradczy odpowiadał na ich bazie.
        </div>
      )}
      <div className="profile-form-grid">
        {FIELDS.map((f) => {
          const errMsg = fieldErrors[f.key];
          return (
            <label key={f.key} className="profile-form-field">
              <span className="profile-form-label">{f.label}</span>
              <span className="profile-form-input-row">
                <input
                  type="number"
                  inputMode="numeric"
                  min={f.min}
                  max={f.max}
                  step={1}
                  value={values[f.key]}
                  onChange={(e) => handleChange(f.key, e.target.value)}
                  disabled={pending}
                  aria-invalid={Boolean(errMsg)}
                  aria-describedby={`hint-${f.key}`}
                />
                <span className="profile-form-unit">{f.unit}</span>
              </span>
              <span id={`hint-${f.key}`} className="profile-form-hint">
                {errMsg ? <span className="error">{errMsg}</span> : f.hint}
              </span>
            </label>
          );
        })}
      </div>
      <div className="profile-form-actions">
        {error && <span className="error">{error}</span>}
        {success && <span className="profile-form-success">{success}</span>}
        <button type="submit" className="profile-form-submit" disabled={pending}>
          {pending ? 'Zapisuję…' : 'Zapisz cele'}
        </button>
      </div>
    </form>
  );
}

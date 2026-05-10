// Sprint 10 A0 — wizard liczenia TDEE z formuły Mifflin-St Jeor.
// Owner wpisuje wzrost / wiek / płeć / activity level / cel,
// backend wylicza BMR + TDEE + proposed makro, owner klika
// "Zastosuj" → PUT /api/profile/targets z body_profile + 4 makro.

import { type FormEvent, useEffect, useState } from 'react';
import {
  ApiError,
  getProfileTargets,
  postCalculateTDEE,
  putProfileTargets,
} from '../../api';
import type {
  ActivityLevel,
  BodyProfile,
  CalculateTDEEResponse,
  Goal,
  Sex,
} from '../../types';

type Props = {
  onTargetsUpdated?: () => void;
};

type WizardForm = {
  height_cm: string;
  age: string;
  sex: Sex;
  activity_level: ActivityLevel;
  goal: Goal;
};

const DEFAULT_FORM: WizardForm = {
  height_cm: '',
  age: '',
  sex: 'male',
  activity_level: 'moderate',
  goal: 'maintain',
};

const ACTIVITY_OPTIONS: { value: ActivityLevel; label: string; hint: string }[] = [
  { value: 'sedentary', label: 'Siedzący', hint: 'Praca biurowa, brak ćwiczeń' },
  { value: 'light', label: 'Lekka aktywność', hint: '1-3 dni/tydzień lekkie ćwiczenia' },
  { value: 'moderate', label: 'Umiarkowana', hint: '3-5 dni/tydzień umiarkowane' },
  { value: 'heavy', label: 'Wysoka', hint: '6-7 dni/tydzień intensywne' },
  { value: 'athlete', label: 'Sportowiec', hint: '2× dziennie / fizyczna praca' },
];

const GOAL_OPTIONS: { value: Goal; label: string; hint: string }[] = [
  { value: 'loss', label: 'Redukcja', hint: '-500 kcal/dzień (~-0.5 kg/tydz.)' },
  { value: 'maintain', label: 'Utrzymanie', hint: 'TDEE bez modyfikacji' },
  { value: 'gain', label: 'Przyrost', hint: '+300 kcal/dzień (lean bulk)' },
];

const SEX_OPTIONS: { value: Sex; label: string }[] = [
  { value: 'male', label: 'Mężczyzna' },
  { value: 'female', label: 'Kobieta' },
];

function bodyProfileToForm(bp: BodyProfile): WizardForm {
  return {
    height_cm: String(bp.height_cm),
    age: String(bp.age),
    sex: bp.sex,
    activity_level: bp.activity_level,
    goal: bp.goal,
  };
}

function parseForm(form: WizardForm): BodyProfile | string {
  const height = Number(form.height_cm);
  const age = Number(form.age);
  if (!Number.isInteger(height) || height < 140 || height > 220) {
    return 'Wzrost — liczba całkowita 140–220 cm';
  }
  if (!Number.isInteger(age) || age < 18 || age > 100) {
    return 'Wiek — liczba całkowita 18–100 lat';
  }
  return {
    height_cm: height,
    age: age,
    sex: form.sex,
    activity_level: form.activity_level,
    goal: form.goal,
  };
}

export function TDEECalculatorWizard({ onTargetsUpdated }: Props) {
  const [form, setForm] = useState<WizardForm>(DEFAULT_FORM);
  const [result, setResult] = useState<CalculateTDEEResponse | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [calcPending, setCalcPending] = useState(false);
  const [applyPending, setApplyPending] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [hasStoredProfile, setHasStoredProfile] = useState(false);

  // Pre-fill z zapisanego body_profile (jeśli jest) — owner wraca do wizardu
  // żeby przeliczyć ponownie po zmianie waga / activity level.
  useEffect(() => {
    let cancelled = false;
    getProfileTargets()
      .then((t) => {
        if (cancelled) return;
        if (t.body_profile) {
          setForm(bodyProfileToForm(t.body_profile));
          setHasStoredProfile(true);
        }
      })
      .catch(() => {
        // Brak profilu / 401 / sieć — nie blokujemy wizardu, owner wpisuje od zera.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleCalculate = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setValidationError(null);
    setApiError(null);
    setSuccess(null);

    const parsed = parseForm(form);
    if (typeof parsed === 'string') {
      setValidationError(parsed);
      return;
    }

    setCalcPending(true);
    try {
      const res = await postCalculateTDEE({ body_profile: parsed });
      setResult(res);
    } catch (e) {
      if (e instanceof ApiError && e.status === 400 && e.message.includes('weight')) {
        setApiError(
          'Brak waga w bazie — wyślij dane z Health Auto Export albo wpisz makro ręcznie poniżej.',
        );
      } else {
        setApiError(e instanceof ApiError ? `Błąd ${e.status}: ${e.message}` : 'Nie udało się obliczyć');
      }
    } finally {
      setCalcPending(false);
    }
  };

  const handleApply = async () => {
    if (!result) return;
    const parsed = parseForm(form);
    if (typeof parsed === 'string') {
      setValidationError(parsed);
      return;
    }
    setApplyPending(true);
    setApiError(null);
    try {
      await putProfileTargets({
        kcal_target: result.target_kcal,
        protein_target_g: result.target_protein_g,
        fat_target_g: result.target_fat_g,
        carbs_target_g: result.target_carbs_g,
        body_profile: parsed,
      });
      setSuccess(
        `Zastosowano. Asystent doradczy będzie używał ${result.target_kcal} kcal / ${result.target_protein_g}g białka / ${result.target_fat_g}g tłuszczu / ${result.target_carbs_g}g węgli.`,
      );
      setHasStoredProfile(true);
      onTargetsUpdated?.();
    } catch (e) {
      setApiError(e instanceof ApiError ? `Błąd ${e.status}: ${e.message}` : 'Nie udało się zapisać');
    } finally {
      setApplyPending(false);
    }
  };

  const handleField = <K extends keyof WizardForm>(key: K, value: WizardForm[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    setValidationError(null);
    setSuccess(null);
  };

  return (
    <section className="tdee-wizard">
      <header className="tdee-wizard-header">
        <h2 className="tdee-wizard-title">Kalkulator TDEE</h2>
        <p className="tdee-wizard-subtitle">
          {hasStoredProfile
            ? 'Twoje dane są zapisane. Przelicz, jeśli waga lub aktywność się zmieniła.'
            : 'Wpisz wzrost, wiek, płeć i poziom aktywności. Backend liczy BMR (Mifflin-St Jeor) + TDEE i proponuje cele kcal/makro dopasowane do Twojego celu.'}
        </p>
      </header>

      <form className="tdee-wizard-form" onSubmit={handleCalculate} noValidate>
        <div className="tdee-wizard-grid">
          <label className="tdee-wizard-field">
            <span>Wzrost</span>
            <span className="tdee-wizard-input-row">
              <input
                type="number"
                inputMode="numeric"
                min={140}
                max={220}
                step={1}
                value={form.height_cm}
                onChange={(e) => handleField('height_cm', e.target.value)}
                disabled={calcPending}
                placeholder="180"
              />
              <span className="tdee-wizard-unit">cm</span>
            </span>
          </label>

          <label className="tdee-wizard-field">
            <span>Wiek</span>
            <span className="tdee-wizard-input-row">
              <input
                type="number"
                inputMode="numeric"
                min={18}
                max={100}
                step={1}
                value={form.age}
                onChange={(e) => handleField('age', e.target.value)}
                disabled={calcPending}
                placeholder="32"
              />
              <span className="tdee-wizard-unit">lat</span>
            </span>
          </label>

          <label className="tdee-wizard-field">
            <span>Płeć</span>
            <select
              value={form.sex}
              onChange={(e) => handleField('sex', e.target.value as Sex)}
              disabled={calcPending}
            >
              {SEX_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>

          <label className="tdee-wizard-field tdee-wizard-field-wide">
            <span>Aktywność dzienna</span>
            <select
              value={form.activity_level}
              onChange={(e) => handleField('activity_level', e.target.value as ActivityLevel)}
              disabled={calcPending}
            >
              {ACTIVITY_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label} — {o.hint}
                </option>
              ))}
            </select>
          </label>

          <label className="tdee-wizard-field tdee-wizard-field-wide">
            <span>Cel</span>
            <select
              value={form.goal}
              onChange={(e) => handleField('goal', e.target.value as Goal)}
              disabled={calcPending}
            >
              {GOAL_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label} — {o.hint}
                </option>
              ))}
            </select>
          </label>
        </div>

        {validationError && <p className="error">{validationError}</p>}
        {apiError && <p className="error">{apiError}</p>}

        <div className="tdee-wizard-actions">
          <button type="submit" className="tdee-wizard-calc-button" disabled={calcPending}>
            {calcPending ? 'Liczę…' : result ? 'Przelicz ponownie' : 'Oblicz mój TDEE'}
          </button>
        </div>
      </form>

      {result && (
        <div className="tdee-wizard-result">
          <div className="tdee-wizard-result-stats">
            <Stat label="BMR" value={result.bmr} unit="kcal" hint="bazowa przemiana materii" />
            <Stat
              label="TDEE"
              value={result.tdee_maintenance}
              unit="kcal"
              hint="utrzymanie wagi"
            />
            <Stat
              label="Cel kcal"
              value={result.target_kcal}
              unit="kcal"
              hint={`waga ${result.weight_kg_used.toFixed(1)} kg`}
              accent
            />
          </div>
          <div className="tdee-wizard-result-macros">
            <Macro label="Białko" value={result.target_protein_g} />
            <Macro label="Tłuszcz" value={result.target_fat_g} />
            <Macro label="Węgle" value={result.target_carbs_g} />
          </div>
          <div className="tdee-wizard-actions">
            <button
              type="button"
              className="tdee-wizard-apply-button"
              onClick={handleApply}
              disabled={applyPending}
            >
              {applyPending ? 'Zapisuję…' : 'Zastosuj do moich celów'}
            </button>
          </div>
          {success && <p className="tdee-wizard-success">{success}</p>}
        </div>
      )}
    </section>
  );
}

function Stat({
  label,
  value,
  unit,
  hint,
  accent,
}: {
  label: string;
  value: number;
  unit: string;
  hint: string;
  accent?: boolean;
}) {
  return (
    <div className={`tdee-wizard-stat${accent ? ' tdee-wizard-stat-accent' : ''}`}>
      <span className="tdee-wizard-stat-label">{label}</span>
      <span className="tdee-wizard-stat-value">
        {value.toLocaleString('pl-PL')} <span className="tdee-wizard-stat-unit">{unit}</span>
      </span>
      <span className="tdee-wizard-stat-hint">{hint}</span>
    </div>
  );
}

function Macro({ label, value }: { label: string; value: number }) {
  return (
    <div className="tdee-wizard-macro">
      <span className="tdee-wizard-macro-label">{label}</span>
      <span className="tdee-wizard-macro-value">{value} g</span>
    </div>
  );
}

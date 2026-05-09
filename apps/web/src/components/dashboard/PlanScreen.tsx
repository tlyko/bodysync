// Sprint 5 — Google Sheets training plan tab.
// MVP-LITE: raw 2D array (sheet content as-is) renderowany jako HTML table.
// Strukturalny parser → exercises objects post-MVP (gdy owner odczuje
// potrzebę structured view).

import { useEffect, useMemo, useState } from 'react';
import { ApiError, getPlan } from '../../api';
import type { PlanResponse } from '../../types';
import { parseTrainings, type Training } from './planParser';

type State =
  | { status: 'loading' }
  | { status: 'ok'; plan: PlanResponse; refreshing: boolean }
  | { status: 'error'; reason: string; retryable: boolean };

function formatRelativeTime(epochSeconds: number): string {
  const diffSec = Math.floor(Date.now() / 1000) - epochSeconds;
  if (diffSec < 60) return 'przed chwilą';
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)} min temu`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)} godz. temu`;
  return `${Math.floor(diffSec / 86400)} dni temu`;
}

function errorMessage(status: number, raw: string): { reason: string; retryable: boolean } {
  if (status === 401) return { reason: 'Sesja wygasła — zaloguj się ponownie.', retryable: false };
  if (status === 503) {
    if (raw === 'not_configured') {
      return {
        reason:
          'Plan treningowy nie jest jeszcze skonfigurowany. Owner musi wpisać Google service account JSON, ID arkusza i nazwę zakładki w SSM.',
        retryable: false,
      };
    }
    if (raw === 'permission_denied') {
      return {
        reason:
          'Service account nie ma dostępu do arkusza. Upewnij się że SA email jest dodany jako Viewer w Share.',
        retryable: false,
      };
    }
    if (raw === 'sheet_not_found_or_no_access') {
      return {
        reason: 'Arkusz nie istnieje lub zakładka ma inną nazwę. Sprawdź SSM training-sheet-id i training-sheet-tab.',
        retryable: false,
      };
    }
    return { reason: 'Plan nieskonfigurowany.', retryable: false };
  }
  if (status === 502) {
    return { reason: 'Google Sheets chwilowo niedostępny. Spróbuj ponownie za chwilę.', retryable: true };
  }
  return { reason: 'Nie udało się pobrać planu.', retryable: true };
}

export function PlanScreen() {
  const [state, setState] = useState<State>({ status: 'loading' });

  const load = async (force: boolean) => {
    if (force) {
      setState((s) => (s.status === 'ok' ? { ...s, refreshing: true } : s));
    }
    try {
      const plan = await getPlan(force);
      setState({ status: 'ok', plan, refreshing: false });
    } catch (e) {
      if (e instanceof ApiError) {
        const { reason, retryable } = errorMessage(e.status, e.message);
        setState({ status: 'error', reason, retryable });
      } else {
        setState({ status: 'error', reason: 'Błąd sieci.', retryable: true });
      }
    }
  };

  useEffect(() => {
    load(false);
  }, []);

  if (state.status === 'loading') {
    return <p className="placeholder-text">Wczytywanie planu…</p>;
  }

  if (state.status === 'error') {
    return (
      <div className="plan-error">
        <p className="error">{state.reason}</p>
        {state.retryable && (
          <button type="button" onClick={() => load(false)} className="plan-refresh-button">
            Spróbuj ponownie
          </button>
        )}
      </div>
    );
  }

  const { plan, refreshing } = state;
  return (
    <section className="plan-screen">
      <div className="plan-meta">
        <div>
          <span className="plan-meta-label">Aktywna zakładka</span>
          <span className="plan-meta-value">{plan.sheet_tab}</span>
        </div>
        <div>
          <span className="plan-meta-label">Pobrane</span>
          <span className="plan-meta-value">
            {formatRelativeTime(plan.fetched_at)}
            {plan.fresh ? '' : ' (z cache)'}
          </span>
        </div>
        <button
          type="button"
          onClick={() => load(true)}
          className="plan-refresh-button"
          disabled={refreshing}
        >
          {refreshing ? 'Odświeżam…' : 'Odśwież z arkusza'}
        </button>
      </div>

      <PlanContent plan={plan} />
    </section>
  );
}

function PlanContent({ plan }: { plan: PlanResponse }) {
  const trainings = useMemo(() => parseTrainings(plan.rows), [plan.rows]);
  // Default = ostatni trening (najnowszy, owner: "to co jest najnizej").
  // Trener appenduje nowe bloki w prawo / w dół, więc last in array = newest.
  const [activeIdx, setActiveIdx] = useState(() =>
    trainings.length > 0 ? trainings.length - 1 : 0,
  );

  if (plan.rows.length === 0) {
    return (
      <p className="placeholder-text">
        Arkusz jest pusty albo zakładka <strong>{plan.sheet_tab}</strong> nie istnieje.
      </p>
    );
  }

  if (trainings.length === 0) {
    return (
      <p className="placeholder-text">
        Nie udało się sparsować planu (brak nagłówka <code>Numer</code> w arkuszu).
        Sprawdź czy zakładka <strong>{plan.sheet_tab}</strong> ma standardowy
        layout od trenerki.
      </p>
    );
  }

  const safeIdx = Math.min(activeIdx, trainings.length - 1);
  const active = trainings[safeIdx];

  return (
    <>
      <nav className="training-tabs" aria-label="Wybierz trening">
        {trainings.map((t, i) => (
          <button
            key={`${t.name}-${i}`}
            type="button"
            className={`training-tab${i === safeIdx ? ' active' : ''}`}
            onClick={() => setActiveIdx(i)}
            aria-current={i === safeIdx ? 'page' : undefined}
          >
            {t.name}
          </button>
        ))}
      </nav>

      <TrainingSections training={active} />
    </>
  );
}

function TrainingSections({ training }: { training: Training }) {
  return (
    <div className="training-sections">
      {training.sections.map((section, si) => (
        <section key={si} className="training-section">
          {section.label && <h3 className="training-section-label">{section.label}</h3>}
          <div className="training-table-wrap">
            <table className="training-table">
              <thead>
                <tr>
                  {section.headers.map((h, i) => (
                    <th key={i}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {section.exercises.map((ex, i) => (
                  <tr key={`${ex.number}-${i}`}>
                    {ex.cells.map((cell, ci) => (
                      <td key={ci} className={cell === '' ? 'plan-cell-empty' : undefined}>
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </div>
  );
}

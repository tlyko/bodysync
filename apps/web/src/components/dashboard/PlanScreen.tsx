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

type TrainingGroup = {
  name: string;
  weeks: Training[]; // sorted by weekIdx asc (najnowszy = last)
};

function groupTrainings(trainings: Training[]): TrainingGroup[] {
  // Zachowaj source order pierwszego wystąpienia każdej grupy
  const order: string[] = [];
  const map = new Map<string, Training[]>();
  for (const t of trainings) {
    if (!map.has(t.name)) {
      order.push(t.name);
      map.set(t.name, []);
    }
    map.get(t.name)!.push(t);
  }
  return order.map((name) => ({ name, weeks: map.get(name)! }));
}

function PlanContent({ plan }: { plan: PlanResponse }) {
  const trainings = useMemo(() => parseTrainings(plan.rows), [plan.rows]);
  const groups = useMemo(() => groupTrainings(trainings), [trainings]);

  const [activeGroupIdx, setActiveGroupIdx] = useState(0);
  // Per-group week selection. Default = najnowszy (last week in group).
  // Map<groupName, weekIdx> — initialize z group.weeks.length (1-indexed).
  const [weekByGroup, setWeekByGroup] = useState<Record<string, number>>(() => {
    const init: Record<string, number> = {};
    for (const g of groups) init[g.name] = g.weeks.length; // 1-indexed last
    return init;
  });

  if (plan.rows.length === 0) {
    return (
      <p className="placeholder-text">
        Arkusz jest pusty albo zakładka <strong>{plan.sheet_tab}</strong> nie istnieje.
      </p>
    );
  }

  if (groups.length === 0) {
    return (
      <p className="placeholder-text">
        Nie udało się sparsować planu (brak nagłówka <code>Numer</code> w arkuszu).
        Sprawdź czy zakładka <strong>{plan.sheet_tab}</strong> ma standardowy
        layout od trenerki.
      </p>
    );
  }

  const safeGroupIdx = Math.min(activeGroupIdx, groups.length - 1);
  const activeGroup = groups[safeGroupIdx];
  const selectedWeekIdx = weekByGroup[activeGroup.name] ?? activeGroup.weeks.length;
  const safeWeek = Math.min(Math.max(1, selectedWeekIdx), activeGroup.weeks.length);
  const activeTraining = activeGroup.weeks[safeWeek - 1];

  return (
    <>
      <nav className="training-tabs" aria-label="Wybierz trening">
        {groups.map((g, i) => (
          <button
            key={g.name}
            type="button"
            className={`training-tab${i === safeGroupIdx ? ' active' : ''}`}
            onClick={() => setActiveGroupIdx(i)}
            aria-current={i === safeGroupIdx ? 'page' : undefined}
          >
            {g.name}
          </button>
        ))}
      </nav>

      {activeGroup.weeks.length > 1 && (
        <div className="training-week-selector">
          <label htmlFor="training-week" className="training-week-label">
            Tydzień:
          </label>
          <select
            id="training-week"
            className="training-week-select"
            value={safeWeek}
            onChange={(e) =>
              setWeekByGroup((prev) => ({
                ...prev,
                [activeGroup.name]: Number(e.target.value),
              }))
            }
          >
            {activeGroup.weeks.map((w) => (
              <option key={w.weekIdx} value={w.weekIdx}>
                {weekLabel(w.weekIdx, w.weekTotal)}
              </option>
            ))}
          </select>
        </div>
      )}

      <TrainingSections training={activeTraining} />
    </>
  );
}

function weekLabel(idx: number, total: number): string {
  if (idx === total) return `#${idx} (najnowszy)`;
  if (idx === total - 1) return `#${idx} (poprzedni)`;
  return `#${idx}`;
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

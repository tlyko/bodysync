// Workout history (2026-05-17) — owner-triggered extraction z Google Sheet.
// Button "Zaktualizuj historię z arkusza" → frontend wysyła pre-parsed Training[]
// → backend Haiku parse per ćwiczenie → DDB → GET /api/workouts re-fetch.

import { useEffect, useState } from 'react';
import { getWorkouts, postWorkoutsExtract, workoutsErrorMessage } from '../../api';
import type { WorkoutEntry } from '../../types';
import type { Training } from './planParser';

type State =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ok'; entries: WorkoutEntry[] }
  | { status: 'error'; reason: string };

type Props = {
  trainings: Training[]; // pre-parsed z planParser w PlanScreen
};

function localTodayIso(): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, '0');
  const d = String(now.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

function groupByDate(entries: WorkoutEntry[]): Map<string, WorkoutEntry[]> {
  // entries już sorted desc po dacie z backendu. Re-group dla date headers.
  const grouped = new Map<string, WorkoutEntry[]>();
  for (const e of entries) {
    if (!grouped.has(e.date)) grouped.set(e.date, []);
    grouped.get(e.date)!.push(e);
  }
  return grouped;
}

const PL_DATE_LONG = new Intl.DateTimeFormat('pl-PL', {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
  year: 'numeric',
});

function formatDate(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number);
  return PL_DATE_LONG.format(new Date(y, m - 1, d));
}

function formatSet(set: { weight_kg?: number | null; weight_kind: string; reps: number }): string {
  if (set.weight_kind === 'bw') {
    const extra = set.weight_kg && set.weight_kg > 0 ? ` +${set.weight_kg}kg` : '';
    return `BW${extra} × ${set.reps}`;
  }
  if (set.weight_kg === null || set.weight_kg === undefined) {
    return `? × ${set.reps}`;
  }
  return `${set.weight_kg}kg × ${set.reps}`;
}

export function WorkoutHistorySection({ trainings }: Props) {
  const [state, setState] = useState<State>({ status: 'idle' });
  const [extracting, setExtracting] = useState(false);
  const [lastExtract, setLastExtract] = useState<string>('');
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const fetchEntries = async () => {
    setState({ status: 'loading' });
    try {
      const data = await getWorkouts(90);
      setState({ status: 'ok', entries: data.workouts ?? [] });
    } catch (err) {
      setState({ status: 'error', reason: workoutsErrorMessage(err) });
    }
  };

  useEffect(() => {
    fetchEntries();
  }, []);

  const triggerExtract = async () => {
    if (extracting || trainings.length === 0) return;
    setExtracting(true);
    setLastExtract('');
    try {
      const res = await postWorkoutsExtract({
        today_iso: localTodayIso(),
        trainings: trainings as unknown[],
      });
      setLastExtract(
        `Wyciągnięto ${res.extracted} ćwiczeń (pominięto ${res.skipped}, błędów ${res.errors}).`,
      );
      // Po ekstrakcji re-fetch listy.
      await fetchEntries();
    } catch (err) {
      setLastExtract(workoutsErrorMessage(err));
    } finally {
      setExtracting(false);
    }
  };

  const toggleExpand = (key: string) => {
    setExpanded((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <section className="workout-history">
      <header className="workout-history-header">
        <h3>Historia wykonana</h3>
        <p>
          Ciężary i powtórzenia wyciągnięte z arkusza. Klik "Zaktualizuj" parsuje aktualny stan
          Twoich wpisów (kolumna „Ciężar x serie x powtórzenia x RIR").
        </p>
        <button
          type="button"
          className="workout-history-button"
          onClick={triggerExtract}
          disabled={extracting || trainings.length === 0}
        >
          {extracting ? 'Parsowanie…' : 'Zaktualizuj historię z arkusza'}
        </button>
        {lastExtract && (
          <p
            className={
              lastExtract.startsWith('Wyciągnięto')
                ? 'workout-history-success'
                : 'workout-history-error'
            }
            role={lastExtract.startsWith('Wyciągnięto') ? 'status' : 'alert'}
          >
            {lastExtract}
          </p>
        )}
      </header>

      {state.status === 'loading' && <p className="placeholder-text">Wczytywanie historii…</p>}

      {state.status === 'error' && (
        <p className="error" role="alert">
          {state.reason}
        </p>
      )}

      {state.status === 'ok' && state.entries.length === 0 && (
        <p className="placeholder-text">
          Brak zapisanej historii. Kliknij „Zaktualizuj" żeby wyciągnąć aktualny stan z arkusza.
        </p>
      )}

      {state.status === 'ok' && state.entries.length > 0 && (
        <div className="workout-history-list">
          {[...groupByDate(state.entries).entries()].map(([date, items]) => (
            <div key={date} className="workout-history-day">
              <h4 className="workout-history-date">{formatDate(date)}</h4>
              <ul>
                {items.map((entry) => {
                  const key = `${date}#${entry.training_slug}#${entry.exercise_number}`;
                  const isOpen = expanded[key] ?? false;
                  return (
                    <li key={key} className="workout-history-item">
                      <button
                        type="button"
                        className="workout-history-item-toggle"
                        onClick={() => toggleExpand(key)}
                        aria-expanded={isOpen}
                      >
                        <span className="workout-history-item-name">
                          {entry.exercise_number}. {entry.exercise_name}
                        </span>
                        <span className="workout-history-item-summary">
                          {entry.sets.length} {entry.sets.length === 1 ? 'set' : 'setów'}
                          {entry.rir != null && ` · RIR ${entry.rir}`}
                        </span>
                      </button>
                      {isOpen && (
                        <div className="workout-history-sets">
                          <table>
                            <thead>
                              <tr>
                                <th>#</th>
                                <th>Set</th>
                              </tr>
                            </thead>
                            <tbody>
                              {entry.sets.map((s, idx) => (
                                <tr key={idx}>
                                  <td>{idx + 1}</td>
                                  <td>{formatSet(s)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                          {entry.notes && (
                            <p className="workout-history-notes">{entry.notes}</p>
                          )}
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

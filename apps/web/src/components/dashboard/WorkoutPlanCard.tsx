// Sprint 10 A10 — "Plan na dziś" tile na Dashboard overview.
// Bridge między tab Plan Treningowy a Dashboard — owner widzi listę
// dostępnych treningów + count Strava 7d + CTA do tab plan, bez
// smart "wykonaj X" suggestion (logbook #23 future, bez tego heurystyka
// halucynuje).

import { useEffect, useState } from 'react';
import { getActivities, getPlan } from '../../api';
import { parseTrainings } from './planParser';

type Props = {
  onSeePlan: () => void;
};

type State =
  | { status: 'loading' }
  | { status: 'no_plan' } // 4xx Sheets / not_configured
  | {
      status: 'ready';
      uniqueTrainings: string[];
      activitiesThisWeek: number;
    };

export function WorkoutPlanCard({ onSeePlan }: Props) {
  const [state, setState] = useState<State>({ status: 'loading' });

  useEffect(() => {
    let cancelled = false;
    Promise.all([getPlan().catch(() => null), getActivities(20).catch(() => null)])
      .then(([plan, activities]) => {
        if (cancelled) return;
        if (!plan) {
          setState({ status: 'no_plan' });
          return;
        }
        const trainings = parseTrainings(plan.rows);
        // Unique base names (Trening A, B, C, D) — drop weekIdx duplicates.
        const uniqueTrainings = Array.from(new Set(trainings.map((t) => t.name)));
        const cutoffMs = Date.now() - 7 * 24 * 3600 * 1000;
        const activitiesThisWeek =
          activities?.items.filter((a) => Date.parse(a.start_date) >= cutoffMs).length ?? 0;
        setState({ status: 'ready', uniqueTrainings, activitiesThisWeek });
      })
      .catch(() => {
        if (cancelled) return;
        setState({ status: 'no_plan' });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section className="section-panel workout-plan-card">
      <div className="section-panel-head">
        <h3 className="section-panel-title">Plan na dziś</h3>
        {state.status === 'ready' && (
          <button type="button" className="section-panel-link" onClick={onSeePlan}>
            Zobacz plan →
          </button>
        )}
      </div>

      {state.status === 'loading' && <p className="placeholder-text">Wczytywanie…</p>}

      {state.status === 'no_plan' && (
        <div className="workout-plan-empty">
          <p className="placeholder-text">
            Plan treningowy nie skonfigurowany. Wpisz Sheet ID w Ustawieniach.
          </p>
          <button type="button" className="section-panel-link" onClick={onSeePlan}>
            Idź do Plan Treningowy →
          </button>
        </div>
      )}

      {state.status === 'ready' && (
        <div className="workout-plan-body">
          <p className="workout-plan-summary">
            <strong>{state.activitiesThisWeek}</strong>{' '}
            {state.activitiesThisWeek === 1 ? 'trening' : 'treningów'} w tym tygodniu
          </p>
          {state.uniqueTrainings.length > 0 && (
            <ul className="workout-plan-list">
              {state.uniqueTrainings.map((name) => (
                <li key={name} className="workout-plan-item">
                  <span className="workout-plan-icon">💪</span>
                  <button
                    type="button"
                    className="workout-plan-name"
                    onClick={onSeePlan}
                  >
                    {name}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {state.uniqueTrainings.length === 0 && (
            <p className="placeholder-text">Plan jest pusty — dodaj treningi w Sheet.</p>
          )}
        </div>
      )}
    </section>
  );
}

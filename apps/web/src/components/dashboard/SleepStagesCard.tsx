// Sprint 10 A11 — sleep stages breakdown z HAE payload.
// Horizontal stacked bar (deep / REM / core / awake) + legenda z h:min
// values + total asleep label. HAE wysyła wartości w godzinach (np. 1.45
// = 1h 27min).

import type { SleepStages } from '../../biometry';

const STAGE_COLORS = {
  deep: '#7c3aed', // głęboki purple — restorative
  rem: '#22d3ee', // cyan — dreaming/memory consolidation
  core: '#10b981', // green — light sleep, większość nocy
  awake: '#ef4444', // red — wybudzenia
} as const;

const STAGE_LABELS_PL = {
  deep: 'Głęboki',
  rem: 'REM',
  core: 'Lekki',
  awake: 'Wybudzenia',
} as const;

type Props = {
  stages: SleepStages | null;
};

function hoursToHmin(hours: number): string {
  if (hours <= 0) return '0min';
  const totalMinutes = Math.round(hours * 60);
  const h = Math.floor(totalMinutes / 60);
  const m = totalMinutes % 60;
  if (h === 0) return `${m}min`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}min`;
}

const PL_DATE = new Intl.DateTimeFormat('pl-PL', {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
});

function relativeDateLabel(dateIso: string): string {
  const today = new Date();
  const todayIso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
  if (dateIso === todayIso) return 'dziś';
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  const yIso = `${yesterday.getFullYear()}-${String(yesterday.getMonth() + 1).padStart(2, '0')}-${String(yesterday.getDate()).padStart(2, '0')}`;
  if (dateIso === yIso) return 'wczoraj';
  return PL_DATE.format(new Date(dateIso));
}

export function SleepStagesCard({ stages }: Props) {
  if (stages === null) {
    return (
      <section className="sleep-stages-card empty">
        <div className="section-panel-head">
          <h3 className="section-panel-title">Struktura snu</h3>
        </div>
        <p className="placeholder-text">
          Brak danych o stadiach snu. HAE webhook wysyła <code>core</code>/<code>rem</code>/
          <code>deep</code> tylko gdy nosisz Apple Watch w nocy.
        </p>
      </section>
    );
  }

  // Total dla bar-percentage = suma 4 stages (asleep + awake okres w łóżku).
  // Używamy tej sumy zamiast inBed bo inBed może mieć dryf z buggy HAE.
  const total = stages.deep + stages.rem + stages.core + stages.awake;
  const order: Array<keyof typeof STAGE_COLORS> = ['deep', 'rem', 'core', 'awake'];

  return (
    <section className="sleep-stages-card">
      <div className="section-panel-head">
        <h3 className="section-panel-title">
          Struktura snu · <span className="sleep-stages-date">{relativeDateLabel(stages.date)}</span>
        </h3>
        <span className="sleep-stages-total">
          {hoursToHmin(stages.asleep)} <span className="sleep-stages-total-unit">snu</span>
        </span>
      </div>

      <div
        className="sleep-stages-bar"
        role="img"
        aria-label={`Struktura snu: głęboki ${hoursToHmin(stages.deep)}, REM ${hoursToHmin(
          stages.rem,
        )}, lekki ${hoursToHmin(stages.core)}, wybudzenia ${hoursToHmin(stages.awake)}`}
      >
        {order.map((stage) => {
          const value = stages[stage];
          if (value <= 0) return null;
          const pct = (value / total) * 100;
          return (
            <span
              key={stage}
              className={`sleep-stages-segment stage-${stage}`}
              style={{ width: `${pct}%`, background: STAGE_COLORS[stage] }}
              title={`${STAGE_LABELS_PL[stage]}: ${hoursToHmin(value)}`}
            />
          );
        })}
      </div>

      <ul className="sleep-stages-legend">
        {order.map((stage) => (
          <li key={stage} className="sleep-stages-legend-item">
            <span
              className="sleep-stages-legend-dot"
              style={{ background: STAGE_COLORS[stage] }}
            />
            <span className="sleep-stages-legend-label">{STAGE_LABELS_PL[stage]}</span>
            <span className="sleep-stages-legend-value">{hoursToHmin(stages[stage])}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

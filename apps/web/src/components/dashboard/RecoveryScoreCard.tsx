import { calculateRecoveryScore, type RecoveryLabel } from '../../recovery';
import type { BiometryDay } from '../../types';

type Props = {
  days: BiometryDay[];
  todayIso: string; // YYYY-MM-DD w boundary Warsaw
};

// CSS color class per label. Mirror status names z KcalBalanceCard.
const LABEL_CLASS: Record<RecoveryLabel, string> = {
  ZREGENEROWANY: 'recovery-score-good',
  UMIARKOWANY: 'recovery-score-moderate',
  WYPOCZYNEK: 'recovery-score-poor',
  'BRAK DANYCH': 'recovery-score-empty',
};

const INT_PL = (v: number) => Math.round(v).toLocaleString('pl-PL');

function formatDelta(delta: number): string {
  if (delta === 0) return '±0';
  const rounded = Math.round(delta);
  return rounded > 0 ? `+${rounded}` : `−${Math.abs(rounded)}`;
}

// 7-day sparkline — per-day recovery score (jednodniowy slide window żeby pokazać trend).
type DayScore = {
  date: string;
  score: number;
  label: RecoveryLabel;
};

function buildPerDayScores(days: BiometryDay[], todayIso: string): DayScore[] {
  // Day-by-day calculation re-uses pełną serię (RHR baseline z 14d window dla
  // każdego dnia). Brak score = pomijamy dzień.
  const out: DayScore[] = [];
  const sortedDates = [...days]
    .map((d) => d.date)
    .sort()
    .slice(-7);
  for (const date of sortedDates) {
    if (date > todayIso) continue;
    const r = calculateRecoveryScore(days, date);
    if (r.score !== null) {
      out.push({ date, score: r.score, label: r.label });
    }
  }
  return out;
}

// Recovery Score card — composite 0-100 z sleep + RHR. Owner zatwierdził
// koncepcję 2026-05-15. HRV celowo pominięte (Garmin nie wysyła do AH,
// PR #177 drop HRV z UI). Pełnej szerokości, między overview-grid a
// KcalBalanceCard.
export function RecoveryScoreCard({ days, todayIso }: Props) {
  const result = calculateRecoveryScore(days, todayIso);
  const perDay = buildPerDayScores(days, todayIso);

  const labelClass = LABEL_CLASS[result.label];

  return (
    <section className="recovery-score-card" aria-label="Recovery score">
      <h3>Recovery</h3>

      <div className="recovery-score-primary">
        <span className={`recovery-score-value ${labelClass}`}>
          {result.score !== null ? result.score : '—'}
          <span className="recovery-score-unit"> / 100</span>
        </span>
        <span className={`recovery-score-label ${labelClass}`}>{result.label}</span>
      </div>

      <div className="recovery-breakdown">
        <div>
          <span className="recovery-breakdown-label">Sen</span>
          <span className="recovery-breakdown-value">
            {result.components.sleepHours !== null
              ? result.components.sleepHours.toFixed(1)
              : '—'}{' '}
            <small>h</small>
          </span>
        </div>
        <div>
          <span className="recovery-breakdown-label">Jakość</span>
          <span className="recovery-breakdown-value">
            {result.components.sleepQualityPct !== null
              ? Math.round(result.components.sleepQualityPct)
              : '—'}{' '}
            <small>%</small>
          </span>
        </div>
        <div>
          <span className="recovery-breakdown-label">RHR Δ</span>
          <span className="recovery-breakdown-value">
            {result.components.rhrDelta !== null
              ? formatDelta(result.components.rhrDelta)
              : '—'}{' '}
            <small>bpm</small>
          </span>
        </div>
      </div>

      {perDay.length > 0 && (
        <div className="recovery-spark">
          <span className="recovery-spark-label">Ost. 7 dni:</span>
          <div
            className="recovery-spark-bars"
            role="img"
            aria-label="Recovery score ostatnich 7 dni"
          >
            {perDay.map((d) => {
              const heightPct = d.score; // 0-100 → 0-100% bar height
              const dayClass = LABEL_CLASS[d.label];
              return (
                <span
                  key={d.date}
                  className={`recovery-spark-bar ${dayClass}`}
                  style={{ height: `${Math.max(heightPct, 8)}%` }}
                  title={`${d.date}: ${INT_PL(d.score)} (${d.label})`}
                />
              );
            })}
          </div>
        </div>
      )}
    </section>
  );
}

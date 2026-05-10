import type { ReactNode } from 'react';
import { Sparkline } from './Sparkline';

const ACCENT_COLOR: Record<Accent, string> = {
  cyan: '#22d3ee',
  green: '#10b981',
  orange: '#f59e0b',
  purple: '#a78bfa',
  red: '#ef4444',
  pink: '#f472b6',
  muted: '#94a3b8',
};

type Accent = 'cyan' | 'green' | 'orange' | 'purple' | 'red' | 'pink' | 'muted';

type Props = {
  label: string;
  value: string | number | null;
  unit?: string;
  accent?: Accent;
  sparkData?: number[];
  change?: number | null;
  icon?: ReactNode;
  // Sprint 10 A2 — opcjonalny target dla makro/kcal_in cards. Gdy podany,
  // zastępuje sparkline progress barem + "X/Y unit · zostało Z" tekstem.
  // `targetValueRaw` (numeric) używany do progress calc; `value` może być
  // pre-formatted string (np. "1 240" z toLocaleString).
  target?: number;
  targetValueRaw?: number;
};

export function StatCard({
  label,
  value,
  unit,
  accent = 'cyan',
  sparkData,
  change,
  icon,
  target,
  targetValueRaw,
}: Props) {
  const isEmpty = value === null || value === '—' || value === undefined;
  const accentClass = `stat-card-accent-${accent}`;
  const sparkColor = ACCENT_COLOR[accent];

  const trendArrow = typeof change === 'number' ? (change >= 0 ? '▲' : '▼') : null;
  const trendClass = typeof change === 'number' ? (change >= 0 ? 'up' : 'down') : '';

  const hasTarget = typeof target === 'number' && target > 0 && typeof targetValueRaw === 'number';
  const pct = hasTarget ? (targetValueRaw / target) * 100 : null;
  const remaining = hasTarget ? target - targetValueRaw : null;

  return (
    <div className={`stat-card ${accentClass}`}>
      <div className="stat-card-header">
        {icon && <span className="stat-card-icon">{icon}</span>}
        <span className="stat-card-label">{label}</span>
      </div>
      <div className="stat-card-value-row">
        <span className="stat-card-value">{isEmpty ? '—' : value}</span>
        {!isEmpty && unit && <span className="stat-card-unit">{unit}</span>}
        {hasTarget && (
          <span className="stat-card-target-suffix">
            / {target.toLocaleString('pl-PL')}
          </span>
        )}
      </div>
      {hasTarget && pct !== null && remaining !== null ? (
        <TargetProgress pct={pct} remaining={remaining} unit={unit} />
      ) : (
        (typeof change === 'number' || (sparkData && sparkData.length >= 2)) && (
          <div className="stat-card-bottom">
            {typeof change === 'number' && (
              <span className={`stat-card-trend ${trendClass}`}>
                {trendArrow} {Math.abs(change).toFixed(0)}%
              </span>
            )}
            {sparkData && sparkData.length >= 2 && !isEmpty && (
              <span className="stat-card-sparkline-wrap">
                <Sparkline data={sparkData} color={sparkColor} width={120} height={36} />
              </span>
            )}
          </div>
        )
      )}
    </div>
  );
}

function TargetProgress({
  pct,
  remaining,
  unit,
}: {
  pct: number;
  remaining: number;
  unit?: string;
}) {
  // Color logic: <100% green (still budget left), 100-110% orange (slight
  // over, w normie dziennej), >110% red (znacznie powyżej target).
  // Reasoning: dietetyczna tolerance ±10% jest ok, większa wymaga uwagi.
  let toneClass = 'progress-under';
  if (pct >= 110) toneClass = 'progress-far-over';
  else if (pct >= 100) toneClass = 'progress-over';

  const fillWidth = Math.min(pct, 100);
  // Overflow ring: gdy >100%, rysujemy second bar w cieniu w tonie warning.
  const overflowWidth = pct > 100 ? Math.min(pct - 100, 50) : 0;

  // Tekst pod barem: "zostało X" / "powyżej +X" — value bez minus znaku, tone
  // wskazuje stan przez kolor + frazę.
  const remainingText =
    remaining >= 0
      ? `zostało ${Math.round(remaining).toLocaleString('pl-PL')}${unit ? ' ' + unit : ''}`
      : `powyżej +${Math.round(-remaining).toLocaleString('pl-PL')}${unit ? ' ' + unit : ''}`;

  return (
    <div className="stat-card-target-bottom">
      <div className={`stat-card-progress-track ${toneClass}`}>
        <div className="stat-card-progress-fill" style={{ width: `${fillWidth}%` }} />
        {overflowWidth > 0 && (
          <div
            className="stat-card-progress-overflow"
            style={{ width: `${overflowWidth}%` }}
          />
        )}
      </div>
      <div className="stat-card-progress-meta">
        <span className={`stat-card-progress-pct ${toneClass}`}>{Math.round(pct)}%</span>
        <span className="stat-card-progress-remaining">{remainingText}</span>
      </div>
    </div>
  );
}

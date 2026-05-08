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
};

export function StatCard({
  label,
  value,
  unit,
  accent = 'cyan',
  sparkData,
  change,
  icon,
}: Props) {
  const isEmpty = value === null || value === '—' || value === undefined;
  const accentClass = `stat-card-accent-${accent}`;
  const sparkColor = ACCENT_COLOR[accent];

  const trendArrow = typeof change === 'number' ? (change >= 0 ? '▲' : '▼') : null;
  const trendClass = typeof change === 'number' ? (change >= 0 ? 'up' : 'down') : '';

  return (
    <div className={`stat-card ${accentClass}`}>
      <div className="stat-card-header">
        {icon && <span className="stat-card-icon">{icon}</span>}
        <span className="stat-card-label">{label}</span>
      </div>
      <div className="stat-card-value-row">
        <span className="stat-card-value">{isEmpty ? '—' : value}</span>
        {!isEmpty && unit && <span className="stat-card-unit">{unit}</span>}
      </div>
      {(typeof change === 'number' || (sparkData && sparkData.length >= 2)) && (
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
      )}
    </div>
  );
}

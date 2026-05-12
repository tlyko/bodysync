import type { SeriesPoint } from '../../biometry';

export type MetricChartColor = 'cyan' | 'orange' | 'green' | 'purple' | 'red';

// Color tokens dla MetricChart — mirror `--{name}` vars z `index.css`. SVG
// `fill="var(--cyan)"` ma niespójne wsparcie w Safari dla niektórych wersji,
// więc trzymamy hex mapping single source of truth.
const COLOR_HEX: Record<MetricChartColor, string> = {
  cyan: '#22d3ee',
  orange: '#f59e0b',
  green: '#10b981',
  purple: '#a78bfa',
  red: '#ef4444',
};

type Props = {
  data: SeriesPoint[];
  label: string;
  unit: string;
  color: MetricChartColor;
  width?: number;
  height?: number;
  formatValue?: (v: number) => string;
};

const PAD_TOP = 16;
const PAD_BOTTOM = 24;
const PAD_LEFT = 36;
const PAD_RIGHT = 8;
const BAR_GAP_RATIO = 0.3;
const BAR_RADIUS = 3;

const defaultFormat = (v: number) => v.toFixed(0);

// Generic bar chart per-day dla pojedynczej metryki w czasie. Empty state
// gdy `data.length === 0`. Y-axis od 0 (bar chart best-practice — proportional
// scale, NIE relatywny diff), padded ~5% nad max żeby najwyższy bar nie
// dotykał górnej krawędzi. Each data point = jeden bar z rounded top.
export function MetricChart({
  data,
  label,
  unit,
  color,
  width = 600,
  height = 180,
  formatValue = defaultFormat,
}: Props) {
  if (data.length === 0) {
    return <div className="metric-chart-empty">Brak danych dla wybranego okresu</div>;
  }

  const sorted = [...data].sort((a, b) => a.date.localeCompare(b.date));
  const values = sorted.map((d) => d.value);
  const maxV = Math.max(...values, 0);
  // Bar chart Y zaczyna od 0 (NIE minV) — proportional comparison między
  // dniami. Top padding 5% nad max żeby bar nie dotykał krawędzi.
  const yMax = Math.ceil(maxV * 1.05) || 1;
  const yMin = 0;
  const yRange = yMax - yMin;

  const plotW = width - PAD_LEFT - PAD_RIGHT;
  const plotH = height - PAD_TOP - PAD_BOTTOM;
  const slotW = plotW / sorted.length;
  const barW = slotW * (1 - BAR_GAP_RATIO);

  const yFor = (v: number) => PAD_TOP + plotH - ((v - yMin) / yRange) * plotH;
  const baseY = PAD_TOP + plotH;

  const firstDate = sorted[0].date;
  const lastDate = sorted[sorted.length - 1].date;
  const lastValue = sorted[sorted.length - 1].value;

  const fill = COLOR_HEX[color];
  // Unique gradient id (3 chart-y na stronie z różnymi kolorami → defs muszą
  // się NIE zderzyć). `label` jest stable identyfikatorem, sanitize do
  // valid SVG id.
  const gradId = `metric-chart-grad-${color}-${label.replace(/[^a-zA-Z0-9]/g, '')}`;

  return (
    <svg
      className="metric-chart"
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
      height={height}
      preserveAspectRatio="none"
      role="img"
      aria-label={`Wykres słupkowy ${label} ${firstDate} — ${lastDate}, ostatnia wartość ${formatValue(lastValue)} ${unit}`}
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={fill} stopOpacity="0.95" />
          <stop offset="100%" stopColor={fill} stopOpacity="0.55" />
        </linearGradient>
      </defs>

      {/* Y-axis labels (max top, 0 bottom) */}
      <text x={PAD_LEFT - 6} y={PAD_TOP + 4} className="metric-chart-axis-label y-label">
        {formatValue(yMax)}
      </text>
      <text x={PAD_LEFT - 6} y={baseY} className="metric-chart-axis-label y-label">
        {formatValue(yMin)}
      </text>

      {/* Horizontal grid line at midpoint */}
      <line
        x1={PAD_LEFT}
        y1={PAD_TOP + plotH / 2}
        x2={PAD_LEFT + plotW}
        y2={PAD_TOP + plotH / 2}
        className="metric-chart-grid"
      />

      {/* Baseline (0) — pomaga wizualnie "zakotwiczyć" bary */}
      <line
        x1={PAD_LEFT}
        y1={baseY}
        x2={PAD_LEFT + plotW}
        y2={baseY}
        className="metric-chart-grid"
      />

      {/* Bars — jeden rect per data point, gradient fill, rounded top corners.
          SVG nie ma per-corner radius, więc używamy global `rx`/`ry` — wpływa
          też na dolne corners, ale baseline line je przykrywa wizualnie. */}
      {sorted.map((d, i) => {
        const x = PAD_LEFT + i * slotW + (slotW - barW) / 2;
        const y = yFor(d.value);
        const h = baseY - y;
        return (
          <rect
            key={d.date}
            x={x}
            y={y}
            width={barW}
            height={Math.max(h, 0)}
            rx={BAR_RADIUS}
            ry={BAR_RADIUS}
            fill={`url(#${gradId})`}
          >
            <title>
              {d.date}: {formatValue(d.value)} {unit}
            </title>
          </rect>
        );
      })}

      {/* X-axis date labels (first + last) */}
      <text x={PAD_LEFT} y={height - 6} className="metric-chart-axis-label">
        {firstDate}
      </text>
      <text x={PAD_LEFT + plotW} y={height - 6} className="metric-chart-axis-label end">
        {lastDate}
      </text>
    </svg>
  );
}

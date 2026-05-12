import type { SeriesPoint } from '../../biometry';

// Color tokens dla MetricChart — reflect `--{name}` vars w `index.css`.
// Inline gradient definicje SVG nie obsługują `var()` w stop-color w 100%
// browserów (Safari edge cases), więc trzymamy mapping na hex tutaj.
// Trzymane jako single source of truth — gdy zmieniamy color tokens w
// index.css, synchronizujemy tutaj.
const COLOR_HEX: Record<MetricChartColor, string> = {
  cyan: '#22d3ee',
  orange: '#f59e0b',
  green: '#10b981',
  purple: '#a78bfa',
  red: '#ef4444',
};

export type MetricChartColor = 'cyan' | 'orange' | 'green' | 'purple' | 'red';

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
const PAD_BOTTOM = 24; // miejsce na first/last date label
const PAD_LEFT = 36; // miejsce na axis labels (Y range)
const PAD_RIGHT = 8;

const defaultFormat = (v: number) => v.toFixed(0);

// Generic line chart dla pojedynczej metryki w czasie. Empty state gdy
// `data.length < 2` (analog WeightChart). Y-axis labele min/max + X-axis
// first/last date pod osią. Mirror SVG struktury z `WeightChart` minus
// EMA overlay i waga-specific footer (trend kg/week).
//
// Reuse: linearGradient pod krzywą, X/Y axis labels, last point dot,
// padding constants. `color` z 5 design tokenów (cyan/orange/green/purple/red).
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
  if (data.length < 2) {
    return (
      <div className="metric-chart-empty">
        Tylko 1 punkt ({formatValue(data[0].value)} {unit}) — wykres pojawi się po kolejnym.
      </div>
    );
  }

  const sorted = [...data].sort((a, b) => a.date.localeCompare(b.date));
  const values = sorted.map((d) => d.value);
  const minV = Math.min(...values);
  const maxV = Math.max(...values);
  // Padding range — chroni przed "płaską linią" gdy wartości identyczne.
  // Używamy 5% range padding, minimum 1 jednostkę (kcal/steps są integer).
  const rangeRaw = maxV - minV;
  const pad = Math.max(rangeRaw * 0.05, 1);
  const yMin = Math.floor(minV - pad);
  const yMax = Math.ceil(maxV + pad);
  const yRange = yMax - yMin || 1;

  const plotW = width - PAD_LEFT - PAD_RIGHT;
  const plotH = height - PAD_TOP - PAD_BOTTOM;

  const xFor = (i: number) =>
    PAD_LEFT + (sorted.length === 1 ? plotW / 2 : (i / (sorted.length - 1)) * plotW);
  const yFor = (v: number) => PAD_TOP + plotH - ((v - yMin) / yRange) * plotH;

  const linePoints = sorted.map((d, i) => `${xFor(i)},${yFor(d.value)}`).join(' ');

  const firstDate = sorted[0].date;
  const lastDate = sorted[sorted.length - 1].date;
  const lastValue = sorted[sorted.length - 1].value;

  const stroke = COLOR_HEX[color];
  // Unique gradient id na render — gdy 3 instancje MetricChart na tej samej
  // stronie z różnymi `color`, gradient defs muszą się NIE zderzyć. Format
  // `metric-chart-grad-${color}-${label}` — `label` jest stable identyfikatorem
  // (np. "Kalorie spożyte") i pozwala mieć 2 chart-y z tym samym color
  // tokenem na tej samej stronie. Sanitize spaces i polish chars dla
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
      aria-label={`Wykres ${label} ${firstDate} — ${lastDate}, ostatnia wartość ${formatValue(lastValue)} ${unit}`}
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.3" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0" />
        </linearGradient>
      </defs>

      {/* Y-axis labels (max top, min bottom) */}
      <text x={PAD_LEFT - 6} y={PAD_TOP + 4} className="metric-chart-axis-label y-label">
        {formatValue(yMax)}
      </text>
      <text x={PAD_LEFT - 6} y={PAD_TOP + plotH} className="metric-chart-axis-label y-label">
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

      {/* Filled gradient area under line */}
      <polygon
        points={`${xFor(0)},${PAD_TOP + plotH} ${linePoints} ${xFor(sorted.length - 1)},${PAD_TOP + plotH}`}
        fill={`url(#${gradId})`}
      />

      {/* Main line */}
      <polyline
        points={linePoints}
        fill="none"
        stroke={stroke}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {/* Last point dot — wyróżnia "current value" na końcu serii. */}
      <circle
        cx={xFor(sorted.length - 1)}
        cy={yFor(lastValue)}
        r="4"
        fill={stroke}
        stroke="#0a0e17"
        strokeWidth="2"
      />

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

import { useEffect, useRef, useState } from 'react';
import { weeklyTrendKg, weightEMA } from '../../biometry';

type WeightPoint = {
  date: string; // YYYY-MM-DD
  weight: number; // kg
};

type Props = {
  data: WeightPoint[];
  height?: number;
};

const PAD_TOP = 16;
const PAD_BOTTOM = 24; // miejsce na first/last date label
const PAD_LEFT = 36; // miejsce na axis labels (kg range)
const PAD_RIGHT = 8;

// Sprint 10 A5 — EMA smoothing α. 0.1 daje ~10-day half-life (waga 10 dni
// temu w EMA = ~37%, 30 dni temu ~4%). Empirycznie dopasowane do raw HAE
// signal (~±0.5 kg dnia-na-dzień noise z hydratacji).
const EMA_ALPHA = 0.1;

// Line chart wagi 30 dni. Empty state gdy `data.length === 0` lub `data.length === 1`
// (jeden punkt = brak skali). Y-axis ma min/max range padded o 0.5 kg każdy
// koniec żeby linia nie dotykała górnej/dolnej krawędzi. Pokazuje labele
// min/max na osi Y + first/last datę pod osią X.
export function WeightChart({ data, height = 220 }: Props) {
  // ResizeObserver — viewBox śledzi pixel width containera, SVG internal
  // coords = pixel coords. Tekst/circle/EMA dashed pattern bez stretchu.
  const wrapRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(600);
  // Hover state: index data point pod kursorem (null = brak hover).
  // Steruje rendering highlight dotów (raw + EMA) i tooltip.
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);

  useEffect(() => {
    if (!wrapRef.current || typeof ResizeObserver === 'undefined') return;
    const el = wrapRef.current;
    const ro = new ResizeObserver((entries) => {
      const w = Math.round(entries[0].contentRect.width);
      if (w > 0) setWidth(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Touch UX: tap outside the chart container closes the tooltip. Mouse leave
  // fires onMouseLeave naturally, but touch tap needs explicit dismiss.
  useEffect(() => {
    if (hoveredIdx === null) return;
    const handler = (e: TouchEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setHoveredIdx(null);
      }
    };
    document.addEventListener('touchstart', handler);
    return () => document.removeEventListener('touchstart', handler);
  }, [hoveredIdx]);

  if (data.length === 0) {
    return (
      <div className="weight-chart-empty">
        Brak danych wagowych. Wpisz pierwszy pomiar przez Health Auto Export.
      </div>
    );
  }
  if (data.length < 2) {
    return (
      <div className="weight-chart-empty">
        Tylko 1 pomiar wagi ({data[0].weight.toFixed(1)} kg) — wykres pojawi się po kolejnym.
      </div>
    );
  }

  const sorted = [...data].sort((a, b) => a.date.localeCompare(b.date));
  // EMA overlay (Sprint 10 A5) — używa SeriesPoint shape z biometry.ts
  // (date+value), więc map weight→value przed wywołaniem.
  const emaPoints = weightEMA(
    sorted.map((d) => ({ date: d.date, value: d.weight })),
    EMA_ALPHA,
  );
  const trendKgPerWeek = weeklyTrendKg(emaPoints);
  // Y-axis scale obejmuje raw + EMA (zwykle EMA jest w środku raw, ale
  // przy strong trend może wystawać na granicy → bezpieczniej liczyć max).
  const allValues = [...sorted.map((d) => d.weight), ...emaPoints.map((p) => p.value)];
  const minW = Math.min(...allValues);
  const maxW = Math.max(...allValues);
  // Padding range — zapobiega "płaskiej" linii gdy waga się nie zmienia.
  const yMin = Math.floor((minW - 0.5) * 2) / 2;
  const yMax = Math.ceil((maxW + 0.5) * 2) / 2;
  const yRange = yMax - yMin || 1;

  const plotW = width - PAD_LEFT - PAD_RIGHT;
  const plotH = height - PAD_TOP - PAD_BOTTOM;

  const xFor = (i: number) =>
    PAD_LEFT + (sorted.length === 1 ? plotW / 2 : (i / (sorted.length - 1)) * plotW);
  const yFor = (w: number) => PAD_TOP + plotH - ((w - yMin) / yRange) * plotH;

  const linePoints = sorted.map((d, i) => `${xFor(i)},${yFor(d.weight)}`).join(' ');
  // EMA polyline — same X positions co raw (lock-step), inne Y.
  const emaLinePoints = emaPoints
    .map((p, i) => `${xFor(i)},${yFor(p.value)}`)
    .join(' ');

  const firstDate = sorted[0].date;
  const lastDate = sorted[sorted.length - 1].date;
  const lastWeight = sorted[sorted.length - 1].weight;
  const lastEMA = emaPoints[emaPoints.length - 1]?.value;
  // Trend label format: "+0,2 kg/tydz." / "−0,3 kg/tydz." / "stabilna" gdy |Δ|<0.05.
  // pl-PL używa przecinka jako separatora dziesiętnego.
  const trendLabel =
    trendKgPerWeek === null
      ? null
      : Math.abs(trendKgPerWeek) < 0.05
        ? 'stabilna (±0,0 kg/tydz.)'
        : `${trendKgPerWeek > 0 ? '+' : ''}${trendKgPerWeek.toFixed(1).replace('.', ',')} kg/tydz.`;

  return (
    <div ref={wrapRef} className="weight-chart-wrap">
    <svg
      className="weight-chart"
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      preserveAspectRatio="none"
      role="img"
      aria-label={`Wykres wagi ${firstDate} — ${lastDate}, aktualnie ${lastWeight.toFixed(1)} kg, smoothed trend ${trendLabel ?? 'brak'}`}
    >
      <defs>
        <linearGradient id="weight-chart-grad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#10b981" stopOpacity="0.3" />
          <stop offset="100%" stopColor="#10b981" stopOpacity="0" />
        </linearGradient>
      </defs>

      {/* Y-axis labels */}
      <text x={PAD_LEFT - 6} y={PAD_TOP + 4} className="weight-chart-axis-label y-label">
        {yMax.toFixed(1)}
      </text>
      <text x={PAD_LEFT - 6} y={PAD_TOP + plotH} className="weight-chart-axis-label y-label">
        {yMin.toFixed(1)}
      </text>

      {/* Horizontal grid line at midpoint */}
      <line
        x1={PAD_LEFT}
        y1={PAD_TOP + plotH / 2}
        x2={PAD_LEFT + plotW}
        y2={PAD_TOP + plotH / 2}
        className="weight-chart-grid"
      />

      {/* Filled gradient area under line */}
      <polygon
        points={`${xFor(0)},${PAD_TOP + plotH} ${linePoints} ${xFor(sorted.length - 1)},${PAD_TOP + plotH}`}
        fill="url(#weight-chart-grad)"
      />

      {/* Main line — raw daily weight */}
      <polyline
        points={linePoints}
        fill="none"
        stroke="#10b981"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {/* Sprint 10 A5 — EMA smoothed line ("true weight") overlay.
          Cieńszy stroke + dashed pattern wizualnie rozdziela od raw line.
          Cyan accent — różny od raw green żeby user nie mylił. */}
      {emaPoints.length >= 2 && (
        <polyline
          points={emaLinePoints}
          fill="none"
          stroke="#22d3ee"
          strokeWidth="1.5"
          strokeDasharray="4 3"
          strokeLinecap="round"
          strokeLinejoin="round"
          opacity="0.85"
        />
      )}

      {/* Last point dot — pokazywany TYLKO gdy brak hover (w przeciwnym
          przypadku hovered dot pełni tę funkcję, bo last point byłby
          duplikatem visual element). */}
      {hoveredIdx === null && (
        <circle
          cx={xFor(sorted.length - 1)}
          cy={yFor(lastWeight)}
          r="4"
          fill="#10b981"
          stroke="#0a0e17"
          strokeWidth="2"
        />
      )}

      {/* Hover highlight — raw dot (green, większy) + EMA dot (cyan). Oba
          jednocześnie żeby user widział obie metryki dla tego samego dnia. */}
      {hoveredIdx !== null && sorted[hoveredIdx] && (
        <>
          <circle
            cx={xFor(hoveredIdx)}
            cy={yFor(sorted[hoveredIdx].weight)}
            r="5"
            fill="#10b981"
            stroke="#0a0e17"
            strokeWidth="2"
          />
          {emaPoints[hoveredIdx] && (
            <circle
              cx={xFor(hoveredIdx)}
              cy={yFor(emaPoints[hoveredIdx].value)}
              r="4"
              fill="#22d3ee"
              stroke="#0a0e17"
              strokeWidth="2"
            />
          )}
          {/* Pionowa linia łącząca oba doty — wizualnie sugeruje że są dla
              tego samego dnia. */}
          <line
            x1={xFor(hoveredIdx)}
            y1={PAD_TOP}
            x2={xFor(hoveredIdx)}
            y2={PAD_TOP + plotH}
            stroke="#94a3b8"
            strokeWidth="1"
            strokeDasharray="2 3"
            opacity="0.4"
          />
        </>
      )}

      {/* Invisible hit areas — jeden rect per data point na pełną wysokość
          plotu. Hover na nim ustawia hoveredIdx. Width = slotW (równy
          podział plotW), x = środek slotu - slotW/2. Transparent fill
          (pointer-events default = auto). */}
      {sorted.map((d, i) => {
        const slotW = sorted.length > 1 ? plotW / (sorted.length - 1) : plotW;
        const x = xFor(i) - slotW / 2;
        return (
          <rect
            key={`hit-${d.date}`}
            x={x}
            y={PAD_TOP}
            width={slotW}
            height={plotH}
            fill="transparent"
            style={{ cursor: 'pointer' }}
            onMouseEnter={() => setHoveredIdx(i)}
            onMouseLeave={() => setHoveredIdx(null)}
            onTouchStart={(e) => {
              e.preventDefault();
              setHoveredIdx(i);
            }}
          />
        );
      })}

      {/* X-axis date labels (first + last) */}
      <text x={PAD_LEFT} y={height - 6} className="weight-chart-axis-label">
        {firstDate}
      </text>
      <text x={PAD_LEFT + plotW} y={height - 6} className="weight-chart-axis-label end">
        {lastDate}
      </text>
    </svg>

    {/* Tooltip — HTML absolute positioned (NIE SVG text), pokazany gdy hover
        aktywny. Format: data + raw waga (kg) + EMA waga (kg) jeśli istnieje. */}
    {hoveredIdx !== null && sorted[hoveredIdx] && (() => {
      const d = sorted[hoveredIdx];
      const ema = emaPoints[hoveredIdx]?.value;
      const dotY = yFor(Math.max(d.weight, ema ?? d.weight));
      return (
        <div
          className="chart-tooltip"
          style={{
            left: `${(xFor(hoveredIdx) / width) * 100}%`,
            top: `${dotY - 8}px`,
          }}
        >
          <div className="chart-tooltip-date">{d.date}</div>
          <div className="chart-tooltip-value">
            {d.weight.toFixed(1)} <span>kg</span>
          </div>
          {ema !== undefined && (
            <div className="chart-tooltip-meta">
              wygładzona: {ema.toFixed(1)} kg
            </div>
          )}
        </div>
      );
    })()}
    {/* Sprint 10 A5 — trend summary pod chartem. EMA smoothed line legenda
        + trend tygodniowy gdy ≥7 punktów. Bez tego user widzi 2 linie ale
        nie wie która jest "true weight". */}
    <div className="weight-chart-footer">
      <span className="weight-chart-legend">
        <span className="weight-chart-legend-item">
          <span className="weight-chart-legend-dot raw" /> Codzienna
        </span>
        {emaPoints.length >= 2 && (
          <span className="weight-chart-legend-item">
            <span className="weight-chart-legend-dot ema" /> Wygładzona
            {lastEMA !== undefined && ` (${lastEMA.toFixed(1)} kg)`}
          </span>
        )}
      </span>
      {trendLabel && (
        <span
          className={
            trendKgPerWeek === null || Math.abs(trendKgPerWeek) < 0.05
              ? 'weight-chart-trend stable'
              : trendKgPerWeek > 0
                ? 'weight-chart-trend up'
                : 'weight-chart-trend down'
          }
        >
          Trend 7d: {trendLabel}
        </span>
      )}
    </div>
    </div>
  );
}

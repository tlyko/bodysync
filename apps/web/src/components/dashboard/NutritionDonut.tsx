/**
 * Donut chart dla makroskładników — 1:1 port z health-dashboard-prototype.jsx
 * (linie 361-413). Białko / Tłuszcz / Węgle jako stroke-dasharray segmenty
 * proporcjonalne do gramów, kcal w środku.
 *
 * Kolory dopasowane do tokenów index.css i NutritionView (Sprint 8 PR #82).
 * Białko=green, Tłuszcz=orange, Węgle=pink.
 */

const COLOR = {
  protein: '#10b981', // var(--green)
  fat: '#f59e0b', // var(--orange)
  carbs: '#f472b6', // var(--pink)
} as const;

type Props = {
  kcal: number | null;
  proteinG: number | null;
  fatG: number | null;
  carbsG: number | null;
  // Sprint 10 A2 — opcjonalny kcal target. Gdy podany, donut ma "X / Y kcal"
  // w środku zamiast samego "X kcal" + sub-text "zostało Z" / "powyżej +Z".
  kcalTarget?: number | null;
};

export function NutritionDonut({ kcal, proteinG, fatG, carbsG, kcalTarget }: Props) {
  const protein = proteinG ?? 0;
  const fat = fatG ?? 0;
  const carbs = carbsG ?? 0;
  const total = protein + fat + carbs;

  const r = 38;
  const cx = 50;
  const cy = 50;
  const circumference = 2 * Math.PI * r;

  // Empty state: gdy brak danych makro, wyświetl tylko placeholder ring.
  const hasData = total > 0;

  const segments = hasData
    ? [
        { pct: protein / total, color: COLOR.protein, label: 'Białko', valueG: protein },
        { pct: fat / total, color: COLOR.fat, label: 'Tłuszcz', valueG: fat },
        { pct: carbs / total, color: COLOR.carbs, label: 'Węgle', valueG: carbs },
      ]
    : [];

  let cumulativeOffset = 0;
  const kcalLabel = kcal === null ? '—' : Math.round(kcal).toLocaleString('pl-PL');
  const hasTarget = typeof kcalTarget === 'number' && kcalTarget > 0;
  const targetLabel = hasTarget ? `/ ${kcalTarget.toLocaleString('pl-PL')}` : null;
  const remainingKcal = hasTarget && kcal !== null ? kcalTarget - kcal : null;
  const remainingLabel =
    remainingKcal === null
      ? null
      : remainingKcal >= 0
        ? `zostało ${Math.round(remainingKcal).toLocaleString('pl-PL')}`
        : `powyżej +${Math.round(-remainingKcal).toLocaleString('pl-PL')}`;

  return (
    <div className="nutrition-donut">
      <svg
        width="120"
        height="120"
        viewBox="0 0 100 100"
        className="nutrition-donut-svg"
        role="img"
        aria-label={`Makroskładniki: białko ${protein}g, tłuszcz ${fat}g, węgle ${carbs}g, łącznie ${kcalLabel} kcal`}
      >
        {!hasData && (
          <circle
            cx={cx}
            cy={cy}
            r={r}
            fill="none"
            stroke="var(--border)"
            strokeWidth="8"
          />
        )}
        {segments.map((seg) => {
          const dashLen = seg.pct * circumference;
          const dashOffset = -cumulativeOffset * circumference;
          cumulativeOffset += seg.pct;
          return (
            <circle
              key={seg.label}
              cx={cx}
              cy={cy}
              r={r}
              fill="none"
              stroke={seg.color}
              strokeWidth="8"
              strokeDasharray={`${dashLen} ${circumference - dashLen}`}
              strokeDashoffset={dashOffset}
              strokeLinecap="round"
              transform={`rotate(-90 ${cx} ${cy})`}
            />
          );
        })}
        <text
          x={cx}
          y={hasTarget ? cy - 8 : cy - 2}
          textAnchor="middle"
          className="nutrition-donut-kcal"
        >
          {kcalLabel}
        </text>
        {hasTarget && targetLabel && (
          <text
            x={cx}
            y={cy + 4}
            textAnchor="middle"
            className="nutrition-donut-target"
          >
            {targetLabel}
          </text>
        )}
        <text
          x={cx}
          y={hasTarget ? cy + 14 : cy + 12}
          textAnchor="middle"
          className="nutrition-donut-unit"
        >
          kcal
        </text>
      </svg>
      {remainingLabel && (
        <p className="nutrition-donut-remaining">{remainingLabel}</p>
      )}
      <ul className="nutrition-donut-legend">
        <li>
          <span
            className="nutrition-donut-legend-dot"
            style={{ background: COLOR.protein }}
          />
          <span className="nutrition-donut-legend-label">Białko</span>
          <span className="nutrition-donut-legend-value">
            {protein > 0 ? `${Math.round(protein)}g` : '—'}
          </span>
        </li>
        <li>
          <span
            className="nutrition-donut-legend-dot"
            style={{ background: COLOR.fat }}
          />
          <span className="nutrition-donut-legend-label">Tłuszcz</span>
          <span className="nutrition-donut-legend-value">
            {fat > 0 ? `${Math.round(fat)}g` : '—'}
          </span>
        </li>
        <li>
          <span
            className="nutrition-donut-legend-dot"
            style={{ background: COLOR.carbs }}
          />
          <span className="nutrition-donut-legend-label">Węgle</span>
          <span className="nutrition-donut-legend-value">
            {carbs > 0 ? `${Math.round(carbs)}g` : '—'}
          </span>
        </li>
      </ul>
    </div>
  );
}

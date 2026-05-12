import { buildSeries, latestValue, sumSeries } from '../../biometry';
import type { BiometryDay } from '../../types';
import { MetricChart } from './MetricChart';
import type { Range } from './RangeToggle';

type Props = {
  days: BiometryDay[];
  // `range` przekazywany dla future-proofingu (różne formatowania per range
  // np. weekly aggregation dla 30d). Obecnie nieużywany — chart pokazuje
  // raw daily points niezależnie od range. Trzymamy w API żeby uniknąć
  // breaking change gdy dodamy weekly bucketing.
  range: Range;
};

type Row = {
  key: string;
  label: string;
  unit: string;
  color: 'orange' | 'green' | 'cyan';
  series: ReturnType<typeof buildSeries>;
};

const integerFmt = (v: number) => Math.round(v).toLocaleString('pl-PL');

// Stacked 3-chart panel: spożyte kcal / kroki / spalone kcal (active+basal).
// Layout zgodny z Recovery panel: header `<h4>` z labelem po lewej i
// last-value po prawej, chart pod spodem. 3 wiersze flex column z gap.
export function TrendCharts({ days, range: _range }: Props) {
  const kcalInSeries = buildSeries(days, 'kcal_in');
  const stepsSeries = buildSeries(days, 'steps');
  const kcalActiveSeries = buildSeries(days, 'kcal_active');
  const kcalBasalSeries = buildSeries(days, 'kcal_basal');
  // "Spalone kalorie" = TDEE proxy = active + basal energy expenditure.
  // Mirror logic z OverviewView TodayMetricStatCard "Spalone kalorie".
  const kcalBurnedSeries = sumSeries(kcalActiveSeries, kcalBasalSeries);

  const rows: Row[] = [
    { key: 'kcal_in', label: 'Kalorie spożyte', unit: 'kcal', color: 'orange', series: kcalInSeries },
    { key: 'steps', label: 'Kroki', unit: 'kroki', color: 'green', series: stepsSeries },
    {
      key: 'kcal_burned',
      label: 'Spalone kalorie',
      unit: 'kcal',
      color: 'cyan',
      series: kcalBurnedSeries,
    },
  ];

  return (
    <div className="trend-charts">
      {rows.map((row) => {
        const last = latestValue(row.series);
        return (
          <div key={row.key} className="trend-charts-row">
            <h4>
              {row.label}
              <span>{last ? `${integerFmt(last.value)} ${row.unit}` : '—'}</span>
            </h4>
            <div className="metric-chart-wrap">
              <MetricChart
                data={row.series}
                label={row.label}
                unit={row.unit}
                color={row.color}
                formatValue={integerFmt}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

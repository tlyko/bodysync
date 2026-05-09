import { describe, expect, test } from 'vitest';
import {
  buildSeries,
  latestValue,
  sumSeries,
  trendPct,
  valueForDate,
  type SeriesPoint,
} from '../biometry';
import type { BiometryDay } from '../types';

function day(date: string, metrics: BiometryDay['metrics']): BiometryDay {
  return { date, metrics };
}

describe('buildSeries', () => {
  test('hrv: multi-window day → averaged single point', () => {
    const days = [
      day('2026-05-01', {
        hrv: [
          { value_ms: 50 },
          { value_ms: 60 },
          { value_ms: 70 },
        ],
      }),
    ];
    expect(buildSeries(days, 'hrv')).toEqual([{ date: '2026-05-01', value: 60 }]);
  });

  test('weight: single value extracted', () => {
    const days = [day('2026-05-02', { weight: { kg: 82.3 } })];
    expect(buildSeries(days, 'weight')).toEqual([{ date: '2026-05-02', value: 82.3 }]);
  });

  test('skips days without metric (no synthetic zero)', () => {
    const days = [
      day('2026-05-01', { weight: { kg: 80 } }),
      day('2026-05-02', { steps: { count: 5000 } }),
      day('2026-05-03', { weight: { kg: 80.5 } }),
    ];
    const result = buildSeries(days, 'weight');
    expect(result).toEqual([
      { date: '2026-05-01', value: 80 },
      { date: '2026-05-03', value: 80.5 },
    ]);
  });

  test('unknown metric returns empty array', () => {
    const days = [day('2026-05-01', { weight: { kg: 80 } })];
    expect(buildSeries(days, 'no_such_metric')).toEqual([]);
  });

  test('sorts ascending by date even when input shuffled', () => {
    const days = [
      day('2026-05-03', { weight: { kg: 81 } }),
      day('2026-05-01', { weight: { kg: 80 } }),
      day('2026-05-02', { weight: { kg: 80.5 } }),
    ];
    const dates = buildSeries(days, 'weight').map((p) => p.date);
    expect(dates).toEqual(['2026-05-01', '2026-05-02', '2026-05-03']);
  });

  test('hrv: empty array yields no point (filtered, not synthetic 0)', () => {
    const days = [day('2026-05-01', { hrv: [] })];
    expect(buildSeries(days, 'hrv')).toEqual([]);
  });

  test('skips entries with non-numeric field', () => {
    const days = [
      day('2026-05-01', { weight: { kg: 'invalid' } }),
      day('2026-05-02', { weight: { kg: 81 } }),
    ];
    expect(buildSeries(days, 'weight')).toEqual([{ date: '2026-05-02', value: 81 }]);
  });
});

describe('latestValue', () => {
  test('empty series → null', () => {
    expect(latestValue([])).toBeNull();
  });

  test('returns last element of series', () => {
    const series: SeriesPoint[] = [
      { date: '2026-05-01', value: 80 },
      { date: '2026-05-02', value: 81 },
      { date: '2026-05-03', value: 82 },
    ];
    expect(latestValue(series)).toEqual({ date: '2026-05-03', value: 82 });
  });
});

describe('trendPct', () => {
  test('series shorter than windowDays*2 → null', () => {
    const series: SeriesPoint[] = Array.from({ length: 10 }, (_, i) => ({
      date: `2026-05-${String(i + 1).padStart(2, '0')}`,
      value: 80,
    }));
    // windowDays=7 wymaga 14 punktów
    expect(trendPct(series, 7)).toBeNull();
  });

  test('+10% increase computed correctly', () => {
    const previous: SeriesPoint[] = Array.from({ length: 7 }, (_, i) => ({
      date: `2026-05-${String(i + 1).padStart(2, '0')}`,
      value: 100,
    }));
    const recent: SeriesPoint[] = Array.from({ length: 7 }, (_, i) => ({
      date: `2026-05-${String(i + 8).padStart(2, '0')}`,
      value: 110,
    }));
    expect(trendPct([...previous, ...recent], 7)).toBeCloseTo(10, 5);
  });

  test('-20% decrease computed correctly', () => {
    const previous: SeriesPoint[] = Array.from({ length: 3 }, (_, i) => ({
      date: `2026-05-${String(i + 1).padStart(2, '0')}`,
      value: 100,
    }));
    const recent: SeriesPoint[] = Array.from({ length: 3 }, (_, i) => ({
      date: `2026-05-${String(i + 4).padStart(2, '0')}`,
      value: 80,
    }));
    expect(trendPct([...previous, ...recent], 3)).toBeCloseTo(-20, 5);
  });

  test('zero baseline → null (avoid division by zero)', () => {
    const series: SeriesPoint[] = Array.from({ length: 14 }, (_, i) => ({
      date: `2026-05-${String(i + 1).padStart(2, '0')}`,
      value: i < 7 ? 0 : 50,
    }));
    expect(trendPct(series, 7)).toBeNull();
  });
});

describe('valueForDate', () => {
  const series: SeriesPoint[] = [
    { date: '2026-05-07', value: 1800 },
    { date: '2026-05-08', value: 1950 },
    { date: '2026-05-09', value: 2100 },
  ];

  test('returns point for matching date', () => {
    expect(valueForDate(series, '2026-05-08')).toEqual({
      date: '2026-05-08',
      value: 1950,
    });
  });

  test('returns null when date not in series (e.g. user nie wpisał kcal_in dziś)', () => {
    expect(valueForDate(series, '2026-05-10')).toBeNull();
  });

  test('returns null for empty series', () => {
    expect(valueForDate([], '2026-05-09')).toBeNull();
  });

  test('handles date present at the start', () => {
    expect(valueForDate(series, '2026-05-07')?.value).toBe(1800);
  });
});

describe('sumSeries', () => {
  test('sums values per matching date', () => {
    const a: SeriesPoint[] = [
      { date: '2026-05-08', value: 500 },
      { date: '2026-05-09', value: 600 },
    ];
    const b: SeriesPoint[] = [
      { date: '2026-05-08', value: 1500 },
      { date: '2026-05-09', value: 1550 },
    ];
    expect(sumSeries(a, b)).toEqual([
      { date: '2026-05-08', value: 2000 },
      { date: '2026-05-09', value: 2150 },
    ]);
  });

  test('union dat — date present only in a, treats b missing as 0', () => {
    const a: SeriesPoint[] = [{ date: '2026-05-08', value: 500 }];
    const b: SeriesPoint[] = [];
    expect(sumSeries(a, b)).toEqual([{ date: '2026-05-08', value: 500 }]);
  });

  test('result sorted by date asc', () => {
    const a: SeriesPoint[] = [{ date: '2026-05-09', value: 100 }];
    const b: SeriesPoint[] = [{ date: '2026-05-07', value: 200 }];
    const result = sumSeries(a, b);
    expect(result.map((p) => p.date)).toEqual(['2026-05-07', '2026-05-09']);
  });

  test('empty + empty → []', () => {
    expect(sumSeries([], [])).toEqual([]);
  });
});

import { describe, expect, test } from 'vitest';
import { buildSeries, latestValue, trendPct, type SeriesPoint } from '../biometry';
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

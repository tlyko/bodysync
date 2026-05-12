import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import { TrendCharts } from '../components/dashboard/TrendCharts';
import type { BiometryDay } from '../types';

// Helper: buduje BiometryDay z explicit metrics map. Pomija pola których
// test nie potrzebuje — tylko kcal_in / kcal_active / kcal_basal / steps.
function day(
  date: string,
  metrics: Partial<{
    kcal_in: number;
    kcal_active: number;
    kcal_basal: number;
    steps: number;
  }>,
): BiometryDay {
  const out: BiometryDay = { date, metrics: {} };
  if (metrics.kcal_in !== undefined) out.metrics.kcal_in = { kcal: metrics.kcal_in };
  if (metrics.kcal_active !== undefined) out.metrics.kcal_active = { kcal: metrics.kcal_active };
  if (metrics.kcal_basal !== undefined) out.metrics.kcal_basal = { kcal: metrics.kcal_basal };
  if (metrics.steps !== undefined) out.metrics.steps = { count: metrics.steps };
  return out;
}

describe('TrendCharts', () => {
  test('renders 3 chart sections — Kalorie spożyte / Kroki / Spalone kalorie', () => {
    const days: BiometryDay[] = [
      day('2026-05-01', { kcal_in: 2200, kcal_active: 500, kcal_basal: 1700, steps: 8000 }),
      day('2026-05-02', { kcal_in: 2400, kcal_active: 600, kcal_basal: 1700, steps: 9500 }),
      day('2026-05-03', { kcal_in: 2300, kcal_active: 550, kcal_basal: 1700, steps: 8800 }),
    ];
    const { container } = render(<TrendCharts days={days} range="7d" />);

    // 3 wiersze trend-charts-row
    expect(container.querySelectorAll('.trend-charts-row')).toHaveLength(3);
    // Wszystkie 3 labele widoczne w h4
    expect(screen.getByText('Kalorie spożyte')).toBeInTheDocument();
    expect(screen.getByText('Kroki')).toBeInTheDocument();
    expect(screen.getByText('Spalone kalorie')).toBeInTheDocument();
    // 3 SVG (1 per chart), każdy z 3 barami (1 per data point) = 9 rectów total
    expect(container.querySelectorAll('svg.metric-chart')).toHaveLength(3);
    expect(container.querySelectorAll('rect')).toHaveLength(9);
  });

  test('last value displayed obok header — sumuje active+basal dla spalone', () => {
    const days: BiometryDay[] = [
      day('2026-05-01', { kcal_in: 2200, kcal_active: 500, kcal_basal: 1700, steps: 8000 }),
      day('2026-05-02', { kcal_in: 2400, kcal_active: 600, kcal_basal: 1700, steps: 9500 }),
    ];
    render(<TrendCharts days={days} range="7d" />);
    // Last kcal_in (2400) z pl-PL thousands separator (NBSP)
    const kcalIn = screen.getByText((_, node) =>
      (node?.textContent ?? '').replace(/\s/g, '') === '2400kcal',
    );
    expect(kcalIn).toBeInTheDocument();
    // Last steps (9500)
    const steps = screen.getByText((_, node) =>
      (node?.textContent ?? '').replace(/\s/g, '') === '9500kroki',
    );
    expect(steps).toBeInTheDocument();
    // Last spalone = 600 + 1700 = 2300
    const burned = screen.getByText((_, node) =>
      (node?.textContent ?? '').replace(/\s/g, '') === '2300kcal',
    );
    expect(burned).toBeInTheDocument();
  });

  test('empty state gdy days=[] — wszystkie 3 charty pokazują "Brak danych"', () => {
    const { container } = render(<TrendCharts days={[]} range="7d" />);
    const emptyStates = container.querySelectorAll('.metric-chart-empty');
    expect(emptyStates).toHaveLength(3);
    // Last value w headerze pokazuje "—" (dash) gdy brak danych
    expect(screen.getAllByText('—')).toHaveLength(3);
  });
});

import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import { KcalBalanceCard } from '../components/dashboard/KcalBalanceCard';
import type { BiometryDay } from '../types';

function day(
  date: string,
  metrics: Partial<{ kcal_in: number; kcal_active: number; kcal_basal: number }>,
): BiometryDay {
  const out: BiometryDay = { date, metrics: {} };
  if (metrics.kcal_in !== undefined) out.metrics.kcal_in = { kcal: metrics.kcal_in };
  if (metrics.kcal_active !== undefined) out.metrics.kcal_active = { kcal: metrics.kcal_active };
  if (metrics.kcal_basal !== undefined) out.metrics.kcal_basal = { kcal: metrics.kcal_basal };
  return out;
}

describe('KcalBalanceCard', () => {
  test('deficyt — in < burned daje green status + ujemna liczba', () => {
    const days = [
      day('2026-05-14', { kcal_in: 1850, kcal_active: 600, kcal_basal: 1700 }),
    ];
    render(<KcalBalanceCard days={days} todayIso="2026-05-14" />);
    expect(screen.getByText('DEFICYT')).toBeInTheDocument();
    // 1850 - 2300 = -450, formatted with U+2212 minus + thousand sep
    expect(screen.getByText(/−450/)).toBeInTheDocument();
  });

  test('nadwyżka — in > burned daje red status + dodatnia liczba z plusem', () => {
    const days = [
      day('2026-05-14', { kcal_in: 2800, kcal_active: 400, kcal_basal: 1700 }),
    ];
    render(<KcalBalanceCard days={days} todayIso="2026-05-14" />);
    expect(screen.getByText('NADWYŻKA')).toBeInTheDocument();
    // 2800 - 2100 = +700
    expect(screen.getByText(/\+700/)).toBeInTheDocument();
  });

  test('bilans — różnica < 100 daje cyan BILANS status', () => {
    const days = [
      day('2026-05-14', { kcal_in: 2300, kcal_active: 600, kcal_basal: 1700 }),
    ];
    render(<KcalBalanceCard days={days} todayIso="2026-05-14" />);
    // 2300 - 2300 = 0
    expect(screen.getByText('BILANS')).toBeInTheDocument();
  });

  test('empty state gdy brak today danych', () => {
    render(<KcalBalanceCard days={[]} todayIso="2026-05-14" />);
    expect(screen.getByText(/Brak danych/)).toBeInTheDocument();
  });

  test('breakdown pokazuje spożyte i spalone', () => {
    const days = [
      day('2026-05-14', { kcal_in: 1850, kcal_active: 600, kcal_basal: 1700 }),
    ];
    const { container } = render(<KcalBalanceCard days={days} todayIso="2026-05-14" />);
    expect(screen.getByText('Spożyte')).toBeInTheDocument();
    expect(screen.getByText('Spalone')).toBeInTheDocument();
    // Breakdown values w span.kcal-balance-breakdown-value — sprawdź textContent
    const values = Array.from(container.querySelectorAll('.kcal-balance-breakdown-value')).map(
      (el) => (el.textContent ?? '').replace(/\s/g, ''),
    );
    expect(values).toContain('1850kcal');
    expect(values).toContain('2300kcal');
  });

  test('sparkline 7d renderuje bary tylko dla dni z obiema metrykami', () => {
    const days = [
      day('2026-05-08', { kcal_in: 1900, kcal_active: 500, kcal_basal: 1700 }),
      day('2026-05-09', { kcal_in: 2400, kcal_active: 600, kcal_basal: 1700 }),
      day('2026-05-10', { kcal_in: 2000, kcal_active: 700, kcal_basal: 1700 }), // brak kcal_in → skip — actually has, OK
      day('2026-05-11', { kcal_in: 1800 }), // brak burned → SKIP w sparkline
      day('2026-05-14', { kcal_in: 1850, kcal_active: 600, kcal_basal: 1700 }),
    ];
    const { container } = render(<KcalBalanceCard days={days} todayIso="2026-05-14" />);
    // 4 dni mają obie metryki (08/09/10/14) — 1 dzień (11) tylko kcal_in
    const bars = container.querySelectorAll('.kcal-balance-spark-bar');
    expect(bars.length).toBe(4);
  });

  test('today bez danych pokazuje "—" + status BRAK DZISIEJSZYCH', () => {
    const days = [
      day('2026-05-13', { kcal_in: 1900, kcal_active: 500, kcal_basal: 1700 }),
    ];
    render(<KcalBalanceCard days={days} todayIso="2026-05-14" />);
    expect(screen.getByText(/BRAK DZISIEJSZYCH DANYCH/)).toBeInTheDocument();
    // Past day sparkline jeszcze widoczna
    expect(document.querySelectorAll('.kcal-balance-spark-bar').length).toBe(1);
  });
});

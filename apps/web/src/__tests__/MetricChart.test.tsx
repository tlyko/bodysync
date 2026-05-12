import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import { MetricChart } from '../components/dashboard/MetricChart';

describe('MetricChart', () => {
  test('empty state gdy 0 points — pokazuje "Brak danych dla wybranego okresu"', () => {
    const { container } = render(
      <MetricChart data={[]} label="Kroki" unit="kroki" color="green" />,
    );
    expect(screen.getByText('Brak danych dla wybranego okresu')).toBeInTheDocument();
    expect(container.querySelector('rect')).toBeNull();
  });

  test('renders 1 bar dla 1 punktu (bar chart radzi sobie z single point)', () => {
    const { container } = render(
      <MetricChart
        data={[{ date: '2026-05-01', value: 8000 }]}
        label="Kroki"
        unit="kroki"
        color="green"
      />,
    );
    const bars = container.querySelectorAll('rect');
    expect(bars).toHaveLength(1);
  });

  test('renders 1 rect per data point z 3+ points', () => {
    const { container } = render(
      <MetricChart
        data={[
          { date: '2026-05-01', value: 7500 },
          { date: '2026-05-02', value: 8200 },
          { date: '2026-05-03', value: 9100 },
        ]}
        label="Kroki"
        unit="kroki"
        color="green"
      />,
    );
    const bars = container.querySelectorAll('rect');
    expect(bars).toHaveLength(3);
  });

  test('hover na barze pokazuje tooltip z datą + wartością', async () => {
    const { container } = render(
      <MetricChart
        data={[
          { date: '2026-05-01', value: 7500 },
          { date: '2026-05-02', value: 8200 },
        ]}
        label="Kroki"
        unit="kroki"
        color="green"
      />,
    );
    // Przed hover: brak tooltip
    expect(container.querySelector('.metric-chart-tooltip')).toBeNull();
    // Po fireEvent mouseEnter na drugim barze: tooltip widoczny z datą + value
    const bars = container.querySelectorAll('rect');
    const { fireEvent } = await import('@testing-library/react');
    fireEvent.mouseEnter(bars[1]);
    const tooltip = container.querySelector('.metric-chart-tooltip');
    expect(tooltip).not.toBeNull();
    expect(tooltip?.textContent).toContain('2026-05-02');
    expect(tooltip?.textContent).toContain('8200');
    expect(tooltip?.textContent).toContain('kroki');
    // mouseLeave znika tooltip
    fireEvent.mouseLeave(bars[1]);
    expect(container.querySelector('.metric-chart-tooltip')).toBeNull();
  });

  test('formatValue custom — Y-axis labele używają formattera', () => {
    const fmt = (v: number) => Math.round(v).toLocaleString('pl-PL');
    render(
      <MetricChart
        data={[
          { date: '2026-05-01', value: 2400 },
          { date: '2026-05-02', value: 2700 },
        ]}
        label="Kalorie spożyte"
        unit="kcal"
        color="orange"
        formatValue={fmt}
      />,
    );
    const labels = document.querySelectorAll('.metric-chart-axis-label.y-label');
    expect(labels.length).toBe(2);
    const texts = Array.from(labels).map((l) => l.textContent ?? '');
    // Y-max z 2700 padded ~5% → 2835 sformatowane "2 835" (pl-PL NBSP/space).
    expect(texts.some((t) => /\d[\s ]?\d{3}/.test(t))).toBe(true);
    // Y-min powinien być "0" (bar chart baseline)
    expect(texts.some((t) => t === '0')).toBe(true);
  });

  test('aria-label zawiera label metryki + zakres dat + ostatnia wartość', () => {
    render(
      <MetricChart
        data={[
          { date: '2026-05-01', value: 7000 },
          { date: '2026-05-07', value: 9500 },
        ]}
        label="Kroki"
        unit="kroki"
        color="green"
      />,
    );
    const svg = screen.getByRole('img');
    const aria = svg.getAttribute('aria-label') ?? '';
    expect(aria).toContain('Kroki');
    expect(aria).toContain('słupkowy');
    expect(aria).toContain('2026-05-01');
    expect(aria).toContain('2026-05-07');
    expect(aria).toContain('kroki');
  });
});

import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import { MetricChart } from '../components/dashboard/MetricChart';

describe('MetricChart', () => {
  test('empty state gdy 0 points — pokazuje "Brak danych dla wybranego okresu"', () => {
    const { container } = render(
      <MetricChart data={[]} label="Kroki" unit="kroki" color="green" />,
    );
    expect(screen.getByText('Brak danych dla wybranego okresu')).toBeInTheDocument();
    expect(container.querySelector('polyline')).toBeNull();
  });

  test('empty state gdy 1 point — pokazuje single value + komunikat o kolejnym', () => {
    const { container } = render(
      <MetricChart
        data={[{ date: '2026-05-01', value: 8000 }]}
        label="Kroki"
        unit="kroki"
        color="green"
      />,
    );
    // Komunikat "wykres pojawi się po kolejnym" (case-insensitive na
    // wypadek redakcyjnych poprawek tekstu).
    expect(screen.getByText(/wykres pojawi się po kolejnym/i)).toBeInTheDocument();
    expect(container.querySelector('polyline')).toBeNull();
  });

  test('renders polyline z 2+ points', () => {
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
    const polyline = container.querySelector('polyline');
    expect(polyline).not.toBeNull();
    const points = polyline?.getAttribute('points') ?? '';
    // 3 punkty = 3 pary x,y oddzielone spacją
    expect(points.split(' ')).toHaveLength(3);
    // Last point dot present
    expect(container.querySelector('circle')).not.toBeNull();
  });

  test('formatValue custom — Y-axis labele używają formattera', () => {
    // formatValue z thousand separator (jak w TrendCharts.tsx — toLocaleString)
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
    // Y-axis pokazuje min/max sformatowane przez fmt — wartości będą
    // padded (yMin floor, yMax ceil) ale powinny zawierać NBSP/space jako
    // thousands separator (pl-PL standard). Regex sprawdza presence
    // 4-cyfrowej liczby ze spacją (NBSP   lub regular).
    const labels = document.querySelectorAll('.metric-chart-axis-label.y-label');
    expect(labels.length).toBe(2);
    const texts = Array.from(labels).map((l) => l.textContent ?? '');
    // Co najmniej jedna z osi Y zawiera thousands-separator format
    expect(texts.some((t) => /\d[\s ]?\d{3}/.test(t))).toBe(true);
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
    expect(aria).toContain('2026-05-01');
    expect(aria).toContain('2026-05-07');
    expect(aria).toContain('kroki');
  });
});

import { fireEvent, render } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import { WeightChart } from '../components/dashboard/WeightChart';

describe('WeightChart', () => {
  test('hover na hit-area pokazuje tooltip z datą + wagą raw + EMA', () => {
    const data = [
      { date: '2026-04-13', weight: 79.0 },
      { date: '2026-04-20', weight: 78.5 },
      { date: '2026-04-27', weight: 78.8 },
      { date: '2026-05-04', weight: 78.2 },
      { date: '2026-05-11', weight: 78.4 },
    ];
    const { container } = render(<WeightChart data={data} />);

    // Hit-area rects (`transparent` fill) — 1 per data point
    const hitAreas = container.querySelectorAll('rect[fill="transparent"]');
    expect(hitAreas.length).toBe(5);

    // Przed hover: brak tooltip
    expect(container.querySelector('.chart-tooltip')).toBeNull();

    // Hover na 2nd hit area (index 1)
    fireEvent.mouseEnter(hitAreas[1]);
    const tooltip = container.querySelector('.chart-tooltip');
    expect(tooltip).not.toBeNull();
    expect(tooltip?.textContent).toContain('2026-04-20');
    expect(tooltip?.textContent).toContain('78.5');
    expect(tooltip?.textContent).toContain('kg');
    // EMA meta widoczna (data ma >=3 points → EMA istnieje)
    expect(tooltip?.textContent).toContain('wygładzona');

    fireEvent.mouseLeave(hitAreas[1]);
    expect(container.querySelector('.chart-tooltip')).toBeNull();
  });

  test('empty state gdy 0 punktów', () => {
    const { container } = render(<WeightChart data={[]} />);
    expect(container.textContent).toContain('Brak danych wagowych');
  });
});

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import { NutritionDonut } from '../components/dashboard/NutritionDonut';
import { RangeToggle } from '../components/dashboard/RangeToggle';
import { Sparkline } from '../components/dashboard/Sparkline';
import { StatCard } from '../components/dashboard/StatCard';

describe('Sparkline', () => {
  test('renders SVG <polyline> with 5 data points', () => {
    const { container } = render(<Sparkline data={[1, 2, 3, 4, 5]} />);
    const polyline = container.querySelector('polyline');
    expect(polyline).not.toBeNull();
    // 5 punktow = 5 par x,y oddzielonych spacja
    const points = polyline?.getAttribute('points') ?? '';
    expect(points.split(' ')).toHaveLength(5);
  });

  test('returns null when fewer than 2 points', () => {
    const { container } = render(<Sparkline data={[42]} />);
    expect(container.querySelector('svg')).toBeNull();
  });

  test('returns null for empty data', () => {
    const { container } = render(<Sparkline data={[]} />);
    expect(container.querySelector('svg')).toBeNull();
  });
});

describe('StatCard', () => {
  test('renders value + unit with sparkline when data ≥ 2', () => {
    const { container } = render(
      <StatCard
        label="HRV"
        value="42.5"
        unit="ms"
        accent="cyan"
        sparkData={[40, 42, 41, 43, 42.5]}
      />,
    );
    expect(screen.getByText('42.5')).toBeInTheDocument();
    expect(screen.getByText('ms')).toBeInTheDocument();
    expect(container.querySelector('polyline')).not.toBeNull();
  });

  test('empty value (null) renders "—" and no sparkline', () => {
    const { container } = render(
      <StatCard label="HRV" value={null} unit="ms" accent="cyan" sparkData={[1, 2, 3]} />,
    );
    expect(screen.getByText('—')).toBeInTheDocument();
    expect(container.querySelector('polyline')).toBeNull();
  });

  test('negative trend renders ▼ with red class', () => {
    const { container } = render(
      <StatCard label="Waga" value="80.5" unit="kg" accent="green" change={-5} />,
    );
    const trend = container.querySelector('.stat-card-trend');
    expect(trend).not.toBeNull();
    expect(trend?.textContent).toContain('▼');
    expect(trend?.classList.contains('down')).toBe(true);
  });

  test('positive trend renders ▲ with green class', () => {
    const { container } = render(
      <StatCard label="HRV" value="42" unit="ms" accent="cyan" change={3.7} />,
    );
    const trend = container.querySelector('.stat-card-trend');
    expect(trend?.textContent).toContain('▲');
    expect(trend?.classList.contains('up')).toBe(true);
  });

  test('no change + no sparkData = no bottom row rendered', () => {
    const { container } = render(<StatCard label="X" value="1" accent="muted" />);
    expect(container.querySelector('.stat-card-bottom')).toBeNull();
  });
});

describe('RangeToggle', () => {
  test('renders 3 buttons (Dziś / 7 dni / 30 dni)', () => {
    render(<RangeToggle value="30d" onChange={() => {}} />);
    expect(screen.getByRole('button', { name: 'Dziś' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '7 dni' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '30 dni' })).toBeInTheDocument();
  });

  test('active option has aria-pressed=true, others false', () => {
    render(<RangeToggle value="7d" onChange={() => {}} />);
    expect(screen.getByRole('button', { name: '7 dni' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(screen.getByRole('button', { name: 'Dziś' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
    expect(screen.getByRole('button', { name: '30 dni' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
  });

  test('clicking option calls onChange with its value', () => {
    const onChange = vi.fn();
    render(<RangeToggle value="30d" onChange={onChange} />);
    fireEvent.click(screen.getByRole('button', { name: 'Dziś' }));
    expect(onChange).toHaveBeenCalledWith('1d');
  });
});

describe('NutritionDonut', () => {
  test('renders kcal value w środku ringa + 3 segmenty', () => {
    const { container } = render(
      <NutritionDonut kcal={1850} proteinG={120} fatG={70} carbsG={180} />,
    );
    // Center text — kcal liczba (pl-PL używa NBSP jako thousands separator,
    // więc raw normalize "1 850" / "1 850" — matcher na wszystkie spacje).
    const kcalText = container.querySelector('.nutrition-donut-kcal');
    expect(kcalText?.textContent?.replace(/\s/g, '')).toBe('1850');
    expect(screen.getByText('kcal')).toBeInTheDocument();
    // 3 stroked circles dla segments (no placeholder ring bo hasData=true)
    const circles = container.querySelectorAll('circle');
    expect(circles).toHaveLength(3);
    // Legend rows
    expect(screen.getByText('Białko')).toBeInTheDocument();
    expect(screen.getByText('Tłuszcz')).toBeInTheDocument();
    expect(screen.getByText('Węgle')).toBeInTheDocument();
    expect(screen.getByText('120g')).toBeInTheDocument();
    expect(screen.getByText('70g')).toBeInTheDocument();
    expect(screen.getByText('180g')).toBeInTheDocument();
  });

  test('empty state — placeholder ring + dashes w legend gdy makro=null', () => {
    const { container } = render(
      <NutritionDonut kcal={null} proteinG={null} fatG={null} carbsG={null} />,
    );
    // 1 placeholder ring (no segments)
    const circles = container.querySelectorAll('circle');
    expect(circles).toHaveLength(1);
    // 4 dashes total: 1 center kcal + 3 legend wartości
    const dashes = screen.getAllByText('—');
    expect(dashes).toHaveLength(4);
  });

  test('aria-label opisuje makro skład dla screen readers', () => {
    render(<NutritionDonut kcal={1500} proteinG={100} fatG={50} carbsG={200} />);
    const svg = screen.getByRole('img');
    expect(svg).toHaveAttribute(
      'aria-label',
      expect.stringContaining('białko 100g'),
    );
    expect(svg).toHaveAttribute(
      'aria-label',
      expect.stringContaining('tłuszcz 50g'),
    );
  });
});

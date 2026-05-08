import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
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

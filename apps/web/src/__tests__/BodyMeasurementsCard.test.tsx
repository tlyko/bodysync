import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { ApiError } from '../api';
import { BodyMeasurementsCard } from '../components/dashboard/BodyMeasurementsCard';
import type { BiometryDay } from '../types';

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    postMeasurements: vi.fn(),
  };
});

import { postMeasurements } from '../api';

const mockPost = vi.mocked(postMeasurements);

beforeEach(() => {
  mockPost.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

function day(date: string, metrics: Partial<Record<'waist' | 'hips' | 'chest' | 'biceps' | 'thigh', number>>): BiometryDay {
  const out: BiometryDay = { date, metrics: {} };
  for (const [key, val] of Object.entries(metrics)) {
    if (val !== undefined) out.metrics[key] = { cm: val };
  }
  return out;
}

describe('BodyMeasurementsCard', () => {
  test('happy submit — waist only — wysyła {date, waist_cm}', async () => {
    mockPost.mockResolvedValueOnce({ saved: ['waist'], date: '2026-05-14' });
    render(<BodyMeasurementsCard days={[]} todayIso="2026-05-14" />);

    fireEvent.change(screen.getByLabelText('Talia'), { target: { value: '85.5' } });
    fireEvent.click(screen.getByRole('button', { name: /Zapisz pomiar/i }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith({
        date: '2026-05-14',
        waist_cm: 85.5,
      });
    });
    expect(await screen.findByRole('status')).toHaveTextContent(/Pomiar zapisany/);
  });

  test('submit disabled gdy wszystkie pola puste', () => {
    render(<BodyMeasurementsCard days={[]} todayIso="2026-05-14" />);
    expect(screen.getByRole('button', { name: /Zapisz pomiar/i })).toBeDisabled();
  });

  test('422 error → banner z PL message', async () => {
    mockPost.mockRejectedValueOnce(new ApiError(422, 'invalid'));
    render(<BodyMeasurementsCard days={[]} todayIso="2026-05-14" />);

    fireEvent.change(screen.getByLabelText('Biceps'), { target: { value: '35' } });
    fireEvent.click(screen.getByRole('button', { name: /Zapisz pomiar/i }));

    const banner = await screen.findByRole('alert');
    expect(banner).toHaveTextContent(/Sprawdź wpisane wartości/);
  });

  test('network error (-1) → "Brak połączenia" banner', async () => {
    mockPost.mockRejectedValueOnce(new ApiError(-1, 'network'));
    render(<BodyMeasurementsCard days={[]} todayIso="2026-05-14" />);

    fireEvent.change(screen.getByLabelText('Talia'), { target: { value: '85' } });
    fireEvent.click(screen.getByRole('button', { name: /Zapisz pomiar/i }));

    const banner = await screen.findByRole('alert');
    expect(banner).toHaveTextContent(/Brak połączenia/);
  });

  test('charts renderują tylko gdy series ma ≥2 punkty', () => {
    // Waist 3 punkty (≥2) → chart visible. Hips 1 punkt (<2) → no chart.
    // Chest/biceps/thigh brak danych → no chart.
    const days: BiometryDay[] = [
      day('2026-05-07', { waist: 86.0 }),
      day('2026-05-10', { waist: 85.5, hips: 98.0 }),
      day('2026-05-14', { waist: 85.0 }),
    ];
    const { container } = render(<BodyMeasurementsCard days={days} todayIso="2026-05-14" />);

    const charts = container.querySelectorAll('.body-measurements-chart');
    // Tylko waist (3 punkty) ma chart — hips (1 punkt) i pozostałe NIE.
    expect(charts.length).toBe(1);
    // Sprawdź że to chart talii (label "Talia" w h4)
    expect(charts[0].querySelector('h4')?.textContent).toContain('Talia');
  });

  test('placeholder pokazuje latest cm value gdy istnieje', () => {
    const days: BiometryDay[] = [
      day('2026-05-07', { waist: 86.0 }),
      day('2026-05-14', { waist: 85.5 }),
    ];
    render(<BodyMeasurementsCard days={days} todayIso="2026-05-14" />);
    // Latest waist value 85.5 → placeholder "85.5"
    expect(screen.getByLabelText('Talia')).toHaveAttribute('placeholder', '85.5');
    // Brak danych biceps → placeholder "—"
    expect(screen.getByLabelText('Biceps')).toHaveAttribute('placeholder', '—');
  });

  test('multi-field submit — wszystkie 5 metryk wysłane jako *_cm', async () => {
    mockPost.mockResolvedValueOnce({
      saved: ['biceps', 'chest', 'hips', 'thigh', 'waist'],
      date: '2026-05-14',
    });
    render(<BodyMeasurementsCard days={[]} todayIso="2026-05-14" />);

    fireEvent.change(screen.getByLabelText('Talia'), { target: { value: '85.5' } });
    fireEvent.change(screen.getByLabelText('Biodra'), { target: { value: '98' } });
    fireEvent.change(screen.getByLabelText('Klatka'), { target: { value: '102' } });
    fireEvent.change(screen.getByLabelText('Biceps'), { target: { value: '35.5' } });
    fireEvent.change(screen.getByLabelText('Udo'), { target: { value: '58' } });
    fireEvent.click(screen.getByRole('button', { name: /Zapisz pomiar/i }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith({
        date: '2026-05-14',
        waist_cm: 85.5,
        hips_cm: 98,
        chest_cm: 102,
        biceps_cm: 35.5,
        thigh_cm: 58,
      });
    });
  });

  test('po sukcesie inputy są clear + onSaved callback wywołany', async () => {
    mockPost.mockResolvedValueOnce({ saved: ['waist'], date: '2026-05-14' });
    const onSaved = vi.fn();
    render(<BodyMeasurementsCard days={[]} todayIso="2026-05-14" onSaved={onSaved} />);

    const waistInput = screen.getByLabelText('Talia') as HTMLInputElement;
    fireEvent.change(waistInput, { target: { value: '85.5' } });
    fireEvent.click(screen.getByRole('button', { name: /Zapisz pomiar/i }));

    await waitFor(() => {
      expect(onSaved).toHaveBeenCalled();
    });
    // Input clear po sukcesie.
    expect(waistInput.value).toBe('');
  });
});

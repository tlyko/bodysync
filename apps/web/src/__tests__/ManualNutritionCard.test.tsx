import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { ApiError } from '../api';
import { ManualNutritionCard } from '../components/dashboard/ManualNutritionCard';
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

describe('ManualNutritionCard', () => {
  test('happy submit — kcal_in only → wysyła {date, kcal_in}', async () => {
    mockPost.mockResolvedValueOnce({ saved: ['kcal_in'], date: '2026-05-17' });
    render(<ManualNutritionCard days={[]} todayIso="2026-05-17" />);

    fireEvent.change(screen.getByLabelText('Kcal spożyte'), {
      target: { value: '2200' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Zapisz spożycie/i }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith({
        date: '2026-05-17',
        kcal_in: 2200,
      });
    });
    expect(await screen.findByRole('status')).toHaveTextContent(/Spożycie zapisane/);
  });

  test('full P/F/C submit → wszystkie 4 pola w payload', async () => {
    mockPost.mockResolvedValueOnce({
      saved: ['kcal_in', 'protein', 'fat', 'carbs'],
      date: '2026-05-17',
    });
    render(<ManualNutritionCard days={[]} todayIso="2026-05-17" />);

    fireEvent.change(screen.getByLabelText('Kcal spożyte'), { target: { value: '2200' } });
    fireEvent.change(screen.getByLabelText('Białko'), { target: { value: '150' } });
    fireEvent.change(screen.getByLabelText('Tłuszcz'), { target: { value: '80' } });
    fireEvent.change(screen.getByLabelText('Węgle'), { target: { value: '250' } });
    fireEvent.click(screen.getByRole('button', { name: /Zapisz spożycie/i }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith({
        date: '2026-05-17',
        kcal_in: 2200,
        protein_g: 150,
        fat_g: 80,
        carbs_g: 250,
      });
    });
  });

  test('submit disabled gdy wszystkie pola puste', () => {
    render(<ManualNutritionCard days={[]} todayIso="2026-05-17" />);
    expect(
      screen.getByRole('button', { name: /Zapisz spożycie/i }),
    ).toBeDisabled();
  });

  test('placeholder pokazuje today HAE value gdy istnieje', () => {
    const days: BiometryDay[] = [
      {
        date: '2026-05-17',
        metrics: {
          kcal_in: { kcal: 1800 },
          protein: { g: 120 },
        },
      },
    ];
    render(<ManualNutritionCard days={days} todayIso="2026-05-17" />);

    expect(screen.getByLabelText('Kcal spożyte')).toHaveAttribute(
      'placeholder',
      '1800',
    );
    expect(screen.getByLabelText('Białko')).toHaveAttribute('placeholder', '120');
    // Brak HAE dla fat/carbs → placeholder "—".
    expect(screen.getByLabelText('Tłuszcz')).toHaveAttribute('placeholder', '—');
    expect(screen.getByLabelText('Węgle')).toHaveAttribute('placeholder', '—');
  });

  test('422 error → banner z PL message', async () => {
    mockPost.mockRejectedValueOnce(new ApiError(422, 'invalid'));
    render(<ManualNutritionCard days={[]} todayIso="2026-05-17" />);

    fireEvent.change(screen.getByLabelText('Kcal spożyte'), { target: { value: '2200' } });
    fireEvent.click(screen.getByRole('button', { name: /Zapisz spożycie/i }));

    const banner = await screen.findByRole('alert');
    expect(banner).toHaveTextContent(/Sprawdź wpisane wartości/);
  });

  test('network error → "Brak połączenia" banner', async () => {
    mockPost.mockRejectedValueOnce(new ApiError(-1, 'network'));
    render(<ManualNutritionCard days={[]} todayIso="2026-05-17" />);

    fireEvent.change(screen.getByLabelText('Białko'), { target: { value: '150' } });
    fireEvent.click(screen.getByRole('button', { name: /Zapisz spożycie/i }));

    const banner = await screen.findByRole('alert');
    expect(banner).toHaveTextContent(/Brak połączenia/);
  });
});

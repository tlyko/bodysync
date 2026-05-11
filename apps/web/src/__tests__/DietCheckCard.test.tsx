import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { ApiError } from '../api';
import { DietCheckCard } from '../components/dashboard/DietCheckCard';
import type { DietCheckResult, ProfileTargets } from '../types';

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    getProfileTargets: vi.fn(),
    postTdeeRecalc: vi.fn(),
  };
});

import { getProfileTargets, postTdeeRecalc } from '../api';

const mockGet = vi.mocked(getProfileTargets);
const mockRecalc = vi.mocked(postTdeeRecalc);

beforeEach(() => {
  mockGet.mockReset();
  mockRecalc.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

const baseTargets: ProfileTargets = {
  kcal_target: 2250,
  protein_target_g: 130,
  fat_target_g: 70,
  carbs_target_g: 275,
  is_default: false,
  body_profile: null,
};

function withDietCheckLast(
  partial: Partial<NonNullable<ProfileTargets['diet_check_last']>> & { date: string },
): ProfileTargets {
  return {
    ...baseTargets,
    diet_check_last: {
      skipped: false,
      skip_reason: null,
      goal_kcal: 2250,
      kcal_in_avg: 2050,
      waga_delta_kg: -0.4,
      diff_kg: -0.04,
      status: 'on_track',
      narrative: 'Idziesz świetnie — zgodnie z planem 0.4 kg/14d.',
      ...partial,
    },
  };
}

const happyResult: DietCheckResult = {
  skipped: false,
  skip_reason: null,
  goal_kcal: 2250,
  kcal_in_avg: 2050,
  waga_now_kg: 79.6,
  waga_then_kg: 80.0,
  waga_delta_kg: -0.4,
  expected_delta_kg: -0.36,
  actual_delta_kg: -0.4,
  diff_kg: -0.04,
  status: 'on_track',
  narrative: 'Świetna robota — schudłeś -0.4 kg w 14 dni, zgodnie z planem. Kontynuuj.',
  narrative_unavailable: false,
};

describe('DietCheckCard', () => {
  test('renders narrative + status badge from diet_check_last on mount', async () => {
    mockGet.mockResolvedValueOnce(withDietCheckLast({ date: new Date().toISOString().slice(0, 10) }));

    render(<DietCheckCard />);

    await waitFor(() => {
      expect(screen.getByText(/Idziesz świetnie/)).toBeInTheDocument();
    });
    expect(screen.getByText('Zgodnie z planem')).toBeInTheDocument();
    expect(screen.getByText(/dzisiaj/)).toBeInTheDocument();
  });

  test('shows muted "jeszcze nie sprawdzone" when no diet_check_last', async () => {
    mockGet.mockResolvedValueOnce(baseTargets);

    render(<DietCheckCard />);

    await waitFor(() => {
      expect(screen.getByText(/Jeszcze nie sprawdzone/)).toBeInTheDocument();
    });
  });

  test('button "Sprawdź teraz" calls postTdeeRecalc + shows narrative + success toast', async () => {
    mockGet.mockResolvedValue(baseTargets);
    mockRecalc.mockResolvedValueOnce(happyResult);

    render(<DietCheckCard />);
    await waitFor(() => screen.getByRole('button', { name: 'Sprawdź teraz' }));

    fireEvent.click(screen.getByRole('button', { name: 'Sprawdź teraz' }));

    await waitFor(() => {
      expect(screen.getByText(/Świetna robota/)).toBeInTheDocument();
    });
    expect(screen.getByText('Sprawdzono postępy.')).toBeInTheDocument();
    expect(mockRecalc).toHaveBeenCalledTimes(1);
    expect(mockGet).toHaveBeenCalledTimes(2);
  });

  test('skipped no_kcal_target shows reason as info toast (not error)', async () => {
    mockGet.mockResolvedValue(baseTargets);
    mockRecalc.mockResolvedValueOnce({
      ...happyResult,
      skipped: true,
      skip_reason: 'no_kcal_target',
      narrative: null,
      status: null,
    });

    render(<DietCheckCard />);
    await waitFor(() => screen.getByRole('button', { name: 'Sprawdź teraz' }));

    fireEvent.click(screen.getByRole('button', { name: 'Sprawdź teraz' }));

    await waitFor(() => {
      expect(
        screen.getByText(/Najpierw ustaw cel kaloryczny w polach powyżej/),
      ).toBeInTheDocument();
    });
  });

  test('narrative_unavailable shows fallback toast (graceful LLM degradation)', async () => {
    mockGet.mockResolvedValue(baseTargets);
    mockRecalc.mockResolvedValueOnce({
      ...happyResult,
      narrative: null,
      narrative_unavailable: true,
    });

    render(<DietCheckCard />);
    await waitFor(() => screen.getByRole('button', { name: 'Sprawdź teraz' }));

    fireEvent.click(screen.getByRole('button', { name: 'Sprawdź teraz' }));

    await waitFor(() => {
      expect(
        screen.getByText(/Narracja LLM chwilowo niedostępna/),
      ).toBeInTheDocument();
    });
    expect(screen.getByText('Zgodnie z planem')).toBeInTheDocument();
  });

  test('network error shows friendly PL message via dietCheckErrorMessage', async () => {
    mockGet.mockResolvedValue(baseTargets);
    mockRecalc.mockRejectedValueOnce(new ApiError(-1, 'network'));

    render(<DietCheckCard />);
    await waitFor(() => screen.getByRole('button', { name: 'Sprawdź teraz' }));

    fireEvent.click(screen.getByRole('button', { name: 'Sprawdź teraz' }));

    await waitFor(() => {
      expect(screen.getByText(/Brak połączenia z serwerem/)).toBeInTheDocument();
    });
  });
});

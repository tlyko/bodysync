import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { ApiError } from '../api';
import { TDEEAdaptiveCard } from '../components/dashboard/TDEEAdaptiveCard';

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

describe('TDEEAdaptiveCard', () => {
  test('renders tdee_adaptive value + delta vs baseline when initialized', async () => {
    mockGet.mockResolvedValueOnce({
      kcal_target: 2280,
      protein_target_g: 145,
      fat_target_g: 70,
      carbs_target_g: 350,
      is_default: false,
      body_profile: null,
      tdee_baseline: 2280,
      tdee_adaptive: 2430,
      tdee_last_recalc: {
        date: new Date().toISOString().slice(0, 10),
        event: 'recalc',
        before: 2280,
        after: 2430,
        kcal_in_avg: 2400,
        waga_delta_kg: -0.4,
        adjustment: 150,
        capped: true,
        reason: null,
      },
      tdee_history: [],
    });

    render(<TDEEAdaptiveCard />);

    await waitFor(() => {
      expect(screen.getByText('2430')).toBeInTheDocument();
    });
    expect(screen.getByText(/baseline 2280/)).toBeInTheDocument();
    expect(screen.getByText('+150')).toBeInTheDocument();
    expect(screen.getByText(/dzisiaj/)).toBeInTheDocument();
  });

  test('shows banner when not initialized (no tdee_baseline)', async () => {
    mockGet.mockResolvedValueOnce({
      kcal_target: 2000,
      protein_target_g: 130,
      fat_target_g: 70,
      carbs_target_g: 200,
      is_default: true,
      body_profile: null,
    });

    render(<TDEEAdaptiveCard />);

    await waitFor(() => {
      expect(screen.getByText(/Najpierw uzupełnij swój profil ciała/)).toBeInTheDocument();
    });
    expect(screen.queryByText(/baseline/)).not.toBeInTheDocument();
  });

  test('button "Przelicz teraz" calls postTdeeRecalc + shows success toast', async () => {
    mockGet.mockResolvedValue({
      kcal_target: 2280,
      protein_target_g: 145,
      fat_target_g: 70,
      carbs_target_g: 350,
      is_default: false,
      body_profile: null,
      tdee_baseline: 2280,
      tdee_adaptive: 2280,
      tdee_last_recalc: null,
      tdee_history: [],
    });
    mockRecalc.mockResolvedValueOnce({
      ok: true,
      skipped: false,
      reason: null,
      tdee_before: 2280,
      tdee_after: 2130,
      kcal_in_avg: 2080,
      waga_delta_kg: 0,
      adjustment: -150,
      capped: true,
    });

    render(<TDEEAdaptiveCard />);
    await waitFor(() => screen.getByRole('button', { name: 'Przelicz teraz' }));

    fireEvent.click(screen.getByRole('button', { name: 'Przelicz teraz' }));

    await waitFor(() => {
      expect(screen.getByText(/TDEE zaktualizowane: 2130 kcal/)).toBeInTheDocument();
    });
    expect(mockRecalc).toHaveBeenCalledTimes(1);
    expect(mockGet).toHaveBeenCalledTimes(2); // initial + post-recalc refresh
  });

  test('skipped recalc shows reason as info toast (not error)', async () => {
    mockGet.mockResolvedValue({
      kcal_target: 2000,
      protein_target_g: 130,
      fat_target_g: 70,
      carbs_target_g: 200,
      is_default: true,
      body_profile: null,
      tdee_baseline: 2280,
      tdee_adaptive: 2280,
      tdee_last_recalc: null,
      tdee_history: [],
    });
    mockRecalc.mockResolvedValueOnce({
      ok: true,
      skipped: true,
      reason: 'insufficient_weight_data',
      tdee_before: 2280,
      tdee_after: 2280,
      kcal_in_avg: null,
      waga_delta_kg: null,
      adjustment: null,
      capped: false,
    });

    render(<TDEEAdaptiveCard />);
    await waitFor(() => screen.getByRole('button', { name: 'Przelicz teraz' }));

    fireEvent.click(screen.getByRole('button', { name: 'Przelicz teraz' }));

    await waitFor(() => {
      expect(
        screen.getByText(/Za mało pomiarów wagi w ostatnich 14 dniach/),
      ).toBeInTheDocument();
    });
  });

  test('network error shows friendly PL message via tdeeRecalcErrorMessage', async () => {
    mockGet.mockResolvedValue({
      kcal_target: 2280,
      protein_target_g: 145,
      fat_target_g: 70,
      carbs_target_g: 350,
      is_default: false,
      body_profile: null,
      tdee_baseline: 2280,
      tdee_adaptive: 2280,
      tdee_last_recalc: null,
      tdee_history: [],
    });
    mockRecalc.mockRejectedValueOnce(new ApiError(-1, 'network'));

    render(<TDEEAdaptiveCard />);
    await waitFor(() => screen.getByRole('button', { name: 'Przelicz teraz' }));

    fireEvent.click(screen.getByRole('button', { name: 'Przelicz teraz' }));

    await waitFor(() => {
      expect(screen.getByText(/Brak połączenia z serwerem/)).toBeInTheDocument();
    });
  });
});

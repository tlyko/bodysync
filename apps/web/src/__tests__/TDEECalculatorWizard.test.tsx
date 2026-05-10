import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { TDEECalculatorWizard } from '../components/dashboard/TDEECalculatorWizard';

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    getProfileTargets: vi.fn(),
    postCalculateTDEE: vi.fn(),
    putProfileTargets: vi.fn(),
  };
});

import { getProfileTargets, postCalculateTDEE, putProfileTargets } from '../api';

const mockGet = vi.mocked(getProfileTargets);
const mockCalc = vi.mocked(postCalculateTDEE);
const mockPut = vi.mocked(putProfileTargets);

beforeEach(() => {
  mockGet.mockReset();
  mockCalc.mockReset();
  mockPut.mockReset();
  // Default: brak zapisanego body_profile (fresh setup)
  mockGet.mockResolvedValue({
    kcal_target: 2000,
    protein_target_g: 130,
    fat_target_g: 70,
    carbs_target_g: 200,
    is_default: true,
    body_profile: null,
  });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('TDEECalculatorWizard', () => {
  test('happy flow: fill form → calculate → preview shown', async () => {
    mockCalc.mockResolvedValueOnce({
      bmr: 1790,
      tdee_maintenance: 2774,
      target_kcal: 2770,
      target_protein_g: 150,
      target_fat_g: 75,
      target_carbs_g: 295,
      weight_kg_used: 82.0,
    });
    render(<TDEECalculatorWizard />);

    await waitFor(() => screen.getByText(/Kalkulator TDEE/));

    fireEvent.change(screen.getByPlaceholderText('180'), { target: { value: '180' } });
    fireEvent.change(screen.getByPlaceholderText('32'), { target: { value: '32' } });
    fireEvent.click(screen.getByRole('button', { name: /Oblicz mój TDEE/ }));

    await waitFor(() => {
      // pl-PL toLocaleString używa NBSP ( ) — regex matche'uje dowolny separator
      expect(screen.getByText(/1.?7.?9.?0/)).toBeInTheDocument();
    });
    expect(screen.getByText(/2.?7.?7.?4/)).toBeInTheDocument();
    expect(screen.getByText(/2.?7.?7.?0/)).toBeInTheDocument();
    expect(screen.getByText(/150 g/)).toBeInTheDocument();
    expect(mockCalc).toHaveBeenCalledWith({
      body_profile: {
        height_cm: 180,
        age: 32,
        sex: 'male',
        activity_level: 'moderate',
        goal: 'maintain',
      },
    });
  });

  test('apply button persists targets + body_profile via putProfileTargets', async () => {
    mockCalc.mockResolvedValueOnce({
      bmr: 1790,
      tdee_maintenance: 2774,
      target_kcal: 2770,
      target_protein_g: 150,
      target_fat_g: 75,
      target_carbs_g: 295,
      weight_kg_used: 82.0,
    });
    mockPut.mockResolvedValueOnce({
      kcal_target: 2770,
      protein_target_g: 150,
      fat_target_g: 75,
      carbs_target_g: 295,
      is_default: false,
      body_profile: {
        height_cm: 180,
        age: 32,
        sex: 'male',
        activity_level: 'moderate',
        goal: 'maintain',
      },
    });
    const onUpdated = vi.fn();
    render(<TDEECalculatorWizard onTargetsUpdated={onUpdated} />);

    await waitFor(() => screen.getByText(/Kalkulator TDEE/));
    fireEvent.change(screen.getByPlaceholderText('180'), { target: { value: '180' } });
    fireEvent.change(screen.getByPlaceholderText('32'), { target: { value: '32' } });
    fireEvent.click(screen.getByRole('button', { name: /Oblicz mój TDEE/ }));

    await waitFor(() => screen.getByRole('button', { name: /Zastosuj do moich celów/ }));
    fireEvent.click(screen.getByRole('button', { name: /Zastosuj do moich celów/ }));

    await waitFor(() => {
      expect(mockPut).toHaveBeenCalledWith({
        kcal_target: 2770,
        protein_target_g: 150,
        fat_target_g: 75,
        carbs_target_g: 295,
        body_profile: {
          height_cm: 180,
          age: 32,
          sex: 'male',
          activity_level: 'moderate',
          goal: 'maintain',
        },
      });
    });
    expect(onUpdated).toHaveBeenCalled();
    expect(screen.getByText(/Zastosowano/)).toBeInTheDocument();
  });

  test('pre-fills form when body_profile already saved', async () => {
    mockGet.mockReset();
    mockGet.mockResolvedValue({
      kcal_target: 2400,
      protein_target_g: 160,
      fat_target_g: 80,
      carbs_target_g: 260,
      is_default: false,
      body_profile: {
        height_cm: 175,
        age: 28,
        sex: 'female',
        activity_level: 'light',
        goal: 'loss',
      },
    });
    render(<TDEECalculatorWizard />);

    await waitFor(() => screen.getByDisplayValue('175'));
    expect(screen.getByDisplayValue('28')).toBeInTheDocument();
    expect(screen.getByText(/Twoje dane są zapisane/)).toBeInTheDocument();
  });

  test('validation rejects out-of-range height', async () => {
    render(<TDEECalculatorWizard />);
    await waitFor(() => screen.getByText(/Kalkulator TDEE/));

    fireEvent.change(screen.getByPlaceholderText('180'), { target: { value: '99' } });
    fireEvent.change(screen.getByPlaceholderText('32'), { target: { value: '32' } });
    fireEvent.click(screen.getByRole('button', { name: /Oblicz mój TDEE/ }));

    await waitFor(() => screen.getByText(/Wzrost — liczba całkowita 140–220/));
    expect(mockCalc).not.toHaveBeenCalled();
  });

  test('weight_not_found shows friendly Polish error', async () => {
    const { ApiError } = await import('../api');
    mockCalc.mockRejectedValueOnce(new ApiError(400, 'weight_not_found'));
    render(<TDEECalculatorWizard />);
    await waitFor(() => screen.getByText(/Kalkulator TDEE/));

    fireEvent.change(screen.getByPlaceholderText('180'), { target: { value: '180' } });
    fireEvent.change(screen.getByPlaceholderText('32'), { target: { value: '32' } });
    fireEvent.click(screen.getByRole('button', { name: /Oblicz mój TDEE/ }));

    await waitFor(() =>
      expect(screen.getByText(/Brak waga w bazie/)).toBeInTheDocument(),
    );
  });
});

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { ApiError } from '../api';
import { ProfileTargetsForm } from '../components/dashboard/ProfileTargetsForm';

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    getProfileTargets: vi.fn(),
    putProfileTargets: vi.fn(),
  };
});

import { getProfileTargets, putProfileTargets } from '../api';

const mockGet = vi.mocked(getProfileTargets);
const mockPut = vi.mocked(putProfileTargets);

beforeEach(() => {
  mockGet.mockReset();
  mockPut.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('ProfileTargetsForm', () => {
  test('default targets show banner + populated inputs', async () => {
    mockGet.mockResolvedValueOnce({
      kcal_target: 2000,
      protein_target_g: 130,
      fat_target_g: 70,
      carbs_target_g: 200,
      is_default: true,
    });
    render(<ProfileTargetsForm />);
    await waitFor(() => {
      expect(screen.getByText(/Używasz wartości domyślnych/)).toBeInTheDocument();
    });
    expect(screen.getByDisplayValue('2000')).toBeInTheDocument();
    expect(screen.getByDisplayValue('130')).toBeInTheDocument();
  });

  test('owner-set targets hide banner', async () => {
    mockGet.mockResolvedValueOnce({
      kcal_target: 2400,
      protein_target_g: 160,
      fat_target_g: 80,
      carbs_target_g: 260,
      is_default: false,
    });
    render(<ProfileTargetsForm />);
    await waitFor(() => {
      expect(screen.getByDisplayValue('2400')).toBeInTheDocument();
    });
    expect(screen.queryByText(/Używasz wartości domyślnych/)).not.toBeInTheDocument();
  });

  test('happy submit calls putProfileTargets and shows success', async () => {
    mockGet.mockResolvedValueOnce({
      kcal_target: 2000,
      protein_target_g: 130,
      fat_target_g: 70,
      carbs_target_g: 200,
      is_default: true,
    });
    mockPut.mockResolvedValueOnce({
      kcal_target: 2400,
      protein_target_g: 160,
      fat_target_g: 80,
      carbs_target_g: 260,
      is_default: false,
    });
    render(<ProfileTargetsForm />);
    await waitFor(() => screen.getByDisplayValue('2000'));

    fireEvent.change(screen.getByDisplayValue('2000'), { target: { value: '2400' } });
    fireEvent.change(screen.getByDisplayValue('130'), { target: { value: '160' } });
    fireEvent.change(screen.getByDisplayValue('70'), { target: { value: '80' } });
    fireEvent.change(screen.getByDisplayValue('200'), { target: { value: '260' } });

    fireEvent.click(screen.getByRole('button', { name: /Zapisz cele/ }));

    await waitFor(() => {
      expect(mockPut).toHaveBeenCalledWith({
        kcal_target: 2400,
        protein_target_g: 160,
        fat_target_g: 80,
        carbs_target_g: 260,
      });
    });
    expect(screen.getByText(/Zapisano\. Asystent/)).toBeInTheDocument();
  });

  test('out of range shows field error and skips PUT', async () => {
    mockGet.mockResolvedValueOnce({
      kcal_target: 2000,
      protein_target_g: 130,
      fat_target_g: 70,
      carbs_target_g: 200,
      is_default: true,
    });
    render(<ProfileTargetsForm />);
    await waitFor(() => screen.getByDisplayValue('2000'));

    fireEvent.change(screen.getByDisplayValue('2000'), { target: { value: '500' } });
    fireEvent.click(screen.getByRole('button', { name: /Zapisz cele/ }));

    expect(screen.getByText(/Zakres 1000–5000/)).toBeInTheDocument();
    expect(mockPut).not.toHaveBeenCalled();
  });

  test('PUT 400 shows server error', async () => {
    mockGet.mockResolvedValueOnce({
      kcal_target: 2000,
      protein_target_g: 130,
      fat_target_g: 70,
      carbs_target_g: 200,
      is_default: true,
    });
    mockPut.mockRejectedValueOnce(new ApiError(400, 'invalid payload'));
    render(<ProfileTargetsForm />);
    await waitFor(() => screen.getByDisplayValue('2000'));

    fireEvent.click(screen.getByRole('button', { name: /Zapisz cele/ }));

    await waitFor(() => {
      expect(screen.getByText(/Błąd 400/)).toBeInTheDocument();
    });
  });
});

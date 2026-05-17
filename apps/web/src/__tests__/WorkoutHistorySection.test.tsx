import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { WorkoutHistorySection } from '../components/dashboard/WorkoutHistorySection';
import type { Training } from '../components/dashboard/planParser';

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    getWorkouts: vi.fn(),
    postWorkoutsExtract: vi.fn(),
  };
});

import { getWorkouts, postWorkoutsExtract } from '../api';

const mockGet = vi.mocked(getWorkouts);
const mockPost = vi.mocked(postWorkoutsExtract);

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

const sampleTrainings: Training[] = [
  {
    name: 'Trening A',
    weekIdx: 1,
    weekTotal: 1,
    sections: [
      {
        label: 'Trening A',
        headers: ['Numer', 'Ćwiczenie', 'Ciężar x serie x powtórzenia x RIR'],
        exercises: [{ number: '01', cells: ['01', 'Squat', '100x3x5'] }],
      },
    ],
  },
];

describe('WorkoutHistorySection', () => {
  test('loading → empty state gdy historia pusta', async () => {
    mockGet.mockResolvedValueOnce({ workouts: [] });
    render(<WorkoutHistorySection trainings={sampleTrainings} />);

    await waitFor(() => expect(screen.getByText(/Brak zapisanej historii/)).toBeInTheDocument());
  });

  test('renderuje listę grouped per date z expand toggle', async () => {
    mockGet.mockResolvedValueOnce({
      workouts: [
        {
          date: '2026-05-11',
          training_slug: 'trening-a',
          training_name: 'Trening A',
          exercise_number: '01',
          exercise_name: 'Sumo Deadlift',
          sets: [
            { weight_kg: 100, weight_kind: 'kg', reps: 5 },
            { weight_kg: 140, weight_kind: 'kg', reps: 3 },
          ],
          rir: null,
          notes: null,
        },
        {
          date: '2026-05-11',
          training_slug: 'trening-a',
          training_name: 'Trening A',
          exercise_number: '02',
          exercise_name: 'Bench Press',
          sets: [{ weight_kg: 70, weight_kind: 'kg', reps: 6 }],
          rir: 2,
          notes: null,
        },
      ],
    });
    render(<WorkoutHistorySection trainings={sampleTrainings} />);

    await waitFor(() =>
      expect(screen.getByText(/01\. Sumo Deadlift/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/02\. Bench Press/)).toBeInTheDocument();
    // 1 grupa = 1 nagłówek daty (poniedziałek 11 maja 2026).
    expect(screen.getByText(/11 maja 2026/)).toBeInTheDocument();

    // Klik expand → tabelka setów Sumo Deadlift widoczna.
    fireEvent.click(screen.getByRole('button', { name: /Sumo Deadlift/ }));
    expect(screen.getByText(/100kg × 5/)).toBeInTheDocument();
    expect(screen.getByText(/140kg × 3/)).toBeInTheDocument();
  });

  test('button "Zaktualizuj" wywołuje postWorkoutsExtract + re-fetch', async () => {
    mockGet
      .mockResolvedValueOnce({ workouts: [] }) // initial load → empty
      .mockResolvedValueOnce({
        workouts: [
          {
            date: '2026-05-11',
            training_slug: 'trening-a',
            training_name: 'Trening A',
            exercise_number: '01',
            exercise_name: 'Squat',
            sets: [{ weight_kg: 100, weight_kind: 'kg', reps: 5 }],
            rir: null,
            notes: null,
          },
        ],
      }); // po extract refetch → 1 entry
    mockPost.mockResolvedValueOnce({
      extracted: 1,
      skipped: 0,
      errors: 0,
      items: [],
    });

    render(<WorkoutHistorySection trainings={sampleTrainings} />);

    await waitFor(() => expect(screen.getByText(/Brak zapisanej historii/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /Zaktualizuj/ }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalled();
    });
    const payload = mockPost.mock.calls[0][0];
    expect(payload.today_iso).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(payload.trainings).toEqual(sampleTrainings);

    // Success message + re-fetch entries widoczne.
    expect(await screen.findByRole('status')).toHaveTextContent(
      /Wyciągnięto 1 ćwiczeń/,
    );
    expect(screen.getByText(/01\. Squat/)).toBeInTheDocument();
  });

  test('button disabled gdy trainings empty', async () => {
    mockGet.mockResolvedValueOnce({ workouts: [] });
    render(<WorkoutHistorySection trainings={[]} />);

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Zaktualizuj/ })).toBeDisabled(),
    );
  });

  test('error fetching workouts pokazuje banner', async () => {
    mockGet.mockRejectedValueOnce(
      Object.assign(new Error('boom'), { name: 'ApiError' }),
    );
    render(<WorkoutHistorySection trainings={sampleTrainings} />);

    const banner = await screen.findByRole('alert');
    expect(banner).toHaveTextContent(/Nieoczekiwany błąd|Coś poszło|błąd/i);
  });

  test('formatSet rozróżnia BW od kg', async () => {
    mockGet.mockResolvedValueOnce({
      workouts: [
        {
          date: '2026-05-11',
          training_slug: 'trening-a',
          training_name: 'Trening A',
          exercise_number: '01',
          exercise_name: 'Pull-up',
          sets: [
            { weight_kind: 'bw', reps: 8 },
            { weight_kg: 5, weight_kind: 'bw', reps: 5 },
          ],
          rir: null,
          notes: null,
        },
      ],
    });
    render(<WorkoutHistorySection trainings={sampleTrainings} />);

    await waitFor(() => expect(screen.getByText(/Pull-up/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /Pull-up/ }));
    // BW (no extra) → "BW × 8". BW+5 → "BW +5kg × 5".
    expect(screen.getByText(/BW × 8/)).toBeInTheDocument();
    expect(screen.getByText(/BW \+5kg × 5/)).toBeInTheDocument();
  });
});

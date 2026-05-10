import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { WorkoutPlanCard } from '../components/dashboard/WorkoutPlanCard';

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    getPlan: vi.fn(),
    getActivities: vi.fn(),
  };
});

// Mock parseTrainings — izolacja od planParser (ma własne testy w planParser.test.ts).
// Returns predefined Training[] na bazie kontroli z testu (mockReset/mockReturnValueOnce).
vi.mock('../components/dashboard/planParser', () => ({
  parseTrainings: vi.fn(),
}));

import { getActivities, getPlan } from '../api';
import { parseTrainings } from '../components/dashboard/planParser';

const mockPlan = vi.mocked(getPlan);
const mockActivities = vi.mocked(getActivities);
const mockParseTrainings = vi.mocked(parseTrainings);

beforeEach(() => {
  mockPlan.mockReset();
  mockActivities.mockReset();
  mockParseTrainings.mockReset();
  // Default — parser zwraca 2 unique trainings.
  mockParseTrainings.mockReturnValue([
    { name: 'Trening A', weekIdx: 1, weekTotal: 1, sections: [] },
    { name: 'Trening B', weekIdx: 1, weekTotal: 1, sections: [] },
  ]);
});

afterEach(() => {
  vi.clearAllMocks();
});

const SAMPLE_ROWS: string[][] = [
  ['Trening A', 'Tydzień 1', '', ''],
  ['Rozgrzewka', '', '', ''],
  ['Pajacyki', '3x10', '', ''],
  ['Trening', '', '', ''],
  ['Przysiad', '4x6', '60kg', ''],
  ['', '', '', ''],
  ['Trening B', 'Tydzień 1', '', ''],
  ['Trening', '', '', ''],
  ['Wyciskanie', '4x8', '80kg', ''],
];

function buildActivities(daysAgoList: number[]) {
  return {
    items: daysAgoList.map((daysAgo, i) => ({
      strava_id: 1000 + i,
      name: `Activity ${i}`,
      sport_type: 'Run',
      type: 'Run',
      distance_m: 5000,
      moving_time_s: 1800,
      elapsed_time_s: 1800,
      elevation_gain_m: 0,
      start_date: new Date(Date.now() - daysAgo * 24 * 3600 * 1000).toISOString(),
      start_date_local: new Date(Date.now() - daysAgo * 24 * 3600 * 1000).toISOString(),
      calories: 300,
      average_heartrate: 145,
      max_heartrate: 165,
      summary_polyline: null,
    })),
  };
}

describe('WorkoutPlanCard', () => {
  test('happy: parses plan + counts activities last 7d + lists unique trainings', async () => {
    mockPlan.mockResolvedValueOnce({
      rows: SAMPLE_ROWS,
      fetched_at: 1700000000,
      fresh: true,
      sheet_tab: 'Arkusz5',
    });
    // 3 activities w 7d (1, 3, 5 dni temu) + 1 stara (10 dni temu — drop)
    mockActivities.mockResolvedValueOnce(buildActivities([1, 3, 5, 10]));

    const onSeePlan = vi.fn();
    render(<WorkoutPlanCard onSeePlan={onSeePlan} />);

    await waitFor(() => {
      expect(screen.getByText(/treningów w tym tygodniu/)).toBeInTheDocument();
    });
    // Count: 3 (drop ten 10 dni temu)
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('Trening A')).toBeInTheDocument();
    expect(screen.getByText('Trening B')).toBeInTheDocument();
  });

  test('singular form: 1 trening (NIE treningów)', async () => {
    mockPlan.mockResolvedValueOnce({
      rows: SAMPLE_ROWS,
      fetched_at: 1700000000,
      fresh: true,
      sheet_tab: 'Arkusz5',
    });
    mockActivities.mockResolvedValueOnce(buildActivities([2]));

    render(<WorkoutPlanCard onSeePlan={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(/trening w tym tygodniu/)).toBeInTheDocument();
    });
  });

  test('plan fail (404 / no_plan): empty state CTA', async () => {
    mockPlan.mockRejectedValueOnce(new Error('not configured'));
    mockActivities.mockResolvedValueOnce(buildActivities([]));

    const onSeePlan = vi.fn();
    render(<WorkoutPlanCard onSeePlan={onSeePlan} />);

    await waitFor(() => {
      expect(screen.getByText(/Plan treningowy nie skonfigurowany/)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole('button', { name: /Idź do Plan/ }));
    expect(onSeePlan).toHaveBeenCalledTimes(1);
  });

  test('training name click → onSeePlan', async () => {
    mockPlan.mockResolvedValueOnce({
      rows: SAMPLE_ROWS,
      fetched_at: 1700000000,
      fresh: true,
      sheet_tab: 'Arkusz5',
    });
    mockActivities.mockResolvedValueOnce(buildActivities([1]));

    const onSeePlan = vi.fn();
    render(<WorkoutPlanCard onSeePlan={onSeePlan} />);

    await waitFor(() => screen.getByText('Trening A'));
    fireEvent.click(screen.getByRole('button', { name: 'Trening A' }));
    expect(onSeePlan).toHaveBeenCalledTimes(1);
  });

  test('zero activities w 7d: count = 0', async () => {
    mockPlan.mockResolvedValueOnce({
      rows: SAMPLE_ROWS,
      fetched_at: 1700000000,
      fresh: true,
      sheet_tab: 'Arkusz5',
    });
    mockActivities.mockResolvedValueOnce(buildActivities([10, 20]));

    render(<WorkoutPlanCard onSeePlan={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText('0')).toBeInTheDocument();
    });
  });
});

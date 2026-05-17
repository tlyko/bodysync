import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { PlanScreen } from '../components/dashboard/PlanScreen';

const fetchMock = vi.fn();
// Queue per-test responses dla /api/plan (initial + refresh). WorkoutHistorySection
// (2026-05-17) auto-fetches /api/workouts na mount — routujemy URL-wise żeby
// nie konsumowała queue.
let planQueue: Response[] = [];

function queuePlanResponse(response: Response): void {
  planQueue.push(response);
}

beforeEach(() => {
  fetchMock.mockReset();
  planQueue = [];
  fetchMock.mockImplementation((url: unknown) => {
    const u = typeof url === 'string' ? url : (url as Request).url;
    if (u.includes('/api/workouts')) {
      return Promise.resolve(
        new Response(JSON.stringify({ workouts: [] }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      );
    }
    if (u.includes('/api/plan')) {
      const next = planQueue.shift();
      if (next) return Promise.resolve(next);
    }
    return Promise.reject(new Error('unexpected fetch ' + u));
  });
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

describe('PlanScreen', () => {
  test('renders parsed trainings + meta after fetch', async () => {
    queuePlanResponse(
      jsonResponse({
        rows: [
          ['Numer', 'Ćwiczenie', 'Link', 'Serie x powt.', 'Ból'],
          ['', '', '', '', ''],
          ['Trening A', '', '', '', ''],
          ['01', 'Squat', 'https://yt/abc', '5x5', '0'],
          ['02', 'Bench', '', '4x8', '0'],
        ],
        fetched_at: Math.floor(Date.now() / 1000) - 120,
        fresh: true,
        sheet_tab: 'Arkusz5',
      }),
    );

    render(<PlanScreen />);

    await waitFor(() => expect(screen.getByText('Squat')).toBeInTheDocument());
    expect(screen.getByText('Bench')).toBeInTheDocument();
    expect(screen.getByText('Arkusz5')).toBeInTheDocument();
    expect(screen.getByText(/2 min temu/)).toBeInTheDocument();
    // Tab "Trening A" widoczny
    expect(screen.getByRole('button', { name: 'Trening A' })).toBeInTheDocument();
  });

  test('cached state pokazuje "(z cache)" w meta', async () => {
    queuePlanResponse(
      jsonResponse({
        rows: [['x']], // brak "Numer" → unparseable, ale meta nadal renderuje
        fetched_at: Math.floor(Date.now() / 1000) - 600,
        fresh: false,
        sheet_tab: 'Arkusz5',
      }),
    );

    render(<PlanScreen />);
    await waitFor(() => expect(screen.getByText(/z cache/)).toBeInTheDocument());
  });

  test('503 not_configured pokazuje friendly error + brak retry button', async () => {
    queuePlanResponse(jsonResponse({ error: 'not_configured' }, 503));

    render(<PlanScreen />);
    await waitFor(() =>
      expect(screen.getByText(/nie jest jeszcze skonfigurowany/i)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/Spróbuj ponownie/)).not.toBeInTheDocument();
  });

  test('502 sheets_api_error → retryable button visible', async () => {
    queuePlanResponse(jsonResponse({ error: 'sheets_api_error' }, 502));

    render(<PlanScreen />);
    // Use getByRole żeby unika collision z error message text
    // ("Spróbuj ponownie za chwilę.") również zawiera tę frazę.
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Spróbuj ponownie/i })).toBeInTheDocument(),
    );
  });

  test('"Zsynchronizuj plan" wywołuje getPlan z refresh=1', async () => {
    const initialRows = [
      ['Numer', 'Ćwiczenie', 'Serie x powt.'],
      ['Trening A', '', ''],
      ['01', 'Initial-exercise', '5x5'],
    ];
    const refreshedRows = [
      ['Numer', 'Ćwiczenie', 'Serie x powt.'],
      ['Trening A', '', ''],
      ['01', 'Fresh-exercise', '4x8'],
    ];
    queuePlanResponse(
      jsonResponse({
        rows: initialRows,
        fetched_at: Math.floor(Date.now() / 1000),
        fresh: true,
        sheet_tab: 'Arkusz5',
      }),
    );
    queuePlanResponse(
      jsonResponse({
        rows: refreshedRows,
        fetched_at: Math.floor(Date.now() / 1000),
        fresh: true,
        sheet_tab: 'Arkusz5',
      }),
    );

    render(<PlanScreen />);
    await waitFor(() => expect(screen.getByText('Initial-exercise')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /Zsynchronizuj/i }));

    await waitFor(() => expect(screen.getByText('Fresh-exercise')).toBeInTheDocument());

    // Filtrujemy plan-specific calls (workouts fetch z WorkoutHistorySection
    // dorzuca dodatkowe wywołanie).
    const planCalls = fetchMock.mock.calls
      .map((c) => String(c[0]))
      .filter((u) => u.includes('/api/plan'));
    expect(planCalls).toHaveLength(2);
    expect(planCalls[1]).toContain('refresh=1');
  });
});

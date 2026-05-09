import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { PlanScreen } from '../components/dashboard/PlanScreen';

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
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
  test('renders plan rows + meta after fetch', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        rows: [
          ['Trening A', 'Squat', '5x5'],
          ['', 'Bench', '5x5'],
        ],
        fetched_at: Math.floor(Date.now() / 1000) - 120,
        fresh: true,
        sheet_tab: 'Arkusz5',
      }),
    );

    render(<PlanScreen />);

    await waitFor(() => expect(screen.getByText('Squat')).toBeInTheDocument());
    expect(screen.getByText('Trening A')).toBeInTheDocument();
    expect(screen.getByText('Arkusz5')).toBeInTheDocument();
    expect(screen.getByText(/2 min temu/)).toBeInTheDocument();
  });

  test('cached state pokazuje "(z cache)" w meta', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        rows: [['x']],
        fetched_at: Math.floor(Date.now() / 1000) - 600,
        fresh: false,
        sheet_tab: 'Arkusz5',
      }),
    );

    render(<PlanScreen />);
    await waitFor(() => expect(screen.getByText(/z cache/)).toBeInTheDocument());
  });

  test('503 not_configured pokazuje friendly error + brak retry button', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: 'not_configured' }, 503));

    render(<PlanScreen />);
    await waitFor(() =>
      expect(screen.getByText(/nie jest jeszcze skonfigurowany/i)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/Spróbuj ponownie/)).not.toBeInTheDocument();
  });

  test('502 sheets_api_error → retryable button visible', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: 'sheets_api_error' }, 502));

    render(<PlanScreen />);
    // Use getByRole żeby unika collision z error message text
    // ("Spróbuj ponownie za chwilę.") również zawiera tę frazę.
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Spróbuj ponownie/i })).toBeInTheDocument(),
    );
  });

  test('"Odśwież" wywołuje getPlan z refresh=1', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        rows: [['a']],
        fetched_at: Math.floor(Date.now() / 1000),
        fresh: true,
        sheet_tab: 'Arkusz5',
      }),
    );
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        rows: [['fresh-row']],
        fetched_at: Math.floor(Date.now() / 1000),
        fresh: true,
        sheet_tab: 'Arkusz5',
      }),
    );

    render(<PlanScreen />);
    await waitFor(() => expect(screen.getByText('a')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /Odśwież/i }));

    await waitFor(() => expect(screen.getByText('fresh-row')).toBeInTheDocument());

    // Druga fetch wywołana z refresh=1
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1][0]).toContain('refresh=1');
  });
});

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { ApiError } from '../api';
import { ActivitiesView } from '../components/dashboard/ActivitiesView';
import {
  formatDistance,
  formatDuration,
  formatPace,
  formatRelativeDate,
  sportIcon,
  sportLabel,
} from '../components/dashboard/activities';
import type { Activity } from '../types';

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    getActivities: vi.fn(),
    stravaOAuthStartUrl: () => 'https://api.bodysync.pl/api/strava/oauth/start',
  };
});

import { getActivities } from '../api';

const mockGetActivities = vi.mocked(getActivities);

beforeEach(() => {
  mockGetActivities.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

// ─── Pure helpers ──────────────────────────────────────────────────────────

describe('sportIcon / sportLabel', () => {
  test('Run → 🏃 / "Bieg"', () => {
    expect(sportIcon('Run')).toBe('🏃');
    expect(sportLabel('Run')).toBe('Bieg');
  });

  test('Ride → 🚴 / "Rower"', () => {
    expect(sportIcon('Ride')).toBe('🚴');
    expect(sportLabel('Ride')).toBe('Rower');
  });

  test('unknown sport → ⚡ / passthrough label', () => {
    expect(sportIcon('Polo')).toBe('⚡');
    expect(sportLabel('Polo')).toBe('Polo');
  });
});

describe('formatDistance', () => {
  test('5234 m → "5.23 km"', () => {
    expect(formatDistance(5234)).toBe('5.23 km');
  });
  test('500 m → "500 m"', () => {
    expect(formatDistance(500)).toBe('500 m');
  });
  test('1000 m → "1.00 km"', () => {
    expect(formatDistance(1000)).toBe('1.00 km');
  });
});

describe('formatDuration', () => {
  test('< 1h: 1820s → "30:20"', () => {
    expect(formatDuration(1820)).toBe('30:20');
  });
  test('>= 1h: 3661s → "1:01:01"', () => {
    expect(formatDuration(3661)).toBe('1:01:01');
  });
  test('0s → "0:00"', () => {
    expect(formatDuration(0)).toBe('0:00');
  });
});

describe('formatPace', () => {
  test('5km @ 25min → "5:00 /km"', () => {
    expect(formatPace(5000, 1500)).toBe('5:00 /km');
  });
  test('zero/short distance → null', () => {
    expect(formatPace(50, 600)).toBeNull();
    expect(formatPace(5000, 5)).toBeNull();
  });
});

describe('formatRelativeDate', () => {
  const now = new Date('2026-05-08T12:00:00');

  test('today → "Dziś"', () => {
    expect(formatRelativeDate('2026-05-08T08:30:00', now)).toBe('Dziś');
  });
  test('yesterday → "Wczoraj"', () => {
    expect(formatRelativeDate('2026-05-07T20:00:00', now)).toBe('Wczoraj');
  });
  test('5 dni temu', () => {
    expect(formatRelativeDate('2026-05-03T10:00:00', now)).toBe('5 dni temu');
  });
  test('older same year — Polish month', () => {
    const result = formatRelativeDate('2026-04-12T10:00:00', now);
    expect(result).toMatch(/12.*kwietn/);
  });
});

// ─── ActivitiesView component ──────────────────────────────────────────────

const sampleActivity: Activity = {
  strava_id: 12345,
  name: 'Wieczorny bieg',
  sport_type: 'Run',
  type: 'Run',
  distance_m: 5234,
  moving_time_s: 1820,
  elapsed_time_s: 1900,
  elevation_gain_m: 45,
  start_date: '2026-05-08T18:00:00Z',
  start_date_local: '2026-05-08T20:00:00',
  calories: 380,
  average_heartrate: 145,
  max_heartrate: 168,
};

describe('ActivitiesView', () => {
  test('renders connect CTA when no activities', async () => {
    mockGetActivities.mockResolvedValueOnce({ items: [] });
    render(<ActivitiesView />);

    await waitFor(() => {
      expect(screen.getByText(/Połącz konto Strava/i)).toBeInTheDocument();
    });
    const link = screen.getByRole('link', { name: /Połącz ze Stravą/i });
    expect(link).toHaveAttribute('href', 'https://api.bodysync.pl/api/strava/oauth/start');
  });

  test('renders activity rows with distance + duration + pace + HR + kcal', async () => {
    mockGetActivities.mockResolvedValueOnce({ items: [sampleActivity] });
    render(<ActivitiesView />);

    await waitFor(() => {
      expect(screen.getByText('Wieczorny bieg')).toBeInTheDocument();
    });
    expect(screen.getByText('5.23 km')).toBeInTheDocument();
    expect(screen.getByText('30:20')).toBeInTheDocument();
    expect(screen.getByText(/\/km/)).toBeInTheDocument(); // pace dla biegu
    expect(screen.getByText('145 bpm')).toBeInTheDocument();
    expect(screen.getByText('380 kcal')).toBeInTheDocument();
  });

  test('shows "Połącz ponownie" link when has activities', async () => {
    mockGetActivities.mockResolvedValueOnce({ items: [sampleActivity] });
    render(<ActivitiesView />);

    await waitFor(() => {
      expect(screen.getByText('Wieczorny bieg')).toBeInTheDocument();
    });
    expect(screen.getByRole('link', { name: /Połącz ponownie/i })).toBeInTheDocument();
  });

  test('error state — 401 shows reauth message', async () => {
    mockGetActivities.mockRejectedValueOnce(new ApiError(401, 'no jwt'));
    render(<ActivitiesView />);

    await waitFor(() => {
      expect(screen.getByText(/Sesja wygasła/i)).toBeInTheDocument();
    });
  });

  test('error state — generic for non-401', async () => {
    mockGetActivities.mockRejectedValueOnce(new ApiError(500, 'server'));
    render(<ActivitiesView />);

    await waitFor(() => {
      expect(screen.getByText(/Nie udało się wczytać/i)).toBeInTheDocument();
    });
  });

  test('Ride activity does not show pace', async () => {
    mockGetActivities.mockResolvedValueOnce({
      items: [{ ...sampleActivity, sport_type: 'Ride', type: 'Ride' }],
    });
    render(<ActivitiesView />);

    await waitFor(() => {
      expect(screen.getByText(/Wieczorny bieg/i)).toBeInTheDocument();
    });
    expect(screen.queryByText(/\/km/)).not.toBeInTheDocument();
  });
});

describe('events flow — fireEvent placeholder', () => {
  // fireEvent dla buttonów w future tests (currently links — browser handles redirect natywnie)
  test('connect link is anchor (not button)', async () => {
    mockGetActivities.mockResolvedValueOnce({ items: [] });
    render(<ActivitiesView />);
    await waitFor(() => screen.getByRole('link', { name: /Połącz ze Stravą/i }));
    const link = screen.getByRole('link', { name: /Połącz ze Stravą/i });
    // No JS click handler — pure href, browser nawiguje (no preventDefault)
    fireEvent.click(link);
    // assertion w sumie redundant — nie mockujemy window.location, ale upewnia
    // że click nie crashuje React
  });
});

// ─── Sprint 10 A8 — sport chips + search filter ───────────────────────────

describe('A8 filters', () => {
  function buildActivity(overrides: Partial<Activity>): Activity {
    return {
      strava_id: Math.floor(Math.random() * 1e9),
      name: 'Activity',
      sport_type: 'Run',
      type: 'Run',
      distance_m: 5000,
      moving_time_s: 1800,
      elapsed_time_s: 1800,
      elevation_gain_m: 0,
      start_date: '2026-05-09T10:00:00Z',
      start_date_local: '2026-05-09T12:00:00',
      calories: 300,
      average_heartrate: 145,
      max_heartrate: 165,
      ...overrides,
    };
  }

  test('chips: lista unique sport_type z PL labels + count badge', async () => {
    mockGetActivities.mockResolvedValueOnce({
      items: [
        buildActivity({ sport_type: 'Run' }),
        buildActivity({ sport_type: 'Run' }),
        buildActivity({ sport_type: 'Run' }),
        buildActivity({ sport_type: 'Ride' }),
        buildActivity({ sport_type: 'Walk' }),
      ],
    });
    render(<ActivitiesView />);

    await waitFor(() => screen.getByText('Wszystkie'));
    // Count w "Wszystkie" chip
    expect(screen.getByRole('button', { name: /Wszystkie\s*5/ })).toBeInTheDocument();
    // PL labels + counts (sortowane po count desc — Bieg first)
    expect(screen.getByRole('button', { name: /Bieg\s*3/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Rower\s*1/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Spacer\s*1/ })).toBeInTheDocument();
  });

  test('chip click filtruje listę', async () => {
    mockGetActivities.mockResolvedValueOnce({
      items: [
        buildActivity({ name: 'Poranny bieg', sport_type: 'Run' }),
        buildActivity({ name: 'Wieczorny rower', sport_type: 'Ride' }),
      ],
    });
    render(<ActivitiesView />);

    await waitFor(() => screen.getByText('Poranny bieg'));
    fireEvent.click(screen.getByRole('button', { name: /Rower/ }));

    expect(screen.queryByText('Poranny bieg')).not.toBeInTheDocument();
    expect(screen.getByText('Wieczorny rower')).toBeInTheDocument();
    expect(screen.getByText(/Znaleziono 1 aktywność/)).toBeInTheDocument();
  });

  test('chip drugi click resetuje filter', async () => {
    mockGetActivities.mockResolvedValueOnce({
      items: [
        buildActivity({ name: 'Bieg A', sport_type: 'Run' }),
        buildActivity({ name: 'Rower B', sport_type: 'Ride' }),
      ],
    });
    render(<ActivitiesView />);

    await waitFor(() => screen.getByText('Bieg A'));
    const biegChip = screen.getByRole('button', { name: /Bieg/ });
    fireEvent.click(biegChip);
    expect(screen.queryByText('Rower B')).not.toBeInTheDocument();
    fireEvent.click(biegChip); // toggle off
    expect(screen.getByText('Rower B')).toBeInTheDocument();
  });

  test('search po nazwie (case-insensitive)', async () => {
    mockGetActivities.mockResolvedValueOnce({
      items: [
        buildActivity({ name: 'Poranny bieg po lesie' }),
        buildActivity({ name: 'Wieczorny trening siłowy' }),
      ],
    });
    render(<ActivitiesView />);

    await waitFor(() => screen.getByText('Poranny bieg po lesie'));
    fireEvent.change(screen.getByPlaceholderText(/Szukaj po nazwie/), {
      target: { value: 'WIECZORNY' },
    });
    expect(screen.queryByText('Poranny bieg po lesie')).not.toBeInTheDocument();
    expect(screen.getByText('Wieczorny trening siłowy')).toBeInTheDocument();
  });

  test('sport + search łącznie (AND)', async () => {
    mockGetActivities.mockResolvedValueOnce({
      items: [
        buildActivity({ name: 'Poranny bieg', sport_type: 'Run' }),
        buildActivity({ name: 'Trening interwał', sport_type: 'Run' }),
        buildActivity({ name: 'Trening rowerowy', sport_type: 'Ride' }),
      ],
    });
    render(<ActivitiesView />);

    await waitFor(() => screen.getByText('Poranny bieg'));
    fireEvent.click(screen.getByRole('button', { name: /Bieg/ }));
    fireEvent.change(screen.getByPlaceholderText(/Szukaj/), {
      target: { value: 'trening' },
    });
    // Tylko "Trening interwał" matche'uje sport=Run AND name contains "trening"
    expect(screen.getByText('Trening interwał')).toBeInTheDocument();
    expect(screen.queryByText('Poranny bieg')).not.toBeInTheDocument();
    expect(screen.queryByText('Trening rowerowy')).not.toBeInTheDocument();
  });

  test('Wyczyść button resetuje sport + search', async () => {
    mockGetActivities.mockResolvedValueOnce({
      items: [
        buildActivity({ name: 'Bieg A', sport_type: 'Run' }),
        buildActivity({ name: 'Rower B', sport_type: 'Ride' }),
      ],
    });
    render(<ActivitiesView />);

    await waitFor(() => screen.getByText('Bieg A'));
    fireEvent.click(screen.getByRole('button', { name: /Bieg/ }));
    fireEvent.change(screen.getByPlaceholderText(/Szukaj/), { target: { value: 'A' } });
    fireEvent.click(screen.getByRole('button', { name: 'Wyczyść' }));

    // Both visible po reset
    expect(screen.getByText('Bieg A')).toBeInTheDocument();
    expect(screen.getByText('Rower B')).toBeInTheDocument();
  });

  test('brak wyników → empty state z hintem', async () => {
    mockGetActivities.mockResolvedValueOnce({
      items: [buildActivity({ name: 'Bieg A', sport_type: 'Run' })],
    });
    render(<ActivitiesView />);

    await waitFor(() => screen.getByText('Bieg A'));
    fireEvent.change(screen.getByPlaceholderText(/Szukaj/), {
      target: { value: 'xyzzy' },
    });
    expect(screen.getByText(/Brak wyników dla filtrów/)).toBeInTheDocument();
    expect(screen.getByText(/Spróbuj innego filtra/)).toBeInTheDocument();
  });
});

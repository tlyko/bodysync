import { useEffect, useMemo, useState } from 'react';
import { ApiError, getActivities, stravaOAuthStartUrl } from '../../api';
import type { Activity } from '../../types';
import { ActivityRow } from './ActivityRow';

type LoadState =
  | { status: 'loading' }
  | { status: 'ready'; activities: Activity[] }
  | { status: 'error'; message: string };

// Sprint 10 A8 — limit bump 20 → 100 żeby filter local-side miał sens.
// Backend activities_list rzuca top-N po start_date desc; 100 ostatnich
// to ~3 mies aktywności dla typowego trenującego (biegi 3×/tydz. = ~12/m).
const FETCH_LIMIT = 100;

const SPORT_LABELS_PL: Record<string, string> = {
  Run: 'Bieg',
  Ride: 'Rower',
  Walk: 'Spacer',
  Hike: 'Trekking',
  Swim: 'Pływanie',
  Workout: 'Trening',
  WeightTraining: 'Siłowy',
  Yoga: 'Joga',
  AlpineSki: 'Narty',
  EBikeRide: 'eRower',
  TrailRun: 'Trail',
  VirtualRide: 'Wirtualny',
};

function sportLabel(sport: string): string {
  return SPORT_LABELS_PL[sport] ?? sport;
}

export function ActivitiesView() {
  const [state, setState] = useState<LoadState>({ status: 'loading' });
  const [sportFilter, setSportFilter] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  useEffect(() => {
    let cancelled = false;
    getActivities(FETCH_LIMIT)
      .then((res) => {
        if (cancelled) return;
        setState({ status: 'ready', activities: res.items });
      })
      .catch((e) => {
        if (cancelled) return;
        const msg =
          e instanceof ApiError && e.status === 401
            ? 'Sesja wygasła. Zaloguj się ponownie.'
            : 'Nie udało się wczytać aktywności.';
        setState({ status: 'error', message: msg });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Unique sport types z aktualnego setu (count per type dla chip badge).
  // Sortuję po count desc — najczęstsze sporty pierwsze.
  const sportCounts = useMemo<Map<string, number>>(() => {
    if (state.status !== 'ready') return new Map();
    const m = new Map<string, number>();
    for (const a of state.activities) {
      m.set(a.sport_type, (m.get(a.sport_type) ?? 0) + 1);
    }
    return m;
  }, [state]);

  const sortedSports = useMemo<string[]>(
    () =>
      Array.from(sportCounts.entries())
        .sort((a, b) => b[1] - a[1])
        .map(([sport]) => sport),
    [sportCounts],
  );

  // Filter: sport_type match (gdy aktywny) AND name lowercase contains query.
  // Search działa case-insensitive. Empty query = match all (po sport).
  const filtered = useMemo<Activity[]>(() => {
    if (state.status !== 'ready') return [];
    const q = searchQuery.trim().toLowerCase();
    return state.activities.filter((a) => {
      if (sportFilter && a.sport_type !== sportFilter) return false;
      if (q && !a.name.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [state, sportFilter, searchQuery]);

  const hasActiveFilter = sportFilter !== null || searchQuery.trim().length > 0;

  if (state.status === 'loading') {
    return <p>Wczytywanie aktywności…</p>;
  }
  if (state.status === 'error') {
    return <p className="error">{state.message}</p>;
  }

  if (state.activities.length === 0) {
    return <ConnectStravaCTA />;
  }

  return (
    <>
      <div className="activities-header">
        <h2>Ostatnie aktywności</h2>
        <a className="activities-reconnect" href={stravaOAuthStartUrl()}>
          Połącz ponownie ze Stravą
        </a>
      </div>

      {/* Sprint 10 A8 — sport chips + search input. Chips auto-collected
          z fetched data (sortowane po count desc). "Wszystkie" resetuje
          sport filter. Search po name (case-insensitive). */}
      <div className="activities-filters">
        <div className="activities-sport-chips">
          <button
            type="button"
            className={`activities-chip${sportFilter === null ? ' active' : ''}`}
            onClick={() => setSportFilter(null)}
          >
            Wszystkie
            <span className="activities-chip-count">{state.activities.length}</span>
          </button>
          {sortedSports.map((sport) => (
            <button
              key={sport}
              type="button"
              className={`activities-chip${sportFilter === sport ? ' active' : ''}`}
              onClick={() => setSportFilter(sportFilter === sport ? null : sport)}
            >
              {sportLabel(sport)}
              <span className="activities-chip-count">{sportCounts.get(sport)}</span>
            </button>
          ))}
        </div>
        <div className="activities-search-row">
          <input
            type="search"
            className="activities-search-input"
            placeholder="Szukaj po nazwie…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            aria-label="Szukaj aktywności po nazwie"
          />
          {hasActiveFilter && (
            <button
              type="button"
              className="activities-reset"
              onClick={() => {
                setSportFilter(null);
                setSearchQuery('');
              }}
            >
              Wyczyść
            </button>
          )}
        </div>
        {hasActiveFilter && (
          <p className="activities-result-count">
            {filtered.length === 0
              ? 'Brak wyników dla filtrów'
              : filtered.length === 1
                ? 'Znaleziono 1 aktywność'
                : `Znaleziono ${filtered.length} aktywności`}
          </p>
        )}
      </div>

      {filtered.length === 0 && hasActiveFilter ? (
        <p className="placeholder-text">
          Spróbuj innego filtra albo wyczyść zapytanie.
        </p>
      ) : (
        <div className="activity-list">
          {filtered.map((a) => (
            <ActivityRow key={a.strava_id} activity={a} />
          ))}
        </div>
      )}
    </>
  );
}

function ConnectStravaCTA() {
  return (
    <div className="strava-connect">
      <span className="strava-connect-icon" aria-hidden>
        🏃
      </span>
      <h2 className="strava-connect-title">Połącz konto Strava</h2>
      <p className="strava-connect-desc">
        Aktywności (biegi, jazdy, treningi) automatycznie pojawią się tutaj po każdym treningu.
        Bodysync prosi o dostęp do Twoich danych Strava — odpowiedz "Authorize" w pop-upie
        Stravy.
      </p>
      <a className="strava-connect-btn" href={stravaOAuthStartUrl()}>
        <span aria-hidden>⚡</span> Połącz ze Stravą
      </a>
      <p className="strava-connect-note">
        Klikając zostaniesz przekierowany na strava.com — po autoryzacji wracasz tutaj.
      </p>
    </div>
  );
}

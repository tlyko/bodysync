import { useEffect, useState } from 'react';
import { ApiError, getActivities, stravaOAuthStartUrl } from '../../api';
import type { Activity } from '../../types';
import { ActivityRow } from './ActivityRow';

type LoadState =
  | { status: 'loading' }
  | { status: 'ready'; activities: Activity[] }
  | { status: 'error'; message: string };

export function ActivitiesView() {
  const [state, setState] = useState<LoadState>({ status: 'loading' });

  useEffect(() => {
    let cancelled = false;
    getActivities(20)
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
      <div className="activity-list">
        {state.activities.map((a) => (
          <ActivityRow key={a.strava_id} activity={a} />
        ))}
      </div>
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


import { useCallback, useEffect, useState } from 'react';
import { ApiError, getMe, postLogout } from './api';
import { LoginScreen } from './components/LoginScreen';
import { Dashboard } from './components/Dashboard';
import type { Me } from './types';

type AuthState =
  | { status: 'loading' }
  | { status: 'logged_out' }
  | { status: 'logged_in'; me: Me }
  | { status: 'error'; message: string };

export function App() {
  const [auth, setAuth] = useState<AuthState>({ status: 'loading' });

  const checkSession = useCallback(async () => {
    try {
      const me = await getMe();
      setAuth({ status: 'logged_in', me });
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 404)) {
        setAuth({ status: 'logged_out' });
      } else {
        setAuth({ status: 'error', message: e instanceof Error ? e.message : 'unknown' });
      }
    }
  }, []);

  useEffect(() => {
    checkSession();
  }, [checkSession]);

  const handleLogout = useCallback(async () => {
    try {
      await postLogout();
    } catch {
      // Nawet gdy backend zwróci 5xx — UI traktuje user jako wylogowanego.
      // Cookie HttpOnly nie da się wyczyścić z JS, ale przy następnym getMe()
      // dostaniemy 401 i tak. Tu nie blokujemy UX na backend errorze.
    }
    setAuth({ status: 'logged_out' });
  }, []);

  if (auth.status === 'loading') {
    return <div className="loading">Wczytywanie…</div>;
  }
  if (auth.status === 'error') {
    return <div className="error-screen">Błąd: {auth.message}</div>;
  }
  if (auth.status === 'logged_in') {
    return (
      <>
        {import.meta.env.VITE_PREVIEW_MODE === 'true' && <PreviewBanner />}
        <Dashboard me={auth.me} onLogout={handleLogout} />
      </>
    );
  }
  return (
    <>
      {import.meta.env.VITE_PREVIEW_MODE === 'true' && <PreviewBanner />}
      <LoginScreen onLoginSuccess={checkSession} />
    </>
  );
}

function PreviewBanner() {
  return (
    <div className="preview-banner" role="status" aria-label="Preview mode">
      🔧 Preview — dane są mock'owane, brak prawdziwego API
    </div>
  );
}

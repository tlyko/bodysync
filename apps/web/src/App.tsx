import { useCallback, useEffect, useState } from 'react';
import { ApiError, getMe } from './api';
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

  const handleLogout = useCallback(() => {
    // HttpOnly cookie nie da się usunąć z JS — `Set-Cookie` z Max-Age=0
    // przez backend (TODO: POST /api/auth/logout). Na razie naive: po
    // przeładowaniu strony cookie nadal działa. UX ostrzeżenie w komencie.
    setAuth({ status: 'logged_out' });
    // TODO: fetch POST /api/auth/logout który zwraca Set-Cookie z Max-Age=0
  }, []);

  if (auth.status === 'loading') {
    return <div className="loading">Wczytywanie…</div>;
  }
  if (auth.status === 'error') {
    return <div className="error-screen">Błąd: {auth.message}</div>;
  }
  if (auth.status === 'logged_in') {
    return <Dashboard me={auth.me} onLogout={handleLogout} />;
  }
  return <LoginScreen onLoginSuccess={checkSession} />;
}

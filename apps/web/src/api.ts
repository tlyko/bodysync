// Fetch wrapper z `credentials: 'include'` żeby cookie sesji
// (`bodysync_session` z Domain=.bodysync.pl) leciało z każdym requestem.

import { API_URL } from './config';
import type {
  ActivitiesResponse,
  ActivitySuggestionResponse,
  BiometryResponse,
  CalculateTDEERequest,
  CalculateTDEEResponse,
  ChatHistoryResponse,
  ChatMessageDTO,
  ChatRequest,
  LoginResponse,
  Me,
  PlanResponse,
  ProfileTargets,
  ProfileTargetsUpdate,
} from './types';

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

// Parse error body — backend zwraca JSON `{detail: "..."}` (FastAPI/Starlette)
// lub plain text. Spróbuj JSON, fallback do raw text.
function parseErrorMessage(body: string): string {
  try {
    const parsed = JSON.parse(body) as {
      detail?: string;
      error?: string | { reason?: string };
    };
    if (typeof parsed.error === 'string') return parsed.error;
    if (typeof parsed.error?.reason === 'string') return parsed.error.reason;
    if (typeof parsed.detail === 'string') return parsed.detail;
    return body;
  } catch {
    return body;
  }
}

async function request<T>(path: string, init?: RequestInit, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      signal,
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        ...(init?.headers ?? {}),
      },
    });
  } catch (e) {
    // AbortError leci tu (signal.abort()) — re-throw jako status 0, UI ignoruje.
    if (e instanceof DOMException && e.name === 'AbortError') {
      throw new ApiError(0, 'aborted');
    }
    // Network / CORS error — fetch rzuca `TypeError: Failed to fetch` gdy
    // browser blokuje response (DNS down, CORS mismatch, missing route
    // bez CORS headers w 404 response). Bez tego wrap'a `chatErrorMessage`
    // dostawał surowy TypeError → fallback "Nieoczekiwany błąd". Status -1
    // (poza HTTP range) żeby odróżnić od abort (0) i HTTP responses (2xx-5xx).
    throw new ApiError(-1, 'network');
  }
  if (!res.ok) {
    const body = await res.text();
    throw new ApiError(res.status, parseErrorMessage(body));
  }
  return (await res.json()) as T;
}

export async function getMe(): Promise<Me> {
  return request<Me>('/api/me');
}

export async function getBiometry(days = 7): Promise<BiometryResponse> {
  return request<BiometryResponse>(`/api/biometry?days=${days}`);
}

export async function loginWithGoogle(idToken: string): Promise<LoginResponse> {
  return request<LoginResponse>('/api/auth/google', {
    method: 'POST',
    body: JSON.stringify({ id_token: idToken }),
  });
}

export async function postAdvisorChat(
  req: ChatRequest,
  signal?: AbortSignal,
): Promise<ChatMessageDTO> {
  return request<ChatMessageDTO>(
    '/api/advisor/chat',
    {
      method: 'POST',
      body: JSON.stringify(req),
    },
    signal,
  );
}

export async function postLogout(): Promise<void> {
  await request<{ ok: true }>('/api/auth/logout', { method: 'POST' });
}

// Sprint 10 A1 — chat history GET dla frontend hydrate na mount.
// Backend zwraca wszystkie tury z dziś (24h DDB TTL). Refresh page nie traci
// kontekstu rozmowy w ramach dnia. `?date` opcjonalny override (default today).
export async function getChatHistory(date?: string): Promise<ChatHistoryResponse> {
  const qs = date ? `?date=${encodeURIComponent(date)}` : '';
  return request<ChatHistoryResponse>(`/api/advisor/chat/history${qs}`);
}

// "Wyczyść rozmowę" — hard wipe dzisiejszej chat history (boundary Warsaw).
// Po nim LLM widzi pusty `<conversation_history>` i nie kontynuuje poprzedniego
// wątku (np. ciasta z 3h temu). Idempotent: brak rows → 200 z `deleted: 0`.
export async function deleteChatHistory(): Promise<{ deleted: number; date: string }> {
  return request<{ deleted: number; date: string }>('/api/advisor/chat/history', {
    method: 'DELETE',
  });
}

export async function getProfileTargets(): Promise<ProfileTargets> {
  return request<ProfileTargets>('/api/profile/targets');
}

export async function putProfileTargets(t: ProfileTargetsUpdate): Promise<ProfileTargets> {
  return request<ProfileTargets>('/api/profile/targets', {
    method: 'PUT',
    body: JSON.stringify(t),
  });
}

// Sprint 10 A0 — TDEE calculator. Backend liczy BMR (Mifflin-St Jeor) + TDEE
// (× activity multiplier) + goal modifier + suggest macros. Body profile
// może być pominięty — backend czyta z PROFILE row jeśli zapisany.
export async function postCalculateTDEE(
  req: CalculateTDEERequest,
): Promise<CalculateTDEEResponse> {
  return request<CalculateTDEEResponse>('/api/profile/calculate-tdee', {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

// Sprint 10 A0.5 — LLM-driven activity level detection. Anthropic Haiku
// patrzy na ostatnie 7d Strava activities + biometry, ocenia poziom
// aktywności (sedentary/light/moderate/heavy/athlete) + zwraca polskie
// reasoning. Frontend pre-selectuje dropdown w wizardzie + pokazuje text.
export async function postSuggestActivityLevel(): Promise<ActivitySuggestionResponse> {
  return request<ActivitySuggestionResponse>('/api/profile/suggest-activity-level', {
    method: 'POST',
    body: JSON.stringify({}),
  });
}

export async function getActivities(limit = 20): Promise<ActivitiesResponse> {
  return request<ActivitiesResponse>(`/api/activities?limit=${limit}`);
}

// Sprint 5 — Google Sheets training plan. Backend cache 15min, frontend
// może `force=true` przekazać żeby wymusić fresh fetch (button "Odśwież").
export async function getPlan(force = false): Promise<PlanResponse> {
  return request<PlanResponse>(`/api/plan${force ? '?refresh=1' : ''}`);
}

// Strava OAuth start endpoint zwraca 302 do strava.com — frontend
// nawiguje przez `window.location.assign(stravaOAuthStartUrl())`.
// `credentials: include` dla JWT cookie potrzebny — zwracamy bezwarunkowy URL.
export function stravaOAuthStartUrl(): string {
  return `${API_URL}/api/strava/oauth/start`;
}

// PL message dla UI banner — mapuje status code na czytelny komunikat.
// Status 0 = aborted (component unmount), caller powinien ignorować.
// Status -1 = network / CORS / browser-blocked (np. preflight fail, DNS down).
export function chatErrorMessage(e: unknown): string {
  if (!(e instanceof ApiError)) {
    return 'Nieoczekiwany błąd';
  }
  if (e.status === 0) {
    return ''; // aborted — UI nie powinno tego pokazywać
  }
  if (e.status === -1) {
    return 'Brak połączenia z serwerem — spróbuj za chwilę.';
  }
  if (e.status === 429) {
    return 'Wykorzystałeś dzienny limit (30 wiadomości). Wróć jutro.';
  }
  if (e.status === 401) {
    return 'Sesja wygasła. Zaloguj się ponownie.';
  }
  if (e.status === 400) {
    return 'Wiadomość zawiera niedozwolone elementy lub jest pusta.';
  }
  if (e.status === 502) {
    return 'Problem z asystentem — spróbuj ponownie za chwilę.';
  }
  return e.message || 'Błąd serwera';
}

export { ApiError };

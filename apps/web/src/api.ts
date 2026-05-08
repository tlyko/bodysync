// Fetch wrapper z `credentials: 'include'` żeby cookie sesji
// (`bodysync_session` z Domain=.bodysync.pl) leciało z każdym requestem.

import { API_URL } from './config';
import type {
  BiometryResponse,
  ChatMessageDTO,
  ChatRequest,
  LoginResponse,
  Me,
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
    const parsed = JSON.parse(body) as { detail?: string; error?: { reason?: string } };
    return parsed.detail ?? parsed.error?.reason ?? body;
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
    throw e;
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

export async function getProfileTargets(): Promise<ProfileTargets> {
  return request<ProfileTargets>('/api/profile/targets');
}

export async function putProfileTargets(t: ProfileTargetsUpdate): Promise<ProfileTargets> {
  return request<ProfileTargets>('/api/profile/targets', {
    method: 'PUT',
    body: JSON.stringify(t),
  });
}

// PL message dla UI banner — mapuje status code na czytelny komunikat.
// Status 0 = aborted (component unmount), caller powinien ignorować.
export function chatErrorMessage(e: unknown): string {
  if (!(e instanceof ApiError)) {
    return 'Nieoczekiwany błąd';
  }
  if (e.status === 0) {
    return ''; // aborted — UI nie powinno tego pokazywać
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

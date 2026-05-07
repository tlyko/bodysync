// Fetch wrapper z `credentials: 'include'` żeby cookie sesji
// (`bodysync_session` z Domain=.bodysync.pl) leciało z każdym requestem.

import { API_URL } from './config';
import type { BiometryResponse, LoginResponse, Me } from './types';

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new ApiError(res.status, body);
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

export { ApiError };

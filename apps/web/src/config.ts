// Public config. VITE_* env vars są inject'owane przez Vite w build time.
// W Cloudflare project settings → Environment Variables → Production:
//   VITE_GOOGLE_CLIENT_ID = <client-id>.apps.googleusercontent.com

export const API_URL = (import.meta.env.VITE_API_URL as string) || 'https://api.bodysync.pl';

export const GOOGLE_CLIENT_ID = (import.meta.env.VITE_GOOGLE_CLIENT_ID as string) || '';

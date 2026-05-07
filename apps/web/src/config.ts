// Public config dla frontu. Wartości pojawiają się w bundle JS i HTML —
// nie sekrety, nie wstydzą się gita.
//
// Google OAuth client_id jest fundamentalnie publiczny (Google docs explicit
// — pojawia się w meta tagach każdej strony używającej GIS). Sekret to
// client_secret, którego my NIE używamy (popup flow opiera się tylko na
// client_id + audience verification po stronie Lambdy).
//
// Cloudflare Workers + Static Assets nie wspiera build env vars dla
// static-only Workers ("Variables cannot be added to a Worker that only
// has static assets"), więc hardkodujemy zamiast VITE_*.

export const API_URL = 'https://api.bodysync.pl';

export const GOOGLE_CLIENT_ID =
  '759389324366-0knvtb3itkqhli45ahlan9hldtjbjo60.apps.googleusercontent.com';

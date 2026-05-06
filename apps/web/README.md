# @bodysync/web

Frontend SPA dla bodysync.pl — React 19 + Vite 7 + TypeScript.

## Local dev

```bash
cd apps/web
npm install
npm run dev    # http://localhost:5173
```

## Build

```bash
npm run build       # → apps/web/dist
npm run preview     # preview produkcyjnego buildu
npm run typecheck   # tsc --noEmit
```

## Cloudflare (Workers + Static Assets)

Cloudflare promował "Pages" project do "Workers + Static Assets" — deploy odbywa się przez `npx wrangler deploy` / `npx wrangler versions upload`, więc potrzebujemy `wrangler.jsonc`. Plik leży w **root repo** (`/wrangler.jsonc`) — wrangler odpalany w cwd = root, ścieżka assets jest pełna (`./apps/web/dist`).

UI Cloudflare → Settings → Build (defaults wystarczą):

| Setting | Wartość |
|---|---|
| Root directory | `/` *(repo root)* |
| Build command | `cd apps/web && npm ci && npm run build` |
| Deploy command | *(default `npx wrangler deploy`)* |
| `NODE_VERSION` | `20` |

`wrangler.jsonc` w root mówi wranglerowi gdzie są assety i włącza SPA fallback (każde 404 → `index.html`). Jeśli nazwa projektu w CF jest inna niż `bodysync-web`, popraw `"name"` w `/wrangler.jsonc` na exact match — inaczej wrangler stworzy duplikat workera.

Branche: `main` → production (`bodysync.pl`), pozostałe → preview deployments (`npx wrangler versions upload`, Workers preview URL).

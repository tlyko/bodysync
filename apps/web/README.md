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

Cloudflare promował "Pages" project do "Workers + Static Assets" — deploy odbywa się przez `npx wrangler deploy`, więc potrzebujemy `wrangler.jsonc` (jest obok).

UI Cloudflare → Settings → Build:

| Setting | Wartość |
|---|---|
| Root directory | `apps/web` |
| Build command | `npm ci && npm run build` |
| Deploy command | `npx wrangler deploy` *(default — można zostawić puste)* |
| `NODE_VERSION` | `20` |

`wrangler.jsonc` mówi wranglerowi gdzie są assety (`./dist`) i włącza SPA fallback (każde 404 → `index.html`). Jeśli nazwa projektu w CF jest inna niż `bodysync-web`, popraw `"name"` w `wrangler.jsonc` na exact match — inaczej wrangler stworzy duplikat.

Branche: `main` → production (`bodysync.pl`), pozostałe → preview deployments (Workers preview URL).

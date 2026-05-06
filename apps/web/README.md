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

## Cloudflare Pages

Build settings (ustawione w UI Cloudflare):

| Setting | Wartość |
|---|---|
| Framework preset | Vite |
| Build command | `cd apps/web && npm ci && npm run build` |
| Build output | `apps/web/dist` |
| Root directory | `/` (repo root) |
| `NODE_VERSION` | `20` |

Branche: `main` → production (`bodysync.pl`), pozostałe → preview deployments.

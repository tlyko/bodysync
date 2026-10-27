# @bodysync/web

Frontend SPA for bodysync.pl: React 19 + Vite 7 + TypeScript.

## Local dev

```bash
cd apps/web
npm install
npm run dev    # http://localhost:5173
```

## Build

```bash
npm run build       # → apps/web/dist
npm run preview     # preview the production build
npm run typecheck   # tsc --noEmit
```

## Cloudflare (Workers + Static Assets)

Cloudflare promoted the "Pages" project to "Workers + Static Assets". Deploys run through `npx wrangler deploy` / `npx wrangler versions upload`, so we need a `wrangler.jsonc`. The file lives in the **repo root** (`/wrangler.jsonc`): wrangler runs with cwd = root, and the assets path is spelled out in full (`./apps/web/dist`).

Cloudflare UI → Settings → Build (defaults are enough):

| Setting | Value |
|---|---|
| Root directory | `/` *(repo root)* |
| Build command | `cd apps/web && npm ci && npm run build` |
| Deploy command | *(default `npx wrangler deploy`)* |
| `NODE_VERSION` | `20` |

`wrangler.jsonc` in the root tells wrangler where the assets are and enables the SPA fallback (every 404 → `index.html`). If the project name in Cloudflare differs from `bodysync-web`, change `"name"` in `/wrangler.jsonc` to an exact match, otherwise wrangler creates a duplicate worker.

Branches: `main` → production (`bodysync.pl`), everything else → preview deployments (`npx wrangler versions upload`, Workers preview URL).

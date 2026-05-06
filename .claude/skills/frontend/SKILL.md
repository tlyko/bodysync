# Skill: Frontend Dashboard

## When to use
Building or modifying React components, pages, styling, or frontend API integration.

## Stack
- React 18+ with hooks (no class components)
- Vite for build/dev
- No Tailwind — custom CSS with design tokens (see below)
- Recharts or Chart.js for data visualization
- Google Sign-In library for auth

## Design tokens
```javascript
const C = {
  bg: "#0a0e17",
  surface: "#111827",
  card: "#1a2332",
  cardHover: "#1e2a3d",
  border: "#2a3548",
  text: "#e2e8f0",
  textMuted: "#8b9dc3",
  textDim: "#5a6f8e",
  accent: "#22d3ee",      // cyan — main accent
  green: "#10b981",        // weight, positive
  orange: "#f59e0b",       // calories, nutrition
  red: "#ef4444",          // heart rate, negative
  purple: "#a78bfa",       // recipes, AI
  pink: "#f472b6",         // fats
};
```

## Typography
- Numbers & headers: `'JetBrains Mono', monospace` — weight 700-800
- Body text: `'Inter', sans-serif` — weight 400-600
- Labels: uppercase, letter-spacing 1px, fontSize 12, color textMuted

## Component library
Build these reusable components:
- `StatCard` — icon + label + big number + unit + sparkline + trend arrow
- `NutritionDonut` — SVG donut chart (protein/carbs/fat) with kcal in center
- `WeightChart` — bar chart with gradient, 30 days, min/max labels
- `ActivityRow` — emoji icon + name + date/source + distance/time + kcal
- `SourceBadge` — integration status with colored dot (green/orange/red/gray)
- `RecipeCard` — name + description + pill badges (kcal, protein, tags)
- `TrainingView` — today's exercises from Google Sheets, with YT links
- `AiAdvisorCard` — daily recommendation, meal plan, chat input

## Layout
- Sidebar: 240px, fixed, dark surface, logo "SyncBody" + nav icons
- Main: flex 1, padding 32px, max-width 1200px
- Grid: `grid-template-columns: repeat(auto-fit, minmax(220px, 1fr))`
- Mobile: sidebar collapses to bottom nav, single column grid

## API integration
- Base URL from `import.meta.env.VITE_API_URL`
- Auth: Google Sign-In → POST /api/auth/google → JWT stored in memory (not localStorage)
- All API calls include `Authorization: Bearer {jwt}`
- Use custom `useApi` hook with loading/error states
- SWR or React Query for data fetching with auto-refresh

## Routing
Use React Router. Pages:
- `/` — Dashboard (stats grid + recent activities + macros + Garmin)
- `/activities` — Activity list
- `/body` — Weight progress + body composition
- `/nutrition` — Daily macros + donut
- `/training` — Today's workout from Google Sheets
- `/ai` — AI advisor recommendation + meal plan + chat
- `/recipes` — Semantic recipe search
- `/settings` — Profile, goals, preferences

## Reference
See `docs/health-dashboard-prototype.jsx` for the full prototype with demo data.

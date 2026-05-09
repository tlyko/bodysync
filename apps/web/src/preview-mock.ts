// Preview mock backend — instaluje window.fetch override dla `/api/*` żeby
// Cloudflare Workers branch deployments mogły pokazywać UI bez prawdziwego
// API/login. Aktywne TYLKO gdy `VITE_PREVIEW_MODE=true` podczas build
// (set w Cloudflare Workers Builds dashboard dla preview environment).
//
// Tree-shaking: ten plik jest dynamic-imported w main.tsx za env-flagiem,
// więc prod bundle nie zawiera mock code (Vite chunks osobno gdy env unset).
//
// Mock data jest deterministyczna (sin jitter z seed = i*0.4) żeby preview
// renderował konsystentny screenshot per branch — owner może porównywać
// wizualnie zmiany między branchami bez "live data noise".

import type { BiometryDay, PlanResponse } from './types';

const ME = { user_id: 'tomek', email: 'tomek@example.com', name: 'Tomek (preview)' };

const ACTIVITIES = {
  items: [
    {
      strava_id: 1,
      name: 'Morning Run',
      sport_type: 'Run',
      type: 'Run',
      distance_m: 5200,
      moving_time_s: 1620,
      elapsed_time_s: 1700,
      elevation_gain_m: 12,
      start_date: new Date(Date.now() - 1 * 86400_000).toISOString(),
      start_date_local: new Date(Date.now() - 1 * 86400_000).toISOString(),
      calories: 410,
      average_heartrate: 152,
      max_heartrate: 174,
    },
    {
      strava_id: 2,
      name: 'Trening A — siła',
      sport_type: 'WeightTraining',
      type: 'WeightTraining',
      distance_m: 0,
      moving_time_s: 3600,
      elapsed_time_s: 3700,
      elevation_gain_m: 0,
      start_date: new Date(Date.now() - 3 * 86400_000).toISOString(),
      start_date_local: new Date(Date.now() - 3 * 86400_000).toISOString(),
      calories: 280,
      average_heartrate: 124,
      max_heartrate: 168,
    },
    {
      strava_id: 3,
      name: 'Easy ride',
      sport_type: 'Ride',
      type: 'Ride',
      distance_m: 28000,
      moving_time_s: 4200,
      elapsed_time_s: 4500,
      elevation_gain_m: 145,
      start_date: new Date(Date.now() - 5 * 86400_000).toISOString(),
      start_date_local: new Date(Date.now() - 5 * 86400_000).toISOString(),
      calories: 720,
      average_heartrate: 138,
      max_heartrate: 165,
    },
    {
      strava_id: 4,
      name: 'Spacer z psem',
      sport_type: 'Walk',
      type: 'Walk',
      distance_m: 3800,
      moving_time_s: 2400,
      elapsed_time_s: 2400,
      elevation_gain_m: 8,
      start_date: new Date(Date.now() - 6 * 86400_000).toISOString(),
      start_date_local: new Date(Date.now() - 6 * 86400_000).toISOString(),
      calories: 180,
      average_heartrate: 96,
      max_heartrate: 112,
    },
  ],
};

const PROFILE_TARGETS = {
  kcal_target: 2400,
  protein_target_g: 160,
  fat_target_g: 80,
  carbs_target_g: 260,
  is_default: false,
};

const PLAN: PlanResponse = {
  rows: [
    ['Rozgrzewka', '', '', '', ''],
    ['Numer', 'Ćwiczenie', 'Serie x powt.', 'Ciężar (Anita)', 'Notatki'],
    ['01', 'Hip opener', '1-2s x 5p/', '—', 'powoli'],
    ['02', 'Wall sit', '2-3s x 45-60s', 'BW', 'RPE6'],
    ['', '', '', '', ''],
    ['Trening A', 'Ćwiczenie', 'Serie x powt.', 'Ciężar (Anita)', 'Notatki'],
    ['01', 'Squat', '5x5', '60kg', 'tempo 3-1-1-1'],
    ['02', 'Bench press', '4x8', '40kg', 'kontrola'],
    ['03', 'Pull-ups', '3xAMRAP', 'BW', 'do failure'],
  ],
  fetched_at: Math.floor(Date.now() / 1000) - 600, // 10min ago
  fresh: false,
  sheet_tab: 'Arkusz5',
};

function fakeBiometryDays(): BiometryDay[] {
  const days: BiometryDay[] = [];
  const now = new Date();
  for (let i = 29; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(now.getDate() - i);
    const iso = d.toISOString().slice(0, 10);
    const jitter = (seed: number, base: number, amp: number) =>
      base + Math.sin(seed + i * 0.4) * amp;
    days.push({
      date: iso,
      metrics: {
        kcal_active: { kcal: Math.round(jitter(1, 520, 90)) },
        kcal_in: { kcal: Math.round(jitter(2, 1850, 160)) },
        protein: { g: Math.round(jitter(3, 125, 18)) },
        fat: { g: Math.round(jitter(4, 68, 10)) },
        carbs: { g: Math.round(jitter(5, 195, 30)) },
        steps: { count: Math.round(jitter(6, 8400, 2200)) },
        weight: { kg: parseFloat(jitter(7, 78.4, 0.6).toFixed(1)) },
        hrv: { value_ms: parseFloat(jitter(8, 56, 6).toFixed(1)) },
        sleep: { asleep: parseFloat(jitter(9, 7.4, 0.7).toFixed(1)) },
        resting_hr: { bpm: Math.round(jitter(10, 58, 3)) },
        body_fat: { pct: parseFloat(jitter(11, 18.6, 0.4).toFixed(1)) },
      },
    });
  }
  return days;
}

const today = new Date().toISOString().slice(0, 10);

const ADVISOR_REPLY = {
  reply:
    '🔧 **Preview mode** — to jest mockowana odpowiedź advisora.\n\n' +
    'W produkcji tu byłaby prawdziwa odpowiedź Haiku 4.5 z RAG context (139 przepisów Lidla/Biedronki).',
  used_recipes: [],
  conv_date: today,
  turn_idx: 0,
};

export function installPreviewMock(): void {
  const realFetch = window.fetch.bind(window);

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === 'string' ? input : (input instanceof URL ? input.toString() : input.url);

    // Tylko /api/* perekrójone — assets, source maps, GIS scripts → real fetch
    if (!url.includes('/api/')) {
      return realFetch(input, init);
    }

    const json = (data: unknown, status = 200) =>
      new Response(JSON.stringify(data), {
        status,
        headers: { 'content-type': 'application/json' },
      });

    if (url.includes('/api/me')) return json(ME);
    if (url.includes('/api/biometry')) return json({ days: fakeBiometryDays() });
    if (url.includes('/api/activities')) return json(ACTIVITIES);
    if (url.includes('/api/profile/targets')) {
      if (init?.method === 'PUT') {
        const body = JSON.parse((init.body as string) ?? '{}');
        return json({ ...body, is_default: false });
      }
      return json(PROFILE_TARGETS);
    }
    if (url.includes('/api/advisor/chat')) {
      // Symuluj 800ms latency dla realistycznego loading state w UI
      await new Promise((resolve) => setTimeout(resolve, 800));
      return json(ADVISOR_REPLY);
    }
    if (url.includes('/api/auth/logout')) return json({ ok: true });
    if (url.includes('/api/plan')) return json(PLAN);

    return new Response('{}', { status: 404 });
  };

  // Visual indicator że ten branch jest preview-mock'd
  document.title = 'bodysync · preview';
  console.info(
    '[bodysync] preview mock mode active — /api/* requests intercepted with fake data',
  );
}

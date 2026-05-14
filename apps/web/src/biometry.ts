// Helpers do transformacji `BiometryResponse.days` na time series per metryk
// + aggregation/trend dla StatCardów. Surowe DDB rows mają mixed shape
// (single value vs array of windowed measurements jak HRV/HR), więc każdy
// metryk ma własną strategię ekstrakcji liczby z `BiometryValue`.

import type { BiometryDay, BiometryValue } from './types';

export type SeriesPoint = {
  date: string; // YYYY-MM-DD
  value: number;
};

// Per-metric extractor. Zwraca null jeśli wartości brak / nieoczekiwany shape.
type Extractor = (raw: BiometryValue | BiometryValue[]) => number | null;

const avgFromArray = (arr: BiometryValue[], field: string): number | null => {
  const values = arr
    .map((p) => p[field])
    .filter((v): v is number => typeof v === 'number');
  if (values.length === 0) return null;
  return values.reduce((a, b) => a + b, 0) / values.length;
};

const singleNumber = (raw: BiometryValue | BiometryValue[], field: string): number | null => {
  if (Array.isArray(raw)) {
    // Niespodziewane (typed jako single) — fallback na pierwszy entry.
    if (raw.length === 0) return null;
    const v = raw[0][field];
    return typeof v === 'number' ? v : null;
  }
  const v = raw[field];
  return typeof v === 'number' ? v : null;
};

const EXTRACTORS: Record<string, Extractor> = {
  hrv: (raw) => (Array.isArray(raw) ? avgFromArray(raw, 'value_ms') : singleNumber(raw, 'value_ms')),
  hr: (raw) => (Array.isArray(raw) ? avgFromArray(raw, 'avg_bpm') : singleNumber(raw, 'avg_bpm')),
  sleep: (raw) => singleNumber(raw, 'asleep'),
  steps: (raw) => singleNumber(raw, 'count'),
  weight: (raw) => singleNumber(raw, 'kg'),
  body_fat: (raw) => singleNumber(raw, 'pct'),
  resting_hr: (raw) => singleNumber(raw, 'bpm'),
  kcal_active: (raw) => singleNumber(raw, 'kcal'),
  kcal_basal: (raw) => singleNumber(raw, 'kcal'),
  kcal_in: (raw) => singleNumber(raw, 'kcal'),
  protein: (raw) => singleNumber(raw, 'g'),
  fat: (raw) => singleNumber(raw, 'g'),
  carbs: (raw) => singleNumber(raw, 'g'),
  // Sprint 12 — manual body tape measurements (cm). Każdy obwód ma DDB
  // attr `cm` (mirror `weight.kg`). Source `manual` (vs HAE), zapisywane
  // przez POST /api/measurements pod SK BIOMETRY#date#metric#manual.
  waist: (raw) => singleNumber(raw, 'cm'),
  hips: (raw) => singleNumber(raw, 'cm'),
  chest: (raw) => singleNumber(raw, 'cm'),
  biceps: (raw) => singleNumber(raw, 'cm'),
  thigh: (raw) => singleNumber(raw, 'cm'),
};

// Buduje listę {date, value} dla danego metrica. Pomija dni bez metryki
// (nie ma syntetycznych zer — empty days = brak punktu w sparkline).
// Sortowanie po date ascending dla stabilnej osi X.
export function buildSeries(days: BiometryDay[], metric: string): SeriesPoint[] {
  const extract = EXTRACTORS[metric];
  if (!extract) return [];

  const points: SeriesPoint[] = [];
  for (const d of days) {
    const raw = d.metrics[metric];
    if (raw === undefined) continue;
    const v = extract(raw);
    if (v === null || !Number.isFinite(v)) continue;
    points.push({ date: d.date, value: v });
  }
  points.sort((a, b) => a.date.localeCompare(b.date));
  return points;
}

// Last value w series (najnowszy point) lub null gdy pusta.
export function latestValue(series: SeriesPoint[]): SeriesPoint | null {
  if (series.length === 0) return null;
  return series[series.length - 1];
}

// Zwraca point dla konkretnej daty (YYYY-MM-DD), null gdy brak.
// Używane dla manualnych metryk (kcal_in, makro) gdzie chcemy pokazać
// "0 spożyte" jeśli user dziś nic nie wpisał, zamiast wartości z wczoraj
// (która myli — wygląda jakby user wpisał kcal_in i są takie samo).
export function valueForDate(series: SeriesPoint[], dateIso: string): SeriesPoint | null {
  return series.find((p) => p.date === dateIso) ?? null;
}

// Sumuje 2 series po dacie. Dla każdego dnia gdzie KTÓRYŚ z metryków
// istnieje (czyli union dat), zwraca punkt z sumą (brakujący traktowany
// jako 0). Używane dla "Spalone kalorie" = kcal_active + kcal_basal
// (Garmin/Apple total daily energy expenditure).
export function sumSeries(a: SeriesPoint[], b: SeriesPoint[]): SeriesPoint[] {
  const aMap = new Map(a.map((p) => [p.date, p.value]));
  const bMap = new Map(b.map((p) => [p.date, p.value]));
  const allDates = [...new Set([...aMap.keys(), ...bMap.keys()])].sort();
  return allDates.map((date) => ({
    date,
    value: (aMap.get(date) ?? 0) + (bMap.get(date) ?? 0),
  }));
}

// Sprint 10 A11 — sleep stages extractor.
// HAE wysyła sleep z fields {asleep, inBed, core, rem, deep, awake, ...}.
// `singleNumber` w EXTRACTORS zwraca tylko `asleep` jako sumaryczny float.
// Tu wyciągamy strukturę 4 stages (deep/rem/core/awake) dla
// SleepStagesCard z horizontal stacked bar.
//
// Returns null gdy brak dnia / brak sleep / brak żadnego sub-stage.
// Stage values w godzinach (jak w DDB; HAE convertuje minuty→hours).
export type SleepStages = {
  asleep: number; // total asleep (suma 3 sub-stages w typowym payloadzie)
  inBed: number | null;
  deep: number;
  rem: number;
  core: number;
  awake: number;
  date: string; // YYYY-MM-DD którego dnia
};

export function extractLatestSleepStages(days: BiometryDay[]): SleepStages | null {
  if (days.length === 0) return null;
  // Iteruj po datach desc, znajdź pierwszy dzień z non-zero stages.
  const sorted = [...days].sort((a, b) => b.date.localeCompare(a.date));
  for (const day of sorted) {
    const raw = day.metrics.sleep;
    if (!raw || Array.isArray(raw)) continue;
    const deep = numberOr(raw.deep, 0);
    const rem = numberOr(raw.rem, 0);
    const core = numberOr(raw.core, 0);
    const awake = numberOr(raw.awake, 0);
    const sumStages = deep + rem + core;
    if (sumStages === 0) continue; // payload bez stages — skip
    const asleep = numberOr(raw.asleep, sumStages);
    return {
      asleep,
      inBed: typeof raw.inBed === 'number' ? raw.inBed : null,
      deep,
      rem,
      core,
      awake,
      date: day.date,
    };
  }
  return null;
}

function numberOr(value: number | string | null | undefined, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

// Sprint 10 A5 — exponential moving average dla "true weight" smoothing
// (MacroFactor-style). Eliminuje noise z hydratacji/sodu/glikogenu z raw
// daily weight (±0.5 kg dnia na dzień typowo). α=0.1 daje ~10-day half-life
// (waga 10 dni temu wciąż waży ~37% w EMA, 30 dni temu ~4%).
//
// EMA[0] = data[0]
// EMA[i] = α × data[i] + (1-α) × EMA[i-1]
export function weightEMA(points: SeriesPoint[], alpha = 0.1): SeriesPoint[] {
  if (alpha <= 0 || alpha > 1) {
    throw new Error(`alpha must be in (0, 1], got ${alpha}`);
  }
  if (points.length === 0) return [];
  const sorted = [...points].sort((a, b) => a.date.localeCompare(b.date));
  const out: SeriesPoint[] = [{ date: sorted[0].date, value: sorted[0].value }];
  for (let i = 1; i < sorted.length; i++) {
    const prev = out[i - 1].value;
    const smoothed = alpha * sorted[i].value + (1 - alpha) * prev;
    out.push({ date: sorted[i].date, value: smoothed });
  }
  return out;
}

// Tygodniowa zmiana wagi w kg na bazie EMA (zwraca null gdy <7 punktów).
// Liczone jako delta między najnowszym (idx -1) a punktem 7 dni wstecz
// (idx -8 dla daily granularity, lub punkt 0 gdy mamy <8 dni). Trend
// kierunkowy: dodatni = przyrost, ujemny = redukcja, ~0 = utrzymanie.
export function weeklyTrendKg(emaPoints: SeriesPoint[]): number | null {
  if (emaPoints.length < 7) return null;
  const last = emaPoints[emaPoints.length - 1].value;
  // 7 dni temu = idx -8 (przy 8+ punktach), albo idx 0 (przy 7 punktach,
  // gdzie last to idx 6 i "7 dni temu" wykracza poza dane → bierzemy first).
  const weekAgoIdx = Math.max(0, emaPoints.length - 8);
  const weekAgo = emaPoints[weekAgoIdx].value;
  return last - weekAgo;
}

// % zmiana avg ostatnie N vs poprzednie N.
// Zwraca null gdy brak danych w którymkolwiek oknie. Domyślnie 7d vs 7-14d ago.
export function trendPct(series: SeriesPoint[], windowDays = 7): number | null {
  if (series.length < windowDays * 2) return null;
  const recent = series.slice(-windowDays);
  const previous = series.slice(-windowDays * 2, -windowDays);
  if (recent.length === 0 || previous.length === 0) return null;

  const avg = (pts: SeriesPoint[]) =>
    pts.reduce((a, p) => a + p.value, 0) / pts.length;
  const prevAvg = avg(previous);
  if (prevAvg === 0) return null;
  return ((avg(recent) - prevAvg) / prevAvg) * 100;
}

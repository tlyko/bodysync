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

// Recovery Score — composite 0-100 z sleep duration + sleep quality + RHR delta.
// Owner zatwierdził koncepcję 2026-05-15 (PROJECT-STATUS active backlog).
// HRV celowo pominięte — Garmin Connect NIE wysyła HRV do Apple Health (PR #177
// drop HRV z UI). Apple Watch dostarcza, ale w MVP polegamy na danych co
// faktycznie spływają.
//
// Scoring (0-100, additive):
//
// Sleep duration (40 pts max) — typowy zdrowy zakres 7-9h, ale recovery
// jest progressive. 7-9h pełne, krócej/dłużej skalowane liniowo:
//   ≥7 i ≤9        → 40
//   ≥6 i <7  OR  >9  i ≤10  → 30
//   ≥5 i <6  OR  >10 i ≤11  → 20
//   <5     OR   >11        → 10
//   brak danych            → 0 + score = null (BRAK DANYCH)
//
// Sleep quality (30 pts max) — (deep+rem)/asleep × 100%, typowe healthy
// 30-50% w zdrowym 7-9h śnie. Skala thresholdy:
//   ≥30 i ≤50  → 30
//   ≥25 i <30  OR  >50 i ≤55  → 20
//   ≥20 i <25  OR  >55 i ≤60  → 10
//   <20     OR   >60          → 5
//   brak stages → 0 (sleep total wystarczy do duration, ale quality wymaga deep+rem)
//
// RHR delta vs 14d baseline (30 pts max) — niższe RHR = lepiej, +bpm = stress.
// Baseline = average RHR z 14 dni przed today (exclusive today). Delta = today - baseline:
//   ≤-2     → 30 (znacznie niżej = świetna regeneracja)
//   >-2 i ≤+2 → 25 (stable = normal)
//   >+2 i ≤+5 → 15 (lekkie podwyższenie)
//   >+5 i ≤+10 → 5 (znaczny stres)
//   >+10    → 0 (silny stres, chyba choroba)
//   brak today RHR lub <3 days baseline → 0 (insufficient signal)
//
// Label:
//   ≥75 → ZREGENEROWANY (green)
//   50-74 → UMIARKOWANY (orange)
//   <50  → WYPOCZYNEK (red, "rest day suggested")
//   score === null → BRAK DANYCH

import { buildSeries, extractLatestSleepStages, sleepQualityPercent } from './biometry';
import type { BiometryDay } from './types';

export type RecoveryLabel =
  | 'ZREGENEROWANY'
  | 'UMIARKOWANY'
  | 'WYPOCZYNEK'
  | 'BRAK DANYCH';

export type RecoveryComponents = {
  sleepHours: number | null;
  sleepQualityPct: number | null;
  rhrDelta: number | null; // bpm difference (today - baseline)
  rhrBaseline: number | null;
};

export type RecoveryResult = {
  score: number | null;
  label: RecoveryLabel;
  components: RecoveryComponents;
};

const SLEEP_DURATION_OPTIMAL = { min: 7, max: 9, pts: 40 };
const SLEEP_DURATION_GOOD = { lo: [6, 7], hi: [9, 10], pts: 30 };
const SLEEP_DURATION_FAIR = { lo: [5, 6], hi: [10, 11], pts: 20 };
const SLEEP_DURATION_POOR_PTS = 10;

const SLEEP_QUALITY_OPTIMAL = { min: 30, max: 50, pts: 30 };
const SLEEP_QUALITY_GOOD = { lo: [25, 30], hi: [50, 55], pts: 20 };
const SLEEP_QUALITY_FAIR = { lo: [20, 25], hi: [55, 60], pts: 10 };
const SLEEP_QUALITY_POOR_PTS = 5;

const RHR_BASELINE_MIN_DAYS = 3;
const RHR_BASELINE_WINDOW = 14;

export function scoreSleepDuration(hours: number): number {
  if (hours >= SLEEP_DURATION_OPTIMAL.min && hours <= SLEEP_DURATION_OPTIMAL.max) {
    return SLEEP_DURATION_OPTIMAL.pts;
  }
  if (
    (hours >= SLEEP_DURATION_GOOD.lo[0] && hours < SLEEP_DURATION_GOOD.lo[1]) ||
    (hours > SLEEP_DURATION_GOOD.hi[0] && hours <= SLEEP_DURATION_GOOD.hi[1])
  ) {
    return SLEEP_DURATION_GOOD.pts;
  }
  if (
    (hours >= SLEEP_DURATION_FAIR.lo[0] && hours < SLEEP_DURATION_FAIR.lo[1]) ||
    (hours > SLEEP_DURATION_FAIR.hi[0] && hours <= SLEEP_DURATION_FAIR.hi[1])
  ) {
    return SLEEP_DURATION_FAIR.pts;
  }
  return SLEEP_DURATION_POOR_PTS;
}

export function scoreSleepQuality(percent: number): number {
  if (percent >= SLEEP_QUALITY_OPTIMAL.min && percent <= SLEEP_QUALITY_OPTIMAL.max) {
    return SLEEP_QUALITY_OPTIMAL.pts;
  }
  if (
    (percent >= SLEEP_QUALITY_GOOD.lo[0] && percent < SLEEP_QUALITY_GOOD.lo[1]) ||
    (percent > SLEEP_QUALITY_GOOD.hi[0] && percent <= SLEEP_QUALITY_GOOD.hi[1])
  ) {
    return SLEEP_QUALITY_GOOD.pts;
  }
  if (
    (percent >= SLEEP_QUALITY_FAIR.lo[0] && percent < SLEEP_QUALITY_FAIR.lo[1]) ||
    (percent > SLEEP_QUALITY_FAIR.hi[0] && percent <= SLEEP_QUALITY_FAIR.hi[1])
  ) {
    return SLEEP_QUALITY_FAIR.pts;
  }
  return SLEEP_QUALITY_POOR_PTS;
}

export function scoreRhrDelta(delta: number): number {
  if (delta <= -2) return 30;
  if (delta <= 2) return 25;
  if (delta <= 5) return 15;
  if (delta <= 10) return 5;
  return 0;
}

export function labelFor(score: number | null): RecoveryLabel {
  if (score === null) return 'BRAK DANYCH';
  if (score >= 75) return 'ZREGENEROWANY';
  if (score >= 50) return 'UMIARKOWANY';
  return 'WYPOCZYNEK';
}

// Average RHR z ostatnich N dni PRZED `todayIso` (exclusive today). Returns
// null gdy mniej niż RHR_BASELINE_MIN_DAYS punktów (insufficient signal —
// pojedyncze day baseline byłoby noise-dominated).
export function rhrBaseline(
  restingHrSeries: { date: string; value: number }[],
  todayIso: string,
  windowDays = RHR_BASELINE_WINDOW,
): number | null {
  const cutoff = new Date(todayIso);
  cutoff.setDate(cutoff.getDate() - windowDays);
  const cutoffIso = cutoff.toISOString().slice(0, 10);

  const window = restingHrSeries.filter(
    (p) => p.date >= cutoffIso && p.date < todayIso,
  );
  if (window.length < RHR_BASELINE_MIN_DAYS) return null;
  const sum = window.reduce((acc, p) => acc + p.value, 0);
  return sum / window.length;
}

export function calculateRecoveryScore(
  days: BiometryDay[],
  todayIso: string,
): RecoveryResult {
  const stages = extractLatestSleepStages(days);
  const restingHrSeries = buildSeries(days, 'resting_hr');

  // Sleep duration — `stages.asleep` w godzinach (per biometry.ts spec).
  const sleepHours = stages?.asleep ?? null;
  const sleepQuality = stages ? sleepQualityPercent(stages) : null;

  // Recovery score wymaga MINIMUM sleep duration danych. Bez tego =
  // BRAK DANYCH (score null).
  if (sleepHours === null || sleepHours <= 0) {
    return {
      score: null,
      label: 'BRAK DANYCH',
      components: {
        sleepHours: null,
        sleepQualityPct: null,
        rhrDelta: null,
        rhrBaseline: null,
      },
    };
  }

  let total = scoreSleepDuration(sleepHours);
  if (sleepQuality !== null) total += scoreSleepQuality(sleepQuality);

  // RHR — find today's value (lub najnowszy w stages.date jeśli today brak).
  const stagesDate = stages?.date ?? todayIso;
  const todayRhr = restingHrSeries.find((p) => p.date === stagesDate)?.value ?? null;
  const baseline = rhrBaseline(restingHrSeries, stagesDate);
  let rhrDelta: number | null = null;
  if (todayRhr !== null && baseline !== null) {
    rhrDelta = todayRhr - baseline;
    total += scoreRhrDelta(rhrDelta);
  }

  // Clamp do 0-100 (theoretical max = 100, ale dla bezpieczeństwa).
  const score = Math.max(0, Math.min(100, Math.round(total)));

  return {
    score,
    label: labelFor(score),
    components: {
      sleepHours,
      sleepQualityPct: sleepQuality,
      rhrDelta,
      rhrBaseline: baseline,
    },
  };
}

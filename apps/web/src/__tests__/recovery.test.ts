import { describe, expect, test } from 'vitest';
import {
  calculateRecoveryScore,
  labelFor,
  rhrBaseline,
  scoreRhrDelta,
  scoreSleepDuration,
  scoreSleepQuality,
} from '../recovery';
import type { BiometryDay } from '../types';

function day(date: string, metrics: BiometryDay['metrics']): BiometryDay {
  return { date, metrics };
}

// ─── Składowe scoring ─────────────────────────────────────────────────────

describe('scoreSleepDuration', () => {
  test('7-9h → 40 pts (optimal)', () => {
    expect(scoreSleepDuration(7)).toBe(40);
    expect(scoreSleepDuration(8)).toBe(40);
    expect(scoreSleepDuration(9)).toBe(40);
  });

  test('6-7h or 9-10h → 30 pts', () => {
    expect(scoreSleepDuration(6)).toBe(30);
    expect(scoreSleepDuration(6.5)).toBe(30);
    expect(scoreSleepDuration(9.5)).toBe(30);
  });

  test('5-6h or 10-11h → 20 pts', () => {
    expect(scoreSleepDuration(5)).toBe(20);
    expect(scoreSleepDuration(5.5)).toBe(20);
    expect(scoreSleepDuration(10.5)).toBe(20);
  });

  test('<5h or >11h → 10 pts', () => {
    expect(scoreSleepDuration(4)).toBe(10);
    expect(scoreSleepDuration(12)).toBe(10);
  });
});

describe('scoreSleepQuality', () => {
  test('30-50% (deep+rem) → 30 pts', () => {
    expect(scoreSleepQuality(30)).toBe(30);
    expect(scoreSleepQuality(40)).toBe(30);
    expect(scoreSleepQuality(50)).toBe(30);
  });

  test('25-30% or 50-55% → 20 pts', () => {
    expect(scoreSleepQuality(27)).toBe(20);
    expect(scoreSleepQuality(53)).toBe(20);
  });

  test('20-25% or 55-60% → 10 pts', () => {
    expect(scoreSleepQuality(22)).toBe(10);
    expect(scoreSleepQuality(58)).toBe(10);
  });

  test('<20% or >60% → 5 pts', () => {
    expect(scoreSleepQuality(15)).toBe(5);
    expect(scoreSleepQuality(65)).toBe(5);
  });
});

describe('scoreRhrDelta', () => {
  test('≤-2 bpm (lower than baseline) → 30 pts', () => {
    expect(scoreRhrDelta(-2)).toBe(30);
    expect(scoreRhrDelta(-5)).toBe(30);
  });

  test('-2 < delta ≤ +2 → 25 pts (stable)', () => {
    expect(scoreRhrDelta(-1)).toBe(25);
    expect(scoreRhrDelta(0)).toBe(25);
    expect(scoreRhrDelta(2)).toBe(25);
  });

  test('+2 < delta ≤ +5 → 15 pts', () => {
    expect(scoreRhrDelta(3)).toBe(15);
    expect(scoreRhrDelta(5)).toBe(15);
  });

  test('+5 < delta ≤ +10 → 5 pts', () => {
    expect(scoreRhrDelta(6)).toBe(5);
    expect(scoreRhrDelta(10)).toBe(5);
  });

  test('>+10 → 0 pts (severe stress)', () => {
    expect(scoreRhrDelta(11)).toBe(0);
    expect(scoreRhrDelta(20)).toBe(0);
  });
});

describe('labelFor', () => {
  test('≥75 → ZREGENEROWANY', () => {
    expect(labelFor(75)).toBe('ZREGENEROWANY');
    expect(labelFor(95)).toBe('ZREGENEROWANY');
  });

  test('50-74 → UMIARKOWANY', () => {
    expect(labelFor(50)).toBe('UMIARKOWANY');
    expect(labelFor(74)).toBe('UMIARKOWANY');
  });

  test('<50 → WYPOCZYNEK', () => {
    expect(labelFor(0)).toBe('WYPOCZYNEK');
    expect(labelFor(49)).toBe('WYPOCZYNEK');
  });

  test('null → BRAK DANYCH', () => {
    expect(labelFor(null)).toBe('BRAK DANYCH');
  });
});

// ─── rhrBaseline ──────────────────────────────────────────────────────────

describe('rhrBaseline', () => {
  test('14-day average excluding today', () => {
    const series = [
      { date: '2026-05-01', value: 60 },
      { date: '2026-05-02', value: 62 },
      { date: '2026-05-03', value: 58 },
      { date: '2026-05-04', value: 64 }, // today
    ];
    // baseline = (60+62+58)/3 = 60
    expect(rhrBaseline(series, '2026-05-04')).toBeCloseTo(60);
  });

  test('<3 days w window → null (insufficient signal)', () => {
    const series = [
      { date: '2026-05-01', value: 60 },
      { date: '2026-05-02', value: 62 },
      { date: '2026-05-03', value: 64 }, // today
    ];
    // Tylko 2 dni przed today (01+02) → null.
    expect(rhrBaseline(series, '2026-05-03')).toBeNull();
  });

  test('today entry NIE wchodzi do baseline', () => {
    const series = [
      { date: '2026-05-01', value: 60 },
      { date: '2026-05-02', value: 60 },
      { date: '2026-05-03', value: 60 },
      { date: '2026-05-04', value: 100 }, // today — IGNORED
    ];
    expect(rhrBaseline(series, '2026-05-04')).toBe(60);
  });
});

// ─── calculateRecoveryScore (E2E) ─────────────────────────────────────────

describe('calculateRecoveryScore', () => {
  test('perfect day: 8h sleep + 40% quality + RHR -3 = 100', () => {
    const days: BiometryDay[] = [
      // 5 days RHR baseline @ 60 bpm
      day('2026-05-01', { resting_hr: { bpm: 60 } }),
      day('2026-05-02', { resting_hr: { bpm: 60 } }),
      day('2026-05-03', { resting_hr: { bpm: 60 } }),
      day('2026-05-04', { resting_hr: { bpm: 60 } }),
      day('2026-05-05', { resting_hr: { bpm: 60 } }),
      // today: 8h sleep, 40% quality (deep+rem=3.2h / 8h), RHR=57 (delta=-3)
      day('2026-05-06', {
        sleep: { asleep: 8, inBed: 8.5, deep: 1.6, rem: 1.6, core: 4.8, awake: 0.5 },
        resting_hr: { bpm: 57 },
      }),
    ];
    const result = calculateRecoveryScore(days, '2026-05-06');
    expect(result.score).toBe(100);
    expect(result.label).toBe('ZREGENEROWANY');
    expect(result.components.sleepHours).toBe(8);
    expect(result.components.sleepQualityPct).toBeCloseTo(40);
    expect(result.components.rhrDelta).toBe(-3);
    expect(result.components.rhrBaseline).toBe(60);
  });

  test('poor day: 4h sleep + 15% quality + RHR +12 = 25 (WYPOCZYNEK)', () => {
    const days: BiometryDay[] = [
      day('2026-05-01', { resting_hr: { bpm: 55 } }),
      day('2026-05-02', { resting_hr: { bpm: 55 } }),
      day('2026-05-03', { resting_hr: { bpm: 55 } }),
      day('2026-05-04', {
        sleep: {
          asleep: 4,
          inBed: 5,
          deep: 0.3,
          rem: 0.3,
          core: 3.4,
          awake: 1,
        },
        resting_hr: { bpm: 67 }, // delta +12
      }),
    ];
    const result = calculateRecoveryScore(days, '2026-05-04');
    // sleep 4h → 10 pts, quality (0.3+0.3)/4=15% → 5 pts, RHR +12 → 0 pts.
    expect(result.score).toBe(15);
    expect(result.label).toBe('WYPOCZYNEK');
  });

  test('moderate day: 6.5h sleep + 28% quality + stable RHR = 70 (UMIARKOWANY)', () => {
    const days: BiometryDay[] = [
      day('2026-05-01', { resting_hr: { bpm: 60 } }),
      day('2026-05-02', { resting_hr: { bpm: 60 } }),
      day('2026-05-03', { resting_hr: { bpm: 60 } }),
      day('2026-05-04', {
        sleep: { asleep: 6.5, inBed: 7, deep: 0.9, rem: 0.92, core: 4.68, awake: 0.5 },
        resting_hr: { bpm: 61 }, // delta +1 → 25 pts
      }),
    ];
    const result = calculateRecoveryScore(days, '2026-05-04');
    // sleep 6.5 → 30, quality (0.9+0.92)/6.5≈28% → 20, RHR +1 → 25. Total 75.
    expect(result.score).toBe(75);
    expect(result.label).toBe('ZREGENEROWANY');
  });

  test('brak sleep data → score null + BRAK DANYCH', () => {
    const days: BiometryDay[] = [
      day('2026-05-04', { resting_hr: { bpm: 60 } }),
    ];
    const result = calculateRecoveryScore(days, '2026-05-04');
    expect(result.score).toBeNull();
    expect(result.label).toBe('BRAK DANYCH');
    expect(result.components.sleepHours).toBeNull();
  });

  test('sleep tylko bez stages → sleep duration tylko, brak quality + RHR pts', () => {
    // Bez deep+rem mamy duration ale nie quality. RHR też brak baseline.
    const days: BiometryDay[] = [
      day('2026-05-04', {
        sleep: { asleep: 8, deep: 0, rem: 0, core: 0 },
      }),
    ];
    const result = calculateRecoveryScore(days, '2026-05-04');
    // extractLatestSleepStages skip'uje gdy sumStages=0 → caller widzi brak sleep stages.
    expect(result.score).toBeNull();
    expect(result.label).toBe('BRAK DANYCH');
  });

  test('sleep stages OK ale brak RHR baseline (<3 days) → score bez RHR component', () => {
    const days: BiometryDay[] = [
      day('2026-05-03', { resting_hr: { bpm: 60 } }),
      // dziś: 8h sleep + 40% quality. RHR baseline tylko 1 dzień → null.
      day('2026-05-04', {
        sleep: { asleep: 8, inBed: 8.5, deep: 1.6, rem: 1.6, core: 4.8, awake: 0.5 },
        resting_hr: { bpm: 60 },
      }),
    ];
    const result = calculateRecoveryScore(days, '2026-05-04');
    // sleep 8h → 40, quality 40% → 30, RHR brak (baseline null) → 0. Total 70.
    expect(result.score).toBe(70);
    expect(result.label).toBe('UMIARKOWANY');
    expect(result.components.rhrDelta).toBeNull();
    expect(result.components.rhrBaseline).toBeNull();
  });
});

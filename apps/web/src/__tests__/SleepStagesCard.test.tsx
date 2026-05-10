import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import { extractLatestSleepStages } from '../biometry';
import { SleepStagesCard } from '../components/dashboard/SleepStagesCard';
import type { BiometryDay } from '../types';

describe('extractLatestSleepStages', () => {
  test('happy: zwraca stages z najnowszego dnia z danymi', () => {
    const days: BiometryDay[] = [
      {
        date: '2026-05-08',
        metrics: {
          sleep: { asleep: 7.5, inBed: 8.1, deep: 1.2, rem: 1.8, core: 4.5, awake: 0.6 },
        },
      },
      {
        date: '2026-05-09',
        metrics: {
          sleep: { asleep: 7.0, inBed: 7.5, deep: 1.0, rem: 1.5, core: 4.5, awake: 0.5 },
        },
      },
    ];
    const result = extractLatestSleepStages(days);
    expect(result).not.toBeNull();
    expect(result!.date).toBe('2026-05-09');
    expect(result!.deep).toBe(1.0);
    expect(result!.rem).toBe(1.5);
    expect(result!.core).toBe(4.5);
    expect(result!.awake).toBe(0.5);
    expect(result!.asleep).toBe(7.0);
  });

  test('null gdy brak żadnego dnia z sleep stages', () => {
    expect(extractLatestSleepStages([])).toBeNull();
    expect(
      extractLatestSleepStages([
        { date: '2026-05-09', metrics: { weight: { kg: 80 } } },
      ]),
    ).toBeNull();
  });

  test('skip dni gdzie sleep ma asleep ale brak sub-stages (Apple Watch off)', () => {
    const days: BiometryDay[] = [
      {
        date: '2026-05-08',
        metrics: {
          sleep: { asleep: 7.5, inBed: 8.1, deep: 1.2, rem: 1.8, core: 4.5, awake: 0.6 },
        },
      },
      {
        date: '2026-05-09', // newer ale no sub-stages — fallback do 05-08
        metrics: { sleep: { asleep: 7.0, inBed: 7.5 } },
      },
    ];
    const result = extractLatestSleepStages(days);
    expect(result).not.toBeNull();
    expect(result!.date).toBe('2026-05-08');
  });

  test('asleep fallback do sumy stages gdy brak top-level asleep', () => {
    const days: BiometryDay[] = [
      {
        date: '2026-05-09',
        metrics: { sleep: { deep: 1.0, rem: 1.5, core: 4.5, awake: 0.5 } },
      },
    ];
    const result = extractLatestSleepStages(days);
    expect(result!.asleep).toBe(7.0); // 1.0 + 1.5 + 4.5 = 7.0
  });
});

describe('SleepStagesCard', () => {
  test('null stages → empty state z hint', () => {
    render(<SleepStagesCard stages={null} />);
    expect(screen.getByText(/Brak danych o stadiach snu/)).toBeInTheDocument();
  });

  test('renderuje 4 segmenty + legendę z h:min', () => {
    const { container } = render(
      <SleepStagesCard
        stages={{
          asleep: 7.5,
          inBed: 8.1,
          deep: 1.2,
          rem: 1.8,
          core: 4.5,
          awake: 0.6,
          date: '2026-05-09',
        }}
      />,
    );
    // 4 segmenty bar (jeden per stage)
    const segments = container.querySelectorAll('.sleep-stages-segment');
    expect(segments.length).toBe(4);
    // Legenda — labele
    expect(screen.getByText('Głęboki')).toBeInTheDocument();
    expect(screen.getByText('REM')).toBeInTheDocument();
    expect(screen.getByText('Lekki')).toBeInTheDocument();
    expect(screen.getByText('Wybudzenia')).toBeInTheDocument();
    // h:min format dla 1.2h = 1h 12min
    expect(screen.getByText('1h 12min')).toBeInTheDocument();
    // 1.8h = 1h 48min
    expect(screen.getByText('1h 48min')).toBeInTheDocument();
    // 4.5h = 4h 30min
    expect(screen.getByText('4h 30min')).toBeInTheDocument();
    // 0.6h = 36min
    expect(screen.getByText('36min')).toBeInTheDocument();
  });

  test('skip segment gdy stage = 0 (np. brak awake)', () => {
    const { container } = render(
      <SleepStagesCard
        stages={{
          asleep: 7.5,
          inBed: 7.5,
          deep: 1.5,
          rem: 1.5,
          core: 4.5,
          awake: 0,
          date: '2026-05-09',
        }}
      />,
    );
    const segments = container.querySelectorAll('.sleep-stages-segment');
    expect(segments.length).toBe(3); // awake skipped
  });

  test('total label format "Xh Ymin snu"', () => {
    render(
      <SleepStagesCard
        stages={{
          asleep: 7.5,
          inBed: null,
          deep: 1.2,
          rem: 1.8,
          core: 4.5,
          awake: 0.6,
          date: '2026-05-09',
        }}
      />,
    );
    // 7.5h = 7h 30min
    expect(screen.getByText('7h 30min')).toBeInTheDocument();
  });
});

import { describe, expect, test } from 'vitest';
import { parseTrainings } from '../components/dashboard/planParser';

// Sample mirror real Arkusz5 layout od trenerki:
//   - R0: "Rozgrzewka" header (powyżej kolumn z "Numer")
//   - R1: header row z "Numer" / "Ćwiczenie" / "Link" / ... / "Ból"
//   - R2-R3: rozgrzewka data
//   - R4: empty
//   - R5: empty
//   - R6: "Trening A" label
//   - R7: header duplicate
//   - R8-R9: main training data

function blockHeader(): string[] {
  return [
    'Numer',
    'Ćwiczenie',
    'Link',
    'Serie x powt.',
    'Int.',
    'Tempo',
    'Ciężar (Anita)',
    'Ciężar x serie x powtórzenia x RIR',
    'Ból',
  ];
}

function dataRow(num: string, ex: string, link: string, sets: string): string[] {
  return [num, ex, link, sets, 'RPE6', 'powoli', '20kg', 'BW x 3 x 10', '0'];
}

function emptyRow(): string[] {
  return Array(9).fill('');
}

function trainingLabelRow(name: string): string[] {
  return [name, ...Array(8).fill('')];
}

describe('parseTrainings — single block z dwoma sekcjami (rozgrzewka + main)', () => {
  const rows = [
    ['Rozgrzewka', ...Array(8).fill('')],
    blockHeader(),
    dataRow('01', 'Hip opener', 'https://yt/abc', '1-2s x 5p/'),
    dataRow('02', 'Wall sit', 'https://yt/def', '2-3s x 45-60s'),
    emptyRow(),
    emptyRow(), // 2+ empty → section break
    trainingLabelRow('Trening A'),
    blockHeader(), // duplicate header
    dataRow('01', 'Squat', 'https://yt/ghi', '5x5'),
    dataRow('02', 'Bench', '', '4x8'),
  ];

  test('1 training, 2 sections (rozgrzewka + Trening A)', () => {
    const result = parseTrainings(rows);
    expect(result).toHaveLength(1);
    expect(result[0].name).toBe('Trening A');
    expect(result[0].sections).toHaveLength(2);
  });

  test('section labels detection (Rozgrzewka + Trening A)', () => {
    const result = parseTrainings(rows);
    const labels = result[0].sections.map((s) => s.label);
    expect(labels).toContain('Rozgrzewka');
    expect(labels).toContain('Trening A');
  });

  test('rozgrzewka section ma 2 ćwiczenia (Hip opener + Wall sit)', () => {
    const result = parseTrainings(rows);
    const rozgrzewka = result[0].sections.find((s) => s.label === 'Rozgrzewka');
    expect(rozgrzewka?.exercises).toHaveLength(2);
    const names = rozgrzewka!.exercises.map((e) => e.cells[1]);
    expect(names).toEqual(['Hip opener', 'Wall sit']);
  });

  test('Trening A section ma 2 ćwiczenia (Squat + Bench), bez Hip opener', () => {
    const result = parseTrainings(rows);
    const trening = result[0].sections.find((s) => s.label === 'Trening A');
    expect(trening?.exercises).toHaveLength(2);
    const names = trening!.exercises.map((e) => e.cells[1]);
    expect(names).toEqual(['Squat', 'Bench']);
  });

  test('drops Link + Ból columns w obu sekcjach', () => {
    const result = parseTrainings(rows);
    for (const s of result[0].sections) {
      expect(s.headers).not.toContain('Link');
      expect(s.headers).not.toContain('Ból');
    }
  });
});

describe('parseTrainings — multi-block (A + B side-by-side)', () => {
  const headerWithTwoBlocks = [
    ...blockHeader(),
    'Numer',
    'Ćwiczenie',
    'Link',
    'Serie x powt.',
    'Int.',
    'Tempo',
    'Ciężar (Anita)',
    'Ciężar x serie x powtórzenia x RIR',
    'Ból',
  ];
  const rows = [
    Array(18).fill(''),
    headerWithTwoBlocks,
    [...dataRow('01', 'Squat', '', '5x5'), ...dataRow('01', 'Pull-up', '', 'AMRAP')],
    [
      ...trainingLabelRow('Trening A').slice(0, 9),
      ...trainingLabelRow('Trening B').slice(0, 9),
    ],
    [...dataRow('02', 'Bench', '', '4x8'), ...dataRow('02', 'Rows', '', '3x10')],
  ];

  test('finds 2 blocks, names z label rows', () => {
    const result = parseTrainings(rows);
    expect(result).toHaveLength(2);
    expect(result[0].name).toBe('Trening A');
    expect(result[1].name).toBe('Trening B');
  });

  test('block A nie zawiera ćwiczeń z bloku B', () => {
    const result = parseTrainings(rows);
    const allACells = result[0].sections.flatMap((s) => s.exercises.flatMap((e) => e.cells));
    expect(allACells).toContain('Squat');
    expect(allACells).not.toContain('Pull-up');
    expect(allACells).not.toContain('Rows');
  });
});

describe('parseTrainings — disambiguation duplicate names', () => {
  // 2 bloki Trening A (poprzedni + bieżący tydzień) — owner: "tylko trening A.
  // jeden sprzed tygodnia drugi z tego". Tabs powinny mieć "Trening A #1" + "#2".
  const headerWithTwoBlocks = [...blockHeader(), ...blockHeader()];
  const rows = [
    headerWithTwoBlocks,
    [...trainingLabelRow('Trening A').slice(0, 9), ...trainingLabelRow('Trening A').slice(0, 9)],
    [...dataRow('01', 'Squat-old', '', '5x5'), ...dataRow('01', 'Squat-new', '', '5x5')],
  ];

  test('appenduje #1, #2 dla duplicate names', () => {
    const result = parseTrainings(rows);
    expect(result.map((t) => t.name)).toEqual(['Trening A #1', 'Trening A #2']);
  });

  test('NIE appenduje suffix gdy unique name', () => {
    const headerSingle = [...blockHeader(), ...blockHeader()];
    const rowsSingle = [
      headerSingle,
      [...trainingLabelRow('Trening A').slice(0, 9), ...trainingLabelRow('Trening B').slice(0, 9)],
      [...dataRow('01', 'Squat', '', '5x5'), ...dataRow('01', 'Pull-up', '', 'AMRAP')],
    ];
    const result = parseTrainings(rowsSingle);
    expect(result.map((t) => t.name)).toEqual(['Trening A', 'Trening B']);
  });
});

describe('parseTrainings — edge cases', () => {
  test('empty rows → []', () => {
    expect(parseTrainings([])).toEqual([]);
  });

  test('rows without "Numer" header → []', () => {
    expect(parseTrainings([['random', 'data']])).toEqual([]);
  });

  test('block z samym headerem (no data rows) → skipped', () => {
    const rows = [blockHeader()];
    expect(parseTrainings(rows)).toEqual([]);
  });

  test('skips "Trening X" / "Numer" / "Rozgrzewka" rows jako section boundaries', () => {
    const rows = [
      blockHeader(),
      trainingLabelRow('Trening A'),
      dataRow('01', 'Squat', '', '5x5'),
    ];
    const result = parseTrainings(rows);
    const allEx = result[0].sections.flatMap((s) => s.exercises);
    // Tylko Squat (Trening A label skipped, Numer skipped — none are real exercises)
    expect(allEx).toHaveLength(1);
    expect(allEx[0].number).toBe('01');
  });

  test('drops kolumna z all-empty values w block', () => {
    const rows = [
      [...blockHeader(), ''],
      [...dataRow('01', 'Squat', '', '5x5'), ''],
    ];
    const result = parseTrainings(rows);
    for (const s of result[0].sections) {
      expect(s.headers.filter((h) => h === '')).toHaveLength(0);
    }
  });
});

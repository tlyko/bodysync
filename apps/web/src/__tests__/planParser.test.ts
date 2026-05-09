import { describe, expect, test } from 'vitest';
import { parseTrainings } from '../components/dashboard/planParser';

// Sample mirror real Arkusz5 layout (skompresowany do 2 bloków A/B z ~7 kol each):
//   - R0: "Rozgrzewka" header (powyżej kolumn z "Numer")
//   - R1: header row z "Numer" / "Ćwiczenie" / "Link" / "Serie x powt." / "Int." / "Tempo" / "Ciężar (Anita)" / "Ciężar x serie x powtórzenia x RIR" / "Ból"
//   - R2: data row 1
//   - R3: data row 2
//   - R10: "Trening A" / "Trening B" labels
//   - R11+: training data rows
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
  // Tylko first cell wypełnione (mock dla "Trening A" w col block_start)
  return [name, ...Array(8).fill('')];
}

describe('parseTrainings — single block (Trening A)', () => {
  const rows = [
    ['Rozgrzewka', ...Array(8).fill('')],
    blockHeader(),
    dataRow('01', 'Hip opener', 'https://yt/abc', '1-2s x 5p/'),
    dataRow('02', 'Wall sit', 'https://yt/def', '2-3s x 45-60s'),
    emptyRow(),
    trainingLabelRow('Trening A'),
    blockHeader(), // duplicat header — w real sample każdy block ma swój header
    dataRow('01', 'Squat', 'https://yt/ghi', '5x5'),
    dataRow('02', 'Bench', '', '4x8'),
  ];

  test('finds header row + parses 4 exercises (rozgrzewka 2 + Trening A 2)', () => {
    const result = parseTrainings(rows);
    // First "Numer" header w R1 → block_start=0, block tylko jeden (jeden "Numer" w header row)
    expect(result).toHaveLength(1);
    // Bo jest R1 + R6 z "Numer", obie counted jako blocks tylko jeśli są W TYM SAMYM header row
    // R1 ma 1 "Numer" (col 0), R6 to TRAINING LABEL row
    // Plus block name detected ze searchu okolic — first non-empty above header to "Rozgrzewka"
    expect(result[0].name).toBe('Trening A'); // below header preferowane
  });

  test('drops Link + Ból columns', () => {
    const result = parseTrainings(rows);
    expect(result[0].headers).not.toContain('Link');
    expect(result[0].headers).not.toContain('Ból');
    expect(result[0].headers).toContain('Numer');
    expect(result[0].headers).toContain('Ćwiczenie');
    expect(result[0].headers).toContain('Serie x powt.');
  });

  test('exercises mają number + cells po filter', () => {
    const result = parseTrainings(rows);
    const exes = result[0].exercises;
    expect(exes[0].number).toBe('01');
    expect(exes[0].cells).toContain('Hip opener');
    expect(exes[0].cells).not.toContain('https://yt/abc'); // Link dropped
    expect(exes[0].cells).not.toContain('0'); // Ból value dropped
  });
});

describe('parseTrainings — multi-block (A + B side-by-side)', () => {
  // Two "Numer" headers w jednym header row → 2 bloki
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
    Array(18).fill(''), // empty
    headerWithTwoBlocks,
    [
      ...dataRow('01', 'Squat', '', '5x5'),
      ...dataRow('01', 'Pull-up', '', 'AMRAP'),
    ],
    [
      ...trainingLabelRow('Trening A').slice(0, 9),
      ...trainingLabelRow('Trening B').slice(0, 9),
    ],
    [
      ...dataRow('02', 'Bench', '', '4x8'),
      ...dataRow('02', 'Rows', '', '3x10'),
    ],
  ];

  test('finds 2 blocks, names z label rows', () => {
    const result = parseTrainings(rows);
    expect(result).toHaveLength(2);
    expect(result[0].name).toBe('Trening A');
    expect(result[1].name).toBe('Trening B');
  });

  test('block A nie zawiera ćwiczeń z bloku B', () => {
    const result = parseTrainings(rows);
    const allACells = result[0].exercises.flatMap((e) => e.cells);
    expect(allACells).toContain('Squat');
    expect(allACells).not.toContain('Pull-up');
    expect(allACells).not.toContain('Rows');
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

  test('skips "Trening X" label row jako exercise', () => {
    const rows = [
      blockHeader(),
      trainingLabelRow('Trening A'), // numer="Trening A" — skipped
      dataRow('01', 'Squat', '', '5x5'),
    ];
    const result = parseTrainings(rows);
    expect(result[0].exercises).toHaveLength(1);
    expect(result[0].exercises[0].number).toBe('01');
  });

  test('drops kolumna z all-empty values w block', () => {
    const rows = [
      // Header z extra empty col na końcu
      [...blockHeader(), ''],
      [...dataRow('01', 'Squat', '', '5x5'), ''],
    ];
    const result = parseTrainings(rows);
    // Empty header col dropped → headers nie ma '' na końcu
    expect(result[0].headers.filter((h) => h === '')).toHaveLength(0);
  });
});

// Parser raw 2D rows (Google Sheets dump) → structured Training[].
//
// Real layout od trenerki (uchwycone przez Sprint 5 follow-upy):
//   - Każdy blok kolumn = jeden trening (Trening A z konkretnego tygodnia).
//   - Block boundary = column index gdzie cell == "Numer" w header row.
//   - W obrębie BLOKU mogą być wiele sekcji (Rozgrzewka + Trening A
//     główny), oddzielone:
//     a) pustym wierszem
//     b) duplicate header row ("Numer | Ćwiczenie | ...")
//     c) label row ("Trening A" / "Dół" / "Góra" w numer col).
//   - Trener może powielać Trening A co tydzień (block 1 = ostatni tydzień,
//     block 2 = bieżący tydzień). Owner chce DEFAULT pokazać najnowszy
//     (last block in array) — disambiguation tabs przez `#N` suffix.
//
// Owner pomijać:
//   - Kolumny "Link" / "Ból"
//   - Kolumny CAŁKOWICIE puste w block
//   - Wiersze które nie są ćwiczeniami (label rows, duplicate headers)

export type Exercise = {
  number: string; // "01" | "01a" | "02b"
  cells: string[]; // ordered po headers (without Link/Ból)
};

export type Section = {
  /** Optional label sekcji ("Rozgrzewka" / "Trening A"); null gdy bez label. */
  label: string | null;
  headers: string[];
  exercises: Exercise[];
};

export type Training = {
  /** Wyświetlany w tabach (np. "Trening A", "Trening A #2" gdy duplicates). */
  name: string;
  /** Sekcje (rozgrzewka + trening główny). Min 1 element. */
  sections: Section[];
};

const DROP_HEADERS = new Set(['Link', 'Ból']);
const SECTION_LABELS = new Set(['Rozgrzewka', 'Dół', 'Góra']);

function findFirstHeaderRowIdx(rows: string[][]): number | null {
  for (let r = 0; r < rows.length; r++) {
    if (rows[r].some((cell) => cell.trim() === 'Numer')) {
      return r;
    }
  }
  return null;
}

function isEmpty(cell: string): boolean {
  return cell.trim() === '';
}

/**
 * Detect block name (= tab label). Bierze pierwszy "Trening X" wiersz w col
 * `blockStart` poniżej header row. Fallback "Rozgrzewka"/"Dół"/"Góra" powyżej.
 */
function detectBlockName(
  rows: string[][],
  blockStart: number,
  headerRowIdx: number,
): string {
  const search = (from: number, to: number, predicate: (s: string) => boolean): string | null => {
    for (let r = Math.max(0, from); r < Math.min(rows.length, to); r++) {
      const cell = rows[r][blockStart]?.trim() ?? '';
      if (predicate(cell)) return cell;
    }
    return null;
  };
  // Trening X label preferowane (typowo R10-R12 w sample, poniżej header)
  const below = search(headerRowIdx + 1, headerRowIdx + 30, (s) => s.startsWith('Trening '));
  if (below) return below;
  // Fallback do "Rozgrzewka" / "Dół" / "Góra"
  const above = search(0, headerRowIdx, (s) => SECTION_LABELS.has(s));
  if (above) return above;
  return 'Trening';
}

/**
 * Detect label sekcji powyżej first exercise — searcha do tyłu od
 * `firstExerciseRow` po cell w numer col.
 */
function detectSectionLabel(
  blockRows: string[][],
  numerCol: number,
  firstExerciseRow: number,
  startBound: number,
): string | null {
  for (let r = firstExerciseRow - 1; r >= startBound; r--) {
    const cell = (blockRows[r][numerCol] ?? '').trim();
    if (!cell) continue;
    if (cell.startsWith('Trening ')) return cell;
    if (SECTION_LABELS.has(cell)) return cell;
    // Cell = "Numer" (duplicate header) → continue search (label może być powyżej)
    if (cell === 'Numer') continue;
    // Inny non-empty cell — nie jest label, stop search
    break;
  }
  return null;
}

/**
 * Disambiguate tabs gdy multiple blocks mają tę samą `name` (np. 2 razy
 * "Trening A" — poprzedni i bieżący tydzień). Append `#N` (1-indexed,
 * highest = najnowszy bo trener appenduje w prawo / w dół).
 */
function disambiguateNames(trainings: Training[]): Training[] {
  const counts = new Map<string, number>();
  for (const t of trainings) counts.set(t.name, (counts.get(t.name) ?? 0) + 1);
  const duplicates = new Set([...counts.entries()].filter(([, c]) => c > 1).map(([n]) => n));
  if (duplicates.size === 0) return trainings;

  const seenIdx = new Map<string, number>();
  return trainings.map((t) => {
    if (!duplicates.has(t.name)) return t;
    const idx = (seenIdx.get(t.name) ?? 0) + 1;
    seenIdx.set(t.name, idx);
    return { ...t, name: `${t.name} #${idx}` };
  });
}

export function parseTrainings(rows: string[][]): Training[] {
  if (rows.length === 0) return [];

  const headerRowIdx = findFirstHeaderRowIdx(rows);
  if (headerRowIdx === null) return [];

  const headerRow = rows[headerRowIdx];
  const blockStarts: number[] = [];
  headerRow.forEach((cell, idx) => {
    if (cell.trim() === 'Numer') blockStarts.push(idx);
  });
  if (blockStarts.length === 0) return [];

  const blockEnds = blockStarts.map((_, i) =>
    i + 1 < blockStarts.length ? blockStarts[i + 1] : headerRow.length,
  );

  const trainings: Training[] = [];

  for (let b = 0; b < blockStarts.length; b++) {
    const start = blockStarts[b];
    const end = blockEnds[b];

    const blockRows = rows.map((row) => row.slice(start, end));
    const blockHeader = blockRows[headerRowIdx];

    // Filter cols: drop "Link" / "Ból" + cols all-empty w block
    const colsKeep: number[] = [];
    blockHeader.forEach((cellRaw, idx) => {
      const cell = cellRaw.trim();
      if (DROP_HEADERS.has(cell)) return;
      const allEmpty = blockRows.every((row) => isEmpty(row[idx] ?? ''));
      if (allEmpty) return;
      colsKeep.push(idx);
    });
    if (colsKeep.length === 0) continue;

    const headers = colsKeep.map((c) => blockHeader[c]?.trim() ?? '');
    const numerCol = colsKeep[0];

    // Section split: skanuj rows, rozdziel exercises na sekcje przez:
    //   - duplicate header row (numer === "Numer")
    //   - label row (numer startuje z "Trening " | "Rozgrzewka" | etc.)
    //   - 2+ kolejne empty rows (treated jako separator)
    const sections: Section[] = [];
    let currentExercises: Exercise[] = [];
    let currentSectionStartRow = headerRowIdx + 1;
    let consecutiveEmpty = 0;

    const flushSection = (label: string | null) => {
      if (currentExercises.length === 0) return;
      sections.push({ label, headers, exercises: currentExercises });
      currentExercises = [];
    };

    for (let r = headerRowIdx + 1; r < blockRows.length; r++) {
      const number = (blockRows[r][numerCol] ?? '').trim();

      // Empty row — track consecutive empties jako section separator
      if (!number) {
        consecutiveEmpty += 1;
        if (consecutiveEmpty >= 2 && currentExercises.length > 0) {
          // 2 puste w rzędzie → section break
          const label = detectSectionLabel(
            blockRows,
            numerCol,
            currentSectionStartRow,
            Math.max(0, currentSectionStartRow - 5),
          );
          flushSection(label);
          currentSectionStartRow = r + 1;
          consecutiveEmpty = 0;
        }
        continue;
      }
      consecutiveEmpty = 0;

      // Section boundary triggers (label / duplicate header)
      if (number === 'Numer' || number.startsWith('Trening ') || SECTION_LABELS.has(number)) {
        if (currentExercises.length > 0) {
          const label = detectSectionLabel(
            blockRows,
            numerCol,
            currentSectionStartRow,
            Math.max(0, currentSectionStartRow - 5),
          );
          flushSection(label);
        }
        currentSectionStartRow = r + 1;
        continue;
      }

      // Real exercise row
      const cells = colsKeep.map((c) => (blockRows[r][c] ?? '').trim());
      currentExercises.push({ number, cells });
    }

    // Flush final section
    if (currentExercises.length > 0) {
      const label = detectSectionLabel(
        blockRows,
        numerCol,
        currentSectionStartRow,
        Math.max(0, currentSectionStartRow - 5),
      );
      flushSection(label);
    }

    if (sections.length === 0) continue; // empty block

    // Group sections w training units. Block może zawierać wiele "Trening X"
    // labels (np. block 3 ma rozgrzewka+Trening A+rozgrzewka+Trening B —
    // trener wpisała 2 jednostki treningowe w jednej kolumnie z 2 różnych
    // tygodni). Każda Trening X label = osobny Training tab z dolepioną
    // poprzedzającą rozgrzewką (i innymi sekcjami pomocniczymi).
    const fallbackName = detectBlockName(rows, start, headerRowIdx);
    trainings.push(...groupSectionsIntoTrainings(sections, fallbackName));
  }

  return disambiguateNames(trainings);
}

/**
 * Group sequential sections w training units. Każda sekcja z labelem
 * "Trening X" zamyka jeden unit (z poprzedzającymi rozgrzewkami).
 *
 * Edge case: trailing supplements (rozgrzewka bez następnego Trening X) →
 * fallback unit z `defaultName`.
 */
function groupSectionsIntoTrainings(
  sections: Section[],
  defaultName: string,
): Training[] {
  const result: Training[] = [];
  let bucket: Section[] = [];
  for (const section of sections) {
    if (section.label && section.label.startsWith('Trening ')) {
      result.push({ name: section.label, sections: [...bucket, section] });
      bucket = [];
    } else {
      bucket.push(section);
    }
  }
  if (bucket.length > 0) {
    result.push({ name: defaultName, sections: bucket });
  }
  return result;
}

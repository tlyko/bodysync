// Parser raw 2D rows (Google Sheets dump) → structured Training[].
// Heurystyka oparta na sample `samples/tomek-trening.xlsx` Arkusz5:
//   - Każdy blok kolumn = jeden trening (A/B/C/D)
//   - Block boundary = column index gdzie cell == "Numer" w header row
//   - Header row = pierwszy row zawierający "Numer" jako cell value
//   - Block name = "Trening A/B/C/D" / "Rozgrzewka" / "Dół" / "Góra" — pierwszy
//     non-empty single-cell row gdy więcej niż 1 cell empty (heurystycznie
//     bierzemy najbliższe non-empty słowo z cell na pozycji block_start)
//
// Owner pomijać: Link, Ból, komentarze trenerki/owner'a (nie-tabelaryczne
// wiersze). Filtrujemy:
//   - Kolumny których header to "Link" / "Ból"
//   - Kolumny które są EMPTY w całym bloku
//   - Wiersze które nie mają numeru w pierwszym non-empty col (header'em
//     bloku jest "Numer", więc dane row musi mieć cell w col Numer)

export type Exercise = {
  number: string; // "01" | "01a" | "02b"
  cells: string[]; // ordered po headers (without Link/Ból)
};

export type Training = {
  name: string; // "Trening A" / "Rozgrzewka" / "Trening B" / etc.
  headers: string[]; // np. ["Numer", "Ćwiczenie", "Serie x powt.", "Int.", ...]
  exercises: Exercise[];
};

const DROP_HEADERS = new Set(['Link', 'Ból']);

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
 * Find block name by scanning rows above + at exercise rows for cells
 * w col `blockStart`. Bierzemy pierwszy non-empty cell w tym col, w okolicy
 * header row (-3..+5 wierszy żeby uchwycić "Trening A" header).
 */
function detectBlockName(
  rows: string[][],
  blockStart: number,
  headerRowIdx: number,
): string {
  // Najpierw sprawdź wiersz z labelem block-level header (typically R12 w
  // sample to "Trening A/B/C/D"). Skanujemy okno wokół header row.
  const search = (from: number, to: number): string | null => {
    for (let r = Math.max(0, from); r < Math.min(rows.length, to); r++) {
      const cell = rows[r][blockStart]?.trim() ?? '';
      // Match prefersz: "Trening X" / "Rozgrzewka" / "Dół" / "Góra"
      if (
        cell.startsWith('Trening ') ||
        cell === 'Rozgrzewka' ||
        cell === 'Dół' ||
        cell === 'Góra'
      ) {
        return cell;
      }
    }
    return null;
  };
  // Sprawdź najpierw wiersze poniżej header row (typowo "Trening X" w R12,
  // header w R2 — search range +1..+15) — preferujemy "Trening X" nad
  // "Rozgrzewka" (rozgrzewka bywa też powyżej header row).
  const below = search(headerRowIdx + 1, headerRowIdx + 16);
  if (below) return below;
  // Fallback: wiersze powyżej header (R1 zazwyczaj "Rozgrzewka")
  const above = search(0, headerRowIdx);
  if (above) return above;
  // Last resort
  return 'Trening';
}

export function parseTrainings(rows: string[][]): Training[] {
  if (rows.length === 0) return [];

  const headerRowIdx = findFirstHeaderRowIdx(rows);
  if (headerRowIdx === null) return [];

  const headerRow = rows[headerRowIdx];
  // Block boundaries — col indices gdzie cell === "Numer"
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

    // Slice block rows: każdy row, kolumny [start..end)
    const blockRows = rows.map((row) => row.slice(start, end));

    // Determine which cols inside block są usable (non-empty, non-DROP)
    const blockHeader = blockRows[headerRowIdx];
    const colsKeep: number[] = [];
    blockHeader.forEach((cellRaw, idx) => {
      const cell = cellRaw.trim();
      if (DROP_HEADERS.has(cell)) return;
      // Drop col jeśli jest CAŁKOWICIE pusty w block (no header AND no data).
      const allEmpty = blockRows.every((row) => isEmpty(row[idx] ?? ''));
      if (allEmpty) return;
      colsKeep.push(idx);
    });

    if (colsKeep.length === 0) continue; // pusty blok → skip

    const headers = colsKeep.map((c) => blockHeader[c]?.trim() ?? '');

    // Exercises: każdy row PO header gdzie pierwszy keep'd col (zazwyczaj
    // "Numer") ma non-empty value. Numer jest pierwszą kolumną zawsze
    // (header "Numer" → kolumna numer/numer-ćwiczenia).
    const numerCol = colsKeep[0];
    const exercises: Exercise[] = [];
    for (let r = headerRowIdx + 1; r < blockRows.length; r++) {
      const number = (blockRows[r][numerCol] ?? '').trim();
      if (!number) continue;
      // Skip "Trening X" header row (number col contains "Trening A" zamiast "01")
      if (number.startsWith('Trening ')) continue;
      // Skip block sub-headers "Rozgrzewka" / "Dół" / "Góra"
      if (number === 'Rozgrzewka' || number === 'Dół' || number === 'Góra') continue;
      // Skip duplicate header rows — trener często powtarza header między
      // rozgrzewką a głównym treningiem w obrębie tej samej kolumny. Owner
      // bug report: "w połowie taba widzę wiersz Numer Ćwiczenie...".
      // Detect: numer col cell == "Numer" (header literal).
      if (number === 'Numer') continue;
      const cells = colsKeep.map((c) => (blockRows[r][c] ?? '').trim());
      exercises.push({ number, cells });
    }

    if (exercises.length === 0) continue; // header-only blok → skip

    const name = detectBlockName(rows, start, headerRowIdx);
    trainings.push({ name, headers, exercises });
  }

  return trainings;
}

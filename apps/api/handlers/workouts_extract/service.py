"""Service layer — extract workout history z Training[] frontu.

Flow:
1. Iteruj wszystkie Trainings × Sections × Exercises.
2. Pomiń sekcje "Rozgrzewka" (warm-up, nie chcemy tropić waga).
3. Per ćwiczenie: zlokalizuj "actual cell" (kolumna z headerem matching
   "Ciężar", lub fallback heuristics). Pomiń jeśli pusty.
4. Call Anthropic Haiku z dedykowanym promptem (zwraca strict JSON).
5. Compute date z (weekIdx, weekTotal, training_name, today_iso) per
   konwencja: latest week = current, Trening A=Mon, B=Wed, C=Fri.
6. PutItem `WORKOUT#{date}#{training-slug}#{exercise_number}`.
"""

from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from datetime import date, timedelta
from typing import Any

from pydantic import ValidationError

from handlers.workouts_extract.schemas import (
    ExtractedExercise,
    SectionIn,
    TrainingIn,
    WorkoutSet,
)
from shared.anthropic_client import (
    AnthropicUnavailableError,
    get_anthropic_client,
)
from shared.dynamo import put_item

logger = logging.getLogger("workouts_extract")

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 400  # JSON output typowo ~50-150 tokens

# Mapping training name suffix → ISO weekday (0=Mon...6=Sun). Owner per pytanie
# 2026-05-17 — default convention Trening A=pon, B=środa, C=piątek. Override
# w follow-up PR jeśli owner chce per-user mapping (np. D=sobota).
_TRAINING_DOW: dict[str, int] = {
    "A": 0,
    "B": 2,
    "C": 4,
    "D": 5,
}

# Warm-up rows pomijamy — owner zapisuje wagi tylko dla głównego treningu.
_SKIP_SECTION_LABELS = {"Rozgrzewka", "Warm-up", "Mobilizacja"}

# Locate "actual" cell — header zawierający "Ciężar" (case-insensitive). Owner
# 2026-05-17 confirmed: jedna kolumna "Ciężar x serie x powtórzenia x RIR".
_ACTUAL_HEADER_RE = re.compile(r"ciężar", re.IGNORECASE)

_SYSTEM_PROMPT = """Jesteś parserem dziennika treningowego siłowego po polsku.

WEJŚCIE — dla pojedynczego ćwiczenia dostajesz:
- nazwę ćwiczenia
- wpis usera w kolumnie "Ciężar x serie x powtórzenia x RIR"
- kontekst z innych kolumn (Schemat, Serie, Powtórzenia, RIR planowane)

ZADANIE: Wyciągnij dokładnie co user zrobił — lista setów z wagą i powtórzeniami.

KONWENCJE WPISÓW (przykłady):
1. "70 x 3 x 6" lub "70kg x 3 x 6" = 3 sety × 6 reps @ 70kg
2. "5,5,5,5,4 @ 102.5" = 4 sety × 5 reps + 1 set × 4 reps @ 102.5kg
3. "50,70,90,100-130, 140x3/120x9" (kontekst plan "rampa 5") = rampa po 5 reps:
   50×5, 70×5, 90×5, 100×5, 110×5, 120×5, 130×5, 140×3, 120×9
   (RANGE "100-130" rozwijaj step po 10kg; SLASH "/" to inny set z innym
   ciężar/reps; "x3" lub "x9" override default-rep z rampy)
4. "BW x 5" = bodyweight, 1 set × 5 reps (weight_kind="bw")
5. "BW+10 x 5" = bodyweight + 10kg dodatkowe = weight_kg=10, weight_kind="bw"
6. RIR (Reps In Reserve) suffix np. "@RIR 2" lub "RPE 8" → rir field.

SPECYFICZNIE:
- "rampa N" w PLANIE = każda waga × N reps, chyba że wpis ma "xK" suffix
- range "A-B" w wagach = rozszerz krokiem 10kg (typowo plates).
- slash "/" oddziela inne sety (zwykle backoff, drop set, max set).
- Jeśli wpis pusty lub niejasny → zwróć pustą listę setów.

OUTPUT — STRICT JSON, NIC POZA TYM (NO markdown fence):
{
  "sets": [
    {"weight_kg": 102.5, "weight_kind": "kg", "reps": 5},
    {"weight_kind": "bw", "reps": 8}
  ],
  "rir": 2,
  "notes": null
}

weight_kind: "kg" (default), "bw" (bodyweight), "other" (lekka/do ostatka itp.)
rir: int 0-10 lub null gdy nie podano
notes: string ≤200 chars lub null — krótka human-readable suma (NIE re-list setów)
"""


def slugify_training(name: str) -> str:
    """`Trening A` → `trening-a`. ASCII-only, no diacritics, dla DDB SK."""
    normalized = unicodedata.normalize("NFKD", name)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    lower = ascii_only.lower()
    # Replace non-alnum with hyphen, collapse consecutive hyphens.
    out = re.sub(r"[^a-z0-9]+", "-", lower).strip("-")
    return out or "trening"


def compute_date_for_training(
    training_name: str,
    week_idx: int,
    week_total: int,
    today_iso: str,
) -> str | None:
    """Zwraca YYYY-MM-DD dla danego Training per konwencja owner.

    Latest week (week_idx == week_total) = bieżący tydzień. Każdy poprzedni
    week_idx = (week_total - week_idx) tygodni temu. Trening name suffix
    (A/B/C/D) → day-of-week per _TRAINING_DOW. Jeśli nie matchuje patternu
    "Trening X" lub X nie w mapie → None (caller skip).
    """
    m = re.match(r"^Trening\s+([A-Z])$", training_name.strip())
    if not m:
        return None
    suffix = m.group(1).upper()
    dow = _TRAINING_DOW.get(suffix)
    if dow is None:
        return None
    today = date.fromisoformat(today_iso)
    # Monday of bieżącego tygodnia (today.weekday() = 0=Mon).
    monday_current = today - timedelta(days=today.weekday())
    weeks_back = week_total - week_idx
    monday_week = monday_current - timedelta(weeks=weeks_back)
    workout_date = monday_week + timedelta(days=dow)
    return workout_date.isoformat()


def find_actual_cell(headers: list[str], cells: list[str]) -> tuple[int, str] | None:
    """Znajdź (header_idx, cell_text) dla kolumny `Ciężar...`. None gdy brak."""
    for idx, header in enumerate(headers):
        if _ACTUAL_HEADER_RE.search(header):
            if idx < len(cells):
                return idx, cells[idx]
            return None
    return None


def build_user_message(
    *,
    exercise_name: str,
    actual_text: str,
    plan_context: dict[str, str],
) -> str:
    """Single-shot user message dla Haiku."""
    plan_lines = [f"- {k}: {v}" for k, v in plan_context.items() if v.strip()]
    plan_block = "\n".join(plan_lines) if plan_lines else "(brak kontekstu)"
    return (
        f"Ćwiczenie: {exercise_name}\n\n"
        f"Plan / kontekst:\n{plan_block}\n\n"
        f'Wpis usera (kolumna "Ciężar x..."): "{actual_text}"\n\n'
        "Zwróć JSON z setami zgodnie z system promptem."
    )


def parse_haiku_json(raw: str) -> dict[str, Any]:
    """Wyciągnij JSON z odpowiedzi Haiku — tolerujemy ewentualny markdown fence."""
    text = raw.strip()
    # Defensive — Haiku czasem opakuje w ```json ... ``` mimo instrukcji.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    parsed: dict[str, Any] = json.loads(text)
    return parsed


def call_haiku_for_exercise(
    *,
    exercise_name: str,
    actual_text: str,
    plan_context: dict[str, str],
) -> dict[str, Any]:
    """Wywołaj Haiku — zwraca dict {sets, rir, notes}. Może rzucić AnthropicError."""
    client = get_anthropic_client()
    user_msg = build_user_message(
        exercise_name=exercise_name,
        actual_text=actual_text,
        plan_context=plan_context,
    )
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=[{"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_msg}],
    )
    content_block = response.content[0]
    if content_block.type != "text":
        raise ValueError(f"unexpected response block type: {content_block.type}")
    return parse_haiku_json(content_block.text)


def extract_section(
    section: SectionIn,
    *,
    training_name: str,
    workout_date: str,
) -> tuple[list[ExtractedExercise], int, int]:
    """Iteruj exercises w sekcji, wołaj Haiku. Returns (out, skipped, errors).

    Per-exercise try/except — 1 bad Haiku response (invalid JSON, Pydantic
    validation fail) nie zabije reszty batcha. Live caught 2026-05-17:
    Haiku zwrócił `weight_kg=-7.5` (assisted pull-up BW-7.5 counterweight),
    odrzucone przez schema `ge=0` → cały batch rzucał 500. Po fix:
    schema akceptuje negative (assisted), plus errors counted bez raise.

    Skipped = ćwiczenia bez wpisu w "Ciężar..." cell (puste, niewypełnione).
    Errors = Haiku zwrócił niepoprawny output (JSON parse fail lub schema
    validation fail).
    """
    out: list[ExtractedExercise] = []
    skipped = 0
    errors = 0
    for exercise in section.exercises:
        actual = find_actual_cell(section.headers, exercise.cells)
        if actual is None or not actual[1].strip():
            skipped += 1
            continue
        idx, actual_text = actual
        exercise_name = exercise.cells[1].strip() if len(exercise.cells) > 1 else "?"
        plan_context = {
            section.headers[i]: cell
            for i, cell in enumerate(exercise.cells)
            if i != idx and i < len(section.headers)
        }
        try:
            parsed = call_haiku_for_exercise(
                exercise_name=exercise_name,
                actual_text=actual_text,
                plan_context=plan_context,
            )
            sets = [WorkoutSet.model_validate(s) for s in parsed.get("sets", [])]
        except (json.JSONDecodeError, ValidationError):
            logger.warning(
                "haiku_parse_failed",
                extra={
                    "exercise_number": exercise.number,
                    "exercise_name": exercise_name,
                    "actual_text": actual_text,
                },
            )
            errors += 1
            continue
        out.append(
            ExtractedExercise(
                date=workout_date,
                training_name=training_name,
                exercise_number=exercise.number,
                exercise_name=exercise_name,
                sets=sets,
                rir=parsed.get("rir"),
                notes=parsed.get("notes"),
            )
        )
    return out, skipped, errors


def persist_workout(user_id: str, item: ExtractedExercise) -> None:
    """PutItem do DDB. SK `WORKOUT#{date}#{training-slug}#{exercise_no}`.

    Last-write-wins — owner może re-trigger extract po edycji arkusza, dostanie
    update tego samego rowa.
    """
    sk = f"WORKOUT#{item.date}#{slugify_training(item.training_name)}#{item.exercise_number}"
    attrs = {
        "training_name": item.training_name,
        "exercise_number": item.exercise_number,
        "exercise_name": item.exercise_name,
        "sets": [s.model_dump() for s in item.sets],
        "rir": item.rir,
        "notes": item.notes,
        "source": "sheet_parser_v1",
        "recorded_at": int(time.time()),
    }
    # Drop None values żeby DDB nie zapisywał "NULL" typu.
    attrs = {k: v for k, v in attrs.items() if v is not None}
    put_item(f"USER#{user_id}", sk, attrs)


def run_extract(
    user_id: str,
    *,
    today_iso: str,
    trainings: list[TrainingIn],
) -> tuple[list[ExtractedExercise], int, int]:
    """Top-level — iteruj Trainings, woła Haiku, persistuje.

    Returns (items, skipped, errors). Errors = exception per-exercise
    (logged, NIE raise) żeby jeden zły wpis nie zabił całego batcha.
    """
    all_items: list[ExtractedExercise] = []
    total_skipped = 0
    errors = 0

    for training in trainings:
        workout_date = compute_date_for_training(
            training.name,
            training.week_idx,
            training.week_total,
            today_iso,
        )
        if workout_date is None:
            # Skip whole training — owner ma nestandard naming.
            total_skipped += sum(len(s.exercises) for s in training.sections)
            continue

        for section in training.sections:
            if section.label and section.label in _SKIP_SECTION_LABELS:
                continue
            try:
                items, skipped, section_errors = extract_section(
                    section,
                    training_name=training.name,
                    workout_date=workout_date,
                )
            except AnthropicUnavailableError:
                # API key niedostępny — twardy fail dla całej sekcji.
                errors += len(section.exercises)
                logger.exception(
                    "section_extract_failed",
                    extra={
                        "training_name": training.name,
                        "section_label": section.label,
                    },
                )
                continue
            total_skipped += skipped
            errors += section_errors
            for item in items:
                try:
                    persist_workout(user_id, item)
                    all_items.append(item)
                except Exception:
                    errors += 1
                    logger.exception(
                        "ddb_put_failed",
                        extra={
                            "exercise_number": item.exercise_number,
                            "date": item.date,
                        },
                    )

    return all_items, total_skipped, errors

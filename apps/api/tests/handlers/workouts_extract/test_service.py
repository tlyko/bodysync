"""Pure-function tests dla workouts_extract.service (date math, slug, parse).

Imports w bodies (NIE top-level) — service.py importuje shared.dynamo które
ma `_resource = boto3.resource("dynamodb")` at module init; w CI bez
AWS_DEFAULT_REGION daje NoRegionError przy pytest collection time.
Lokalnie test trzyma się autouse `_aws_credentials` fixture który ustawia
region PRZED test body. Wzorzec mirror reszty handlerów (measurements,
me_export, etc.).
"""

from __future__ import annotations


def test_slugify_training_basic() -> None:
    from handlers.workouts_extract.service import slugify_training

    assert slugify_training("Trening A") == "trening-a"
    assert slugify_training("Trening B") == "trening-b"


def test_slugify_training_strips_diacritics() -> None:
    # NFKD nie rozkłada Ł (separate letter, nie combining char) — dropujemy.
    # Owner używa wyłącznie "Trening A/B/C/D" więc edge case nie pojawia się
    # w praktyce; test deterministyczności slug-u.
    from handlers.workouts_extract.service import slugify_training

    assert slugify_training("Ćwiczenie Łatwe") == "cwiczenie-atwe"


def test_slugify_training_fallback_empty() -> None:
    from handlers.workouts_extract.service import slugify_training

    assert slugify_training("###") == "trening"


# ─── Date assignment ──────────────────────────────────────────────────────


def test_date_latest_week_trening_a_today_sunday() -> None:
    from handlers.workouts_extract.service import compute_date_for_training

    # 2026-05-17 = niedziela. Monday current = 2026-05-11. Latest week
    # (weekIdx=3 of 3) Trening A = pon = 2026-05-11.
    assert compute_date_for_training("Trening A", 3, 3, "2026-05-17") == "2026-05-11"


def test_date_latest_week_trening_b_wednesday() -> None:
    from handlers.workouts_extract.service import compute_date_for_training

    assert compute_date_for_training("Trening B", 3, 3, "2026-05-17") == "2026-05-13"


def test_date_latest_week_trening_c_friday() -> None:
    from handlers.workouts_extract.service import compute_date_for_training

    assert compute_date_for_training("Trening C", 3, 3, "2026-05-17") == "2026-05-15"


def test_date_previous_week() -> None:
    from handlers.workouts_extract.service import compute_date_for_training

    # weekIdx=2 of 3 → 1 tydzień temu → pon = 2026-05-04.
    assert compute_date_for_training("Trening A", 2, 3, "2026-05-17") == "2026-05-04"


def test_date_today_monday_trening_a() -> None:
    from handlers.workouts_extract.service import compute_date_for_training

    # today=2026-05-11 (poniedziałek). monday_current = 2026-05-11.
    assert compute_date_for_training("Trening A", 1, 1, "2026-05-11") == "2026-05-11"


def test_date_unrecognized_training_name_returns_none() -> None:
    from handlers.workouts_extract.service import compute_date_for_training

    assert compute_date_for_training("Rozgrzewka", 1, 1, "2026-05-17") is None


def test_date_unrecognized_letter_returns_none() -> None:
    from handlers.workouts_extract.service import compute_date_for_training

    assert compute_date_for_training("Trening Z", 1, 1, "2026-05-17") is None


# ─── Cell finder ──────────────────────────────────────────────────────────


def test_find_actual_cell_basic() -> None:
    from handlers.workouts_extract.service import find_actual_cell

    headers = ["Numer", "Ćwiczenie", "Schemat", "Ciężar x serie x powtórzenia x RIR"]
    cells = ["01", "Squat", "rampa 5", "50,70,90"]
    result = find_actual_cell(headers, cells)
    assert result is not None
    assert result == (3, "50,70,90")


def test_find_actual_cell_case_insensitive() -> None:
    from handlers.workouts_extract.service import find_actual_cell

    headers = ["numer", "ćwiczenie", "ciężar"]
    cells = ["01", "Squat", "70 x 3 x 6"]
    result = find_actual_cell(headers, cells)
    assert result is not None
    assert result[1] == "70 x 3 x 6"


def test_find_actual_cell_missing_returns_none() -> None:
    from handlers.workouts_extract.service import find_actual_cell

    headers = ["Numer", "Ćwiczenie", "Schemat"]
    cells = ["01", "Squat", "rampa"]
    assert find_actual_cell(headers, cells) is None


# ─── JSON parsing tolerance ───────────────────────────────────────────────


def test_parse_haiku_json_plain() -> None:
    from handlers.workouts_extract.service import parse_haiku_json

    raw = '{"sets": [{"weight_kg": 70, "weight_kind": "kg", "reps": 6}], "rir": 2, "notes": null}'
    parsed = parse_haiku_json(raw)
    assert parsed["sets"][0]["weight_kg"] == 70
    assert parsed["rir"] == 2


def test_parse_haiku_json_strips_markdown_fence() -> None:
    from handlers.workouts_extract.service import parse_haiku_json

    raw = '```json\n{"sets": [], "rir": null, "notes": null}\n```'
    parsed = parse_haiku_json(raw)
    assert parsed["sets"] == []


def test_parse_haiku_json_strips_bare_fence() -> None:
    from handlers.workouts_extract.service import parse_haiku_json

    raw = '```\n{"sets": [], "rir": null, "notes": null}\n```'
    parsed = parse_haiku_json(raw)
    assert parsed["sets"] == []

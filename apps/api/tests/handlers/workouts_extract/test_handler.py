"""Tests dla handlers.workouts_extract — POST /api/workouts/extract.

Anthropic Haiku mockowany przez `responses` lib (same pattern co advisor_chat).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

_CSRF_TEST_TOKEN = "test-csrf-token-deterministic"


@pytest.fixture
def reset_anthropic_singleton() -> Any:
    """Drop module-level singleton dla testów które importują shared.anthropic_client.
    NIE autouse — import na top triggerwałby boto3.client przed moto context.
    """
    from shared import anthropic_client

    anthropic_client.reset_client_for_tests()
    yield
    anthropic_client.reset_client_for_tests()


def _event(
    cookie: str | None,
    *,
    body: dict[str, Any] | None = None,
    csrf: bool = True,
) -> dict[str, Any]:
    cookies: list[str] = [cookie] if cookie else []
    headers: dict[str, str] = {"content-type": "application/json"}
    if csrf:
        cookies.append(f"bodysync_csrf={_CSRF_TEST_TOKEN}")
        headers["x-csrf-token"] = _CSRF_TEST_TOKEN
    return {
        "version": "2.0",
        "routeKey": "POST /api/workouts/extract",
        "rawPath": "/api/workouts/extract",
        "requestContext": {"http": {"method": "POST"}},
        "headers": headers,
        "cookies": cookies,
        "body": json.dumps(body) if body is not None else None,
        "isBase64Encoded": False,
    }


class _FakeContext:
    aws_request_id = "test-req-id"


def _mint_test_jwt(user_id: str) -> str:
    from shared.auth import mint_jwt

    return mint_jwt(user_id)


def _sample_trainings() -> list[dict[str, Any]]:
    """Mock Training[] z 1 sekcją Trening A z 2 ćwiczeniami."""
    return [
        {
            "name": "Trening A",
            "weekIdx": 1,
            "weekTotal": 1,
            "sections": [
                {
                    "label": "Trening A",
                    "headers": [
                        "Numer",
                        "Ćwiczenie",
                        "Schemat",
                        "Ciężar x serie x powtórzenia x RIR",
                    ],
                    "exercises": [
                        {
                            "number": "01",
                            "cells": ["01", "Sumo Deadlift", "rampa 5", "50,70,90,100-130,140x3"],
                        },
                        {
                            "number": "02",
                            "cells": ["02", "Bench Press", "3s x 4-6p", "70 x 3 x 6"],
                        },
                    ],
                }
            ],
        }
    ]


def _make_mock_anthropic_response(text: str) -> Any:
    """Minimal struktura mirror Anthropic SDK response z 1 text block."""
    from unittest.mock import MagicMock

    response = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = text
    response.content = [block]
    return response


# ─── Auth/CSRF ─────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_missing_cookie_returns_401() -> None:
    from handlers.workouts_extract import handler as h

    result = h.handle(
        _event(None, body={"today_iso": "2026-05-17", "trainings": _sample_trainings()}),
        _FakeContext(),
    )
    assert result["statusCode"] == 401


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_missing_csrf_returns_403() -> None:
    from handlers.workouts_extract import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handle(
        _event(
            cookie,
            body={"today_iso": "2026-05-17", "trainings": _sample_trainings()},
            csrf=False,
        ),
        _FakeContext(),
    )
    assert result["statusCode"] == 403


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_invalid_date_format_returns_422() -> None:
    from handlers.workouts_extract import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handle(
        _event(cookie, body={"today_iso": "2026-5-17", "trainings": _sample_trainings()}),
        _FakeContext(),
    )
    assert result["statusCode"] == 422


# ─── Happy path z mocked Haiku ─────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_params", "reset_anthropic_singleton")
def test_happy_extract_persists_to_ddb(dynamodb_table: Any) -> None:
    """2 ćwiczenia → 2 LLM calls → 2 DDB rows pod USER#tomek z WORKOUT#... SK."""
    from handlers.workouts_extract import handler as h

    deadlift_response = _make_mock_anthropic_response(
        json.dumps(
            {
                "sets": [
                    {"weight_kg": 50, "weight_kind": "kg", "reps": 5},
                    {"weight_kg": 70, "weight_kind": "kg", "reps": 5},
                    {"weight_kg": 140, "weight_kind": "kg", "reps": 3},
                ],
                "rir": None,
                "notes": "Rampa do 140kg",
            }
        )
    )
    bench_response = _make_mock_anthropic_response(
        json.dumps(
            {
                "sets": [
                    {"weight_kg": 70, "weight_kind": "kg", "reps": 6},
                    {"weight_kg": 70, "weight_kind": "kg", "reps": 6},
                    {"weight_kg": 70, "weight_kind": "kg", "reps": 6},
                ],
                "rir": 2,
                "notes": None,
            }
        )
    )

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"

    with patch("handlers.workouts_extract.service.get_anthropic_client") as mock_get_client:
        client = mock_get_client.return_value
        client.messages.create.side_effect = [deadlift_response, bench_response]

        result = h.handle(
            _event(
                cookie,
                body={"today_iso": "2026-05-17", "trainings": _sample_trainings()},
            ),
            _FakeContext(),
        )

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["extracted"] == 2
    assert body["skipped"] == 0
    assert body["errors"] == 0
    assert client.messages.create.call_count == 2

    # DDB rows zapisane pod USER#tomek z proper SK.
    items = dynamodb_table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :skp)",
        ExpressionAttributeValues={":pk": "USER#tomek", ":skp": "WORKOUT#"},
    )["Items"]
    assert len(items) == 2
    sks = sorted(it["SK"] for it in items)
    # today_iso=2026-05-17 (niedziela), weekIdx=1 of 1, Trening A → pon 2026-05-11.
    assert sks == [
        "WORKOUT#2026-05-11#trening-a#01",
        "WORKOUT#2026-05-11#trening-a#02",
    ]
    deadlift = next(it for it in items if it["SK"].endswith("#01"))
    assert deadlift["exercise_name"] == "Sumo Deadlift"
    assert len(deadlift["sets"]) == 3
    bench = next(it for it in items if it["SK"].endswith("#02"))
    assert bench["rir"] == 2


@pytest.mark.usefixtures("ssm_params")
def test_skips_empty_actual_cell(dynamodb_table: Any) -> None:
    """Ćwiczenie z pustym wpisem w "Ciężar..." cell → skipped, brak LLM call."""
    from handlers.workouts_extract import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    trainings = _sample_trainings()
    # Wyczyść actual cell drugiego ćwiczenia.
    trainings[0]["sections"][0]["exercises"][1]["cells"][3] = ""

    with patch("handlers.workouts_extract.service.get_anthropic_client") as mock_get_client:
        client = mock_get_client.return_value
        client.messages.create.return_value = _make_mock_anthropic_response(
            json.dumps({"sets": [], "rir": None, "notes": None})
        )

        result = h.handle(
            _event(
                cookie,
                body={"today_iso": "2026-05-17", "trainings": trainings},
            ),
            _FakeContext(),
        )

    body = json.loads(result["body"])
    assert body["extracted"] == 1
    assert body["skipped"] == 1
    # Tylko 1 LLM call (drugi ćwiczenie pominięte).
    assert client.messages.create.call_count == 1


@pytest.mark.usefixtures("ssm_params")
def test_warmup_section_skipped(dynamodb_table: Any) -> None:
    """Sekcja "Rozgrzewka" pomijana — owner nie loguje wag rozgrzewki."""
    from handlers.workouts_extract import handler as h

    trainings = [
        {
            "name": "Trening A",
            "weekIdx": 1,
            "weekTotal": 1,
            "sections": [
                {
                    "label": "Rozgrzewka",
                    "headers": ["Numer", "Ćwiczenie", "Ciężar x serie x powtórzenia x RIR"],
                    "exercises": [
                        {"number": "W01", "cells": ["W01", "Plank", "30s"]},
                    ],
                },
                {
                    "label": "Trening A",
                    "headers": ["Numer", "Ćwiczenie", "Ciężar x serie x powtórzenia x RIR"],
                    "exercises": [
                        {"number": "01", "cells": ["01", "Squat", "100 x 3 x 5"]},
                    ],
                },
            ],
        }
    ]
    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"

    with patch("handlers.workouts_extract.service.get_anthropic_client") as mock_get_client:
        client = mock_get_client.return_value
        client.messages.create.return_value = _make_mock_anthropic_response(
            json.dumps(
                {
                    "sets": [{"weight_kg": 100, "weight_kind": "kg", "reps": 5}],
                    "rir": None,
                    "notes": None,
                }
            )
        )

        result = h.handle(
            _event(cookie, body={"today_iso": "2026-05-17", "trainings": trainings}),
            _FakeContext(),
        )

    body = json.loads(result["body"])
    assert body["extracted"] == 1
    # Tylko 1 LLM call (Plank rozgrzewki pominięty).
    assert client.messages.create.call_count == 1


@pytest.mark.usefixtures("ssm_params")
def test_unrecognized_training_name_skipped_entire(dynamodb_table: Any) -> None:
    """`Trening Z` (nie w mapie A/B/C/D) → cały training pominięty, brak LLM."""
    from handlers.workouts_extract import handler as h

    trainings = [
        {
            "name": "Trening Z",
            "weekIdx": 1,
            "weekTotal": 1,
            "sections": [
                {
                    "label": "Trening Z",
                    "headers": ["Numer", "Ćwiczenie", "Ciężar x serie x powtórzenia x RIR"],
                    "exercises": [
                        {"number": "01", "cells": ["01", "Cardio", "30min"]},
                    ],
                },
            ],
        }
    ]
    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"

    with patch("handlers.workouts_extract.service.get_anthropic_client") as mock_get_client:
        client = mock_get_client.return_value

        result = h.handle(
            _event(cookie, body={"today_iso": "2026-05-17", "trainings": trainings}),
            _FakeContext(),
        )

    body = json.loads(result["body"])
    assert body["extracted"] == 0
    assert body["skipped"] == 1
    assert client.messages.create.call_count == 0


@pytest.mark.usefixtures("ssm_params")
def test_pk_isolation_user_a_writes_under_own_partition(dynamodb_table: Any) -> None:
    """Extract dla tomka NIE pisze pod USER#weronika."""
    from handlers.workouts_extract import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"

    with patch("handlers.workouts_extract.service.get_anthropic_client") as mock_get_client:
        client = mock_get_client.return_value
        client.messages.create.return_value = _make_mock_anthropic_response(
            json.dumps(
                {
                    "sets": [{"weight_kg": 100, "weight_kind": "kg", "reps": 5}],
                    "rir": None,
                    "notes": None,
                }
            )
        )

        h.handle(
            _event(cookie, body={"today_iso": "2026-05-17", "trainings": _sample_trainings()}),
            _FakeContext(),
        )

    tomek_items = dynamodb_table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": "USER#tomek"},
    )["Items"]
    weronika_items = dynamodb_table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": "USER#weronika"},
    )["Items"]

    assert len(tomek_items) > 0
    assert len(weronika_items) == 0


@pytest.mark.usefixtures("ssm_params")
def test_negative_weight_assisted_accepted(dynamodb_table: Any) -> None:
    """Assisted exercise (BW-7.5 counterweight) → schema accepts negative weight_kg.
    Live regression 2026-05-17 — Haiku zwrócił -7.5, schema z `ge=0` odrzucała
    cały batch przez ValidationError raise.
    """
    from handlers.workouts_extract import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"

    with patch("handlers.workouts_extract.service.get_anthropic_client") as mock_get_client:
        client = mock_get_client.return_value
        client.messages.create.return_value = _make_mock_anthropic_response(
            json.dumps(
                {
                    "sets": [
                        {"weight_kg": -7.5, "weight_kind": "bw", "reps": 8},
                        {"weight_kg": -5.0, "weight_kind": "bw", "reps": 6},
                    ],
                    "rir": None,
                    "notes": "assisted pull-up",
                }
            )
        )

        result = h.handle(
            _event(
                cookie,
                body={"today_iso": "2026-05-17", "trainings": _sample_trainings()},
            ),
            _FakeContext(),
        )

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["errors"] == 0
    assert body["extracted"] >= 1


@pytest.mark.usefixtures("ssm_params")
def test_invalid_haiku_response_skips_exercise_not_batch(dynamodb_table: Any) -> None:
    """Haiku zwraca invalid JSON dla 1 ćwiczenia → tylko ono w errors,
    reszta batcha przechodzi (defense in depth).
    """
    from handlers.workouts_extract import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    good = _make_mock_anthropic_response(
        json.dumps(
            {
                "sets": [{"weight_kg": 100, "weight_kind": "kg", "reps": 5}],
                "rir": None,
                "notes": None,
            }
        )
    )
    bad = _make_mock_anthropic_response("not valid json {{")

    with patch("handlers.workouts_extract.service.get_anthropic_client") as mock_get_client:
        client = mock_get_client.return_value
        # Pierwszy ćwiczenie OK, drugie corrupt.
        client.messages.create.side_effect = [good, bad]

        result = h.handle(
            _event(
                cookie,
                body={"today_iso": "2026-05-17", "trainings": _sample_trainings()},
            ),
            _FakeContext(),
        )

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["extracted"] == 1
    assert body["errors"] == 1

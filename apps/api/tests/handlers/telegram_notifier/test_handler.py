"""Smoke tests dla telegram_notifier — SNS subscriber forwarduje
CloudWatch alarm payload na Telegram bota.

Mock strategy:
- moto SSM dla bot_token + chat_id (per-test seed via fixture).
- monkeypatch `urllib.request.urlopen` dla wysyłki HTTP — zwraca fake
  response (2xx) lub rzuca HTTPError/URLError/TimeoutError.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import boto3
import pytest

from handlers.telegram_notifier.handler import handler


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(aws_request_id="test-req-1")


def _alarm_event(
    *,
    state: str = "ALARM",
    name: str = "bodysync-anthropic-daily-cost-high",
    reason: str = "Threshold Crossed: 1500000 < 1600000",
) -> dict[str, Any]:
    """Build SNS event mirror'ujący CloudWatch alarm notification."""
    payload = {
        "AlarmName": name,
        "NewStateValue": state,
        "NewStateReason": reason,
        "StateChangeTime": "2026-05-09T12:00:00.000+0000",
    }
    return {"Records": [{"Sns": {"Message": json.dumps(payload)}}]}


@pytest.fixture
def telegram_ssm(ssm_params: None) -> Iterator[None]:
    """Seed SSM z telegram bot_token + chat_id."""
    client = boto3.client("ssm", region_name="eu-west-1")
    client.put_parameter(
        Name="/bodysync/telegram/bot_token",
        Value="1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
        Type="SecureString",
    )
    client.put_parameter(
        Name="/bodysync/telegram/chat_id",
        Value="987654321",
        Type="String",
    )
    from shared import ssm as _ssm

    _ssm.clear_cache()
    yield
    _ssm.clear_cache()


class _FakeResponse:
    def __init__(self, status: int = 200) -> None:
        self.status = status

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_: Any) -> None:
        return None


def test_alarm_state_sends_telegram_message_with_payload(
    telegram_ssm: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[urllib.request.Request] = []

    def fake_urlopen(req: urllib.request.Request, timeout: float | None = None) -> _FakeResponse:
        captured.append(req)
        return _FakeResponse(status=200)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    res = handler(_alarm_event(state="ALARM"), _ctx())

    assert res == {"ok": True}
    assert len(captured) == 1
    req = captured[0]
    assert req.full_url.startswith("https://api.telegram.org/bot1234567890:")
    assert req.full_url.endswith("/sendMessage")
    assert req.method == "POST"
    assert req.headers["Content-type"] == "application/json"
    assert req.data is not None
    body = json.loads(req.data)
    assert body["chat_id"] == "987654321"
    assert body["parse_mode"] == "HTML"
    assert "🚨" in body["text"]
    assert "<b>Cost guard ALARM</b>" in body["text"]
    assert "bodysync-anthropic-daily-cost-high" in body["text"]


def test_ok_state_sends_recovery_icon(telegram_ssm: None, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[urllib.request.Request] = []
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=None: captured.append(req) or _FakeResponse(status=200),
    )

    res = handler(_alarm_event(state="OK"), _ctx())

    assert res == {"ok": True}
    body = json.loads(captured[0].data or b"{}")
    assert "✅" in body["text"]
    assert "<b>Cost guard OK</b>" in body["text"]


def test_html_special_chars_in_alarm_payload_are_escaped(
    telegram_ssm: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`<`/`>`/`&` w `NewStateReason` (np. "Threshold > 1500000") muszą być
    escape'owane bo Telegram parse_mode=HTML rzuci 400 inaczej.
    """
    captured: list[urllib.request.Request] = []
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=None: captured.append(req) or _FakeResponse(status=200),
    )

    event = _alarm_event(reason="Threshold > 1.5M & datapoint <breached>")
    handler(event, _ctx())

    body = json.loads(captured[0].data or b"{}")
    assert "&gt;" in body["text"]
    assert "&lt;breached&gt;" in body["text"]
    assert "&amp;" in body["text"]
    # Raw chars NIE w wysłanym tekście (regex sanity)
    assert " > 1.5M" not in body["text"]


def test_malformed_sns_event_returns_no_send(
    telegram_ssm: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    called = False

    def fake_urlopen(*_: Any, **__: Any) -> _FakeResponse:
        nonlocal called
        called = True
        return _FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    # Records[0].Sns.Message nie jest valid JSON
    bad_event = {"Records": [{"Sns": {"Message": "not-json"}}]}
    res = handler(bad_event, _ctx())

    assert res == {"ok": False, "reason": "malformed_event"}
    assert called is False


def test_empty_records_returns_no_send(telegram_ssm: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_, **__: _FakeResponse())

    res = handler({"Records": []}, _ctx())

    assert res == {"ok": False, "reason": "no_records"}


def test_placeholder_bot_token_skips_send(
    ssm_params: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pre-deploy stan gdy Terraform stworzył SSM placeholder ale owner
    nie wpisał real tokena. `load_secure_secret` rzuca, handler zwraca
    `ok=False` zamiast crashować.
    """
    client = boto3.client("ssm", region_name="eu-west-1")
    client.put_parameter(
        Name="/bodysync/telegram/bot_token",
        Value="PLACEHOLDER",
        Type="SecureString",
    )
    client.put_parameter(
        Name="/bodysync/telegram/chat_id",
        Value="PLACEHOLDER",
        Type="String",
    )
    from shared import ssm as _ssm

    _ssm.clear_cache()

    called = False

    def fake_urlopen(*_: Any, **__: Any) -> _FakeResponse:
        nonlocal called
        called = True
        return _FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    res = handler(_alarm_event(), _ctx())

    assert res == {"ok": False}
    assert called is False
    _ssm.clear_cache()


def test_telegram_http_error_returns_failure_no_raise(
    telegram_ssm: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_urlopen(req: urllib.request.Request, timeout: float | None = None) -> _FakeResponse:
        raise urllib.error.HTTPError(
            url=req.full_url, code=400, msg="Bad Request", hdrs=None, fp=None
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    # Handler nie powinien rzucać — best-effort delivery.
    res = handler(_alarm_event(), _ctx())

    assert res == {"ok": False}


def test_telegram_timeout_returns_failure_no_raise(
    telegram_ssm: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_urlopen(*_: Any, **__: Any) -> _FakeResponse:
        raise TimeoutError("connection timed out")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    res = handler(_alarm_event(), _ctx())

    assert res == {"ok": False}


def test_telegram_url_error_returns_failure_no_raise(
    telegram_ssm: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_urlopen(*_: Any, **__: Any) -> _FakeResponse:
        raise urllib.error.URLError("DNS resolution failed")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    res = handler(_alarm_event(), _ctx())

    assert res == {"ok": False}

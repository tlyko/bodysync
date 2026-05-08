"""Tests dla `scripts/strava_subscribe.py` CLI."""

from __future__ import annotations

from unittest.mock import patch

import boto3
import httpx
import pytest


def _make_response(status: int, json_body: object | None = None) -> httpx.Response:
    """httpx.Response wymaga `request` żeby raise_for_status nie crashował."""
    return httpx.Response(
        status,
        json=json_body,
        request=httpx.Request("GET", "https://stub"),
    )


@pytest.fixture
def subscribe_ssm(ssm_params: None) -> None:
    """Pre-seed strava client_id + client_secret z REAL values (nie PLACEHOLDER)."""
    client = boto3.client("ssm", region_name="eu-west-1")
    client.put_parameter(
        Name="/bodysync/strava/client_id",
        Value="123456",
        Type="String",
    )
    client.put_parameter(
        Name="/bodysync/strava/client_secret",
        Value="0123456789abcdef0123456789abcdef01234567",
        Type="SecureString",
    )
    client.put_parameter(
        Name="/bodysync/strava/verify_token",
        Value="PLACEHOLDER",
        Type="SecureString",
    )
    client.put_parameter(
        Name="/bodysync/strava/subscription_id",
        Value="PLACEHOLDER",
        Type="String",
    )


def test_subscribe_happy_path_persists_verify_token_and_subscription_id(
    subscribe_ssm: None,
) -> None:
    from scripts.strava_subscribe import main

    list_resp = _make_response(200, [])  # no existing subs
    create_resp = _make_response(201, {"id": 555, "callback_url": "x"})

    with (
        patch("scripts.strava_subscribe.httpx.get", return_value=list_resp),
        patch("scripts.strava_subscribe.httpx.post", return_value=create_resp),
    ):
        rc = main(["subscribe"])

    assert rc == 0

    ssm = boto3.client("ssm", region_name="eu-west-1")
    sub_id = ssm.get_parameter(Name="/bodysync/strava/subscription_id")["Parameter"]["Value"]
    verify = ssm.get_parameter(Name="/bodysync/strava/verify_token", WithDecryption=True)[
        "Parameter"
    ]["Value"]
    assert sub_id == "555"
    assert verify != "PLACEHOLDER"
    assert len(verify) >= 32  # token_urlsafe(32) → ~43 chars


def test_subscribe_aborts_when_existing_without_force(subscribe_ssm: None) -> None:
    from scripts.strava_subscribe import main

    existing_resp = _make_response(
        200, [{"id": 999, "callback_url": "https://api.bodysync.pl/api/strava/webhook"}]
    )
    with patch("scripts.strava_subscribe.httpx.get", return_value=existing_resp):
        rc = main(["subscribe"])
    assert rc == 1


def test_subscribe_force_unsubscribes_existing(subscribe_ssm: None) -> None:
    from scripts.strava_subscribe import main

    list_resp = _make_response(200, [{"id": 999, "callback_url": "x"}])
    create_resp = _make_response(201, {"id": 1234, "callback_url": "x"})
    delete_resp = _make_response(204)

    with (
        patch("scripts.strava_subscribe.httpx.get", return_value=list_resp),
        patch("scripts.strava_subscribe.httpx.delete", return_value=delete_resp),
        patch("scripts.strava_subscribe.httpx.post", return_value=create_resp),
    ):
        rc = main(["subscribe", "--force"])

    assert rc == 0
    sub_id = boto3.client("ssm", region_name="eu-west-1").get_parameter(
        Name="/bodysync/strava/subscription_id"
    )["Parameter"]["Value"]
    assert sub_id == "1234"


def test_subscribe_aborts_when_client_id_placeholder(ssm_params: None) -> None:
    """Owner nie wpisał real values → fail loud."""
    boto3.client("ssm", region_name="eu-west-1").put_parameter(
        Name="/bodysync/strava/client_id",
        Value="PLACEHOLDER",
        Type="String",
    )
    boto3.client("ssm", region_name="eu-west-1").put_parameter(
        Name="/bodysync/strava/client_secret",
        Value="0123456789abcdef0123456789abcdef01234567",
        Type="SecureString",
    )

    from scripts.strava_subscribe import main

    rc = main(["subscribe"])
    assert rc == 1


def test_unsubscribe_deletes_existing_and_resets_ssm(subscribe_ssm: None) -> None:
    boto3.client("ssm", region_name="eu-west-1").put_parameter(
        Name="/bodysync/strava/subscription_id",
        Value="555",
        Type="String",
        Overwrite=True,
    )
    boto3.client("ssm", region_name="eu-west-1").put_parameter(
        Name="/bodysync/strava/verify_token",
        Value="real_verify_token_aaaaaaaaaaaaaaaaaaaaaa",
        Type="SecureString",
        Overwrite=True,
    )

    from scripts.strava_subscribe import main

    list_resp = _make_response(200, [{"id": 555, "callback_url": "x"}])
    delete_resp = _make_response(204)
    with (
        patch("scripts.strava_subscribe.httpx.get", return_value=list_resp),
        patch("scripts.strava_subscribe.httpx.delete", return_value=delete_resp),
    ):
        rc = main(["unsubscribe"])

    assert rc == 0
    ssm = boto3.client("ssm", region_name="eu-west-1")
    assert (
        ssm.get_parameter(Name="/bodysync/strava/subscription_id")["Parameter"]["Value"]
        == "PLACEHOLDER"
    )
    assert (
        ssm.get_parameter(Name="/bodysync/strava/verify_token", WithDecryption=True)["Parameter"][
            "Value"
        ]
        == "PLACEHOLDER"
    )


def test_list_returns_0_when_no_subscriptions(subscribe_ssm: None) -> None:
    from scripts.strava_subscribe import main

    list_resp = _make_response(200, [])
    with patch("scripts.strava_subscribe.httpx.get", return_value=list_resp):
        rc = main(["list"])
    assert rc == 0

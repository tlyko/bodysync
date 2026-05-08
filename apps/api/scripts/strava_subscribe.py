"""Strava webhook subscribe CLI — jednorazowo po deploy Step 4 + Step 7.

Flow:
1. Generate cryptographic `verify_token` (32 bytes random base64).
2. PUT do SSM `/bodysync/strava/verify_token` (SecureString).
3. POST `https://www.strava.com/api/v3/push_subscriptions` z client_id +
   client_secret + callback_url + verify_token.
4. Strava sama wystrzeli **GET handshake** na nasz callback_url —
   webhook Lambda (Step 4) odpowiada echo challenge gdy verify_token
   matchuje.
5. Strava odpowiada na POST z `{id: <subscription_id>}`.
6. PUT do SSM `/bodysync/strava/subscription_id` (String).

Idempotent — re-run sprawdza najpierw czy subscription już istnieje
(GET /push_subscriptions), jeśli tak: skip subscribe, zsync verify_token
+ subscription_id do SSM (ALE verify_token już byłby u Strava — można
tylko unsubscribe + resubscribe).

Uruchom raz:
    cd apps/api
    .venv/bin/python scripts/strava_subscribe.py

Lub `--unsubscribe` żeby usunąć:
    .venv/bin/python scripts/strava_subscribe.py --unsubscribe
"""

from __future__ import annotations

import argparse
import logging
import secrets
import sys

import boto3
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("strava_subscribe")

STRAVA_SUBSCRIPTIONS_URL = "https://www.strava.com/api/v3/push_subscriptions"
CALLBACK_URL = "https://api.bodysync.pl/api/strava/webhook"

CLIENT_ID_PARAM = "/bodysync/strava/client_id"
CLIENT_SECRET_PARAM = "/bodysync/strava/client_secret"
VERIFY_TOKEN_PARAM = "/bodysync/strava/verify_token"
SUBSCRIPTION_ID_PARAM = "/bodysync/strava/subscription_id"


def _ssm_get(client: object, name: str, decrypt: bool = False) -> str:
    return client.get_parameter(Name=name, WithDecryption=decrypt)["Parameter"]["Value"]  # type: ignore[attr-defined]


def _ssm_put(client: object, name: str, value: str, secure: bool, overwrite: bool = True) -> None:
    client.put_parameter(  # type: ignore[attr-defined]
        Name=name,
        Value=value,
        Type="SecureString" if secure else "String",
        Overwrite=overwrite,
    )


def list_subscriptions(client_id: str, client_secret: str) -> list[dict]:
    """GET /push_subscriptions — Strava zwraca listę istniejących subscriptions
    dla tego app. Limit 1 per app (jeśli już istnieje, można tylko unsubscribe
    + resubscribe).
    """
    resp = httpx.get(
        STRAVA_SUBSCRIPTIONS_URL,
        params={"client_id": client_id, "client_secret": client_secret},
        timeout=10.0,
    )
    resp.raise_for_status()
    return resp.json()  # type: ignore[no-any-return]


def create_subscription(
    client_id: str, client_secret: str, callback_url: str, verify_token: str
) -> int:
    """POST nowej subscription. Strava sama wykonuje GET handshake na
    callback_url — webhook Lambda musi byc deployed + verify_token musi
    byc w SSM PRZED tym call'em (inaczej handshake fail i Strava 400).
    """
    resp = httpx.post(
        STRAVA_SUBSCRIPTIONS_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "callback_url": callback_url,
            "verify_token": verify_token,
        },
        timeout=30.0,  # Strava handshake do nas + odpowiedz — może być slow
    )
    if resp.status_code != 201:
        logger.error("strava POST status=%s body=%s", resp.status_code, resp.text)
        resp.raise_for_status()
    sub_id: int = int(resp.json()["id"])
    return sub_id


def delete_subscription(client_id: str, client_secret: str, sub_id: int) -> None:
    resp = httpx.delete(
        f"{STRAVA_SUBSCRIPTIONS_URL}/{sub_id}",
        params={"client_id": client_id, "client_secret": client_secret},
        timeout=10.0,
    )
    if resp.status_code != 204:
        logger.error("strava DELETE status=%s body=%s", resp.status_code, resp.text)
        resp.raise_for_status()


def cmd_subscribe(args: argparse.Namespace) -> int:
    ssm = boto3.client("ssm", region_name="eu-west-1")

    client_id = _ssm_get(ssm, CLIENT_ID_PARAM)
    client_secret = _ssm_get(ssm, CLIENT_SECRET_PARAM, decrypt=True)
    if client_id == "PLACEHOLDER" or client_secret == "PLACEHOLDER":
        logger.error("client_id lub client_secret w SSM nadal PLACEHOLDER")
        return 1

    # Sprawdź istniejące subscriptions (Strava limit 1 per app).
    existing = list_subscriptions(client_id, client_secret)
    if existing:
        logger.warning(
            "Istnieje już %d subscription(s): %s",
            len(existing),
            [{"id": s["id"], "callback": s["callback_url"]} for s in existing],
        )
        if not args.force:
            logger.info("Use --force żeby unsubscribe istniejące + create nowy. Aborting.")
            return 1
        for s in existing:
            logger.info("Deleting existing subscription id=%s", s["id"])
            delete_subscription(client_id, client_secret, int(s["id"]))

    # Generate fresh verify_token i wpisz do SSM PRZED POST (Strava
    # natychmiast wykonuje GET handshake na callback_url).
    verify_token = secrets.token_urlsafe(32)
    logger.info("Persisting verify_token do SSM (length=%d)", len(verify_token))
    _ssm_put(ssm, VERIFY_TOKEN_PARAM, verify_token, secure=True)

    # Subscribe.
    callback_url = args.callback_url or CALLBACK_URL
    logger.info(
        "POST /push_subscriptions callback_url=%s (Strava wykona handshake)",
        callback_url,
    )
    sub_id = create_subscription(client_id, client_secret, callback_url, verify_token)
    logger.info("Subscription created id=%d", sub_id)

    _ssm_put(ssm, SUBSCRIPTION_ID_PARAM, str(sub_id), secure=False)
    logger.info("Persisted subscription_id=%d do SSM", sub_id)

    logger.info("✓ Subscription complete. Strava będzie pushować events przy każdej activity.")
    return 0


def cmd_unsubscribe(_args: argparse.Namespace) -> int:
    ssm = boto3.client("ssm", region_name="eu-west-1")

    client_id = _ssm_get(ssm, CLIENT_ID_PARAM)
    client_secret = _ssm_get(ssm, CLIENT_SECRET_PARAM, decrypt=True)

    existing = list_subscriptions(client_id, client_secret)
    if not existing:
        logger.info("Brak active subscriptions — nothing to unsubscribe")
        return 0

    for s in existing:
        sub_id = int(s["id"])
        logger.info("Deleting subscription id=%d", sub_id)
        delete_subscription(client_id, client_secret, sub_id)

    # Reset SSM placeholdery.
    _ssm_put(ssm, SUBSCRIPTION_ID_PARAM, "PLACEHOLDER", secure=False)
    _ssm_put(ssm, VERIFY_TOKEN_PARAM, "PLACEHOLDER", secure=True)
    logger.info("✓ Unsubscribe complete. SSM placeholders restored.")
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    ssm = boto3.client("ssm", region_name="eu-west-1")
    client_id = _ssm_get(ssm, CLIENT_ID_PARAM)
    client_secret = _ssm_get(ssm, CLIENT_SECRET_PARAM, decrypt=True)
    existing = list_subscriptions(client_id, client_secret)
    if not existing:
        logger.info("No active subscriptions")
        return 0
    for s in existing:
        logger.info(
            "id=%s callback=%s created=%s",
            s.get("id"),
            s.get("callback_url"),
            s.get("created_at"),
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_sub = sub.add_parser("subscribe", help="Create push subscription")
    p_sub.add_argument(
        "--callback-url",
        default=CALLBACK_URL,
        help=f"Webhook callback URL (default: {CALLBACK_URL})",
    )
    p_sub.add_argument(
        "--force",
        action="store_true",
        help="Unsubscribe existing przed nowym subscribe",
    )
    p_sub.set_defaults(func=cmd_subscribe)

    p_unsub = sub.add_parser("unsubscribe", help="Delete current subscription")
    p_unsub.set_defaults(func=cmd_unsubscribe)

    p_list = sub.add_parser("list", help="List existing subscriptions (no SSM writes)")
    p_list.set_defaults(func=cmd_list)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())

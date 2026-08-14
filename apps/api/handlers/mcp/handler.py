"""AWS Lambda entry point serwera MCP — endpoint danych + serwer autoryzacji.

Routing (wszystkie trasy trafiają w tę samą Lambdę):

  POST /mcp                                     JSON-RPC 2.0, wymaga Bearer
  GET  /.well-known/oauth-protected-resource    RFC 9728
  GET  /.well-known/oauth-authorization-server  RFC 8414
  POST /mcp/register                            RFC 7591 DCR
  GET  /mcp/authorize                           ekran zgody
  POST /mcp/authorize                           wydanie kodu
  POST /mcp/token                               wymiana kodu / refresh

`POST /mcp` odpowiada `application/json`, nie SSE — API Gateway HTTP nie
wspiera response streamingu, a przy czterech narzędziach read-only nie ma
czego streamować (ADR-010).
"""

from __future__ import annotations

import base64
import json
from typing import Any
from urllib.parse import parse_qs

from handlers.mcp import oauth, protocol
from handlers.mcp.auth import AuthError, resolve_user_id
from shared.auth import AuthError as SessionAuthError
from shared.auth import verify_jwt
from shared.dynamo import get_item
from shared.http import extract_session_cookie
from shared.logging import get_logger

logger = get_logger("mcp")

RESOURCE_METADATA_URL = f"{oauth.ISSUER}/.well-known/oauth-protected-resource"
MAX_BODY_BYTES = 256 * 1024


def _response(
    status: int,
    body: str | dict[str, Any] | None,
    headers: dict[str, str] | None = None,
    *,
    content_type: str = "application/json",
) -> dict[str, Any]:
    payload = json.dumps(body, ensure_ascii=False) if isinstance(body, dict) else (body or "")
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": content_type,
            # Dokumenty discovery i odpowiedzi tokenowe nigdy nie mogą
            # wylądować w cache pośrednika.
            "Cache-Control": "no-store",
            **(headers or {}),
        },
        "body": payload,
    }


def _unauthorized(detail: str) -> dict[str, Any]:
    """401 z WWW-Authenticate — start flow OAuth po stronie klienta.

    Spec: Claude nie honoruje `WWW-Authenticate` na odpowiedzi 200, więc
    status MUSI być 401, a `resource_metadata` musi wskazywać dokument RFC 9728.
    """
    return _response(
        401,
        {"error": "unauthorized", "error_description": detail},
        {"WWW-Authenticate": f'Bearer resource_metadata="{RESOURCE_METADATA_URL}"'},
    )


def _oauth_error(exc: oauth.OAuthError) -> dict[str, Any]:
    return _response(exc.status, oauth.error_body(exc))


def _query(event: dict[str, Any]) -> dict[str, Any]:
    return event.get("queryStringParameters") or {}


def raw_body(event: dict[str, Any]) -> str:
    """Body requestu, zdekodowane gdy API Gateway zakodował je base64.

    HTTP API v2 traktuje `application/json` jako tekst i przekazuje wprost,
    ale `application/x-www-form-urlencoded` uznaje za binarny i **koduje
    base64**, ustawiając `isBase64Encoded: true`. Czytanie `event["body"]`
    wprost działa więc dla JSON-a i po cichu zwraca śmieci dla formularzy —
    czego skutkiem był `brak request_token` po kliknięciu "Zezwalam"
    na produkcji.
    """
    raw = event.get("body") or ""
    if not event.get("isBase64Encoded"):
        return raw
    try:
        return base64.b64decode(raw).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return ""


def _form(event: dict[str, Any]) -> dict[str, str]:
    """Parsuje `application/x-www-form-urlencoded`.

    RFC 6749 §4.1.3 — Claude wysyła tak zarówno wymianę kodu, jak i refresh,
    a przeglądarka tak samo wysyła formularz z ekranu zgody.
    """
    return {k: v[0] for k, v in parse_qs(raw_body(event), keep_blank_values=True).items()}


def _session_user(event: dict[str, Any]) -> dict[str, Any] | None:
    """User zalogowany cookie `bodysync_session`, albo None."""
    token = extract_session_cookie(event)
    if not token:
        return None
    try:
        payload = verify_jwt(token)
    except SessionAuthError:
        return None
    return payload if isinstance(payload.get("user_id"), str) else None


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = getattr(context, "aws_request_id", "local")
    route = event.get("routeKey", "")

    try:
        if route == "GET /.well-known/oauth-protected-resource":
            return _response(200, oauth.protected_resource_metadata())
        if route == "GET /.well-known/oauth-authorization-server":
            return _response(200, oauth.authorization_server_metadata())
        if route == "POST /mcp/register":
            return _handle_register(event)
        if route == "GET /mcp/authorize":
            return _handle_authorize_get(event)
        if route == "POST /mcp/authorize":
            return _handle_authorize_post(event, request_id=request_id)
        if route == "POST /mcp/token":
            return _response(200, oauth.handle_token_request(_form(event)))
        if route == "POST /mcp":
            return _handle_rpc(event, request_id=request_id)
    except oauth.OAuthError as exc:
        logger.info("mcp_oauth_error", extra={"request_id": request_id, "code": exc.code})
        return _oauth_error(exc)

    return _response(404, {"error": "not_found", "error_description": f"nieznana trasa: {route}"})


def _handle_register(event: dict[str, Any]) -> dict[str, Any]:
    try:
        body = json.loads(raw_body(event) or "{}")
    except json.JSONDecodeError as exc:
        raise oauth.OAuthError("invalid_request", "body nie jest poprawnym JSON-em") from exc
    if not isinstance(body, dict):
        raise oauth.OAuthError("invalid_request", "oczekiwano obiektu JSON")
    return _response(201, oauth.register_client(body))


def _handle_authorize_get(event: dict[str, Any]) -> dict[str, Any]:
    request = oauth.validate_authorize_request(_query(event))

    session = _session_user(event)
    if session is None:
        # Brak sesji → login na froncie, potem powrót tutaj.
        return _response(
            302, None, {"Location": oauth.login_redirect_url(event.get("rawQueryString") or "")}
        )

    page = oauth.consent_page(
        request,
        request_token=oauth.mint_request_token(request),
        user_email=_profile_email(str(session["user_id"])),
    )
    return _response(200, page, content_type="text/html; charset=utf-8")


def _profile_email(user_id: str) -> str:
    """Mail do wyświetlenia na ekranie zgody. JWT sesyjny niesie tylko
    `user_id`, a przy udzielaniu dostępu warto widzieć, które to konto."""
    profile = get_item(f"USER#{user_id}", "PROFILE") or {}
    email = profile.get("email")
    return str(email) if isinstance(email, str) else user_id


def _handle_authorize_post(event: dict[str, Any], *, request_id: str) -> dict[str, Any]:
    session = _session_user(event)
    if session is None:
        # Zgoda bez ważnej sesji — nie ma komu udzielić dostępu.
        raise oauth.OAuthError("access_denied", "sesja wygasła, zaloguj się ponownie", status=401)

    request = oauth.verify_request_token(_form(event).get("request_token"))
    code = oauth.issue_authorization_code(request, user_id=str(session["user_id"]))
    logger.info(
        "mcp_authorize_granted",
        extra={
            "request_id": request_id,
            "user_id": session["user_id"],
            "client_id": request["client_id"],
        },
    )
    return _response(302, None, {"Location": oauth.success_redirect_url(request, code)})


def _handle_rpc(event: dict[str, Any], *, request_id: str) -> dict[str, Any]:
    raw = raw_body(event)
    if len(raw) > MAX_BODY_BYTES:
        return _response(413, {"error": "payload_too_large"})

    try:
        user_id = resolve_user_id(event)
    except AuthError as exc:
        logger.info("mcp_unauthorized", extra={"request_id": request_id, "reason": str(exc)})
        return _unauthorized(str(exc))

    try:
        message = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        logger.info("mcp_parse_error", extra={"request_id": request_id})
        return _response(
            400,
            {
                "jsonrpc": protocol.JSONRPC_VERSION,
                "id": None,
                "error": {
                    "code": protocol.PARSE_ERROR,
                    "message": "body nie jest poprawnym JSON-em",
                },
            },
        )

    reply = protocol.dispatch(message, user_id=user_id)
    if reply is None:
        # Notyfikacja — JSON-RPC nie przewiduje odpowiedzi.
        return _response(202, None)
    return _response(200, reply)

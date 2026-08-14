"""Serwer autoryzacji OAuth 2.0 dla konektora MCP.

Claude nie pozwala wpiąć statycznego nagłówka na planach indywidualnych
(zweryfikowane w UI, ADR-010 decyzja 3), a spec autoryzacji MCP zabrania
tokenów w URL. Zostaje OAuth — ale nie budujemy własnego systemu tożsamości:
`/authorize` sprawdza istniejące cookie `bodysync_session`, czyli reużywa
działający login Google i allowlistę 2 maili.

Endpointy:
  GET  /.well-known/oauth-protected-resource   RFC 9728
  GET  /.well-known/oauth-authorization-server RFC 8414
  POST /mcp/register                           RFC 7591 (DCR, klient publiczny)
  GET  /mcp/authorize                          ekran zgody
  POST /mcp/authorize                          wydanie kodu
  POST /mcp/token                              wymiana kodu / refresh

Kontrole bezpieczeństwa:
  - PKCE S256 wymagane; `plain` odrzucane
  - `redirect_uri` musi być dokładnie tym zarejestrowanym, a jego host musi
    należeć do allowlisty (claude.ai / claude.com / loopback dla Claude Code)
  - kod autoryzacyjny jednorazowy (atomowy delete) z TTL 60 s, związany
    z client_id + redirect_uri + code_challenge
  - refresh tokeny rotowane przy każdym użyciu (wymóg spec dla klientów
    publicznych), trzymane jako SHA-256, nigdy w postaci jawnej
  - access token podpisany ODDZIELNYM sekretem niż cookie sesyjne, z `aud`
    i `typ` — token MCP nie może zostać użyty jako sesja aplikacji
  - między GET a POST /authorize parametry niesie podpisany `request_token`,
    co blokuje ich podmianę i działa jak zabezpieczenie CSRF
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import secrets
import time
from typing import Any
from urllib.parse import urlencode, urlparse

import jwt

from shared.dynamo import delete_item_if_exists, get_item, put_item
from shared.logging import get_logger
from shared.ssm import load_secure_secret

logger = get_logger("mcp.oauth")

ISSUER = "https://api.bodysync.pl"
MCP_RESOURCE = f"{ISSUER}/mcp"
FRONTEND_LOGIN = "https://bodysync.pl/"

# Osobny sekret od `/bodysync/jwt/signing_secret`. Gdyby access token MCP był
# podpisany tym samym kluczem co cookie sesyjne, `shared.auth.verify_jwt`
# przyjęłoby go jako sesję — token do odczytu stałby się pełnym dostępem
# zapisu (profil, pomiary, advisor). Rozdzielenie kluczy zamyka tę ścieżkę.
TOKEN_SECRET_PARAM = "/bodysync/mcp/token_signing_secret"
TOKEN_ALGORITHM = "HS256"

ACCESS_TOKEN_TTL_SECONDS = 3600
REFRESH_TOKEN_TTL_SECONDS = 30 * 24 * 3600
AUTH_CODE_TTL_SECONDS = 60
REQUEST_TOKEN_TTL_SECONDS = 300
CLIENT_REGISTRATION_TTL_SECONDS = 90 * 24 * 3600

ACCESS_TOKEN_TYPE = "mcp_access"
REQUEST_TOKEN_TYPE = "mcp_authorize_request"

# Dokąd wolno odesłać kod autoryzacyjny. Rejestracja klienta jest otwarta
# (DCR), więc to ta lista — a nie rejestracja — decyduje, że kod nie trafi
# pod kontrolę osoby trzeciej.
ALLOWED_REDIRECT_HOSTS = frozenset({"claude.ai", "claude.com"})
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1"})


class OAuthError(Exception):
    """Błąd zgodny z RFC 6749 — `code` trafia do pola `error` odpowiedzi."""

    def __init__(self, code: str, description: str, *, status: int = 400) -> None:
        super().__init__(description)
        self.code = code
        self.description = description
        self.status = status


# ---------------------------------------------------------------- utilities


def _now() -> int:
    return int(time.time())


def _token_secret() -> str:
    return load_secure_secret(TOKEN_SECRET_PARAM, min_length=32)


def _sha256_b64url(raw: str) -> str:
    digest = hashlib.sha256(raw.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _hash_token(token: str) -> str:
    """Refresh tokeny trzymamy jako hash — wyciek tabeli nie daje dostępu."""
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _redirect_uri_allowed(uri: str) -> bool:
    parsed = urlparse(uri)
    if parsed.hostname in LOOPBACK_HOSTS:
        # RFC 8252: Claude Code używa loopbacku na losowym porcie.
        return parsed.scheme in ("http", "https")
    return parsed.scheme == "https" and parsed.hostname in ALLOWED_REDIRECT_HOSTS


# ------------------------------------------------------------- discovery


def protected_resource_metadata() -> dict[str, Any]:
    """RFC 9728. `resource` musi się zgadzać z URL-em wpisanym w Claude."""
    return {
        "resource": MCP_RESOURCE,
        "authorization_servers": [ISSUER],
        "bearer_methods_supported": ["header"],
        "scopes_supported": ["bodysync:read"],
    }


def authorization_server_metadata() -> dict[str, Any]:
    """RFC 8414. `code_challenge_methods_supported` jest wymagane przez spec
    MCP, żeby klient mógł zweryfikować wsparcie PKCE przed startem flow."""
    return {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/mcp/authorize",
        "token_endpoint": f"{ISSUER}/mcp/token",
        "registration_endpoint": f"{ISSUER}/mcp/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": ["bodysync:read"],
    }


# ------------------------------------------------------ dynamic registration


def register_client(body: dict[str, Any]) -> dict[str, Any]:
    """RFC 7591. Rejestrujemy wyłącznie klientów publicznych (bez sekretu),
    bo Claude uwierzytelnia się PKCE."""
    redirect_uris = body.get("redirect_uris")
    if not isinstance(redirect_uris, list) or not redirect_uris:
        raise OAuthError("invalid_redirect_uri", "`redirect_uris` musi być niepustą listą")
    if not all(isinstance(u, str) and _redirect_uri_allowed(u) for u in redirect_uris):
        raise OAuthError(
            "invalid_redirect_uri",
            "redirect_uri musi wskazywać na claude.ai/claude.com przez https albo na loopback",
        )

    client_id = f"mcp-{secrets.token_urlsafe(24)}"
    client_name = str(body.get("client_name") or "nieznany klient")[:120]
    put_item(
        pk=f"MCP_CLIENT#{client_id}",
        sk="REGISTRATION",
        attrs={
            "redirect_uris": redirect_uris,
            "client_name": client_name,
            "created_at": _now(),
            "ttl": _now() + CLIENT_REGISTRATION_TTL_SECONDS,
        },
    )
    logger.info("mcp_client_registered", extra={"client_id": client_id, "client_name": client_name})

    return {
        "client_id": client_id,
        "client_name": client_name,
        "redirect_uris": redirect_uris,
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "client_id_issued_at": _now(),
    }


def _load_client(client_id: Any) -> dict[str, Any]:
    if not isinstance(client_id, str) or not client_id:
        raise OAuthError("invalid_client", "brak `client_id`")
    item = get_item(f"MCP_CLIENT#{client_id}", "REGISTRATION")
    if item is None:
        raise OAuthError("invalid_client", "nieznany `client_id` — zarejestruj klienta ponownie")
    return item


# ------------------------------------------------------------- authorize


def validate_authorize_request(params: dict[str, Any]) -> dict[str, Any]:
    """Waliduje parametry `/authorize` i zwraca znormalizowany komplet."""
    client = _load_client(params.get("client_id"))

    redirect_uri = params.get("redirect_uri")
    if redirect_uri not in client["redirect_uris"]:
        # Świadomie NIE przekierowujemy — nieznane redirect_uri to potencjalny
        # open redirect, więc błąd zostaje na naszej stronie.
        raise OAuthError("invalid_request", "`redirect_uri` nie pasuje do rejestracji klienta")

    if params.get("response_type") != "code":
        raise OAuthError("unsupported_response_type", "wspieramy wyłącznie `response_type=code`")
    if params.get("code_challenge_method") != "S256":
        raise OAuthError("invalid_request", "PKCE `S256` jest wymagane; `plain` nie jest wspierane")
    challenge = params.get("code_challenge")
    if not isinstance(challenge, str) or len(challenge) < 43:
        raise OAuthError("invalid_request", "brak poprawnego `code_challenge`")

    return {
        "client_id": params["client_id"],
        "client_name": client.get("client_name", "nieznany klient"),
        "redirect_uri": redirect_uri,
        "code_challenge": challenge,
        "state": params.get("state") or "",
        "resource": params.get("resource") or MCP_RESOURCE,
    }


def mint_request_token(request: dict[str, Any]) -> str:
    """Podpisany nośnik parametrów między ekranem zgody a wydaniem kodu.

    Blokuje podmianę `redirect_uri`/`code_challenge` po wyświetleniu zgody
    i pełni rolę tokenu CSRF — atakujący nie potrafi go wytworzyć.
    """
    payload = {**request, "typ": REQUEST_TOKEN_TYPE, "exp": _now() + REQUEST_TOKEN_TTL_SECONDS}
    return jwt.encode(payload, _token_secret(), algorithm=TOKEN_ALGORITHM)


def verify_request_token(token: Any) -> dict[str, Any]:
    if not isinstance(token, str) or not token:
        raise OAuthError("invalid_request", "brak `request_token`")
    try:
        payload = jwt.decode(token, _token_secret(), algorithms=[TOKEN_ALGORITHM])
    except jwt.InvalidTokenError as exc:
        raise OAuthError("invalid_request", "`request_token` wygasł lub jest niepoprawny") from exc
    if payload.get("typ") != REQUEST_TOKEN_TYPE:
        raise OAuthError("invalid_request", "niewłaściwy typ tokenu")
    return payload


def issue_authorization_code(request: dict[str, Any], *, user_id: str) -> str:
    """Kod jednorazowy z TTL 60 s, związany z klientem, redirectem i PKCE."""
    code = secrets.token_urlsafe(32)
    put_item(
        pk=f"MCP_CODE#{code}",
        sk="CODE",
        attrs={
            "user_id": user_id,
            "client_id": request["client_id"],
            "redirect_uri": request["redirect_uri"],
            "code_challenge": request["code_challenge"],
            "ttl": _now() + AUTH_CODE_TTL_SECONDS,
        },
    )
    logger.info("mcp_code_issued", extra={"client_id": request["client_id"], "user_id": user_id})
    return code


def consent_page(request: dict[str, Any], *, request_token: str, user_email: str) -> str:
    """Ekran zgody. Wszystkie wartości sterowane z zewnątrz są escapowane —
    `client_name` i `redirect_uri` pochodzą z otwartej rejestracji."""
    return f"""<!doctype html>
<html lang="pl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>bodysync — zgoda na dostęp</title>
<style>
 body{{background:#0a0e17;color:#e8eef7;font-family:system-ui,-apple-system,sans-serif;
      display:flex;align-items:center;justify-content:center;min-height:100dvh;margin:0;padding:1rem}}
 .card{{background:#1a2332;border:1px solid #2a3548;border-radius:14px;padding:2rem;max-width:30rem}}
 h1{{font-size:1.2rem;margin:0 0 1rem}} dl{{margin:1.2rem 0;font-size:.9rem}}
 dt{{color:#5a6f8e;margin-top:.6rem}} dd{{margin:.15rem 0 0;word-break:break-all}}
 ul{{font-size:.9rem;color:#a9bad2;padding-left:1.1rem}}
 button{{background:#22d3ee;color:#06232b;border:0;border-radius:9px;padding:.7rem 1.3rem;
         font-weight:700;font-size:.95rem;cursor:pointer;width:100%}}
 .muted{{color:#5a6f8e;font-size:.8rem;margin-top:1rem}}
</style></head><body><div class="card">
<h1>Udzielić dostępu do Twoich danych?</h1>
<dl>
  <dt>Aplikacja</dt><dd>{html.escape(request["client_name"])}</dd>
  <dt>Przekieruje do</dt><dd>{html.escape(request["redirect_uri"])}</dd>
  <dt>Twoje konto</dt><dd>{html.escape(user_email)}</dd>
</dl>
<p style="font-size:.9rem">Aplikacja będzie mogła <strong>odczytywać</strong>:</p>
<ul>
  <li>skład ciała i obwody</li>
  <li>metryki dzienne: kalorie, makro, kroki, sen, tętno</li>
  <li>historię treningów siłowych</li>
</ul>
<p style="font-size:.9rem">Nie może niczego zapisywać ani usuwać.</p>
<form method="POST" action="/mcp/authorize">
  <input type="hidden" name="request_token" value="{html.escape(request_token)}">
  <button type="submit">Zezwalam</button>
</form>
<p class="muted">Jeśli nie próbujesz właśnie podłączyć konektora — zamknij tę stronę.</p>
</div></body></html>"""


def login_redirect_url(query_string: str) -> str:
    """Brak sesji → login na froncie, z powrotem tutaj po zalogowaniu."""
    back = f"{ISSUER}/mcp/authorize?{query_string}" if query_string else f"{ISSUER}/mcp/authorize"
    return f"{FRONTEND_LOGIN}?{urlencode({'mcp_return_to': back})}"


def success_redirect_url(request: dict[str, Any], code: str) -> str:
    params = {"code": code}
    if request.get("state"):
        params["state"] = request["state"]
    return f"{request['redirect_uri']}?{urlencode(params)}"


# ----------------------------------------------------------------- token


def _mint_access_token(user_id: str, client_id: str) -> str:
    payload = {
        "iss": ISSUER,
        "aud": MCP_RESOURCE,
        "sub": user_id,
        "client_id": client_id,
        "typ": ACCESS_TOKEN_TYPE,
        "iat": _now(),
        "exp": _now() + ACCESS_TOKEN_TTL_SECONDS,
    }
    return jwt.encode(payload, _token_secret(), algorithm=TOKEN_ALGORITHM)


def _mint_refresh_token(user_id: str, client_id: str) -> str:
    token = secrets.token_urlsafe(40)
    put_item(
        pk=f"MCP_REFRESH#{_hash_token(token)}",
        sk="TOKEN",
        attrs={
            "user_id": user_id,
            "client_id": client_id,
            "ttl": _now() + REFRESH_TOKEN_TTL_SECONDS,
        },
    )
    return token


def _token_response(user_id: str, client_id: str) -> dict[str, Any]:
    return {
        "access_token": _mint_access_token(user_id, client_id),
        "token_type": "Bearer",
        "expires_in": ACCESS_TOKEN_TTL_SECONDS,
        "refresh_token": _mint_refresh_token(user_id, client_id),
        "scope": "bodysync:read",
    }


def exchange_authorization_code(form: dict[str, str]) -> dict[str, Any]:
    code = form.get("code")
    if not code:
        raise OAuthError("invalid_request", "brak `code`")

    # Atomowy delete = jednorazowość kodu. Dwa równoległe żądania: tylko
    # pierwsze dostanie item, drugie zobaczy None.
    item = delete_item_if_exists(f"MCP_CODE#{code}", "CODE")
    if item is None:
        raise OAuthError("invalid_grant", "kod nieznany, już użyty albo wygasł")
    if int(item.get("ttl", 0)) < _now():
        raise OAuthError("invalid_grant", "kod wygasł")

    if form.get("client_id") != item["client_id"]:
        raise OAuthError("invalid_grant", "`client_id` nie zgadza się z kodem")
    if form.get("redirect_uri") != item["redirect_uri"]:
        raise OAuthError("invalid_grant", "`redirect_uri` nie zgadza się z kodem")

    verifier = form.get("code_verifier")
    if not verifier:
        raise OAuthError("invalid_request", "brak `code_verifier` (PKCE)")
    if not secrets.compare_digest(_sha256_b64url(verifier), str(item["code_challenge"])):
        raise OAuthError("invalid_grant", "`code_verifier` nie pasuje do `code_challenge`")

    logger.info(
        "mcp_token_issued",
        extra={"client_id": item["client_id"], "user_id": item["user_id"], "grant": "code"},
    )
    return _token_response(str(item["user_id"]), str(item["client_id"]))


def exchange_refresh_token(form: dict[str, str]) -> dict[str, Any]:
    token = form.get("refresh_token")
    if not token:
        raise OAuthError("invalid_request", "brak `refresh_token`")

    # Rotacja: stary token znika w tej samej operacji, w której go czytamy.
    # Spec MCP wymaga rotacji dla klientów publicznych.
    item = delete_item_if_exists(f"MCP_REFRESH#{_hash_token(token)}", "TOKEN")
    if item is None:
        raise OAuthError("invalid_grant", "refresh token nieznany, już użyty albo wygasł")
    if int(item.get("ttl", 0)) < _now():
        raise OAuthError("invalid_grant", "refresh token wygasł")
    if form.get("client_id") and form["client_id"] != item["client_id"]:
        raise OAuthError("invalid_grant", "`client_id` nie zgadza się z tokenem")

    logger.info(
        "mcp_token_issued",
        extra={"client_id": item["client_id"], "user_id": item["user_id"], "grant": "refresh"},
    )
    return _token_response(str(item["user_id"]), str(item["client_id"]))


def handle_token_request(form: dict[str, str]) -> dict[str, Any]:
    grant = form.get("grant_type")
    if grant == "authorization_code":
        return exchange_authorization_code(form)
    if grant == "refresh_token":
        return exchange_refresh_token(form)
    raise OAuthError("unsupported_grant_type", f"nieobsługiwany `grant_type`: {grant!r}")


# --------------------------------------------------------- token validation


def user_id_from_access_token(token: str) -> str:
    """Weryfikuje access token i zwraca `user_id`. Rzuca `OAuthError`."""
    try:
        payload = jwt.decode(
            token,
            _token_secret(),
            algorithms=[TOKEN_ALGORITHM],
            audience=MCP_RESOURCE,
            issuer=ISSUER,
        )
    except jwt.InvalidTokenError as exc:
        raise OAuthError("invalid_token", "token wygasł lub jest niepoprawny", status=401) from exc

    if payload.get("typ") != ACCESS_TOKEN_TYPE:
        # Blokuje podanie tokenu innego typu (np. request_token) jako access.
        raise OAuthError("invalid_token", "niewłaściwy typ tokenu", status=401)
    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise OAuthError("invalid_token", "token bez `sub`", status=401)
    return user_id


def error_body(exc: OAuthError) -> str:
    return json.dumps({"error": exc.code, "error_description": exc.description}, ensure_ascii=False)

"""Tests dla serwera autoryzacji OAuth MCP.

Nacisk na kontrole bezpieczeństwa: PKCE, jednorazowość kodu, rotacja refresh
tokenów, allowlista redirect_uri, rozdzielenie sekretów od cookie sesyjnego.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any

import pytest

CLAUDE_REDIRECT = "https://claude.ai/api/mcp/auth_callback"
VERIFIER = "a" * 64


def _challenge(verifier: str = VERIFIER) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _register(oauth: Any, redirect: str = CLAUDE_REDIRECT) -> str:
    return oauth.register_client({"redirect_uris": [redirect], "client_name": "Claude"})[
        "client_id"
    ]


def _authorize_params(client_id: str, **over: Any) -> dict[str, Any]:
    return {
        "client_id": client_id,
        "redirect_uri": CLAUDE_REDIRECT,
        "response_type": "code",
        "code_challenge": _challenge(),
        "code_challenge_method": "S256",
        "state": "xyz",
        **over,
    }


# ------------------------------------------------------------- discovery


def test_protected_resource_matches_mcp_url(oauth_env: Any) -> None:
    """Spec: `resource` musi być dokładnie URL-em wpisywanym w Claude."""
    doc = oauth_env.protected_resource_metadata()

    assert doc["resource"] == "https://api.bodysync.pl/mcp"
    assert doc["authorization_servers"] == ["https://api.bodysync.pl"]


def test_as_metadata_advertises_s256(oauth_env: Any) -> None:
    """Bez `code_challenge_methods_supported` klient nie zweryfikuje PKCE."""
    doc = oauth_env.authorization_server_metadata()

    assert doc["code_challenge_methods_supported"] == ["S256"]
    assert doc["token_endpoint_auth_methods_supported"] == ["none"]


# ---------------------------------------------------------- registration


def test_register_rejects_foreign_redirect_host(oauth_env: Any) -> None:
    """Rejestracja jest otwarta (DCR), więc to allowlista hostów decyduje,
    że kod nie trafi pod kontrolę osoby trzeciej."""
    for bad in ["https://evil.example/cb", "http://claude.ai/cb", "https://claude.ai.evil.com/cb"]:
        with pytest.raises(oauth_env.OAuthError) as exc:
            oauth_env.register_client({"redirect_uris": [bad]})
        assert exc.value.code == "invalid_redirect_uri"


def test_register_allows_loopback_for_claude_code(oauth_env: Any) -> None:
    """RFC 8252 — Claude Code używa loopbacku na losowym porcie."""
    out = oauth_env.register_client({"redirect_uris": ["http://127.0.0.1:3118/callback"]})

    assert out["client_id"].startswith("mcp-")
    assert out["token_endpoint_auth_method"] == "none"


def test_register_issues_no_client_secret(oauth_env: Any) -> None:
    """Klient publiczny — sekret byłby fikcją, bo Claude i tak by go nie ukrył."""
    assert "client_secret" not in oauth_env.register_client({"redirect_uris": [CLAUDE_REDIRECT]})


# ------------------------------------------------------------- authorize


def test_authorize_requires_s256_pkce(oauth_env: Any) -> None:
    client_id = _register(oauth_env)

    with pytest.raises(oauth_env.OAuthError, match="S256"):
        oauth_env.validate_authorize_request(
            _authorize_params(client_id, code_challenge_method="plain")
        )


def test_authorize_rejects_unregistered_redirect(oauth_env: Any) -> None:
    """Podmiana redirect_uri po rejestracji nie może przejść."""
    client_id = _register(oauth_env)

    with pytest.raises(oauth_env.OAuthError, match="redirect_uri"):
        oauth_env.validate_authorize_request(
            _authorize_params(client_id, redirect_uri="https://claude.ai/inny")
        )


def test_authorize_rejects_unknown_client(oauth_env: Any) -> None:
    with pytest.raises(oauth_env.OAuthError) as exc:
        oauth_env.validate_authorize_request(_authorize_params("mcp-nieistnieje"))

    assert exc.value.code == "invalid_client"


def test_request_token_blocks_tampering_between_consent_and_code(oauth_env: Any) -> None:
    """Podpisany request_token uniemożliwia podmianę redirect_uri po tym,
    jak użytkownik zobaczył ekran zgody."""
    client_id = _register(oauth_env)
    request = oauth_env.validate_authorize_request(_authorize_params(client_id))
    token = oauth_env.mint_request_token(request)

    restored = oauth_env.verify_request_token(token)
    assert restored["redirect_uri"] == CLAUDE_REDIRECT

    with pytest.raises(oauth_env.OAuthError):
        oauth_env.verify_request_token(token[:-4] + "aaaa")


def test_consent_page_escapes_client_controlled_values(oauth_env: Any) -> None:
    """`client_name` pochodzi z otwartej rejestracji — nie może wstrzyknąć HTML."""
    oauth_env.register_client(
        {"redirect_uris": [CLAUDE_REDIRECT], "client_name": "<script>alert(1)</script>"}
    )
    request = {
        "client_name": "<script>alert(1)</script>",
        "redirect_uri": CLAUDE_REDIRECT,
        "client_id": "mcp-x",
        "code_challenge": _challenge(),
        "state": "",
    }

    page = oauth_env.consent_page(request, request_token="tok", user_email="a@b.pl")

    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


# ----------------------------------------------------------------- token


def _issue_code(oauth: Any, client_id: str, user_id: str = "tomek") -> str:
    request = oauth.validate_authorize_request(_authorize_params(client_id))
    return oauth.issue_authorization_code(request, user_id=user_id)


def test_full_code_exchange_returns_usable_access_token(oauth_env: Any) -> None:
    client_id = _register(oauth_env)
    code = _issue_code(oauth_env, client_id)

    tokens = oauth_env.handle_token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": CLAUDE_REDIRECT,
            "code_verifier": VERIFIER,
        }
    )

    assert tokens["token_type"] == "Bearer"
    assert tokens["expires_in"] == 3600
    assert oauth_env.user_id_from_access_token(tokens["access_token"]) == "tomek"


def test_authorization_code_is_single_use(oauth_env: Any) -> None:
    """Drugie użycie tego samego kodu musi polec — atomowy delete."""
    client_id = _register(oauth_env)
    code = _issue_code(oauth_env, client_id)
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "redirect_uri": CLAUDE_REDIRECT,
        "code_verifier": VERIFIER,
    }

    oauth_env.handle_token_request(form)

    with pytest.raises(oauth_env.OAuthError) as exc:
        oauth_env.handle_token_request(form)
    assert exc.value.code == "invalid_grant"


def test_wrong_pkce_verifier_is_rejected(oauth_env: Any) -> None:
    """Bez tego przechwycony kod wystarczyłby do zdobycia tokenu."""
    client_id = _register(oauth_env)
    code = _issue_code(oauth_env, client_id)

    with pytest.raises(oauth_env.OAuthError) as exc:
        oauth_env.handle_token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "redirect_uri": CLAUDE_REDIRECT,
                "code_verifier": "b" * 64,
            }
        )
    assert exc.value.code == "invalid_grant"


def test_code_bound_to_client_and_redirect(oauth_env: Any) -> None:
    client_id = _register(oauth_env)
    other_id = _register(oauth_env)
    code = _issue_code(oauth_env, client_id)

    with pytest.raises(oauth_env.OAuthError, match="client_id"):
        oauth_env.handle_token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": other_id,
                "redirect_uri": CLAUDE_REDIRECT,
                "code_verifier": VERIFIER,
            }
        )


def test_refresh_token_is_rotated(oauth_env: Any) -> None:
    """Spec MCP wymaga rotacji dla klientów publicznych: stary token musi
    przestać działać w tej samej chwili, w której wydajemy nowy."""
    client_id = _register(oauth_env)
    code = _issue_code(oauth_env, client_id)
    first = oauth_env.handle_token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": CLAUDE_REDIRECT,
            "code_verifier": VERIFIER,
        }
    )

    second = oauth_env.handle_token_request(
        {
            "grant_type": "refresh_token",
            "refresh_token": first["refresh_token"],
            "client_id": client_id,
        }
    )

    assert second["refresh_token"] != first["refresh_token"]
    with pytest.raises(oauth_env.OAuthError) as exc:
        oauth_env.handle_token_request(
            {"grant_type": "refresh_token", "refresh_token": first["refresh_token"]}
        )
    assert exc.value.code == "invalid_grant"


def test_refresh_tokens_are_not_stored_in_plaintext(oauth_env: Any) -> None:
    """Wyciek tabeli nie może oddać ważnych refresh tokenów."""
    from shared.dynamo import get_item

    client_id = _register(oauth_env)
    code = _issue_code(oauth_env, client_id)
    tokens = oauth_env.handle_token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": CLAUDE_REDIRECT,
            "code_verifier": VERIFIER,
        }
    )

    assert get_item(f"MCP_REFRESH#{tokens['refresh_token']}", "TOKEN") is None
    hashed = hashlib.sha256(tokens["refresh_token"].encode()).hexdigest()
    assert get_item(f"MCP_REFRESH#{hashed}", "TOKEN") is not None


def test_unsupported_grant_type(oauth_env: Any) -> None:
    with pytest.raises(oauth_env.OAuthError) as exc:
        oauth_env.handle_token_request({"grant_type": "client_credentials"})

    assert exc.value.code == "unsupported_grant_type"


# ------------------------------------------------- rozdzielenie sekretów


def test_session_cookie_is_not_accepted_as_mcp_token(oauth_env: Any) -> None:
    """Sedno rozdzielenia kluczy: JWT sesyjny aplikacji nie może uwierzytelnić
    requestu MCP."""
    from shared.auth import mint_jwt

    with pytest.raises(oauth_env.OAuthError):
        oauth_env.user_id_from_access_token(mint_jwt("tomek"))


def test_mcp_token_is_not_accepted_as_session_cookie(oauth_env: Any) -> None:
    """Kierunek odwrotny — ważniejszy. Token MCP daje wyłącznie odczyt; gdyby
    przechodził jako sesja, dałby też zapis (profil, pomiary, advisor)."""
    from shared.auth import AuthError as SessionAuthError
    from shared.auth import verify_jwt

    client_id = _register(oauth_env)
    code = _issue_code(oauth_env, client_id)
    tokens = oauth_env.handle_token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": CLAUDE_REDIRECT,
            "code_verifier": VERIFIER,
        }
    )

    with pytest.raises(SessionAuthError):
        verify_jwt(tokens["access_token"])


def test_request_token_cannot_be_used_as_access_token(oauth_env: Any) -> None:
    """Request token i access token dzielą sekret podpisujący, więc muszą je
    rozróżniać claimy. Bronią dwie niezależne bariery: `aud`/`iss` (których
    request token nie ma) oraz pole `typ`."""
    client_id = _register(oauth_env)
    request = oauth_env.validate_authorize_request(_authorize_params(client_id))

    with pytest.raises(oauth_env.OAuthError):
        oauth_env.user_id_from_access_token(oauth_env.mint_request_token(request))


def test_typ_claim_alone_blocks_a_forged_access_token(oauth_env: Any) -> None:
    """Druga bariera osobno: token z poprawnym `aud`/`iss`, ale cudzym `typ`,
    nadal musi polec — inaczej `aud`/`iss` byłyby jedyną obroną."""
    import jwt as pyjwt

    forged = pyjwt.encode(
        {
            "iss": oauth_env.ISSUER,
            "aud": oauth_env.MCP_RESOURCE,
            "sub": "tomek",
            "typ": oauth_env.REQUEST_TOKEN_TYPE,
            "exp": oauth_env._now() + 600,
        },
        oauth_env._token_secret(),
        algorithm=oauth_env.TOKEN_ALGORITHM,
    )

    with pytest.raises(oauth_env.OAuthError, match="typ"):
        oauth_env.user_id_from_access_token(forged)

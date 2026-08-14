"""Tests dla shared.session — unieważnianie sesji przez `token_version`.

Audyt bezpieczeństwa 2026-08-14, Sprint 12 Step 1. Sedno: token przestaje być
samowystarczalny, a jego ważność da się cofnąć bez czekania na `exp` (30 dni).
"""

from __future__ import annotations

from typing import Any

import pytest


def _event(cookie: str | None) -> dict[str, Any]:
    return {"cookies": [f"bodysync_session={cookie}"] if cookie else []}


def _profile(user_id: str, **attrs: Any) -> None:
    from shared.dynamo import put_item

    put_item(pk=f"USER#{user_id}", sk="PROFILE", attrs={"email": f"{user_id}@example.com", **attrs})


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_valid_session_returns_user_id() -> None:
    from shared.auth import mint_jwt
    from shared.session import resolve_session

    _profile("alice", token_version=3)
    assert resolve_session(_event(mint_jwt("alice", token_version=3))) == "alice"


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_legacy_token_without_tv_still_works() -> None:
    """Cookie sprzed deployu nie ma claimu `tv`, profil nie ma atrybutu —
    oba czytane jako 0, więc nikt nie zostaje wylogowany przez sam deploy."""
    import jwt as pyjwt

    from shared.auth import JWT_ALGORITHM, JWT_SSM_PARAM
    from shared.session import resolve_session
    from shared.ssm import load_secure_secret

    _profile("alice")
    legacy = pyjwt.encode(
        {"user_id": "alice", "exp": 2**31 - 1},
        load_secure_secret(JWT_SSM_PARAM, min_length=32),
        algorithm=JWT_ALGORITHM,
    )
    assert resolve_session(_event(legacy)) == "alice"


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_bump_revokes_previously_issued_token() -> None:
    """Rdzeń całego sprintu: token wydany przed bumpem przestaje działać."""
    from shared.auth import mint_jwt
    from shared.session import SessionError, bump_token_version, resolve_session

    _profile("alice")
    token = mint_jwt("alice", token_version=0)
    assert resolve_session(_event(token)) == "alice"

    assert bump_token_version("alice") == 1

    with pytest.raises(SessionError) as exc:
        resolve_session(_event(token))
    assert exc.value.reason == "session_revoked"


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_bump_does_not_touch_other_user() -> None:
    """Wylogowanie Alice nie może wywalić Boba (PK isolation dla revocation)."""
    from shared.auth import mint_jwt
    from shared.session import bump_token_version, resolve_session

    _profile("alice")
    _profile("bob")
    bob_token = mint_jwt("bob", token_version=0)

    bump_token_version("alice")

    assert resolve_session(_event(bob_token)) == "bob"


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_bump_is_atomic_across_repeated_calls() -> None:
    from shared.session import bump_token_version, current_token_version

    _profile("alice")
    assert [bump_token_version("alice") for _ in range(3)] == [1, 2, 3]
    assert current_token_version("alice") == 3


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_deleted_account_token_rejected() -> None:
    """Token przeżywa `DELETE /api/me/account` (podpis nadal ważny), ale bez
    profilu nie ma komu przyznać dostępu — inaczej po ponownym użyciu tego
    samego `user_id` stary token zobaczyłby nowe dane."""
    from shared.auth import mint_jwt
    from shared.session import SessionError, resolve_session

    token = mint_jwt("ghost", token_version=0)

    with pytest.raises(SessionError) as exc:
        resolve_session(_event(token))
    assert exc.value.reason == "profile_missing"


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_missing_cookie_rejected() -> None:
    from shared.session import SessionError, resolve_session

    with pytest.raises(SessionError) as exc:
        resolve_session(_event(None))
    assert exc.value.reason == "cookie_missing"


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_tampered_signature_rejected() -> None:
    from shared.auth import mint_jwt
    from shared.session import SessionError, resolve_session

    _profile("alice")
    with pytest.raises(SessionError) as exc:
        resolve_session(_event(mint_jwt("alice") + "tampered"))
    assert exc.value.reason == "jwt_invalid"


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_forged_tv_claim_does_not_bypass_revocation() -> None:
    """`tv` jest w podpisanej części tokenu — podmiana psuje podpis."""
    import jwt as pyjwt

    from shared.auth import JWT_ALGORITHM, JWT_SSM_PARAM
    from shared.session import SessionError, resolve_session
    from shared.ssm import load_secure_secret

    _profile("alice", token_version=5)
    forged = pyjwt.encode(
        {"user_id": "alice", "tv": 5, "exp": 2**31 - 1},
        "nie-nasz-sekret-tylko-atakujacego-xxxxx",
        algorithm=JWT_ALGORITHM,
    )
    with pytest.raises(SessionError) as exc:
        resolve_session(_event(forged))
    assert exc.value.reason == "jwt_invalid"

    # Kontrola: ten sam payload podpisany naszym sekretem przechodzi, czyli
    # test faktycznie mierzy podpis, a nie przypadkiem coś innego.
    valid = pyjwt.encode(
        {"user_id": "alice", "tv": 5, "exp": 2**31 - 1},
        load_secure_secret(JWT_SSM_PARAM, min_length=32),
        algorithm=JWT_ALGORITHM,
    )
    assert resolve_session(_event(valid)) == "alice"


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_non_integer_tv_claim_rejected() -> None:
    """Claim spoza naszego mintera (string) nie może udawać wersji 0."""
    import jwt as pyjwt

    from shared.auth import JWT_ALGORITHM, JWT_SSM_PARAM
    from shared.session import SessionError, resolve_session
    from shared.ssm import load_secure_secret

    _profile("alice")
    token = pyjwt.encode(
        {"user_id": "alice", "tv": "0", "exp": 2**31 - 1},
        load_secure_secret(JWT_SSM_PARAM, min_length=32),
        algorithm=JWT_ALGORITHM,
    )
    with pytest.raises(SessionError) as exc:
        resolve_session(_event(token))
    assert exc.value.reason == "jwt_bad_token_version"


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_bump_on_missing_profile_raises() -> None:
    """`increment_attr` nie może wyczarować profilu z samym licznikiem."""
    from botocore.exceptions import ClientError

    from shared.session import bump_token_version

    with pytest.raises(ClientError) as exc:
        bump_token_version("ghost")
    assert exc.value.response["Error"]["Code"] == "ConditionalCheckFailedException"


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_login_mints_token_carrying_current_version(monkeypatch: Any) -> None:
    """Po "wyloguj wszędzie" ponowny login musi dawać działające cookie."""
    from handlers.google_auth import service
    from handlers.google_auth.schemas import LoginRequest
    from shared.session import bump_token_version, resolve_session

    _profile("alice")
    bump_token_version("alice")
    bump_token_version("alice")

    monkeypatch.setattr(
        service,
        "_verify_google_token",
        lambda _token: {
            "email": "alice@example.com",
            "email_verified": True,
            "name": "Alice",
            "nonce": "nonce-po-revoke-aaaaaaaa",
        },
    )
    _, token = service.login(
        LoginRequest(id_token="stub-id-token-value", nonce="nonce-po-revoke-aaaaaaaa")
    )

    assert resolve_session(_event(token)) == "alice"

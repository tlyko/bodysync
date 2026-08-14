"""Fixtures wspólne dla testów MCP."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest


@pytest.fixture
def mcp_secret(ssm_params: Any) -> Iterator[None]:
    """Sekret podpisujący tokeny MCP w mocku SSM.

    Osobny od `/bodysync/jwt/signing_secret` — patrz `oauth.TOKEN_SECRET_PARAM`.
    """
    import boto3

    from handlers.mcp import oauth
    from shared import ssm

    boto3.client("ssm", region_name="eu-west-1").put_parameter(
        Name=oauth.TOKEN_SECRET_PARAM,
        Value="s" * 48,
        Type="SecureString",
        Overwrite=True,
    )
    ssm.clear_cache()
    yield
    ssm.clear_cache()


@pytest.fixture
def oauth_env(dynamodb_table: Any, mcp_secret: None) -> Any:
    """Moduł `oauth` z gotowym DDB i sekretem."""
    from handlers.mcp import oauth

    return oauth


@pytest.fixture
def mcp_env(dynamodb_table: Any, mcp_secret: None) -> Any:
    """Moduł `handler` z gotowym DDB i sekretem."""
    from handlers.mcp import handler

    return handler

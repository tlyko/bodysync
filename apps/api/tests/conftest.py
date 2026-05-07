"""Global pytest fixtures.

`dynamodb_table` — moto-mocked DDB single-table z PK/SK + GSI-1.
`ssm_params` — moto-mocked SSM z preset SecureString + String values dla
testów handlerów (Anthropic key, JWT secret, OAuth client_id, allowlist).

Każdy test który dotyka boto3 ma `mock_aws` aktywne via fixture chain.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from moto import mock_aws


@pytest.fixture(autouse=True)
def _aws_credentials() -> None:
    """Avoid accidental AWS calls in tests."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "eu-west-1"
    os.environ["TABLE_NAME"] = "bodysync-data-test"
    os.environ["RAW_BUCKET_NAME"] = "bodysync-data-test-bucket"


@pytest.fixture
def dynamodb_table() -> Iterator[Any]:
    with mock_aws():
        client = boto3.client("dynamodb", region_name="eu-west-1")
        client.create_table(
            TableName="bodysync-data-test",
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "GSI-1",
                    "KeySchema": [
                        {"AttributeName": "SK", "KeyType": "HASH"},
                        {"AttributeName": "PK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
        )
        # Re-import shared.dynamo so its module-level Table() handle picks up
        # the moto resource (autouse fixture runs after import otherwise).
        import importlib

        from shared import dynamo as _dynamo

        importlib.reload(_dynamo)
        yield boto3.resource("dynamodb", region_name="eu-west-1").Table("bodysync-data-test")


@pytest.fixture
def s3_bucket(dynamodb_table: Any) -> Iterator[Any]:
    """Pre-create the raw archive bucket inside the same `mock_aws` context.

    Depends on `dynamodb_table` so the moto session is shared. Returns the
    boto3 client so tests can `head_object`/`get_object` on the archive.
    """
    client = boto3.client("s3", region_name="eu-west-1")
    client.create_bucket(
        Bucket="bodysync-data-test-bucket",
        CreateBucketConfiguration={"LocationConstraint": "eu-west-1"},
    )
    # Reset s3 module-level cached client so the fresh moto bucket binds.
    import importlib

    from shared import s3 as _s3

    importlib.reload(_s3)
    yield client


@pytest.fixture
def ssm_params(dynamodb_table: Any) -> Iterator[None]:
    """Pre-seed SSM with values used by handlers under test.

    Depends on dynamodb_table so `mock_aws` is already active and we share
    one mock instance across DDB + SSM in a test.
    """
    client = boto3.client("ssm", region_name="eu-west-1")
    client.put_parameter(
        Name="/bodysync/jwt/signing_secret",
        Value="test-jwt-secret-do-not-use-in-prod",
        Type="SecureString",
    )
    client.put_parameter(
        Name="/bodysync/google/oauth_client_id",
        Value="test-google-client-id.apps.googleusercontent.com",
        Type="String",
    )
    client.put_parameter(
        Name="/bodysync/auth/allowed_emails",
        Value=json.dumps(
            [
                {"email": "alice@example.com", "user_id": "alice"},
                {"email": "bob@example.com", "user_id": "bob"},
            ]
        ),
        Type="String",
    )
    # HAE webhook secrets per user — handler resolves user_id po
    # Bearer match. Wartości muszą mieć ≥32 chars (load_secure_secret guard).
    client.put_parameter(
        Name="/bodysync/health-auto-export/webhook_secret_tomek",
        Value="tomek-webhook-secret-aaaaaaaaaaaaaaaa",
        Type="SecureString",
    )
    client.put_parameter(
        Name="/bodysync/health-auto-export/webhook_secret_weronika",
        Value="weronika-webhook-secret-bbbbbbbbbbbbbb",
        Type="SecureString",
    )
    # Reset module-level cache so the test's SSM values are read fresh.
    from shared import ssm as _ssm

    _ssm.clear_cache()
    yield
    _ssm.clear_cache()

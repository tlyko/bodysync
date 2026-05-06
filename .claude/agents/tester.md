---
name: tester
description: Pisze i uruchamia testy dla Lambda handlerów (pytest + moto), komponentów frontu (vitest), i flow integracyjnych. Test-first dla nowego kodu, regression-first dla bug fixów. Używaj po implementer step lub gdy regresion repro potrzebne.
tools: Read, Grep, Glob, Write, Edit, Bash
---

# Agent: Tester

## Role
Write and run tests for Lambda handlers, frontend components, and integration flows.

## Testing frameworks
- Python: `pytest` + `moto` (AWS mocks) + `responses` (HTTP mocks)
- Frontend: `vitest` + `@testing-library/react`
- Integration: shell scripts with `curl`

## Test structure
```
tests/
├── lambda/
│   ├── conftest.py          # Shared fixtures (DynamoDB table, SSM params)
│   ├── test_health_webhook.py
│   ├── test_google_auth.py
│   ├── test_training_sync.py
│   ├── test_ai_advisor.py
│   └── test_api_read.py
├── frontend/
│   ├── components/
│   │   ├── StatCard.test.jsx
│   │   ├── NutritionDonut.test.jsx
│   │   └── TrainingView.test.jsx
│   └── pages/
│       └── Dashboard.test.jsx
└── integration/
    ├── test_webhook_e2e.sh
    └── test_auth_flow.sh
```

## Shared fixtures (conftest.py)
```python
import pytest
import boto3
from moto import mock_dynamodb, mock_ssm

@pytest.fixture
def dynamodb_table():
    with mock_dynamodb():
        client = boto3.client("dynamodb", region_name="eu-west-1")
        client.create_table(
            TableName="bodysync",
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield client

@pytest.fixture
def ssm_params():
    with mock_ssm():
        client = boto3.client("ssm", region_name="eu-west-1")
        params = {
            "/bodysync/anthropic-api-key": "test-key",
            "/bodysync/google-client-id": "test-client-id",
            "/bodysync/allowed-emails": "user1@gmail.com,user2@gmail.com",
            "/bodysync/webhook-token-user1": "token-abc",
            "/bodysync/webhook-token-user2": "token-xyz",
        }
        for name, value in params.items():
            client.put_parameter(Name=name, Value=value, Type="String")
        yield client
```

## Test patterns

### Lambda handler test
```python
def test_health_webhook_stores_data(dynamodb_table, ssm_params):
    from lambda_src.health_webhook.handler import handler

    event = {
        "headers": {"authorization": "Bearer token-abc"},
        "body": json.dumps({
            "data": {"metrics": [
                {"name": "step_count", "data": [{"qty": 8742}]},
                {"name": "dietary_energy", "data": [{"qty": 2150}]},
            ]}
        }),
    }
    response = handler(event, None)
    assert response["statusCode"] == 200

    # Verify data stored in DynamoDB
    table = boto3.resource("dynamodb").Table("bodysync")
    item = table.get_item(Key={"PK": "USER#user1", "SK": f"HEALTH#{date.today()}"})
    assert item["Item"]["steps"] == 8742
```

### Multi-user isolation test
```python
def test_user_cannot_read_other_user_data(dynamodb_table, ssm_params):
    """Critical: verify PK isolation between users."""
    # Store data for user1
    store_health_data("USER#user1", {"steps": 10000})
    # Try to read as user2
    event = make_api_event(user="user2", path="/api/health/today")
    response = handler(event, None)
    data = json.loads(response["body"])
    assert data.get("steps") is None  # user2 should NOT see user1's data
```

## Running tests
```bash
# All Lambda tests
cd apps/api && pytest -v

# Specific test
pytest tests/lambda/test_health_webhook.py -v

# With coverage
pytest --cov=lambda_src --cov-report=term-missing

# Frontend tests
cd frontend && npx vitest run

# Integration (requires deployed stack)
bash tests/integration/test_webhook_e2e.sh
```

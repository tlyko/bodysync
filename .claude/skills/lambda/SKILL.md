# Skill: Lambda Backend

## When to use
Writing or modifying Lambda handler code, shared utilities, DynamoDB operations, or webhook parsing.

## Handler pattern
Every Lambda follows this structure:
```python
import json
import logging
from shared.dynamo import get_item, put_item
from shared.auth import verify_jwt

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def handler(event, context):
    """Short description of what this Lambda does."""
    try:
        # 1. Auth (if API GW trigger)
        user_id = verify_jwt(event["headers"].get("authorization", ""))

        # 2. Parse input
        body = json.loads(event.get("body", "{}"))

        # 3. Business logic (call service functions)
        result = do_something(user_id, body)

        # 4. Return
        return {"statusCode": 200, "body": json.dumps(result, ensure_ascii=False)}
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
```

## Shared modules (`lambda-src/shared/`)
- `dynamo.py` — DynamoDB helpers: `get_item(pk, sk)`, `put_item(pk, sk, data)`, `query_by_date_range(pk, sk_prefix, start, end)`
- `auth.py` — `verify_jwt(token)` → returns user_id or raises 401. `verify_webhook_token(token)` for HAE.
- `ssm.py` — `get_param(name)` with caching (avoid repeated SSM calls in warm Lambda)
- `anthropic_client.py` — Anthropic API wrapper with prompt caching setup

## Health Auto Export webhook payload
The webhook receives POST with JSON array of metrics. Key mapping:
```python
HAE_METRIC_MAP = {
    "active_energy": "active_calories",
    "dietary_energy": "calories_consumed",
    "dietary_protein": "protein",
    "dietary_carbohydrates": "carbs",
    "dietary_fat_total": "fat",
    "step_count": "steps",
    "heart_rate": "heart_rate",
    "resting_heart_rate": "resting_hr",
    "body_mass": "weight",
    "body_fat_percentage": "body_fat",
    "sleep_analysis": "sleep",
}
```

## Google Sheets integration
- Use `google-auth` + `gspread` libraries
- Service account key stored in SSM at `/syncbody/google-sa-key`
- Read spreadsheet by ID, parse raw text per week, save AS-IS to DynamoDB TRAINING# record
- Cron every 6 hours — don't over-parse, let AI advisor handle interpretation

## Testing
- Use `moto` to mock DynamoDB
- Use `responses` library to mock HTTP calls (Anthropic API, Google Sheets, Strava)
- Every handler test covers: happy path, missing auth, invalid payload, DynamoDB error
- Test file naming: `test_{function_name}.py` next to `handler.py`

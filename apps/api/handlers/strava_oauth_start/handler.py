"""Skeleton — Step 2 zaimplementuje GET /api/strava/oauth/start.

W Step 1 tylko placeholder żeby `scripts/build.py` autodiscovery widziało
moduł. Handler zwraca 501 do czasu Step 2.
"""

from __future__ import annotations

from typing import Any


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return {
        "statusCode": 501,
        "headers": {"Content-Type": "text/plain"},
        "body": "WIP — Sprint 4 Step 2",
    }

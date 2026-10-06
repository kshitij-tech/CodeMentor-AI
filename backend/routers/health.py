from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text

from backend.database import engine

router = APIRouter(tags=['Health'])
SERVICE_VERSION = os.getenv('APP_VERSION', '0.2.0')

def _live_response() -> dict[str, str]:
    return {'status': 'ok', 'service': 'codementor-ai-api', 'version': SERVICE_VERSION}

@router.get('/health')
def health_check() -> dict[str, str]:
    return _live_response()

@router.get('/health/live')
def liveness_check() -> dict[str, str]:
    return _live_response()

@router.get('/health/ready')
def readiness_check() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text('SELECT 1'))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail='Database is not ready.') from exc
    response = _live_response()
    response['database'] = 'ok'
    return response

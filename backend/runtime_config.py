from __future__ import annotations

import os

PRODUCTION_ENVS = {'prod', 'production'}

DEVELOPMENT_CORS_ORIGINS = [
    'http://localhost:3000',
    'http://localhost:5173',
    'http://localhost:5500',
    'http://127.0.0.1:5500',
    'null',
]

def cors_options() -> dict[str, object]:
    app_env = os.getenv('APP_ENV', 'development').strip().lower()
    configured = [origin.strip() for origin in os.getenv('CORS_ORIGINS', '').split(',') if origin.strip()]
    if app_env in PRODUCTION_ENVS and not configured:
        raise RuntimeError('CORS_ORIGINS must be configured for production deployments.')
    options: dict[str, object] = {
        'allow_origins': configured or DEVELOPMENT_CORS_ORIGINS,
        'allow_credentials': True,
        'allow_methods': ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
        'allow_headers': ['Authorization', 'Content-Type'],
    }
    if app_env not in PRODUCTION_ENVS:
        options['allow_origin_regex'] = r'^https?://(localhost|127\.0\.0\.1)(:\d+)?$'
    return options

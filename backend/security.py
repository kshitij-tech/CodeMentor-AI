import os
import secrets
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import jwt
from dotenv import load_dotenv
from pwdlib import PasswordHash


BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(PROJECT_ROOT / ".env")

JWT_ISSUER = "codementor-ai"
ALGORITHM = "HS256"
DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES = 15
DEFAULT_REFRESH_TOKEN_EXPIRE_DAYS = 7
MIN_SECRET_BYTES = 32
ALLOWED_APP_ENVS = {"development", "testing", "production"}

_INSECURE_SECRET_MARKERS = {
    "",
    "change-me",
    "dev-only-secret-change-me",
    "replace-this-with-a-random-secret-at-least-32-bytes-long",
}


def _configured_secret() -> str:
    configured = os.getenv("JWT_SECRET_KEY", "").strip()
    app_env = os.getenv("APP_ENV", "development").strip().lower()

    if configured in _INSECURE_SECRET_MARKERS:
        if app_env == "production":
            raise RuntimeError(
                "JWT_SECRET_KEY must be set to a unique random value of at least 32 bytes in production."
            )
        # Development receives an ephemeral secret instead of a predictable
        # repository-visible fallback. Tokens are intentionally invalidated
        # whenever the development process restarts.
        return secrets.token_urlsafe(48)

    if len(configured.encode("utf-8")) < MIN_SECRET_BYTES:
        raise RuntimeError(
            "JWT_SECRET_KEY must be at least 32 bytes long."
        )
    return configured


SECRET_KEY = _configured_secret()
APP_ENV = os.getenv("APP_ENV", "development").strip().lower() or "development"

try:
    ACCESS_TOKEN_EXPIRE_MINUTES = int(
        os.getenv(
            "ACCESS_TOKEN_EXPIRE_MINUTES",
            str(DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES),
        )
    )
    REFRESH_TOKEN_EXPIRE_DAYS = int(
        os.getenv(
            "REFRESH_TOKEN_EXPIRE_DAYS",
            str(DEFAULT_REFRESH_TOKEN_EXPIRE_DAYS),
        )
    )
except ValueError as exc:
    raise RuntimeError(
        "ACCESS_TOKEN_EXPIRE_MINUTES and REFRESH_TOKEN_EXPIRE_DAYS must be integers."
    ) from exc

if ACCESS_TOKEN_EXPIRE_MINUTES < 5 or ACCESS_TOKEN_EXPIRE_MINUTES > 120:
    raise RuntimeError(
        "ACCESS_TOKEN_EXPIRE_MINUTES must be between 5 and 120."
    )
if REFRESH_TOKEN_EXPIRE_DAYS < 1 or REFRESH_TOKEN_EXPIRE_DAYS > 30:
    raise RuntimeError(
        "REFRESH_TOKEN_EXPIRE_DAYS must be between 1 and 30."
    )


password_hash = PasswordHash.recommended()


def validate_password(password: str) -> None:
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters long.")
    if len(password) > 128:
        raise ValueError("Password must not exceed 128 characters.")


def hash_password(password: str) -> str:
    validate_password(password)
    return password_hash.hash(password)


def verify_password(password: str, password_hash_value: str) -> bool:
    try:
        return password_hash.verify(password, password_hash_value)
    except (ValueError, TypeError):
        return False


def _build_token(subject: str, token_type: str, lifetime: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "type": token_type,
        "jti": uuid4().hex,
        "iat": now,
        "nbf": now,
        "exp": now + lifetime,
        "iss": JWT_ISSUER,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(subject: str) -> str:
    return _build_token(
        subject,
        "access",
        timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(subject: str) -> str:
    return _build_token(
        subject,
        "refresh",
        timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )


def _decode_token(token: str, expected_type: str) -> dict:
    payload = jwt.decode(
        token,
        SECRET_KEY,
        algorithms=[ALGORITHM],
        issuer=JWT_ISSUER,
        options={
            "require": [
                "sub",
                "type",
                "jti",
                "iat",
                "nbf",
                "exp",
                "iss",
            ]
        },
    )
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("Unexpected token type.")

    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject.isdigit():
        raise jwt.InvalidTokenError("Invalid token subject.")

    jti = payload.get("jti")
    if is_token_revoked(jti):
        raise jwt.InvalidTokenError("Token has been revoked.")

    return payload


def decode_access_token(token: str) -> dict:
    return _decode_token(token, "access")


def decode_refresh_token(token: str) -> dict:
    return _decode_token(token, "refresh")


_revoked_tokens: dict[str, float] = {}
_revocation_lock = threading.RLock()


def _prune_revoked_tokens(now: float | None = None) -> None:
    current = now if now is not None else time.time()
    expired = [
        jti
        for jti, expires_at in _revoked_tokens.items()
        if expires_at <= current
    ]
    for jti in expired:
        _revoked_tokens.pop(jti, None)


def is_token_revoked(jti: str) -> bool:
    if not isinstance(jti, str) or not jti:
        return True
    with _revocation_lock:
        _prune_revoked_tokens()
        return jti in _revoked_tokens


def revoke_token(jti: str, expires_at: float) -> None:
    if not isinstance(jti, str) or not jti:
        return
    with _revocation_lock:
        _prune_revoked_tokens()
        _revoked_tokens[jti] = max(expires_at, time.time() + 1)


def consume_refresh_token(jti: str, expires_at: float) -> bool:
    """Atomically consume a refresh-token JTI so rotated tokens cannot be reused."""
    if not isinstance(jti, str) or not jti:
        return False
    with _revocation_lock:
        _prune_revoked_tokens()
        if jti in _revoked_tokens:
            return False
        _revoked_tokens[jti] = max(expires_at, time.time() + 1)
        return True


class RateLimitExceeded(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = max(1, retry_after)
        super().__init__("Too many requests. Please try again later.")


_rate_events: dict[str, deque[float]] = {}
_rate_lock = threading.RLock()


def enforce_rate_limit(key: str, *, limit: int, window_seconds: int) -> None:
    now = time.monotonic()
    with _rate_lock:
        events = _rate_events.setdefault(key, deque())
        while events and now - events[0] >= window_seconds:
            events.popleft()

        if len(events) >= limit:
            retry_after = int(max(1, window_seconds - (now - events[0]) + 0.999))
            raise RateLimitExceeded(retry_after)

        events.append(now)


def reset_security_state_for_tests() -> None:
    with _revocation_lock:
        _revoked_tokens.clear()
    with _rate_lock:
        _rate_events.clear()


def _parse_positive_int(value: str, field_name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise RuntimeError(f"{field_name} must be an integer.") from exc
    if parsed <= 0:
        raise RuntimeError(f"{field_name} must be greater than zero.")
    return parsed


def get_cors_origins() -> list[str]:
    app_env = os.getenv("APP_ENV", APP_ENV).strip().lower() or APP_ENV
    configured = os.getenv("CORS_ORIGINS", "").strip()
    if not configured:
        if app_env == "production":
            raise RuntimeError(
                "CORS_ORIGINS must be configured explicitly in production."
            )
        return [
            "http://localhost:3000",
            "http://localhost:5173",
            "http://localhost:5500",
            "http://127.0.0.1:5500",
        ]

    origins = [origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()]
    if not origins:
        raise RuntimeError("CORS_ORIGINS must contain at least one origin.")
    if any(origin in {"*", "null"} or "*" in origin for origin in origins):
        raise RuntimeError("CORS_ORIGINS must not contain wildcard or null origins.")

    for origin in origins:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RuntimeError(
                "Each CORS origin must be an absolute http(s) origin."
            )
        if parsed.path or parsed.query or parsed.fragment:
            raise RuntimeError(
                "CORS origins must not contain paths, query strings, or fragments."
            )
    return origins


def validate_security_configuration() -> None:
    app_env = os.getenv("APP_ENV", "development").strip().lower() or "development"
    if app_env not in ALLOWED_APP_ENVS:
        raise RuntimeError(
            f"APP_ENV must be one of: {', '.join(sorted(ALLOWED_APP_ENVS))}."
        )

    configured_secret = os.getenv("JWT_SECRET_KEY", "").strip()
    if app_env == "production":
        if not configured_secret or configured_secret.lower() in _INSECURE_SECRET_MARKERS:
            raise RuntimeError(
                "Production requires JWT_SECRET_KEY to be explicitly configured."
            )
        if len(configured_secret.encode("utf-8")) < MIN_SECRET_BYTES:
            raise RuntimeError(
                "Production JWT_SECRET_KEY must be at least 32 bytes long."
            )

    get_cors_origins()

    access_minutes = _parse_positive_int(
        os.getenv(
            "ACCESS_TOKEN_EXPIRE_MINUTES",
            str(DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES),
        ),
        "ACCESS_TOKEN_EXPIRE_MINUTES",
    )
    refresh_days = _parse_positive_int(
        os.getenv(
            "REFRESH_TOKEN_EXPIRE_DAYS",
            str(DEFAULT_REFRESH_TOKEN_EXPIRE_DAYS),
        ),
        "REFRESH_TOKEN_EXPIRE_DAYS",
    )
    if access_minutes < 5 or access_minutes > 120:
        raise RuntimeError(
            "ACCESS_TOKEN_EXPIRE_MINUTES must be between 5 and 120."
        )
    if refresh_days < 1 or refresh_days > 30:
        raise RuntimeError(
            "REFRESH_TOKEN_EXPIRE_DAYS must be between 1 and 30."
        )

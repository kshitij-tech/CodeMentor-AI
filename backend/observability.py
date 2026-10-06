from __future__ import annotations

import contextvars
import json
import logging
import os
import platform
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, FastAPI
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SERVICE_NAME = os.getenv("OBSERVABILITY_SERVICE_NAME", "codementor-ai-api")
_REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_REQUEST_ID_CONTEXT: contextvars.ContextVar[str] = contextvars.ContextVar(
    "codementor_request_id", default="-"
)
_CAPTURE_LIMIT_BYTES = 128 * 1024

AUTH_PREFIXES = ("/auth", "/login", "/register", "/refresh")
EXECUTION_PREFIX = "/execution"
AI_PREFIX = "/mentor"
RECOMMENDATION_PREFIX = "/recommendations"

HTTP_REQUESTS = Counter(
    "codementor_http_requests_total",
    "Total HTTP requests processed by CodeMentor AI.",
    ("method", "route", "status_code", "category"),
)
HTTP_LATENCY = Histogram(
    "codementor_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ("method", "route"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
IN_FLIGHT_REQUESTS = Gauge(
    "codementor_http_requests_in_flight",
    "Current number of in-flight HTTP requests.",
)
EXECUTION_LATENCY = Histogram(
    "codementor_execution_duration_seconds",
    "Execution API request duration in seconds.",
    ("route", "status_code"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
AI_LATENCY = Histogram(
    "codementor_ai_duration_seconds",
    "AI Mentor API request duration in seconds.",
    ("route", "status_code"),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
)
OPERATION_FAILURES = Counter(
    "codementor_operation_failures_total",
    "Categorized operation failures.",
    ("operation", "category", "status_code"),
)
DATABASE_ERRORS = Counter(
    "codementor_database_errors_total",
    "Database exceptions observed by the API.",
    ("operation",),
)
AUTH_FAILURES = Counter(
    "codementor_authentication_failures_total",
    "Authentication failures observed by the API.",
    ("route", "status_code"),
)
EXECUTION_FAILURES = Counter(
    "codementor_execution_failures_total",
    "Execution failures, including judge outcomes such as wrong answer or runtime error.",
    ("route", "status_code"),
)
AI_FAILURES = Counter(
    "codementor_ai_failures_total",
    "AI Mentor request failures.",
    ("route", "status_code"),
)
RECOMMENDATION_FAILURES = Counter(
    "codementor_recommendation_failures_total",
    "Recommendation API failures.",
    ("route", "status_code"),
)


@dataclass(frozen=True)
class ObservabilityConfig:
    enabled: bool = True
    metrics_enabled: bool = True
    diagnostics_enabled: bool = False

    @classmethod
    def from_env(cls) -> "ObservabilityConfig":
        return cls(
            enabled=_env_bool("OBSERVABILITY_ENABLED", True),
            metrics_enabled=_env_bool("OBSERVABILITY_METRICS_ENABLED", True),
            diagnostics_enabled=_env_bool(
                "OBSERVABILITY_DIAGNOSTICS_ENABLED", False
            ),
        )


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def request_id() -> str:
    return _REQUEST_ID_CONTEXT.get()


def _safe_request_id(value: str | None) -> str:
    if value and _REQUEST_ID_PATTERN.fullmatch(value.strip()):
        return value.strip()
    return str(uuid.uuid4())


def _route_template(scope: Scope) -> str:
    route = scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str) and template:
        return template
    return "<unmatched>"


def _operation_for_path(path: str) -> str:
    if path.startswith(EXECUTION_PREFIX):
        return "execution"
    if path.startswith(AI_PREFIX):
        return "ai"
    if path.startswith(RECOMMENDATION_PREFIX):
        return "recommendation"
    if path.startswith(AUTH_PREFIXES):
        return "authentication"
    return "http"


def _json_body(body: bytes) -> dict[str, Any] | None:
    if not body:
        return None
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _is_execution_failure(status_code: int, body: bytes) -> bool:
    if status_code >= 400:
        return True
    payload = _json_body(body)
    if not payload:
        return False
    if payload.get("valid") is False:
        return True
    status = str(payload.get("status") or "").strip().lower()
    return bool(status and status not in {"accepted", "ok", "valid"})


def _is_ai_failure(status_code: int, body: bytes) -> bool:
    if status_code >= 500:
        return True
    payload = _json_body(body)
    return isinstance(payload, dict) and "answer" not in payload


def categorize_request(
    path: str,
    status_code: int,
    *,
    exception: BaseException | None = None,
    body: bytes = b"",
) -> str:
    if exception is not None and isinstance(exception, SQLAlchemyError):
        return "database_error"
    if path.startswith(AUTH_PREFIXES) and status_code in {401, 403}:
        return "authentication_error"
    if path.startswith(EXECUTION_PREFIX) and _is_execution_failure(
        status_code, body
    ):
        return "execution_error"
    if path.startswith(AI_PREFIX) and _is_ai_failure(status_code, body):
        return "ai_error"
    if path.startswith(RECOMMENDATION_PREFIX) and status_code >= 500:
        return "recommendation_error"
    if status_code == 404:
        return "not_found"
    if status_code == 422:
        return "validation_error"
    if status_code >= 500:
        return "server_error"
    if status_code >= 400:
        return "client_error"
    return "success"


def _safe_error_message(exc: BaseException) -> str:
    if isinstance(exc, SQLAlchemyError):
        return "database operation failed"
    message = str(exc).replace("\n", " ")[:500]
    return re.sub(
        r"(?i)(password|secret|token|api[_-]?key|authorization)\s*[:=]\s*[^,;\s]+",
        r"\1=<redacted>",
        message,
    )


class JsonFormatter(logging.Formatter):
    """Compact JSON logs for ingestion by standard log collectors."""

    RESERVED = set(
        logging.LogRecord(None, 0, "", 0, "", (), None).__dict__
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(
                record, "%Y-%m-%dT%H:%M:%S%z"
            ),
            "level": record.levelname,
            "logger": record.name,
            "service": SERVICE_NAME,
            "message": record.getMessage(),
            "request_id": request_id(),
        }
        for key, value in record.__dict__.items():
            if key.startswith("_") or key in self.RESERVED or key in payload:
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                payload[key] = value
        return json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        )


def configure_logging() -> None:
    logger = logging.getLogger("codementor.observability")
    level = getattr(
        logging,
        os.getenv("OBSERVABILITY_LOG_LEVEL", "INFO").upper(),
        logging.INFO,
    )
    logger.setLevel(level)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)


def database_ready() -> tuple[bool, str | None]:
    """Perform a SQL connectivity check without exposing connection details."""
    try:
        from backend.database import SessionLocal

        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return True, None
    except SQLAlchemyError:
        DATABASE_ERRORS.labels(operation="readiness").inc()
        return False, "database_unavailable"
    except Exception:
        return False, "database_check_failed"


def readiness_payload() -> tuple[dict[str, Any], int]:
    ready, reason = database_ready()
    if ready:
        return {
            "status": "ready",
            "service": SERVICE_NAME,
            "checks": {"database": "ok"},
        }, 200
    return {
        "status": "not_ready",
        "service": SERVICE_NAME,
        "checks": {"database": "failed"},
        "reason": reason,
    }, 503


def diagnostics_payload() -> dict[str, Any]:
    """Return safe runtime facts only; never return raw environment variables."""
    return {
        "service": SERVICE_NAME,
        "environment": os.getenv("APP_ENV", "development"),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "ai_provider": os.getenv("AI_PROVIDER", "ollama"),
        "ai_model": os.getenv("AI_MODEL", "qwen2.5-coder:3b"),
        "execution_sandbox": os.getenv("EXECUTION_SANDBOX", "local"),
        "metrics_enabled": _env_bool(
            "OBSERVABILITY_METRICS_ENABLED", True
        ),
    }


def _record_metrics(
    path: str,
    route: str,
    method: str,
    status_code: int,
    category: str,
    elapsed: float,
) -> None:
    status = str(status_code)
    HTTP_REQUESTS.labels(
        method=method,
        route=route,
        status_code=status,
        category=category,
    ).inc()
    HTTP_LATENCY.labels(method=method, route=route).observe(elapsed)

    if path.startswith(EXECUTION_PREFIX):
        EXECUTION_LATENCY.labels(
            route=route, status_code=status
        ).observe(elapsed)
    if path.startswith(AI_PREFIX):
        AI_LATENCY.labels(
            route=route, status_code=status
        ).observe(elapsed)
    if category == "authentication_error":
        AUTH_FAILURES.labels(
            route=route, status_code=status
        ).inc()
    if category == "execution_error":
        EXECUTION_FAILURES.labels(
            route=route, status_code=status
        ).inc()
    if category == "ai_error":
        AI_FAILURES.labels(
            route=route, status_code=status
        ).inc()
    if category == "recommendation_error":
        RECOMMENDATION_FAILURES.labels(
            route=route, status_code=status
        ).inc()
    if category.endswith("_error") and category != "database_error":
        OPERATION_FAILURES.labels(
            operation=_operation_for_path(path),
            category=category,
            status_code=status,
        ).inc()


class ObservabilityMiddleware:
    """Observe requests without buffering full response bodies."""

    def __init__(self, app: ASGIApp, config: ObservabilityConfig):
        self.app = app
        self.config = config
        configure_logging()
        self.logger = logging.getLogger("codementor.observability")

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method", "GET"))
        path = str(scope.get("path", "/"))
        rid = _safe_request_id(
            _header_value(scope.get("headers", []), _REQUEST_ID_HEADER)
        )
        token = _REQUEST_ID_CONTEXT.set(rid)
        started = time.perf_counter()
        status_code = 500
        route = "<unmatched>"
        response_started = False
        response_body = bytearray()

        if self.config.metrics_enabled:
            IN_FLIGHT_REQUESTS.inc()

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code, route, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = int(message["status"])
                route = _route_template(scope)
                headers = list(message.get("headers", []))
                request_id_header = _REQUEST_ID_HEADER.encode(
                    "latin-1"
                ).lower()
                headers = [
                    (key, value)
                    for key, value in headers
                    if key.lower() != request_id_header
                ]
                headers.append(
                    (
                        _REQUEST_ID_HEADER.encode("latin-1"),
                        rid.encode("latin-1"),
                    )
                )
                message = {**message, "headers": headers}
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                if body and len(response_body) < _CAPTURE_LIMIT_BYTES:
                    response_body.extend(
                        body[: _CAPTURE_LIMIT_BYTES - len(response_body)]
                    )
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            elapsed = time.perf_counter() - started
            route = _route_template(scope)
            category = categorize_request(
                path, 500, exception=exc
            )
            if self.config.metrics_enabled:
                _record_metrics(
                    path, route, method, 500, category, elapsed
                )
                if isinstance(exc, SQLAlchemyError):
                    DATABASE_ERRORS.labels(
                        operation=_operation_for_path(path)
                    ).inc()
            self.logger.exception(
                "request.failed",
                extra={
                    "event": "request.failed",
                    "method": method,
                    "path": path,
                    "route": route,
                    "status_code": 500,
                    "category": category,
                    "latency_ms": round(elapsed * 1000, 2),
                    "error_type": type(exc).__name__,
                    "error": _safe_error_message(exc),
                },
            )
            if not response_started:
                response = JSONResponse(
                    {
                        "detail": "Internal server error.",
                        "request_id": rid,
                    },
                    status_code=500,
                    headers={_REQUEST_ID_HEADER: rid},
                )
                await response(scope, receive, send)
                return
            raise
        finally:
            if response_started:
                elapsed = time.perf_counter() - started
                category = categorize_request(
                    path,
                    status_code,
                    body=bytes(response_body),
                )
                if self.config.metrics_enabled:
                    _record_metrics(
                        path,
                        route,
                        method,
                        status_code,
                        category,
                        elapsed,
                    )
                log_method = (
                    self.logger.warning
                    if category != "success"
                    else self.logger.info
                )
                log_method(
                    "request.completed"
                    if category == "success"
                    else "request.completed_with_error",
                    extra={
                        "event": (
                            "request.completed"
                            if category == "success"
                            else "request.completed_with_error"
                        ),
                        "method": method,
                        "path": path,
                        "route": route,
                        "status_code": status_code,
                        "category": category,
                        "latency_ms": round(elapsed * 1000, 2),
                    },
                )
            if self.config.metrics_enabled:
                IN_FLIGHT_REQUESTS.dec()
            _REQUEST_ID_CONTEXT.reset(token)


def _header_value(
    headers: list[tuple[bytes, bytes]], wanted: str
) -> str | None:
    wanted_bytes = wanted.lower().encode("latin-1")
    for key, value in headers:
        if key.lower() == wanted_bytes:
            try:
                return value.decode("latin-1")
            except UnicodeDecodeError:
                return None
    return None


def install_observability(
    app: FastAPI, config: ObservabilityConfig | None = None
) -> None:
    config = config or ObservabilityConfig.from_env()
    if not config.enabled:
        return

    app.add_middleware(ObservabilityMiddleware, config=config)

    health_router = APIRouter(tags=["Health"])

    @health_router.get("/health/live")
    async def live_health() -> dict[str, str]:
        return {"status": "ok", "service": SERVICE_NAME}

    @health_router.get("/health/ready")
    async def ready_health() -> Response:
        payload, status_code = readiness_payload()
        return JSONResponse(payload, status_code=status_code)

    if config.metrics_enabled:

        @health_router.get("/metrics")
        async def metrics() -> Response:
            return Response(
                generate_latest(), media_type=CONTENT_TYPE_LATEST
            )

    if config.diagnostics_enabled:

        @health_router.get("/diagnostics")
        async def diagnostics() -> dict[str, Any]:
            return diagnostics_payload()

    app.include_router(health_router)

# Observability

CodeMentor AI uses a centralized ASGI observability layer so individual feature routers do not need to be modified for request tracing, latency tracking, or operational metrics.

## Architecture

```
Client
  |
  | X-Request-ID (optional)
  v
FastAPI
  |
  +--> ObservabilityMiddleware
  |      +-- request ID + context
  |      +-- structured JSON request logs
  |      +-- request/operation latency
  |      +-- error categorization
  |      +-- operation failure counters
  |      +-- response request ID
  |
  +--> Feature routers
  |      +-- /auth
  |      +-- /execution
  |      +-- /mentor
  |      +-- /recommendations
  |      +-- /...
  |
  +--> /health/live
  +--> /health/ready
  +--> /metrics
  +--> /diagnostics (explicitly opt-in)
```

The middleware uses low-cardinality route templates for metrics. Request IDs are never metric labels, which prevents unbounded Prometheus cardinality.

## Endpoints

- `GET /health` — existing application liveness endpoint.
- `GET /health/live` — dedicated liveness probe; no database dependency.
- `GET /health/ready` — readiness probe; executes `SELECT 1` and returns HTTP 503 when the database is unavailable.
- `GET /metrics` — Prometheus text exposition, enabled by default.
- `GET /diagnostics` — safe runtime diagnostics, disabled by default.

All observed HTTP responses receive an `X-Request-ID` response header. Valid incoming IDs are preserved; malformed or oversized IDs are replaced with a UUID.

## Metrics

### Request metrics

- `codementor_http_requests_total{method,route,status_code,category}`
- `codementor_http_request_duration_seconds{method,route}`
- `codementor_http_requests_in_flight`

### Operation latency

- `codementor_execution_duration_seconds{route,status_code}`
- `codementor_ai_duration_seconds{route,status_code}`

These measure end-to-end API operation latency, including application-side work surrounding the execution or AI call.

### Failure metrics

- `codementor_operation_failures_total{operation,category,status_code}`
- `codementor_database_errors_total{operation}`
- `codementor_authentication_failures_total{route,status_code}`
- `codementor_execution_failures_total{route,status_code}`
- `codementor_ai_failures_total{route,status_code}`
- `codementor_recommendation_failures_total{route,status_code}`

Execution outcomes such as Wrong Answer, Runtime Error, Compile Error, Time Limit Exceeded, and Output Limit Exceeded are counted as execution failures even when the API itself returns HTTP 200. AI provider errors are counted from failed mentor responses, and recommendation failures are counted from 5xx responses/exceptions.

Failure rates can be derived safely in Prometheus/Grafana, for example:

```promql
sum(rate(codementor_operation_failures_total{operation="ai"}[5m]))
/
sum(rate(codementor_http_requests_total{category!="success"}[5m]))
```

For an endpoint-specific error ratio:

```promql
sum(rate(codementor_http_requests_total{route="/mentor/analyze",category="ai_error"}[5m]))
/
sum(rate(codementor_http_requests_total{route="/mentor/analyze"}[5m]))
```

## Structured logging

Observability logs are JSON lines with fields such as:

```json
{
  "timestamp": "2026-10-06T13:00:00+0000",
  "level": "INFO",
  "logger": "codementor.observability",
  "service": "codementor-ai-api",
  "message": "request.completed",
  "request_id": "req-123",
  "method": "GET",
  "path": "/recommendations/next",
  "route": "/recommendations/next",
  "status_code": 200,
  "category": "success",
  "latency_ms": 18.42
}
```

Unhandled exceptions log the exception type and a redacted, size-limited message. Request bodies, passwords, authorization headers, API keys, and raw SQL/response payloads are not logged by the observability layer.

## Prometheus integration

A Prometheus server can scrape:

```yaml
scrape_configs:
  - job_name: codementor-api
    metrics_path: /metrics
    static_configs:
      - targets:
          - codementor-api:8000
```

In production, expose `/metrics` only to the monitoring network or service mesh. The application does not put credentials or request IDs into Prometheus labels.

## Configuration

```env
OBSERVABILITY_ENABLED=true
OBSERVABILITY_METRICS_ENABLED=true
OBSERVABILITY_DIAGNOSTICS_ENABLED=false
OBSERVABILITY_SERVICE_NAME=codementor-ai-api
OBSERVABILITY_LOG_LEVEL=INFO
```

Developer diagnostics intentionally require an explicit opt-in flag. They report environment/runtime identifiers and selected non-secret configuration, never raw environment variables.

## Future extension points

The current interface is intentionally suitable for adding OpenTelemetry tracing, Prometheus/Grafana dashboards, alert rules, log aggregation, and distributed request propagation later without modifying the feature routers.
import json
import logging
import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from backend import observability as obs


class ObservabilityTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        obs.install_observability(
            self.app,
            obs.ObservabilityConfig(
                enabled=True,
                metrics_enabled=True,
                diagnostics_enabled=True,
            ),
        )

        @self.app.get("/demo")
        def demo():
            return {"ok": True}

        @self.app.get("/auth/test")
        def auth_failure():
            raise HTTPException(
                status_code=401,
                detail="bad credentials",
            )

        @self.app.get("/execution/run")
        def execution_failure():
            return {"status": "Wrong Answer", "results": []}

        @self.app.get("/mentor/chat")
        def mentor_failure():
            from starlette.responses import JSONResponse

            return JSONResponse(
                {"detail": "provider unavailable"},
                status_code=503,
            )

        @self.app.get("/recommendations/next")
        def recommendation_failure():
            raise RuntimeError("recommendation calculation failed")

        @self.app.get("/db-error")
        def database_failure():
            raise OperationalError(
                "SELECT * FROM users",
                [],
                RuntimeError("secret=abc"),
            )

        self.client = TestClient(self.app)

    def test_request_id_is_generated_and_returned(self):
        response = self.client.get("/demo")
        self.assertEqual(response.status_code, 200)
        request_id = response.headers.get("X-Request-ID")
        self.assertIsNotNone(request_id)
        self.assertRegex(request_id, r"^[0-9a-f-]{36}$")

    def test_valid_incoming_request_id_is_preserved(self):
        response = self.client.get(
            "/demo",
            headers={"X-Request-ID": "req-123_abc"},
        )
        self.assertEqual(
            response.headers["X-Request-ID"],
            "req-123_abc",
        )

    def test_invalid_incoming_request_id_is_replaced(self):
        response = self.client.get(
            "/demo",
            headers={"X-Request-ID": "bad id with spaces"},
        )
        self.assertRegex(
            response.headers["X-Request-ID"],
            r"^[0-9a-f-]{36}$",
        )

    def test_auth_failure_is_categorized(self):
        response = self.client.get("/auth/test")
        self.assertEqual(response.status_code, 401)
        value = obs.AUTH_FAILURES.labels(
            route="/auth/test",
            status_code="401",
        )._value.get()
        self.assertGreaterEqual(value, 1)

    def test_execution_semantic_failure_is_counted(self):
        response = self.client.get("/execution/run")
        self.assertEqual(response.status_code, 200)
        value = obs.EXECUTION_FAILURES.labels(
            route="/execution/run",
            status_code="200",
        )._value.get()
        self.assertGreaterEqual(value, 1)

        latency = obs.EXECUTION_LATENCY.labels(
            route="/execution/run",
            status_code="200",
        )
        self.assertGreaterEqual(latency._sum.get(), 0)

    def test_ai_failure_is_counted(self):
        response = self.client.get("/mentor/chat")
        self.assertEqual(response.status_code, 503)
        value = obs.AI_FAILURES.labels(
            route="/mentor/chat",
            status_code="503",
        )._value.get()
        self.assertGreaterEqual(value, 1)

        latency = obs.AI_LATENCY.labels(
            route="/mentor/chat",
            status_code="503",
        )
        self.assertGreaterEqual(latency._sum.get(), 0)

    def test_recommendation_unhandled_error_is_categorized(self):
        response = self.client.get("/recommendations/next")
        self.assertEqual(response.status_code, 500)
        self.assertIn("request_id", response.json())
        value = obs.RECOMMENDATION_FAILURES.labels(
            route="/recommendations/next",
            status_code="500",
        )._value.get()
        self.assertGreaterEqual(value, 1)

    def test_database_exception_is_counted_and_details_are_not_returned(self):
        response = self.client.get("/db-error")
        self.assertEqual(response.status_code, 500)
        self.assertIn("request_id", response.json())
        self.assertNotIn("SELECT", response.text)
        value = obs.DATABASE_ERRORS.labels(
            operation="http",
        )._value.get()
        self.assertGreaterEqual(value, 1)

    def test_database_exception_is_categorized(self):
        exc = OperationalError(
            "SELECT * FROM users",
            [],
            RuntimeError("secret=abc"),
        )
        self.assertEqual(
            obs.categorize_request(
                "/profile",
                500,
                exception=exc,
            ),
            "database_error",
        )

    def test_metrics_endpoint_exposes_prometheus_format(self):
        response = self.client.get("/metrics")
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "codementor_http_requests_total",
            response.text,
        )
        self.assertIn(
            "codementor_http_request_duration_seconds",
            response.text,
        )

    def test_liveness_endpoint_is_database_independent(self):
        response = self.client.get("/health/live")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_diagnostics_contains_no_secret_environment_values(self):
        with patch.dict(
            "os.environ",
            {
                "JWT_SECRET_KEY": "super-secret",
                "MISTRAL_API_KEY": "api-secret",
            },
            clear=False,
        ):
            response = self.client.get("/diagnostics")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("super-secret", response.text)
        self.assertNotIn("api-secret", response.text)
        self.assertIn("python", response.json())

    def test_readiness_returns_unavailable_without_database_details(self):
        with patch.object(
            obs,
            "database_ready",
            return_value=(False, "database_unavailable"),
        ):
            response = self.client.get("/health/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "not_ready")
        self.assertNotIn("SELECT", response.text)

    def test_json_formatter_outputs_structured_request_fields(self):
        token = obs._REQUEST_ID_CONTEXT.set("req-formatter")
        try:
            record = logging.LogRecord(
                "codementor.observability",
                logging.INFO,
                __file__,
                1,
                "request.completed",
                (),
                None,
            )
            record.event = "request.completed"
            record.method = "GET"
            record.path = "/demo"
            record.status_code = 200
            record.category = "success"
            record.latency_ms = 12.34
            payload = json.loads(obs.JsonFormatter().format(record))
        finally:
            obs._REQUEST_ID_CONTEXT.reset(token)

        self.assertEqual(payload["request_id"], "req-formatter")
        self.assertEqual(payload["event"], "request.completed")
        self.assertEqual(payload["status_code"], 200)
        self.assertEqual(payload["latency_ms"], 12.34)
        self.assertNotIn("pathname", payload)
        self.assertNotIn("levelno", payload)

    def test_sanitize_error_message_redacts_secret_like_values(self):
        error = RuntimeError(
            "api_key=abc123 password=hello token=xyz"
        )
        safe = obs._safe_error_message(error)
        self.assertNotIn("abc123", safe)
        self.assertNotIn("hello", safe)
        self.assertNotIn("xyz", safe)
        self.assertIn("<redacted>", safe)


if __name__ == "__main__":
    unittest.main()

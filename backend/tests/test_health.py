import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from backend.routers.health import health_check, liveness_check, readiness_check

class HealthEndpointTests(unittest.TestCase):
    def test_health_is_backward_compatible(self):
        result = health_check()
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['service'], 'codementor-ai-api')

    def test_liveness_does_not_require_database(self):
        self.assertEqual(liveness_check()['status'], 'ok')

    def test_readiness_confirms_database_connectivity(self):
        connection = MagicMock()
        context_manager = MagicMock()
        context_manager.__enter__.return_value = connection
        context_manager.__exit__.return_value = False
        with patch('backend.routers.health.engine.connect', return_value=context_manager):
            result = readiness_check()
        self.assertEqual(result['database'], 'ok')
        connection.execute.assert_called_once()

    def test_readiness_returns_503_when_database_is_unavailable(self):
        context_manager = MagicMock()
        context_manager.__enter__.side_effect = RuntimeError('database down')
        context_manager.__exit__.return_value = False
        with patch('backend.routers.health.engine.connect', return_value=context_manager):
            with self.assertRaises(HTTPException) as context:
                readiness_check()
        self.assertEqual(context.exception.status_code, 503)
        self.assertEqual(context.exception.detail, 'Database is not ready.')

if __name__ == '__main__': unittest.main()

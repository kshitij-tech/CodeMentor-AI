import os
import unittest
from unittest.mock import patch

from backend.runtime_config import cors_options

class RuntimeConfigTests(unittest.TestCase):
    def test_production_requires_explicit_cors_origins(self):
        with patch.dict(os.environ, {'APP_ENV':'production','CORS_ORIGINS':''}, clear=False):
            with self.assertRaises(RuntimeError): cors_options()

    def test_production_uses_only_configured_origins(self):
        with patch.dict(os.environ, {'APP_ENV':'production','CORS_ORIGINS':'https://example.com, https://app.example.com'}, clear=False):
            options=cors_options()
        self.assertEqual(options['allow_origins'], ['https://example.com','https://app.example.com'])
        self.assertNotIn('allow_origin_regex', options)

    def test_development_keeps_local_defaults(self):
        with patch.dict(os.environ, {'APP_ENV':'development','CORS_ORIGINS':''}, clear=False):
            options=cors_options()
        self.assertIn('http://localhost:5500', options['allow_origins'])
        self.assertIn('allow_origin_regex', options)

if __name__ == '__main__': unittest.main()

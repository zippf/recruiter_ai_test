import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import main as legacy_main
from app.main import app as modular_app


class TestPhase1Scaffold(unittest.TestCase):
    def test_modular_entrypoint_reuses_legacy_application(self):
        self.assertIs(modular_app, legacy_main.app)
        self.assertEqual(modular_app.title, legacy_main.app.title)
        self.assertEqual(modular_app.version, legacy_main.app.version)

    def test_modular_entrypoint_preserves_route_count(self):
        self.assertEqual(len(modular_app.routes), len(legacy_main.app.routes))


if __name__ == "__main__":
    unittest.main()

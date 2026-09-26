import os
import sys
import unittest

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(__file__))

from main import app


class TestPhase0Baseline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_application_metadata_and_import(self):
        self.assertEqual(app.title, "Kozker Recruiter AI Backend")
        self.assertEqual(app.version, "1.0.0")

    def test_index_response_and_correlation_header(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "ok",
                "message": "Kozker Recruiter AI FastAPI middleware is running.",
            },
        )
        self.assertTrue(response.headers.get("X-Correlation-ID"))

    def test_compatibility_routes_are_registered(self):
        route_methods_and_paths = {
            (method, route.path)
            for route in app.routes
            if hasattr(route, "methods")
            for method in route.methods
        }

        expected_routes = {
            ("POST", "/api/v1/jobs/{job_id}/scan-publish"),
            ("POST", "/api/v1/jobs/{job_id}/scan-and-publish"),
            ("PATCH", "/api/v1/applications/{app_id}/accept"),
            ("POST", "/api/v1/applications/{app_id}/accept"),
        }

        self.assertTrue(expected_routes.issubset(route_methods_and_paths))

    def test_callback_requires_authorization(self):
        response = self.client.post("/api/v1/callbacks/job-openings", json={})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Missing Authorization header")


if __name__ == "__main__":
    unittest.main()

import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from report_worker.server import app, parse_allowed_origins, store


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.environ["CONTROL_PLANE_DB"] = str(Path(self.temp.name) / "control.sqlite3")
        os.environ["CONTROL_PLANE_ADMIN_TOKEN"] = "admin-test"
        store.cache_clear()
        self.client = TestClient(app)
        self.admin = {"Authorization": "Bearer admin-test"}
        token = self.client.post(
            "/api/admin/worker-tokens",
            headers=self.admin,
            json={"name": "test-worker"},
        ).json()["token"]
        self.worker = {"Authorization": f"Bearer {token}"}

    def tearDown(self):
        store.cache_clear()
        self.temp.cleanup()

    def test_job_can_only_be_claimed_once(self):
        created = self.client.post(
            "/api/admin/jobs",
            headers=self.admin,
            json={"report_text": "تقرير تجريبي", "mode": "fast"},
        ).json()["job"]
        first = self.client.post(
            "/api/worker/jobs/claim",
            headers=self.worker,
            json={"worker_id": "worker-1"},
        ).json()["job"]
        second = self.client.post(
            "/api/worker/jobs/claim",
            headers=self.worker,
            json={"worker_id": "worker-2"},
        ).json()["job"]
        self.assertEqual(first["id"], created["id"])
        self.assertIsNone(second)

    def test_worker_can_submit_analysis(self):
        job = self.client.post(
            "/api/admin/jobs",
            headers=self.admin,
            json={"report_text": "تقرير تجريبي"},
        ).json()["job"]
        self.client.post(
            "/api/worker/jobs/claim",
            headers=self.worker,
            json={"worker_id": "worker-1"},
        )
        response = self.client.post(
            f"/api/worker/jobs/{job['id']}/analysis",
            headers=self.worker,
            json={
                "output": {"status": "ready_to_render"},
                "provider": {"name": "local", "model": "gemma4:e4b"},
            },
        )
        self.assertEqual(response.status_code, 200)
        saved = self.client.get(
            f"/api/admin/jobs/{job['id']}", headers=self.admin
        ).json()["job"]
        self.assertEqual(saved["status"], "validated")
        self.assertEqual(saved["provider"]["name"], "local")

    def test_allowed_origins_are_parsed_for_frontend_cors(self):
        self.assertEqual(
            parse_allowed_origins(" https://reportar.netlify.app/, http://127.0.0.1:8777 "),
            ["https://reportar.netlify.app", "http://127.0.0.1:8777"],
        )


if __name__ == "__main__":
    unittest.main()

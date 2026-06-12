from __future__ import annotations

import base64
from typing import Any

from .http import request_json


class ControlPlaneClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"}

    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return request_json(
            method,
            f"{self.base_url}{path}",
            payload=payload,
            headers=self.headers,
            timeout=60,
        )

    def heartbeat(self, worker_id: str, capabilities: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/worker/heartbeat",
            {"worker_id": worker_id, "capabilities": capabilities},
        )

    def claim(self, worker_id: str) -> dict[str, Any] | None:
        response = self._request(
            "POST", "/api/worker/jobs/claim", {"worker_id": worker_id}
        )
        return response.get("job")

    def event(
        self, job_id: str, status: str, message: str, metadata: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/worker/jobs/{job_id}/events",
            {"status": status, "message": message, "metadata": metadata or {}},
        )

    def submit_questions(
        self, job_id: str, output: dict[str, Any], provider: dict[str, Any]
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/worker/jobs/{job_id}/questions",
            {"output": output, "provider": provider},
        )

    def submit_analysis(
        self, job_id: str, output: dict[str, Any], provider: dict[str, Any]
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/worker/jobs/{job_id}/analysis",
            {"output": output, "provider": provider},
        )

    def submit_artifact(
        self,
        job_id: str,
        output: dict[str, Any],
        provider: dict[str, Any],
        pdf_bytes: bytes,
        file_name: str = "report.pdf",
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/worker/jobs/{job_id}/artifact",
            {
                "output": output,
                "provider": provider,
                "file_name": file_name,
                "pdf_base64": base64.b64encode(pdf_bytes).decode("ascii"),
            },
        )

    def fail(self, job_id: str, reason: str, retryable: bool) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/worker/jobs/{job_id}/fail",
            {"reason": reason[:500], "retryable": retryable},
        )

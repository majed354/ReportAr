from __future__ import annotations

import base64
import hmac
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .store import Store


class WorkerHeartbeat(BaseModel):
    worker_id: str
    capabilities: dict[str, Any]


class WorkerClaim(BaseModel):
    worker_id: str


class EventInput(BaseModel):
    status: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResultInput(BaseModel):
    output: dict[str, Any]
    provider: dict[str, Any]


class FailureInput(BaseModel):
    reason: str
    retryable: bool = True


class JobInput(BaseModel):
    report_text: str
    instructions: str = ""
    mode: str = "fast"
    ai_provider: Optional[str] = None
    ai_model: Optional[str] = None
    fallback_allowed: bool = True
    fallback_provider: Optional[str] = None


class AppJobInput(BaseModel):
    report_text: str = Field(min_length=5)
    instructions: str = ""
    mode: str = "fast"
    visual_theme: str = ""
    chart_policy: str = "auto"


class ArtifactInput(BaseModel):
    output: dict[str, Any]
    provider: dict[str, Any]
    file_name: str = "report.pdf"
    pdf_base64: str


class TokenInput(BaseModel):
    name: str = "local-worker"


@lru_cache
def store() -> Store:
    return Store(os.getenv("CONTROL_PLANE_DB", "./data/control-plane.sqlite3"))


def bearer(authorization: Optional[str]) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return authorization.removeprefix("Bearer ").strip()


def require_worker(authorization: Optional[str] = Header(default=None)) -> None:
    if not store().valid_worker_token(bearer(authorization)):
        raise HTTPException(status_code=401, detail="Invalid worker token")


def require_admin(authorization: Optional[str] = Header(default=None)) -> None:
    configured = os.getenv("CONTROL_PLANE_ADMIN_TOKEN", "")
    if not configured or not hmac.compare_digest(bearer(authorization), configured):
        raise HTTPException(status_code=401, detail="Invalid admin token")


def parse_allowed_origins(value: str) -> list[str]:
    return [origin.strip().rstrip("/") for origin in value.split(",") if origin.strip()]


def artifact_root() -> Path:
    path = Path(os.getenv("CONTROL_PLANE_ARTIFACT_DIR", "./data/artifacts"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    events = [
        {
            "status": event["status"],
            "message": event["message"],
            "created_at": event["created_at"],
        }
        for event in job.get("events", [])
    ]
    result = {
        "id": job["id"],
        "status": job["status"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "events": events,
    }
    if job.get("artifact_path"):
        result["download_url"] = f"/api/app/jobs/{job['id']}/pdf"
        result["file_name"] = job.get("artifact_name") or "report.pdf"
        result["file_size"] = job.get("artifact_size") or 0
    return result


app = FastAPI(title="Arabic Report Control Plane", version="0.1.0")

ALLOWED_ORIGINS = parse_allowed_origins(os.getenv("CONTROL_PLANE_ALLOWED_ORIGINS", ""))
if ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/app/jobs")
def create_app_job(body: AppJobInput) -> dict[str, Any]:
    instructions = "\n".join(
        part
        for part in (
            body.instructions.strip(),
            f"النمط البصري المطلوب: {body.visual_theme}" if body.visual_theme else "",
            f"سياسة المخططات: {body.chart_policy}" if body.chart_policy else "",
        )
        if part
    )
    job = store().create_job(
        {
            "report_text": body.report_text,
            "instructions": instructions,
            "mode": body.mode if body.mode in {"fast", "guided"} else "fast",
            "fallback_allowed": True,
        }
    )
    return {"job": public_job(job)}


@app.get("/api/app/jobs/{job_id}")
def get_app_job(job_id: str) -> dict[str, Any]:
    try:
        return {"job": public_job(store().get_job(job_id))}
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found") from None


@app.get("/api/app/jobs/{job_id}/pdf")
def download_app_job_pdf(job_id: str) -> FileResponse:
    try:
        job = store().get_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found") from None
    if job.get("status") != "completed" or not job.get("artifact_path"):
        raise HTTPException(status_code=404, detail="PDF is not ready")
    path = Path(job["artifact_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="PDF file is missing")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=job.get("artifact_name") or "report.pdf",
    )


@app.post("/api/admin/worker-tokens", dependencies=[Depends(require_admin)])
def create_worker_token(body: TokenInput) -> dict[str, str]:
    return {"token": store().create_worker_token(body.name)}


@app.post("/api/admin/jobs", dependencies=[Depends(require_admin)])
def create_job(body: JobInput) -> dict[str, Any]:
    return {"job": store().create_job(body.model_dump())}


@app.get("/api/admin/jobs/{job_id}", dependencies=[Depends(require_admin)])
def get_job(job_id: str) -> dict[str, Any]:
    try:
        return {"job": store().get_job(job_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found") from None


@app.post("/api/worker/heartbeat", dependencies=[Depends(require_worker)])
def heartbeat(body: WorkerHeartbeat) -> dict[str, bool]:
    store().heartbeat(body.worker_id, body.capabilities)
    return {"ok": True}


@app.post("/api/worker/jobs/claim", dependencies=[Depends(require_worker)])
def claim(body: WorkerClaim) -> dict[str, Any]:
    return {"job": store().claim(body.worker_id)}


@app.post("/api/worker/jobs/{job_id}/events", dependencies=[Depends(require_worker)])
def event(job_id: str, body: EventInput) -> dict[str, bool]:
    store().add_event(job_id, body.status, body.message, body.metadata)
    return {"ok": True}


@app.post("/api/worker/jobs/{job_id}/questions", dependencies=[Depends(require_worker)])
def questions(job_id: str, body: ResultInput) -> dict[str, bool]:
    store().finish(job_id, "waiting_for_user", body.output, body.provider)
    return {"ok": True}


@app.post("/api/worker/jobs/{job_id}/analysis", dependencies=[Depends(require_worker)])
def analysis(job_id: str, body: ResultInput) -> dict[str, bool]:
    store().finish(job_id, "validated", body.output, body.provider)
    return {"ok": True}


@app.post("/api/worker/jobs/{job_id}/artifact", dependencies=[Depends(require_worker)])
def artifact(job_id: str, body: ArtifactInput) -> dict[str, bool]:
    try:
        pdf_bytes = base64.b64decode(body.pdf_base64, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid PDF payload") from None
    if not pdf_bytes.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="Artifact is not a PDF")
    safe_name = Path(body.file_name).name or "report.pdf"
    folder = artifact_root() / job_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / safe_name
    path.write_bytes(pdf_bytes)
    store().attach_artifact(
        job_id,
        str(path),
        safe_name,
        len(pdf_bytes),
        body.output,
        body.provider,
    )
    return {"ok": True}


@app.post("/api/worker/jobs/{job_id}/fail", dependencies=[Depends(require_worker)])
def fail(job_id: str, body: FailureInput) -> dict[str, bool]:
    store().add_event(
        job_id,
        "failed",
        body.reason[:500],
        {"retryable": body.retryable},
    )
    return {"ok": True}

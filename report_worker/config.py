from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _path(name: str, default: str) -> Path:
    value = Path(os.getenv(name, default))
    return value if value.is_absolute() else (ROOT / value).resolve()


@dataclass(frozen=True)
class Settings:
    provider: str = field(default_factory=lambda: os.getenv("REPORT_PROVIDER", "local"))
    fallback_provider: str = field(
        default_factory=lambda: os.getenv("REPORT_FALLBACK_PROVIDER", "")
    )
    ollama_base_url: str = field(
        default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    )
    ollama_model: str = field(
        default_factory=lambda: os.getenv("OLLAMA_MODEL", "gemma4:31b")
    )
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_model: str = field(
        default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    )
    gemini_base_url: str = field(
        default_factory=lambda: os.getenv(
            "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
        )
    )
    control_plane_url: str = field(
        default_factory=lambda: os.getenv("CONTROL_PLANE_URL", "")
    )
    worker_token: str = field(default_factory=lambda: os.getenv("WORKER_TOKEN", ""))
    worker_id: str = field(
        default_factory=lambda: os.getenv("WORKER_ID", "local-worker-01")
    )
    poll_seconds: float = field(
        default_factory=lambda: float(os.getenv("WORKER_POLL_SECONDS", "5"))
    )
    max_jobs: int = field(
        default_factory=lambda: int(os.getenv("WORKER_MAX_JOBS", "1"))
    )
    system_prompt_path: Path = field(
        default_factory=lambda: _path(
            "REPORT_SYSTEM_PROMPT", "./prompts/report-system-prompt.txt"
        )
    )
    response_schema_path: Path = field(
        default_factory=lambda: _path(
            "REPORT_RESPONSE_SCHEMA", "./prompts/report-response.schema.json"
        )
    )

    def validate_provider(self, provider: str) -> None:
        if provider not in {"local", "gemini"}:
            raise ValueError(f"Unsupported provider: {provider}")
        if provider == "gemini" and not self.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required for the Gemini provider")

    def validate_worker(self) -> None:
        if not self.control_plane_url:
            raise ValueError("CONTROL_PLANE_URL is required")
        if not self.worker_token:
            raise ValueError("WORKER_TOKEN is required")

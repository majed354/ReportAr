from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from .config import Settings
from .control_plane import ControlPlaneClient
from .preflight import automatic_setup_brief
from .report_pipeline import generate_report


LOGGER = logging.getLogger("report-worker")


def presentation_instructions(report_text: str) -> str:
    identity_words = (
        "شعار",
        "ختم",
        "خلفية",
        "غلاف",
        "ألوان",
        "الوان",
        "هوية بصرية",
        "نمط",
        "تصميم",
        "خط",
    )
    unsafe_words = ("تجاهل تعليمات", "اكتب latex", "تعليمات النظام", "احذف")
    lines = [
        line.strip()
        for line in report_text.splitlines()
        if any(word in line.lower() for word in identity_words)
        and not any(word in line.lower() for word in unsafe_words)
    ]
    return "\n".join(dict.fromkeys(lines))


def build_user_prompt(mode: str, report_text: str, instructions: str = "") -> str:
    mode_text = (
        "الوضع المطلوب: guided. نبه المستخدم إلى التعارضات والنقص واسأله قبل البناء."
        if mode == "guided"
        else "الوضع المطلوب: fast. أنجز التقرير دون أسئلة وسجل التعارضات والنقص."
    )
    trusted = "\n".join(
        part
        for part in (
            instructions.strip(),
            presentation_instructions(report_text),
            automatic_setup_brief(report_text, mode),
        )
        if part
    )
    return f"""{mode_text}

تعليمات إضافية موثوقة من المستخدم:
{trusted or "لا توجد"}

التقرير الخام:
---
{report_text}
---
"""


class ReportWorker:
    def __init__(self, settings: Settings):
        settings.validate_worker()
        self.settings = settings
        self.client = ControlPlaneClient(
            settings.control_plane_url, settings.worker_token
        )
        self.system = settings.system_prompt_path.read_text(encoding="utf-8")
        self.schema = json.loads(settings.response_schema_path.read_text(encoding="utf-8"))

    def capabilities(self) -> dict[str, Any]:
        return {
            "providers": ["local", "gemini"],
            "renderer": "lualatex-local",
            "max_jobs": self.settings.max_jobs,
            "version": "0.1.0",
        }

    def process(self, job: dict[str, Any]) -> None:
        job_id = str(job["id"])
        primary = job.get("ai_provider") or self.settings.provider
        fallback = (
            job.get("fallback_provider")
            if job.get("fallback_allowed", True)
            else ""
        ) or self.settings.fallback_provider
        self.client.event(job_id, "analyzing", f"بدأ التحليل عبر {primary}")
        try:
            result, fallback_used, primary_error = generate_report(
                settings=self.settings,
                primary=primary,
                fallback=fallback,
                system=self.system,
                user=build_user_prompt(
                    job.get("mode", "fast"),
                    job["report_text"],
                    job.get("instructions", ""),
                ),
                schema=self.schema,
                mode=job.get("mode", "fast"),
                report_text=job["report_text"],
                instructions=job.get("instructions", ""),
                model_override=job.get("ai_model"),
            )
            provider = {
                "name": result.provider,
                "model": result.model,
                "elapsed_seconds": result.elapsed_seconds,
                "usage": result.usage,
                "fallback_used": fallback_used,
                "primary_error": primary_error,
            }
            if result.parsed.get("status") == "needs_user_input":
                self.client.submit_questions(job_id, result.parsed, provider)
            else:
                self.client.submit_analysis(job_id, result.parsed, provider)
        except Exception as error:
            LOGGER.exception("Job %s failed", job_id)
            self.client.fail(job_id, str(error), retryable=True)

    def run_once(self) -> bool:
        self.client.heartbeat(self.settings.worker_id, self.capabilities())
        job = self.client.claim(self.settings.worker_id)
        if not job:
            return False
        self.process(job)
        return True

    def run_forever(self) -> None:
        LOGGER.info("Worker %s started", self.settings.worker_id)
        while True:
            try:
                worked = self.run_once()
                if not worked:
                    time.sleep(self.settings.poll_seconds)
            except KeyboardInterrupt:
                return
            except Exception:
                LOGGER.exception("Worker loop failed")
                time.sleep(self.settings.poll_seconds)


def load_job(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

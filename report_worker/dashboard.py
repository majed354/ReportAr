from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from telegram import Bot

from .config import Settings
from .http import request_json
from .providers import create_provider
from .qa_suite import run_local_qa_suite
from .renderer import render_report
from .settings_vault import SettingsVault
from .telegram_bot import TelegramReportBot


ROOT = Path(__file__).resolve().parents[1]
VAULT = SettingsVault(ROOT / "data" / "settings.json")
BOT_TASK: Optional[asyncio.Task] = None
BOT_ERROR = ""
QA_TASK: Optional[asyncio.Task] = None
QA_STATUS: dict[str, Any] = {"running": False}
CHART_TEST_PROMPT = """أنشئ تقريرًا عربيًا مختصرًا بعنوان اختبار المخططات الديناميكية.
الوضع المطلوب: fast. أنجز التقرير دون أسئلة.
استخدم البيانات التالية فقط وأنشئ أهداف المخططات المناسبة:
- مؤشرات الأداء: الجودة 88، السرعة 76، الرضا 91، الالتزام 69.
- الإيرادات الزمنية: 2020=20، 2021=28، 2022=35، 2023=43، 2024=52، 2025=64.
- مقارنة طويلة: تطوير الخدمات الرقمية 88، تحسين تجربة العملاء 76، رفع كفاءة العمليات 69، تطوير الموظفين 62.
- المراحل: البدء يناير، التحليل مارس، النسخة التجريبية يونيو، الإطلاق أكتوبر.
- تغير الربح: البداية 500 ألف، المبيعات +220 ألف، التشغيل -90 ألف، التسويق -40 ألف، النهاية 590 ألف."""


class SettingsInput(BaseModel):
    telegram_bot_token: str = ""
    gemini_api_key: str = ""
    provider: str = "local"
    fallback_provider: str = ""
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "gemma4:31b"
    gemini_model: str = "gemini-3.5-flash"
    allowed_telegram_users: str = ""
    enable_web_research: bool = False


app = FastAPI(title="لوحة تحكم بوت التقارير", version="0.1.0")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (ROOT / "web" / "index.html").read_text(encoding="utf-8")


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    return VAULT.public()


@app.post("/api/settings")
def save_settings(body: SettingsInput) -> dict[str, Any]:
    if body.provider not in {"local", "gemini"}:
        raise HTTPException(400, "المزوّد غير صحيح")
    if body.fallback_provider not in {"", "local", "gemini"}:
        raise HTTPException(400, "المزوّد الاحتياطي غير صحيح")
    VAULT.save(body.model_dump())
    return {"ok": True, "settings": VAULT.public()}


@app.get("/api/models/local")
async def local_models() -> dict[str, Any]:
    base_url = VAULT.load()["ollama_base_url"].rstrip("/")
    try:
        response = await asyncio.to_thread(
            request_json, "GET", f"{base_url}/api/tags", timeout=10
        )
    except Exception as error:
        raise HTTPException(400, str(error)[:500]) from None
    models = []
    for item in response.get("models", []):
        name = item.get("name", "")
        family = "Qwen" if name.lower().startswith(("qwen", "qwq")) else "Gemma"
        if family == "Gemma" and "gemma" not in name.lower():
            continue
        if "embedding" in name.lower() or item.get("size", 0) == 0:
            continue
        models.append(
            {
                "name": name,
                "family": family,
                "size_gb": round(item.get("size", 0) / 1_000_000_000, 1),
            }
        )
    return {"ok": True, "models": models}


@app.post("/api/test/{provider}")
async def test_provider(provider: str) -> dict[str, Any]:
    values = VAULT.load()
    settings = Settings(
        ollama_base_url=values["ollama_base_url"],
        ollama_model=values["ollama_model"],
        gemini_api_key=values["gemini_api_key"],
        gemini_model=values["gemini_model"],
    )
    try:
        result = await asyncio.to_thread(create_provider(provider, settings).healthcheck)
        return result
    except Exception as error:
        raise HTTPException(400, str(error)[:500]) from None


@app.post("/api/test/gemini/report")
async def test_gemini_report() -> dict[str, Any]:
    return await test_report_generation("gemini")


@app.post("/api/test/local/report")
async def test_local_report() -> dict[str, Any]:
    return await test_report_generation("local")


@app.post("/api/test/local/qa-suite")
async def start_local_qa_suite() -> dict[str, Any]:
    return await launch_local_qa_suite()


@app.post("/api/test/local/qa-suite/retry-failed")
async def retry_failed_local_qa_suite() -> dict[str, Any]:
    summaries = sorted((ROOT / "qa-results").glob("*/summary.json"))
    if not summaries:
        raise HTTPException(400, "لا توجد جولة سابقة لإعادة اختبارها")
    latest = json.loads(summaries[-1].read_text(encoding="utf-8"))
    failed_ids = [result["id"] for result in latest.get("results", []) if not result["passed"]]
    if not failed_ids:
        return {"running": False, "passed": latest.get("passed"), "failed": 0, "total": latest.get("total")}
    return await launch_local_qa_suite(failed_ids, "retry")


async def launch_local_qa_suite(
    scenario_ids: list[str] | None = None,
    prefix: str = "run",
) -> dict[str, Any]:
    global QA_TASK, QA_STATUS
    if QA_TASK and not QA_TASK.done():
        return QA_STATUS
    values = VAULT.load()
    settings = Settings(
        provider="local",
        fallback_provider="",
        ollama_base_url=values["ollama_base_url"],
        ollama_model=values["ollama_model"],
        gemini_api_key=values["gemini_api_key"],
        gemini_model=values["gemini_model"],
    )
    destination = ROOT / "qa-results" / datetime.now().strftime(f"{prefix}-%Y%m%d-%H%M%S")
    total = len(scenario_ids or []) or 10
    QA_STATUS = {"running": True, "current": 0, "total": total, "scenario": "بدء الاختبارات"}

    def progress(value: dict[str, Any]) -> None:
        global QA_STATUS
        QA_STATUS = value

    async def runner() -> None:
        global QA_STATUS
        try:
            QA_STATUS = await asyncio.to_thread(
                run_local_qa_suite, settings, destination, progress, scenario_ids
            )
        except Exception as error:
            QA_STATUS = {"running": False, "error": str(error)[:700]}

    QA_TASK = asyncio.create_task(runner())
    return QA_STATUS


@app.get("/api/test/local/qa-suite")
def local_qa_suite_status() -> dict[str, Any]:
    return QA_STATUS


async def test_report_generation(provider: str) -> dict[str, Any]:
    values = VAULT.load()
    settings = Settings(
        provider=provider,
        ollama_base_url=values["ollama_base_url"],
        ollama_model=values["ollama_model"],
        gemini_api_key=values["gemini_api_key"],
        gemini_model=values["gemini_model"],
    )
    schema = json.loads(settings.response_schema_path.read_text(encoding="utf-8"))
    try:
        result = await asyncio.to_thread(
            create_provider(provider, settings).generate,
            settings.system_prompt_path.read_text(encoding="utf-8"),
            CHART_TEST_PROMPT,
            schema,
        )
        chart_kinds = [
            chart.get("kind", "") for chart in result.parsed.get("chart_intents", [])
        ]
        rendered_size = 0
        if result.parsed.get("status") == "ready_to_render":
            pdf_path = await asyncio.to_thread(
                render_report,
                result.parsed,
                Path(tempfile.mkdtemp(prefix=f"{provider}-chart-test-")),
            )
            rendered_size = pdf_path.stat().st_size
        return {
            "ok": result.parsed.get("status") == "ready_to_render" and rendered_size > 0,
            "provider": result.provider,
            "model": result.model,
            "status": result.parsed.get("status"),
            "title": (result.parsed.get("report") or {}).get("title", ""),
            "chart_kinds": chart_kinds,
            "chart_count": len(chart_kinds),
            "rendered_size": rendered_size,
            "elapsed_seconds": result.elapsed_seconds,
        }
    except Exception as error:
        raise HTTPException(400, str(error)[:500]) from None


@app.get("/api/bot/status")
def bot_status() -> dict[str, Any]:
    return {
        "configured": bool(VAULT.load()["telegram_bot_token"]),
        "running": bool(BOT_TASK and not BOT_TASK.done()),
        "error": BOT_ERROR,
    }


@app.post("/api/bot/start")
async def start_bot() -> dict[str, Any]:
    global BOT_TASK, BOT_ERROR
    if BOT_TASK and not BOT_TASK.done():
        return {"ok": True, "running": True}
    token = VAULT.load()["telegram_bot_token"]
    if not token:
        raise HTTPException(400, "احفظ مفتاح Telegram Bot أولًا")
    try:
        identity = await Bot(token).get_me()
    except Exception as error:
        BOT_ERROR = str(error)[:500]
        raise HTTPException(400, f"مفتاح Telegram غير صالح أو تعذر الاتصال: {BOT_ERROR}") from None
    bot = TelegramReportBot(VAULT)
    ready = asyncio.Event()
    BOT_ERROR = ""
    BOT_TASK = asyncio.create_task(bot.run_async(ready))

    def record_failure(task: asyncio.Task) -> None:
        global BOT_ERROR
        if task.cancelled():
            return
        error = task.exception()
        if error:
            BOT_ERROR = str(error)[:500]

    BOT_TASK.add_done_callback(record_failure)
    await asyncio.wait_for(ready.wait(), timeout=20)
    if BOT_TASK.done():
        error = BOT_TASK.exception()
        raise HTTPException(400, f"تعذر تشغيل البوت: {str(error)[:500]}") from None
    return {"ok": True, "running": True, "username": identity.username or ""}
